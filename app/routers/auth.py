"""구글 로그인.

받는 것은 구글 계정의 `sub`(회원번호) 하나. 이메일·프로필은 요청하지 않는다.
그래서 동의 화면에 민감 항목이 없고 검수가 필요 없다.
"""

from __future__ import annotations

import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import clear_auth_cookies, set_session_cookie
from app.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_TOKENINFO = "https://oauth2.googleapis.com/tokeninfo"
STATE_COOKIE = "pk_oauth_state"
PROVIDER = "google"


def redirect_uri(settings: Settings) -> str:
    return f"{settings.public_origin.rstrip('/')}/api/auth/google/callback"


def _safe_next(value: str | None) -> str:
    # 같은 사이트 경로만. 외부로 튕기는 open redirect 를 막는다.
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return "/"


@router.get("/google/start")
def google_start(next: str | None = None, settings: Settings = Depends(get_settings)):
    if not settings.google_client_id:
        raise HTTPException(status_code=503, detail="구글 로그인이 아직 준비되지 않았어")
    state = secrets.token_urlsafe(24)
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri(settings),
        "response_type": "code",
        "scope": "openid",
        "state": state,
        "prompt": "select_account",
    }
    resp = RedirectResponse(f"{GOOGLE_AUTH}?{urlencode(params)}", status_code=302)
    resp.set_cookie(
        STATE_COOKIE,
        f"{state}|{_safe_next(next)}",
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/api/auth",
    )
    return resp


async def exchange_code(code: str, settings: Settings) -> str:
    """인가 코드를 토큰으로 바꾸고 id_token 을 돌려준다."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            GOOGLE_TOKEN,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri(settings),
                "grant_type": "authorization_code",
            },
        )
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail="구글이 토큰을 주지 않았어")
    return r.json()["id_token"]


async def verify_id_token(id_token: str, settings: Settings) -> str:
    """구글 tokeninfo 로 검증하고 sub 를 돌려준다. (JWKS 검증 대신 구글에 묻는다. MVP 용.)"""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(GOOGLE_TOKENINFO, params={"id_token": id_token})
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="구글 토큰이 유효하지 않아")
    info = r.json()
    if info.get("aud") != settings.google_client_id or info.get("iss") not in ("https://accounts.google.com", "accounts.google.com"):
        raise HTTPException(status_code=401, detail="구글 토큰이 유효하지 않아")
    sub = info.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="구글 토큰이 유효하지 않아")
    return sub


@router.get("/google/callback")
async def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    saved = request.cookies.get(STATE_COOKIE, "")
    saved_state, _, next_path = saved.partition("|")

    def fail(reason: str):
        resp = RedirectResponse(f"/?login={reason}", status_code=302)
        resp.delete_cookie(STATE_COOKIE, path="/api/auth")
        return resp

    if error:  # 사용자가 취소함
        return fail("cancel")
    if not code or not state or not saved_state or not secrets.compare_digest(state, saved_state):
        return fail("state")

    id_token = await exchange_code(code, settings)
    sub = await verify_id_token(id_token, settings)

    user = db.query(User).filter_by(provider=PROVIDER, provider_id=sub).one_or_none()
    if user is None:
        user = User(provider=PROVIDER, provider_id=sub)
        db.add(user)
        db.commit()
        db.refresh(user)

    resp = RedirectResponse(_safe_next(next_path), status_code=302)
    resp.delete_cookie(STATE_COOKIE, path="/api/auth")
    set_session_cookie(resp, user, settings)
    return resp


@router.post("/logout", status_code=204)
def logout(settings: Settings = Depends(get_settings)):
    from fastapi import Response

    resp = Response(status_code=204)
    clear_auth_cookies(resp, settings)
    return resp
