import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db import SessionLocal
from app.main import app
from app.models import Basket, Candy, User


@pytest.fixture
def client():
    """쿠키를 유지하는 클라이언트 하나 = 브라우저 하나."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def stranger():
    """쿠키가 없는 다른 브라우저."""
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _cleanup():
    """테스트가 만든 익명 유저(와 바구니, 사탕)를 지운다."""
    yield
    with SessionLocal() as db:
        db.execute(delete(Candy).where(Candy.basket_id.in_(
            db.query(Basket.id).filter(Basket.name.like("__t_%")).subquery().select()
        )))
        db.execute(delete(Basket).where(Basket.name.like("__t_%")))
        db.commit()
        # 바구니 없는 익명 유저와 테스트 구글 유저 정리
        db.query(User).filter(User.provider == "google", User.provider_id.like("sub-%")).delete(synchronize_session=False)
        orphan = db.query(User).filter(User.provider == "anon", ~User.basket.has()).all()
        for u in orphan:
            db.delete(u)
        db.commit()
