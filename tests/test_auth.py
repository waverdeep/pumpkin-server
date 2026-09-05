from urllib.parse import parse_qs, urlparse

import pytest

from app.config import get_settings
from app.routers import auth as auth_mod

T = "__t_"


@pytest.fixture
def google(monkeypatch):
    """구글 왕복을 흉내 낸다. 코드 'good' 은 sub 'sub-123' 으로."""
    settings = get_settings()
    monkeypatch.setattr(settings, "google_client_id", "test-client")
    monkeypatch.setattr(settings, "google_client_secret", "test-secret")
    monkeypatch.setattr(settings, "public_origin", "http://testserver")

    async def fake_exchange(code, _settings):
        return f"idtoken-for-{code}"

    async def fake_verify(id_token, _settings):
        return "sub-123" if id_token == "idtoken-for-good" else "sub-other"

    monkeypatch.setattr(auth_mod, "exchange_code", fake_exchange)
    monkeypatch.setattr(auth_mod, "verify_id_token", fake_verify)
    yield


def _login(client, code="good"):
    r = client.get("/api/auth/google/start?next=/me", follow_redirects=False)
    assert r.status_code == 302
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    r = client.get(f"/api/auth/google/callback?code={code}&state={state}", follow_redirects=False)
    assert r.status_code == 302, r.text
    return r


def test_start_redirects_to_google_with_openid_only(client, google):
    r = client.get("/api/auth/google/start", follow_redirects=False)
    assert r.status_code == 302
    u = urlparse(r.headers["location"])
    q = parse_qs(u.query)
    assert u.netloc == "accounts.google.com"
    assert q["scope"] == ["openid"]
    assert q["redirect_uri"] == ["http://testserver/api/auth/google/callback"]
    assert auth_mod.STATE_COOKIE in client.cookies


def test_start_without_config(client):
    assert client.get("/api/auth/google/start", follow_redirects=False).status_code == 503


def test_callback_rejects_bad_state(client, google):
    client.get("/api/auth/google/start", follow_redirects=False)
    r = client.get("/api/auth/google/callback?code=good&state=wrong", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/?login=state"
    assert get_settings().session_cookie_name not in client.cookies


def test_callback_cancel(client, google):
    client.get("/api/auth/google/start", follow_redirects=False)
    r = client.get("/api/auth/google/callback?error=access_denied", follow_redirects=False)
    assert r.headers["location"] == "/?login=cancel"


def test_login_creates_user_and_session(client, google):
    r = _login(client)
    assert r.headers["location"] == "/me"
    assert get_settings().session_cookie_name in client.cookies
    me = client.get("/api/me").json()
    assert me["user"] == {"provider": "google"} and me["basket"] is None
    # 같은 사람이 다시 로그인해도 유저는 하나
    _login(client)
    b = client.post("/api/baskets", json={"name": T + "구글"}).json()
    assert b["is_owner"] is True
    assert client.get("/api/me").json()["basket"]["slug"] == b["slug"]


def test_logout(client, google):
    _login(client)
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/me").json()["user"] is None


def test_next_must_be_local_path(client, google):
    r = client.get("/api/auth/google/start?next=https://evil.example", follow_redirects=False)
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    r = client.get(f"/api/auth/google/callback?code=good&state={state}", follow_redirects=False)
    assert r.headers["location"] == "/"


def test_tampered_session_is_ignored(client, google):
    _login(client)
    name = get_settings().session_cookie_name
    client.cookies.set(name, client.cookies[name][:-3] + "abc")
    assert client.get("/api/me").json()["user"] is None


def test_login_required_blocks_anonymous_creation(client, stranger, google, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "login_required", True)
    assert stranger.get("/api/me").json()["login_required"] is True
    r = stranger.post("/api/baskets", json={"name": T + "익명"})
    assert r.status_code == 401
    _login(client)
    assert client.post("/api/baskets", json={"name": T + "구글"}).status_code == 201
