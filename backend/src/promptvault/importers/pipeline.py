"""The import pipeline: parse -> normalize -> validate -> dedupe -> preview -> commit.

`analyze()` and `preview()` never write. `plan()` turns analyzed rows plus the user's choices into
a list of job rows; `execute()` writes them (the caller owns the transaction).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from promptvault.importers import base, normalize
from promptvault.importers.base import PromptDraft
from promptvault.importers.dedupe import Deduper, Existing, Match
from promptvault.models import Category, Prompt
from promptvault.services import prompts as prompt_svc
from promptvault.services.errors import DomainError, PayloadTooLarge, ValidationFailed

log = logging.getLogger(__name__)

DupAction = Literal["skip", "replace", "keep_both"]
RowStatus = Literal["new", "duplicate", "invalid"]
# What commit will do with a row, and what it did.
Outcome = Literal["created", "replaced", "skipped", "invalid", "refused"]

LICENSE_REFUSAL = "license is missing or unclear; confirm it in the request to import this row"


@dataclass
class Row:
    index: int
    draft: PromptDraft
    status: RowStatus
    match: Match | None = None
    needs_license_confirm: bool = False


@dataclass(frozen=True)
class Defaults:
    """Request-level provenance for rows that lack their own (a whole file's license, say)."""

    license: str | None = None
    source_url: str | None = None

    def apply(self, draft: PromptDraft) -> None:
        if self.license and not (draft.license or "").strip():
            draft.license = self.license
        if self.source_url and not (draft.source_url or "").strip():
            draft.source_url = self.source_url


@dataclass
class CommitOptions:
    default_action: DupAction = "skip"
    actions: dict[int, DupAction] = field(default_factory=dict)  # row index -> action
    confirm_license: bool = False  # confirm every row with a missing/unclear license
    confirmed_rows: frozenset[int] = frozenset()  # or confirm individual rows


def match_dict(m: Match | None) -> dict[str, Any] | None:
    if m is None:
        return None
    return {
        "kind": m.kind,
        "score": round(m.score, 4),
        "title": m.title,
        "prompt_id": m.prompt_id,
        "batch_index": m.batch_index,
    }


def analyze(
    session: Session,
    importer_name: str,
    source: Any,
    max_rows: int,
    defaults: Defaults | None = None,
) -> list[Row]:
    """Parse, normalize, validate and dedupe. Reads the database, writes nothing.

    `defaults` (license, source_url) fill in only the rows that have none of their own."""
    importer = base.get(importer_name)
    try:
        drafts = importer.parse(source)
    except DomainError:
        raise
    except Exception as exc:  # importers are plugins; report their failures as 422s
        raise ValidationFailed(
            f"Importer '{importer_name}' could not parse the source: {exc}"
        ) from exc
    if len(drafts) > max_rows:
        raise PayloadTooLarge(f"Too many rows: {len(drafts)} (limit {max_rows})")

    categories = normalize.category_lookup(
        [(s, n) for s, n in session.execute(select(Category.slug, Category.name)).all()]
    )
    live = [
        Existing(i, t, b, h)
        for i, t, b, h in session.execute(
            select(Prompt.id, Prompt.title, Prompt.body, Prompt.body_hash).where(
                Prompt.deleted_at.is_(None)
            )
        ).all()
    ]
    trashed = {
        h: i
        for h, i in session.execute(
            select(Prompt.body_hash, Prompt.id).where(Prompt.deleted_at.is_not(None))
        ).all()
        if h
    }
    deduper = Deduper(live, trashed)

    rows: list[Row] = []
    for index, draft in enumerate(drafts):
        if defaults is not None:
            defaults.apply(draft)
        normalize.normalize(draft, categories)
        if not draft.errors:  # the importer already rejected this row
            normalize.validate(draft)
        if draft.errors:
            rows.append(Row(index, draft, "invalid"))
            continue
        result = deduper.check(index, draft.title, draft.body)
        if result.trashed_id:
            draft.warnings.append(
                f"same body as trashed prompt {result.trashed_id}; it stays in Trash and "
                "a new prompt is created"
            )
        rows.append(
            Row(
                index,
                draft,
                "duplicate" if result.match else "new",
                result.match,
                normalize.needs_license_confirm(draft),
            )
        )
    return rows


def preview(
    session: Session,
    importer_name: str,
    source: Any,
    max_rows: int,
    defaults: Defaults | None = None,
) -> list[Row]:
    """Dry run. Identical to analyze(); named for the API and guaranteed not to flush."""
    with session.no_autoflush:
        return analyze(session, importer_name, source, max_rows, defaults)


def plan(rows: list[Row], options: CommitOptions) -> list[dict[str, Any]]:
    """Decide per row what commit does. Returns the JSON rows stored on the job."""
    for index, action in options.actions.items():
        if not 0 <= index < len(rows):
            raise ValidationFailed(f"actions: row {index} does not exist")
        row = rows[index]
        if action == "replace" and row.match is not None and row.match.prompt_id is None:
            raise ValidationFailed(
                f"actions: row {index} duplicates an earlier row of this batch; "
                "it can be skipped or kept, not replaced"
            )
    out: list[dict[str, Any]] = []
    for row in rows:
        act: str
        reason: str | None = None
        if row.status == "invalid":
            act, reason = "invalid", "; ".join(row.draft.errors)
        else:
            if row.status == "duplicate":
                chosen = options.actions.get(row.index, options.default_action)
                if chosen == "replace" and (row.match is None or row.match.prompt_id is None):
                    chosen = "skip"  # a batch-internal duplicate cannot replace anything
                act = {"skip": "skip", "replace": "replace", "keep_both": "create"}[chosen]
            else:
                act = "create"
            confirmed = options.confirm_license or row.index in options.confirmed_rows
            if act in ("create", "replace") and row.needs_license_confirm and not confirmed:
                act, reason = "refuse", LICENSE_REFUSAL
        out.append(
            {
                "index": row.index,
                "status": row.status,
                "action": act,
                "reason": reason,
                "draft": row.draft.to_dict(),
                "match": match_dict(row.match),
                "outcome": None,
                "prompt_id": None,
            }
        )
    return out


def _write_data(draft: dict[str, Any], importer: str, *, replacing: bool) -> dict[str, Any]:
    """Fields handed to create/update. A replace only overwrites what the draft provides."""
    data: dict[str, Any] = {
        "title": draft["title"],
        "body": draft["body"],
        "source": f"import:{importer}",
        "source_url": draft.get("source_url"),
        "license": draft.get("license"),
    }
    for key in ("model_hints", "output_format", "disclaimer"):
        if draft.get(key) is not None or not replacing:
            data[key] = draft.get(key)
    for key in ("category", "difficulty", "prompt_type"):
        if draft.get(key):
            data[key] = draft[key]
    if draft.get("description") or not replacing:
        data["description"] = draft.get("description") or ""
    if draft.get("tags") or not replacing:
        data["tags"] = draft.get("tags") or []
    return data


def execute(
    session: Session,
    importer: str,
    rows: list[dict[str, Any]],
    on_row: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    """Write the planned rows. Never touches trashed prompts or categories. Mutates `rows`
    with each row's outcome and prompt id; the caller commits (or rolls back) the session."""
    for row in rows:
        action = row["action"]
        outcome: Outcome
        if action == "create":
            p = prompt_svc.create_prompt(
                session, _write_data(row["draft"], importer, replacing=False)
            )
            outcome, row["prompt_id"] = "created", p.id
        elif action == "replace":
            target_id = (row["match"] or {}).get("prompt_id")
            target = session.get(Prompt, target_id) if target_id else None
            if target is None or target.deleted_at is not None:
                outcome = "skipped"
                row["reason"] = "the prompt to replace was deleted or trashed since the preview"
            else:
                prompt_svc.update_prompt(
                    session, target, _write_data(row["draft"], importer, replacing=True)
                )
                outcome, row["prompt_id"] = "replaced", target.id
        elif action == "refuse":
            outcome = "refused"
        elif action == "invalid":
            outcome = "invalid"
        else:
            outcome = "skipped"
        row["outcome"] = outcome
        if on_row is not None:
            on_row(row)
