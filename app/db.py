from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

settings = get_settings()

# Supabase 풀러(트랜잭션 모드)는 서버측 prepared statement를 지원하지 않으므로 끈다.
# 세션 설정(search_path)도 유지되지 않으므로 모든 테이블은 모델에서 스키마를 명시한다.
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    connect_args={"prepare_threshold": None},
)


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
