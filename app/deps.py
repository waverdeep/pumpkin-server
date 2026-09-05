from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import Basket, User

ANON_PROVIDER = "anon"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def is_open(settings: Settings, at: datetime | None = None) -> bool:
    """개봉 여부는 서버 시각으로만 판정한다. open_at이 없으면 항상 열려 있다(테스트 모드)."""
    if settings.open_at is None:
        return True
    return (at or now_utc()) >= settings.open_at


def get_owner_token(request: Request, settings: Settings = Depends(get_settings)) -> str | None:
    token = request.cookies.get(settings.cookie_name)
    if token and 32 <= len(token) <= 128:
        return token
    return None


# ---- 세션 쿠키 (로그인 사용자) -------------------------------------------------
# 값: <user_id>.<만료 epoch>.<hmac>. 서버 상태 없이 검증한다.

_ephemeral_secret = secrets.token_urlsafe(32)


def _secret(settings: Settings) -> bytes:
    return (settings.session_secret or _ephemeral_secret).encode()


def _sign(payload: str, settings: Settings) -> str:
    mac = hmac.new(_secret(settings), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def make_session(user_id: uuid.UUID, settings: Settings) -> str:
    payload = f"{user_id}.{int(time.time()) + settings.session_max_age}"
    return f"{payload}.{_sign(payload, settings)}"


def parse_session(value: str | None, settings: Settings) -> uuid.UUID | None:
    if not value:
        return None
    try:
        uid, exp, sig = value.rsplit(".", 2)
    except ValueError:
        return None
    if not hmac.compare_digest(sig, _sign(f"{uid}.{exp}", settings)):
        return None
    if int(exp) < time.time():
        return None
    try:
        return uuid.UUID(uid)
    except ValueError:
        return None


def set_session_cookie(response: Response, user: User, settings: Settings) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        make_session(user.id, settings),
        max_age=settings.session_max_age,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def clear_auth_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.cookie_name, path="/")


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    token: str | None = Depends(get_owner_token),
    settings: Settings = Depends(get_settings),
) -> User | None:
    """로그인 세션이 있으면 그 사용자, 없으면 익명 주인 쿠키."""
    uid = parse_session(request.cookies.get(settings.session_cookie_name), settings)
    if uid is not None:
        user = db.get(User, uid)
        if user is not None:
            return user
    if token is None:
        return None
    return db.query(User).filter_by(provider=ANON_PROVIDER, provider_id=token).one_or_none()


def get_current_basket(user: User | None = Depends(get_current_user)) -> Basket | None:
    return user.basket if user else None


def issue_owner(db: Session, response: Response, settings: Settings) -> User:
    """새 익명 사용자를 만들고 쿠키를 발급한다."""
    token = secrets.token_urlsafe(48)
    user = User(provider=ANON_PROVIDER, provider_id=token)
    db.add(user)
    db.flush()
    response.set_cookie(
        settings.cookie_name,
        token,
        max_age=settings.cookie_max_age,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return user


class RateLimiter:
    """아주 단순한 인메모리 슬라이딩 윈도우. 인스턴스 하나 기준이라 MVP용."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            raise HTTPException(status_code=429, detail="사탕을 너무 빨리 던지고 있어. 잠깐 쉬었다 와.")
        q.append(now)


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
