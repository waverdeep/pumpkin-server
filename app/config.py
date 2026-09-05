from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    db_host: str
    db_port: int = 5432
    db_user: str
    db_password: str
    db_name: str = "postgres"
    db_ssl: bool = True
    db_schema: str = "pumpkin"

    # 개봉 시각. 비어 있으면 언제든 개봉 가능(테스트 모드). ISO 8601, 타임존 포함 권장.
    open_at: datetime | None = None

    # 브라우저 쿠키 옵션
    cookie_name: str = "pk_owner"
    cookie_secure: bool = False
    cookie_max_age: int = 60 * 60 * 24 * 120  # 120일. 시즌 전체를 덮는다.

    # 사탕 넣기 속도 제한 (IP 기준, 분당)
    throw_rate_per_minute: int = 20

    # 로그인. 구글 OAuth 는 openid 스코프만 쓴다 (받는 건 sub 하나).
    google_client_id: str = ""
    google_client_secret: str = ""
    # 리다이렉트 URI 의 기준 주소. 예: https://pumpkin.zzam.today  (로컬: http://127.0.0.1:5173)
    public_origin: str = "http://127.0.0.1:5173"
    # 세션 쿠키 서명 키. 비어 있으면 서버가 뜰 때마다 바뀌어 로그인이 풀린다.
    session_secret: str = ""
    session_cookie_name: str = "pk_session"
    session_max_age: int = 60 * 60 * 24 * 120
    # true 면 바구니 만들기에 로그인이 필요하다. 로컬 개발·테스트는 false.
    login_required: bool = False

    @field_validator("open_at", mode="before")
    @classmethod
    def _empty_to_none(cls, v):
        if v in ("", None):
            return None
        return v

    @field_validator("open_at")
    @classmethod
    def _ensure_tz(cls, v: datetime | None):
        if v is not None and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v

    @property
    def database_url(self) -> str:
        ssl = "require" if self.db_ssl else "disable"
        return (
            f"postgresql+psycopg://{quote_plus(self.db_user)}:{quote_plus(self.db_password)}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}?sslmode={ssl}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
