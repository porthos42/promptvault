"""Hugging Face importer: rows of a public dataset through the datasets-server JSON API.

Source: a dataset URL string or {url, config?, split?, limit?, mapping?}. Accepted URLs:
`https://huggingface.co/datasets/<org>/<name>` (also `/datasets/<name>` for legacy ids, with a
trailing viewer/tree path). Columns map through the usual aliases and `mapping`; a dataset that
has no title column needs `mapping`, for example {"title": "act", "body": "prompt"}.

Only the JSON API is used (no parquet and no pyarrow). The license comes from the dataset card
(`cardData.license`, else a `license:` tag); a missing or `other` license makes rows need
confirmation. Gated and private datasets are refused: no Hugging Face token is accepted.
"""

from __future__ import annotations

import json
from typing import Any, get_args
from urllib.parse import quote, urlsplit

from promptvault.importers import net, sources, tabular
from promptvault.importers.base import PromptDraft
from promptvault.importers.json_import import JsonImporter
from promptvault.schemas import Difficulty, PromptType
from promptvault.services.errors import ValidationFailed

HUB = "https://huggingface.co"
SERVER = "https://datasets-server.huggingface.co"
PAGE = 100  # the rows API serves at most 100 rows per request
HF_HOSTS = ("huggingface.co", "www.huggingface.co")
PAGE_WORDS = frozenset(
    {"viewer", "tree", "blob", "resolve", "raw", "discussions", "commits", "settings", "edit"}
)
# Columns such as `type` or `level` are auto-matched to these fields but often mean something else
# in a dataset (`type: TEXT`). Unless the caller maps them explicitly, values that are not valid
# choices are dropped instead of making every row invalid.
LOOSE_CHOICES = {"prompt_type": set(get_args(PromptType)), "difficulty": set(get_args(Difficulty))}
UNCLEAR_LICENSES = frozenset({"", "other", "unknown", "none"})


def parse_dataset_id(url: str) -> str:
    try:
        parts = urlsplit(url.strip())
    except ValueError as exc:
        raise ValidationFailed("Not a valid Hugging Face URL") from exc
    segs = [s for s in parts.path.split("/") if s]
    if (
        parts.scheme.lower() not in ("http", "https")
        or (parts.hostname or "").lower() not in HF_HOSTS
        or len(segs) < 2
        or segs[0] != "datasets"
    ):
        raise ValidationFailed(
            "Expected a dataset URL like https://huggingface.co/datasets/<org>/<name>"
        )
    rest = segs[1:]
    ident = rest[0] if len(rest) == 1 or rest[1] in PAGE_WORDS else f"{rest[0]}/{rest[1]}"
    if not all(
        p
        and p not in (".", "..")
        and p.replace("-", "").replace("_", "").replace(".", "").isalnum()
        for p in ident.split("/")
    ):
        raise ValidationFailed("Not a valid Hugging Face dataset id")
    return ident


def _error_text(res: net.Fetched) -> str:
    try:
        data = json.loads(res.body)
        if isinstance(data, dict) and data.get("error"):
            return str(data["error"])[:200]
    except ValueError:
        pass
    return f"status {res.status}"


def _int_option(value: Any, name: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationFailed(f"{name} must be a whole number") from exc
    if number < 1:
        raise ValidationFailed(f"{name} must be at least 1")
    return number


def _card_license(card: dict[str, Any]) -> str | None:
    value = (card.get("cardData") or {}).get("license")
    if isinstance(value, list):
        value = ", ".join(str(v) for v in value)
    if not value:
        for tag in card.get("tags") or []:
            if isinstance(tag, str) and tag.startswith("license:"):
                value = tag.removeprefix("license:")
                break
    text = str(value or "").strip()
    return None if text.lower() in UNCLEAR_LICENSES else text[:100]


class HuggingFaceImporter:
    name = "huggingface"
    description = "Hugging Face dataset (public): rows via the datasets-server JSON API"

    def parse(self, source: Any) -> list[PromptDraft]:
        url = source if isinstance(source, str) else sources.option(source, "url")
        if not isinstance(url, str) or not url.strip():
            raise ValidationFailed("Hugging Face source needs a dataset `url`")
        mapping = tabular.parse_mapping(sources.option(source, "mapping"))
        config = sources.option(source, "config")
        split = sources.option(source, "split")
        fetcher = net.get_fetcher()
        max_rows = fetcher.config.max_rows
        limit = min(_int_option(sources.option(source, "limit"), "limit") or max_rows, max_rows)
        ident = parse_dataset_id(url)

        card = self._json(fetcher, f"{HUB}/api/datasets/{quote(ident, safe='/')}", ident)
        if card.get("private") or card.get("gated"):
            raise ValidationFailed(
                f"Dataset '{ident}' is gated or private; only public datasets can be imported"
            )
        license_ = _card_license(card)
        canonical = str(card.get("id") or ident)  # the hub redirects renamed datasets to the new id
        renamed = canonical != ident
        if renamed:
            ident = parse_dataset_id(f"{HUB}/datasets/{canonical}")
        config, split = self._config_split(fetcher, ident, config, split)
        rows, features, total, truncated = self._rows(fetcher, ident, config, split, limit)
        if not rows:
            raise ValidationFailed(f"Dataset '{ident}' ({config}/{split}) has no rows")

        drafts = JsonImporter().parse({"prompts": rows, "mapping": mapping})
        page_url = f"{HUB}/datasets/{ident}"
        headers = features or [k for k in rows[0] if isinstance(k, str)]
        columns, _ = tabular.resolve_columns(headers, mapping)
        used = {headers[i] for i in columns.values() if i < len(headers)}
        for draft, cells in zip(drafts, truncated, strict=True):
            if not (draft.source_url or "").strip():
                draft.source_url = page_url
            if license_ and not (draft.license or "").strip():
                draft.license = license_
            cut = sorted(used & set(cells))
            if cut:
                draft.errors.append(
                    f"column(s) {', '.join(cut)} were truncated by the datasets-server"
                )
        dropped = self._drop_foreign_choices(drafts, mapping)
        notes = [
            f"Hugging Face dataset {ident}: config '{config}', split '{split}', "
            f"{len(rows)} of {total} rows"
        ]
        if total > len(rows):
            notes.append(
                f"only the first {len(rows)} rows were fetched "
                "(option `limit`, up to PV_IMPORT_MAX_ROWS)"
            )
        notes.extend(dropped)
        if renamed:
            notes.insert(0, f"the dataset was renamed on Hugging Face; imported from '{ident}'")
        if license_ is None:
            notes.append("the dataset card has no clear license: rows need license confirmation")
        drafts[0].warnings.extend(notes)
        return drafts

    @staticmethod
    def _drop_foreign_choices(
        drafts: list[PromptDraft], mapping: dict[str, str] | None
    ) -> list[str]:
        notes: list[str] = []
        for fld, valid in LOOSE_CHOICES.items():
            if fld in (mapping or {}):
                continue
            bad = [d for d in drafts if (getattr(d, fld) or "").strip().lower() not in valid | {""}]
            for d in bad:
                setattr(d, fld, None)
            if bad:
                notes.append(f"ignored {len(bad)} {fld} value(s) that are not valid choices")
        return notes

    # -- API calls

    @staticmethod
    def _json(
        fetcher: net.Fetcher, url: str, ident: str, missing: str | None = None
    ) -> dict[str, Any]:
        res = fetcher.get(
            url,
            accept="application/json",
            allowed_types=("application/json",),
            raise_for_status=False,
        )
        if res.status == 200:
            try:
                data = json.loads(res.body)
            except ValueError as exc:
                raise net.FetchError("Hugging Face returned invalid JSON") from exc
            if isinstance(data, dict):
                return data
            raise net.FetchError("Hugging Face returned an unexpected response")
        if res.status in (401, 403):
            raise ValidationFailed(
                f"Dataset '{ident}' is gated or private; only public datasets can be imported"
            )
        if res.status == 404:
            raise ValidationFailed(missing or f"Hugging Face dataset '{ident}' was not found")
        raise net.FetchError(f"Hugging Face answered: {_error_text(res)}")

    def _config_split(
        self, fetcher: net.Fetcher, ident: str, config: Any, split: Any
    ) -> tuple[str, str]:
        if isinstance(config, str) and config and isinstance(split, str) and split:
            return config, split
        data = self._json(fetcher, f"{SERVER}/splits?dataset={quote(ident, safe='')}", ident)
        splits = [s for s in data.get("splits") or [] if isinstance(s, dict)]
        if config:
            splits = [s for s in splits if s.get("config") == config]
        if not splits:
            raise ValidationFailed(
                f"Dataset '{ident}' has no splits" + (f" for config '{config}'" if config else "")
            )
        chosen_config = str(config or splits[0].get("config"))
        names = [str(s.get("split")) for s in splits if s.get("config") == chosen_config]
        if split:
            if split not in names:
                raise ValidationFailed(f"Split '{split}' not found (available: {', '.join(names)})")
            return chosen_config, str(split)
        return chosen_config, "train" if "train" in names else names[0]

    def _rows(
        self, fetcher: net.Fetcher, ident: str, config: str, split: str, limit: int
    ) -> tuple[list[dict[str, Any]], list[str], int, list[list[str]]]:
        rows: list[dict[str, Any]] = []
        truncated: list[list[str]] = []
        features: list[str] = []
        total = 0
        while len(rows) < limit:
            length = min(PAGE, limit - len(rows))
            url = (
                f"{SERVER}/rows?dataset={quote(ident, safe='')}&config={quote(config, safe='')}"
                f"&split={quote(split, safe='')}&offset={len(rows)}&length={length}"
            )
            data = self._json(
                fetcher,
                url,
                ident,
                f"Config '{config}' / split '{split}' was not found in dataset '{ident}'",
            )
            if not features:
                features = [
                    str(f.get("name")) for f in data.get("features") or [] if isinstance(f, dict)
                ]
            total = int(data.get("num_rows_total") or total or 0)
            page = [
                r
                for r in data.get("rows") or []
                if isinstance(r, dict) and isinstance(r.get("row"), dict)
            ]
            if not page:
                break
            for item in page:
                rows.append(item["row"])
                truncated.append([str(c) for c in item.get("truncated_cells") or []])
            if len(rows) >= total:
                break
        return rows, features, max(total, len(rows)), truncated
