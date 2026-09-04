from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.curses import CURSES

T = "__t_"  # 테스트 바구니 이름 접두어(정리용)


def _create(client, name="감자"):
    r = client.post("/api/baskets", json={"name": T + name})
    assert r.status_code == 201, r.text
    return r.json()


def test_health(client):
    assert client.get("/api/health").json() == {"ok": True}


def test_create_basket_sets_cookie_and_me(client):
    assert client.get("/api/me").json() == {"basket": None}
    b = _create(client)
    assert b["name"] == T + "감자"
    assert len(b["slug"]) == 8
    assert b["count"] == 0 and b["shells"] == []
    assert b["is_owner"] is True
    assert get_settings().cookie_name in client.cookies
    me = client.get("/api/me").json()["basket"]
    assert me["slug"] == b["slug"]


def test_one_basket_per_owner(client):
    _create(client)
    r = client.post("/api/baskets", json={"name": T + "둘"})
    assert r.status_code == 409


def test_name_validation(client):
    r = client.post("/api/baskets", json={"name": "   "})
    assert r.status_code == 422
    assert "이름" in r.json()["detail"]
    r = client.post("/api/baskets", json={"name": "가" * 13})
    assert r.status_code == 422


def test_public_view_hides_content(client, stranger):
    b = _create(client)
    slug = b["slug"]
    r = stranger.post(f"/api/baskets/{slug}/candies", json={"shell": 3, "kind": "letter", "content": "비밀 편지"})
    assert r.status_code == 201, r.text
    assert r.json() == {"count": 1, "shell": 3}

    pub = stranger.get(f"/api/baskets/{slug}").json()
    assert pub["count"] == 1
    assert pub["shells"] == [3]
    assert pub["is_owner"] is False
    assert "비밀" not in stranger.get(f"/api/baskets/{slug}").text
    assert "candies" not in pub


def test_unknown_basket(stranger):
    assert stranger.get("/api/baskets/nope1234").status_code == 404
    assert stranger.post("/api/baskets/nope1234/candies", json={"shell": 0, "kind": "plain"}).status_code == 404


def test_candy_validation(client, stranger):
    slug = _create(client)["slug"]
    url = f"/api/baskets/{slug}/candies"
    assert stranger.post(url, json={"shell": 12, "kind": "plain"}).status_code == 422
    assert stranger.post(url, json={"shell": 0, "kind": "letter", "content": "  "}).status_code == 422
    assert stranger.post(url, json={"shell": 0, "kind": "letter", "content": "a" * 201}).status_code == 422
    assert stranger.post(url, json={"shell": 0, "kind": "curse"}).status_code == 422
    assert stranger.post(url, json={"shell": 0, "kind": "curse", "curse_id": 9999}).status_code == 422
    assert stranger.post(url, json={"shell": 0, "kind": "steal"}).status_code == 422


def test_curse_dedup_per_basket(client, stranger):
    slug = _create(client)["slug"]
    all_ids = {c.id for c in CURSES}
    avail = stranger.get(f"/api/baskets/{slug}/curses").json()
    assert {c["id"] for c in avail} == all_ids and len(avail) == 40

    r = stranger.post(f"/api/baskets/{slug}/candies", json={"shell": 5, "kind": "curse", "curse_id": 7})
    assert r.status_code == 201
    avail = stranger.get(f"/api/baskets/{slug}/curses").json()
    assert 7 not in {c["id"] for c in avail} and len(avail) == 39

    r = stranger.post(f"/api/baskets/{slug}/candies", json={"shell": 5, "kind": "curse", "curse_id": 7})
    assert r.status_code == 409


def test_open_owner_only(client, stranger):
    slug = _create(client)["slug"]
    stranger.post(f"/api/baskets/{slug}/candies", json={"shell": 1, "kind": "plain"})
    assert stranger.get(f"/api/baskets/{slug}/candies").status_code == 403
    r = client.get(f"/api/baskets/{slug}/candies")
    assert r.status_code == 200
    body = r.json()
    assert body["is_open"] is True
    assert [c["kind"] for c in body["candies"]] == ["plain"]


def test_open_returns_all_kinds_in_order(client, stranger):
    slug = _create(client)["slug"]
    stranger.post(f"/api/baskets/{slug}/candies", json={"shell": 0, "kind": "letter", "content": "고생 많았어"})
    stranger.post(f"/api/baskets/{slug}/candies", json={"shell": 1, "kind": "curse", "curse_id": 2})
    stranger.post(f"/api/baskets/{slug}/candies", json={"shell": 2, "kind": "plain"})
    cs = client.get(f"/api/baskets/{slug}/candies").json()["candies"]
    assert [c["shell"] for c in cs] == [0, 1, 2]
    assert cs[0]["content"] == "고생 많았어" and cs[0]["curse"] is None
    assert cs[1]["content"] is None and cs[1]["curse"]["id"] == 2 and "저주" in cs[1]["curse"]["text"]
    assert cs[2]["content"] is None and cs[2]["curse"] is None


def test_open_locked_before_open_at(client, stranger, monkeypatch):
    slug = _create(client)["slug"]
    stranger.post(f"/api/baskets/{slug}/candies", json={"shell": 0, "kind": "plain"})
    settings = get_settings()
    monkeypatch.setattr(settings, "open_at", datetime.now(timezone.utc) + timedelta(days=1))
    try:
        pub = stranger.get(f"/api/baskets/{slug}").json()
        assert pub["is_open"] is False and pub["count"] == 1
        r = client.get(f"/api/baskets/{slug}/candies")
        assert r.status_code == 423
        assert r.json()["detail"]["open_at"]
        # 시각이 지나면 열린다
        monkeypatch.setattr(settings, "open_at", datetime.now(timezone.utc) - timedelta(seconds=1))
        assert client.get(f"/api/baskets/{slug}/candies").status_code == 200
    finally:
        monkeypatch.setattr(settings, "open_at", None)


def test_rate_limit(client, stranger):
    from app.routers import baskets as mod

    slug = _create(client)["slug"]
    mod._limiter = mod.RateLimiter(3)
    try:
        for _ in range(3):
            assert stranger.post(f"/api/baskets/{slug}/candies", json={"shell": 0, "kind": "plain"}).status_code == 201
        assert stranger.post(f"/api/baskets/{slug}/candies", json={"shell": 0, "kind": "plain"}).status_code == 429
    finally:
        mod._limiter = None


def test_sender_optional_and_trimmed(client, stranger):
    slug = _create(client)["slug"]
    url = f"/api/baskets/{slug}/candies"
    assert stranger.post(url, json={"shell": 0, "kind": "letter", "content": "안녕", "sender": "  옆자리  고구마 "}).status_code == 201
    assert stranger.post(url, json={"shell": 1, "kind": "curse", "curse_id": 3, "sender": "   "}).status_code == 201
    assert stranger.post(url, json={"shell": 2, "kind": "plain"}).status_code == 201
    assert stranger.post(url, json={"shell": 2, "kind": "plain", "sender": "가" * 13}).status_code == 422
    cs = client.get(url).json()["candies"]
    assert [c["sender"] for c in cs] == ["옆자리 고구마", None, None]
    # 공개 조회에는 보낸이가 나가지 않는다
    assert "고구마" not in stranger.get(f"/api/baskets/{slug}").text
