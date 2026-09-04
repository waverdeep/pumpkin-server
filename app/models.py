from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import get_settings

SCHEMA = get_settings().db_schema


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


class User(Base):
    """provider + provider_id 조합만 받는다. 이메일·프로필 없음.
    MVP에서는 provider='anon', provider_id=쿠키 토큰. 나중에 'google' 등이 추가된다."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("provider", "provider_id", name="uq_users_provider"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    basket: Mapped["Basket | None"] = relationship(back_populates="user", uselist=False)


class Basket(Base):
    """사람마다 바구니는 하나. slug가 공개 주소."""

    __tablename__ = "baskets"
    __table_args__ = (UniqueConstraint("user_id", name="uq_baskets_user"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(12), nullable=False)
    slug: Mapped[str] = mapped_column(String(16), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user: Mapped[User] = relationship(back_populates="basket")
    candies: Mapped[list["Candy"]] = relationship(back_populates="basket", order_by="Candy.created_at")


class Candy(Base):
    """사탕은 껍질이다. shell(0-11)이 껍질, kind가 내용물의 종류."""

    __tablename__ = "candies"
    __table_args__ = (
        CheckConstraint("shell >= 0 AND shell < 12", name="ck_candies_shell"),
        CheckConstraint("kind IN ('letter', 'curse', 'plain')", name="ck_candies_kind"),
        CheckConstraint(
            "(kind = 'letter' AND content IS NOT NULL AND curse_id IS NULL) OR "
            "(kind = 'curse' AND curse_id IS NOT NULL AND content IS NULL) OR "
            "(kind = 'plain' AND content IS NULL AND curse_id IS NULL)",
            name="ck_candies_payload",
        ),
        # 한 바구니에 같은 저주 카드는 한 번만
        Index("uq_candies_basket_curse", "basket_id", "curse_id", unique=True, postgresql_where="curse_id IS NOT NULL"),
        Index("ix_candies_basket_created", "basket_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    basket_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.baskets.id", ondelete="CASCADE"), nullable=False)
    shell: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    curse_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 보낸이 닉네임. 인증되지 않은 자칭. 비우면 익명
    sender: Mapped[str | None] = mapped_column(String(12), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    basket: Mapped[Basket] = relationship(back_populates="candies")
