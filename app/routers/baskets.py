from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.curses import CURSES, CURSES_BY_ID
from app.db import get_db
from app.deps import (
    RateLimiter,
    client_ip,
    get_current_basket,
    get_current_user,
    is_open,
    issue_owner,
    now_utc,
)
from app.models import Basket, Candy, User
from app.schemas import (
    BasketCreate,
    BasketPublic,
    CandyCreate,
    CandyOut,
    CurseOut,
    MeResponse,
    OpenResponse,
    ThrowResult,
)
from app.slug import new_slug

router = APIRouter(prefix="/api", tags=["baskets"])

SHELLS_PREVIEW = 24


def _count(db: Session, basket: Basket) -> int:
    return db.scalar(select(func.count()).select_from(Candy).where(Candy.basket_id == basket.id)) or 0


def _recent_shells(db: Session, basket: Basket) -> list[int]:
    rows = db.scalars(
        select(Candy.shell)
        .where(Candy.basket_id == basket.id)
        .order_by(Candy.created_at.desc())
        .limit(SHELLS_PREVIEW)
    ).all()
    return list(reversed(rows))  # 오래된 것이 먼저 → 더미 아래쪽에 깔린다


def _public(db: Session, basket: Basket, settings: Settings, is_owner: bool) -> BasketPublic:
    now = now_utc()
    return BasketPublic(
        slug=basket.slug,
        name=basket.name,
        count=_count(db, basket),
        shells=_recent_shells(db, basket),
        is_open=is_open(settings, now),
        open_at=settings.open_at,
        is_owner=is_owner,
        server_time=now,
    )


def _get_basket_or_404(db: Session, slug: str) -> Basket:
    basket = db.scalar(select(Basket).where(Basket.slug == slug))
    if basket is None:
        raise HTTPException(status_code=404, detail="그런 바구니는 없어")
    return basket


@router.post("/baskets", response_model=BasketPublic, status_code=201)
def create_basket(
    body: BasketCreate,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    user: User | None = Depends(get_current_user),
):
    if user is None:
        user = issue_owner(db, response, settings)
    elif user.basket is not None:
        raise HTTPException(status_code=409, detail="바구니는 하나만 가질 수 있어")

    basket: Basket | None = None
    for _ in range(5):  # slug 충돌은 사실상 없지만, 나면 세이브포인트만 되감고 다시 뽑는다
        candidate = Basket(user_id=user.id, name=body.name, slug=new_slug())
        try:
            with db.begin_nested():
                db.add(candidate)
                db.flush()
            basket = candidate
            break
        except IntegrityError:
            continue
    if basket is None:
        raise HTTPException(status_code=500, detail="주소를 만들지 못했어. 다시 해봐.")
    db.commit()
    db.refresh(basket)
    return _public(db, basket, settings, is_owner=True)


@router.get("/me", response_model=MeResponse)
def me(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    basket: Basket | None = Depends(get_current_basket),
):
    if basket is None:
        return MeResponse(basket=None)
    return MeResponse(basket=_public(db, basket, settings, is_owner=True))


@router.get("/baskets/{slug}", response_model=BasketPublic)
def get_basket(
    slug: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    mine: Basket | None = Depends(get_current_basket),
):
    basket = _get_basket_or_404(db, slug)
    return _public(db, basket, settings, is_owner=bool(mine and mine.id == basket.id))


@router.get("/baskets/{slug}/curses", response_model=list[CurseOut])
def available_curses(slug: str, db: Session = Depends(get_db)):
    """이 바구니에 아직 안 들어간 저주 카드만. 서버가 상태를 알아야 하므로 여기서 거른다."""
    basket = _get_basket_or_404(db, slug)
    used = set(
        db.scalars(
            select(Candy.curse_id).where(Candy.basket_id == basket.id, Candy.curse_id.is_not(None))
        ).all()
    )
    return [CurseOut(id=c.id, text=c.text, duration=c.duration) for c in CURSES if c.id not in used]


_limiter: RateLimiter | None = None


def _get_limiter(settings: Settings = Depends(get_settings)) -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter(settings.throw_rate_per_minute)
    return _limiter


@router.post("/baskets/{slug}/candies", response_model=ThrowResult, status_code=201)
def throw_candy(
    slug: str,
    body: CandyCreate,
    request: Request,
    db: Session = Depends(get_db),
    limiter: RateLimiter = Depends(_get_limiter),
):
    limiter.check(client_ip(request))
    basket = _get_basket_or_404(db, slug)

    if body.kind == "curse":
        if body.curse_id not in CURSES_BY_ID:
            raise HTTPException(status_code=422, detail="그런 저주 카드는 없어")

    candy = Candy(
        basket_id=basket.id, shell=body.shell, kind=body.kind, content=body.content, curse_id=body.curse_id, sender=body.sender
    )
    db.add(candy)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="이 저주는 이미 누가 걸어뒀어. 다른 걸 골라줘.")
    return ThrowResult(count=_count(db, basket), shell=candy.shell)


@router.get("/baskets/{slug}/candies", response_model=OpenResponse)
def open_basket(
    slug: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    mine: Basket | None = Depends(get_current_basket),
):
    """개봉. 주인만, 그리고 서버 시각이 개봉 시각을 지났을 때만 내용을 내려준다."""
    basket = _get_basket_or_404(db, slug)
    if mine is None or mine.id != basket.id:
        raise HTTPException(status_code=403, detail="이 바구니는 주인만 열 수 있어")
    now = now_utc()
    if not is_open(settings, now):
        raise HTTPException(
            status_code=423,
            detail={"message": "아직 열 수 없어", "open_at": settings.open_at.isoformat() if settings.open_at else None},
        )
    candies = db.scalars(
        select(Candy).where(Candy.basket_id == basket.id).order_by(Candy.created_at.asc(), Candy.id.asc())
    ).all()
    out = []
    for c in candies:
        curse = CURSES_BY_ID.get(c.curse_id) if c.curse_id is not None else None
        out.append(
            CandyOut(
                id=c.id,
                shell=c.shell,
                kind=c.kind,  # type: ignore[arg-type]
                content=c.content,
                curse=CurseOut(id=curse.id, text=curse.text, duration=curse.duration) if curse else None,
                sender=c.sender,
                created_at=c.created_at,
            )
        )
    return OpenResponse(
        slug=basket.slug, name=basket.name, is_open=True, open_at=settings.open_at, server_time=now, candies=out
    )
