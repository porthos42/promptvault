"""SQLAlchemy models (see docs/SPEC.md section 3.2)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


def _now() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return str(uuid.uuid4())


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC datetimes (SQLite drops tzinfo, so restore it on read)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is not None and value.tzinfo is not None:
            return value.astimezone(UTC)
        return value

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class Base(DeclarativeBase):
    pass


prompt_tag = Table(
    "prompt_tag",
    Base.metadata,
    Column("prompt_id", ForeignKey("prompt.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True),
)


class Category(Base):
    __tablename__ = "category"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("category.id", ondelete="SET NULL"), nullable=True
    )
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Tag(Base):
    __tablename__ = "tag"
    __table_args__ = (UniqueConstraint("name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), index=True)


class Prompt(Base):
    __tablename__ = "prompt"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    seed_id: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True)
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("category.id", ondelete="SET NULL"), nullable=True, index=True
    )
    variables: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    model_hints: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_format: Mapped[str | None] = mapped_column(String(200), nullable=True)
    difficulty: Mapped[str] = mapped_column(String(20), default="beginner")
    prompt_type: Mapped[str] = mapped_column(String(20), default="template")
    disclaimer: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(200), default="user")
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    license: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    tags_text: Mapped[str] = mapped_column(Text, default="")  # denormalised for FTS
    body_hash: Mapped[str] = mapped_column(String(64), index=True, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now, onupdate=_now)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    category: Mapped[Category | None] = relationship()
    tags: Mapped[list[Tag]] = relationship(secondary=prompt_tag)
    revisions: Mapped[list[PromptRevision]] = relationship(
        back_populates="prompt", cascade="all, delete-orphan", order_by="PromptRevision.version"
    )


class PromptRevision(Base):
    __tablename__ = "prompt_revision"
    __table_args__ = (UniqueConstraint("prompt_id", "version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prompt_id: Mapped[str] = mapped_column(ForeignKey("prompt.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_now)

    prompt: Mapped[Prompt] = relationship(back_populates="revisions")
