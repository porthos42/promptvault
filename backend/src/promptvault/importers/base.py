"""PromptDraft, the Importer protocol and the importer registry."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol, runtime_checkable

from promptvault.services.errors import NotFoundError


@dataclass
class PromptDraft:
    """One candidate prompt produced by an importer, before it is normalized or stored.

    `errors` (validation problems, row is not importable) and `warnings` (informational) are
    filled in by the pipeline, not by importers. `variables` is detected from the body.
    """

    title: str = ""
    body: str = ""
    description: str = ""
    category: str | None = None  # slug (or a name the pipeline maps to an existing slug)
    tags: list[str] = field(default_factory=list)
    difficulty: str | None = None
    prompt_type: str | None = None
    model_hints: str | None = None
    output_format: str | None = None
    disclaimer: str | None = None
    source_url: str | None = None
    license: str | None = None
    variables: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PromptDraft:
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})


@runtime_checkable
class Importer(Protocol):
    """A source format. `parse` only reads the source; the pipeline does everything else."""

    name: str

    def parse(self, source: Any) -> list[PromptDraft]: ...


class ImporterRegistry:
    def __init__(self) -> None:
        self._items: dict[str, Importer] = {}

    def register(self, importer: Importer, *, replace: bool = False) -> None:
        if not importer.name or not importer.name.replace("-", "").replace("_", "").isalnum():
            raise ValueError(f"Invalid importer name: {importer.name!r}")
        if importer.name in self._items and not replace:
            raise ValueError(f"Importer '{importer.name}' is already registered")
        self._items[importer.name] = importer

    def unregister(self, name: str) -> None:
        self._items.pop(name, None)

    def get(self, name: str) -> Importer:
        try:
            return self._items[name]
        except KeyError:
            known = ", ".join(sorted(self._items)) or "none"
            raise NotFoundError(f"Unknown importer '{name}' (available: {known})") from None

    def names(self) -> list[str]:
        return sorted(self._items)


registry = ImporterRegistry()


def register(importer: Importer, *, replace: bool = False) -> None:
    registry.register(importer, replace=replace)


def get(name: str) -> Importer:
    return registry.get(name)


def names() -> list[str]:
    return registry.names()
