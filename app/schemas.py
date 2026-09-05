from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

CandyKind = Literal["letter", "curse", "plain"]

NAME_MAX = 12
LETTER_MAX = 200
SENDER_MAX = 12


class BasketCreate(BaseModel):
    name: str = Field(min_length=1, max_length=NAME_MAX)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("이름을 정해줘")
        return v


class BasketPublic(BaseModel):
    """공개 주소로 보는 바구니. 이름과 개수, 껍질만. 내용은 절대 내려주지 않는다."""

    slug: str
    name: str
    count: int
    shells: list[int]  # 최근 사탕 껍질 번호(최대 24). 더미 그리기에 쓴다.
    is_open: bool
    open_at: datetime | None
    is_owner: bool
    server_time: datetime


class UserOut(BaseModel):
    provider: str  # 'anon' | 'google'


class MeResponse(BaseModel):
    user: UserOut | None
    basket: BasketPublic | None
    login_required: bool
    google_enabled: bool


class CurseOut(BaseModel):
    id: int
    text: str
    duration: str


class CandyCreate(BaseModel):
    shell: int = Field(ge=0, le=11)
    kind: CandyKind
    content: str | None = Field(default=None, max_length=LETTER_MAX)
    curse_id: int | None = None
    sender: str | None = Field(default=None, max_length=SENDER_MAX)

    @field_validator("sender", mode="before")
    @classmethod
    def _clean_sender(cls, v):
        if v is None:
            return None
        v = " ".join(str(v).split())
        return v or None

    @model_validator(mode="after")
    def _check_payload(self):
        if self.kind == "letter":
            text = (self.content or "").strip()
            if not text:
                raise ValueError("편지를 적어줘")
            self.content = text
            self.curse_id = None
        elif self.kind == "curse":
            if self.curse_id is None:
                raise ValueError("저주 카드를 골라줘")
            self.content = None
        else:
            self.content = None
            self.curse_id = None
        return self


class ThrowResult(BaseModel):
    count: int
    shell: int


class CandyOut(BaseModel):
    id: uuid.UUID
    shell: int
    kind: CandyKind
    content: str | None
    curse: CurseOut | None
    sender: str | None
    created_at: datetime


class OpenResponse(BaseModel):
    slug: str
    name: str
    is_open: bool
    open_at: datetime | None
    server_time: datetime
    candies: list[CandyOut]
