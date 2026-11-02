"""Duplicate detection: exact normalized-body hash, then a cheap prefilter, then difflib.

`similarity()` is the only place that knows how fuzzy matching works, so rapidfuzz (or anything
else) can replace it in this one file. Order of checks for each draft: exact hash against live
prompts, fuzzy against live prompts, exact then fuzzy against earlier rows in the same batch.
Trashed prompts are never matched (they are only reported as a warning on exact hits).
"""

from __future__ import annotations

import bisect
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from promptvault.services.prompts import body_hash

FUZZY_THRESHOLD = 0.92  # spec 3.5; not tuned, review against real imports
MAX_COMPARE_CHARS = 8000  # only this much of a body takes part in fuzzy comparison
_TOKEN_FLOOR = 8  # token-overlap prefilter applies only to bodies with at least this many words
_TOKEN_JACCARD_MIN = 0.5

# SequenceMatcher.ratio() <= 2*min(la, lb)/(la+lb), so anything shorter than this ratio of the
# longer text can never reach the threshold.
MIN_LENGTH_RATIO = FUZZY_THRESHOLD / (2 - FUZZY_THRESHOLD)


def compare_text(body: str) -> str:
    """Case- and whitespace-insensitive form used for fuzzy comparison."""
    return " ".join(body.split()).lower()[:MAX_COMPARE_CHARS]


def similarity(a: str, b: str) -> float:
    """0..1 similarity of two compare_text() strings; 0.0 means 'clearly below the threshold'.

    Cheap checks (length ratio, token overlap, character multiset) run before the expensive
    SequenceMatcher pass. The length and character checks are exact upper bounds; the token
    check is a heuristic that only applies to longer bodies.
    """
    la, lb = len(a), len(b)
    if not la or not lb:
        return 1.0 if la == lb else 0.0
    if min(la, lb) / max(la, lb) < MIN_LENGTH_RATIO:
        return 0.0
    ta, tb = set(a.split()), set(b.split())
    if min(len(ta), len(tb)) >= _TOKEN_FLOOR and len(ta & tb) / len(ta | tb) < _TOKEN_JACCARD_MIN:
        return 0.0
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    if matcher.quick_ratio() < FUZZY_THRESHOLD:
        return 0.0
    return matcher.ratio()


def _may_overlap(a: frozenset[str], b: frozenset[str]) -> bool:
    """Token-overlap prefilter on precomputed sets (the corpus-scale form of the check that
    similarity() also makes), so scanning thousands of prompts does not re-tokenise each one."""
    small, large = (a, b) if len(a) <= len(b) else (b, a)
    if len(small) < _TOKEN_FLOOR:
        return True
    if len(small) / len(large) < _TOKEN_JACCARD_MIN:
        return False
    inter = len(small & large)
    return inter / (len(a) + len(b) - inter) >= _TOKEN_JACCARD_MIN


MatchKind = Literal["exact", "fuzzy"]


@dataclass(frozen=True)
class Match:
    kind: MatchKind
    score: float
    title: str
    prompt_id: str | None = None  # an existing (live) prompt
    batch_index: int | None = None  # an earlier row of the same batch


@dataclass(frozen=True)
class Existing:
    id: str
    title: str
    body: str
    body_hash: str


@dataclass
class DedupeResult:
    match: Match | None = None
    trashed_id: str | None = None  # exact hit on a prompt in Trash (informational only)


def _tokens(text: str) -> frozenset[str]:
    return frozenset(sys.intern(t) for t in text.split())


@dataclass
class _Entry:
    ref: str | int
    title: str
    text: str
    tokens: frozenset[str]


class _Corpus:
    """Texts kept sorted by length so a lookup only scans the lengths that can match."""

    def __init__(self) -> None:
        self._lengths: list[int] = []
        self._entries: list[_Entry] = []

    def add(self, entry: _Entry) -> None:
        pos = bisect.bisect_right(self._lengths, len(entry.text))
        self._lengths.insert(pos, len(entry.text))
        self._entries.insert(pos, entry)

    def best(self, text: str) -> tuple[_Entry, float] | None:
        tokens = _tokens(text)
        n = len(text)
        lo = bisect.bisect_left(self._lengths, int(n * MIN_LENGTH_RATIO))
        hi = bisect.bisect_right(self._lengths, int(n / MIN_LENGTH_RATIO) + 1)
        found: tuple[_Entry, float] | None = None
        for entry in self._entries[lo:hi]:
            if not _may_overlap(tokens, entry.tokens):  # same test as in similarity(), no re-split
                continue
            score = similarity(text, entry.text)
            if score >= FUZZY_THRESHOLD and (found is None or score > found[1]):
                found = (entry, score)
        return found


class Deduper:
    def __init__(self, live: Iterable[Existing], trashed_hashes: dict[str, str] | None = None):
        self._live_by_hash: dict[str, Existing] = {}
        self._live = _Corpus()
        for e in live:
            self._live_by_hash.setdefault(e.body_hash or body_hash(e.body), e)
            text = compare_text(e.body)
            self._live.add(_Entry(e.id, e.title, text, _tokens(text)))
        self._trashed = trashed_hashes or {}
        self._batch = _Corpus()
        self._batch_by_hash: dict[str, tuple[int, str]] = {}

    def check(self, index: int, title: str, body: str) -> DedupeResult:
        """Find what this row duplicates; a row with no match becomes a candidate for later rows."""
        digest = body_hash(body)
        hit = self._live_by_hash.get(digest)
        if hit is not None:
            return DedupeResult(Match("exact", 1.0, hit.title, prompt_id=hit.id))
        text = compare_text(body)
        fuzzy = self._live.best(text)
        if fuzzy is not None:
            entry, score = fuzzy
            return DedupeResult(Match("fuzzy", score, entry.title, prompt_id=str(entry.ref)))
        earlier = self._batch_by_hash.get(digest)
        if earlier is not None:
            return DedupeResult(Match("exact", 1.0, earlier[1], batch_index=earlier[0]))
        fuzzy = self._batch.best(text)
        if fuzzy is not None:
            entry, score = fuzzy
            return DedupeResult(Match("fuzzy", score, entry.title, batch_index=int(entry.ref)))
        self._batch_by_hash[digest] = (index, title)
        self._batch.add(_Entry(index, title, text, _tokens(text)))
        return DedupeResult(trashed_id=self._trashed.get(digest))
