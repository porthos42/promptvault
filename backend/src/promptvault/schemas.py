"""Pydantic request/response models for the HTTP API and CLI."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Difficulty = Literal["beginner", "intermediate", "advanced"]
PromptType = Literal["system", "user", "template", "chain"]
VariableType = Literal["text", "textarea", "number", "select"]


class VariableSpec(BaseModel):
    name: str
    label: str | None = None
    type: VariableType = "text"
    default: str | None = None
    options: list[str] = Field(default_factory=list)


class CategoryRef(BaseModel):
    slug: str
    name: str


class PromptCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1)
    description: str = ""
    category: str | None = Field(default=None, description="Category slug")
    tags: list[str] = Field(default_factory=list)
    variables: list[VariableSpec] | None = Field(
        default=None, description="Optional metadata; names are always auto-detected from body"
    )
    model_hints: str | None = None
    output_format: str | None = Field(default=None, max_length=200)
    difficulty: Difficulty = "beginner"
    prompt_type: PromptType = "template"
    disclaimer: str | None = None
    source: str = Field(default="user", max_length=200)
    source_url: str | None = Field(default=None, max_length=1000)
    license: str | None = Field(default=None, max_length=100)
    is_favorite: bool = False


class PromptPatch(BaseModel):
    """Partial update: only fields present in the request are changed."""

    title: str | None = Field(default=None, min_length=1, max_length=300)
    body: str | None = Field(default=None, min_length=1)
    description: str | None = None
    category: str | None = None
    tags: list[str] | None = None
    variables: list[VariableSpec] | None = None
    model_hints: str | None = None
    output_format: str | None = Field(default=None, max_length=200)
    difficulty: Difficulty | None = None
    prompt_type: PromptType | None = None
    disclaimer: str | None = None
    source: str | None = Field(default=None, max_length=200)
    source_url: str | None = Field(default=None, max_length=1000)
    license: str | None = Field(default=None, max_length=100)
    is_favorite: bool | None = None
    rating: int | None = Field(default=None, ge=1, le=5)


class PromptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    seed_id: str | None
    title: str
    body: str
    description: str
    category: CategoryRef | None
    tags: list[str]
    variables: list[dict[str, Any]]
    model_hints: str | None
    output_format: str | None
    difficulty: str
    prompt_type: str
    disclaimer: str | None
    source: str
    source_url: str | None
    license: str | None
    is_favorite: bool
    rating: int | None
    use_count: int
    version: int | None = None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class PromptList(BaseModel):
    items: list[PromptOut]
    total: int
    next_cursor: str | None


class RevisionOut(BaseModel):
    version: int
    created_at: datetime
    snapshot: dict[str, Any]


class RenderRequest(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)


class RenderOut(BaseModel):
    rendered: str
    missing: list[str]
    variables: list[dict[str, Any]]


class BulkRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)
    action: Literal[
        "add_tags", "remove_tags", "set_category", "favorite", "unfavorite", "delete", "restore"
    ]
    tags: list[str] = Field(default_factory=list)
    category: str | None = Field(default=None, description="Slug; null clears the category")


class BulkOut(BaseModel):
    affected: int
    not_found: list[str]


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=100)
    parent: str | None = Field(default=None, description="Parent category slug")
    icon: str | None = Field(default=None, max_length=50)
    sort_order: int = 0


class CategoryPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    parent: str | None = None
    icon: str | None = Field(default=None, max_length=50)
    sort_order: int | None = None


class CategoryOut(BaseModel):
    slug: str
    name: str
    parent: str | None
    icon: str | None
    sort_order: int
    prompt_count: int


class TagOut(BaseModel):
    name: str
    prompt_count: int


class TagRename(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class PurgeOut(BaseModel):
    purged: int
