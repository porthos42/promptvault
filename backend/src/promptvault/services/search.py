"""Full-text search helpers: safe FTS5 query building and typo correction."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)  # matches the unicode61 tokenizer
PHRASE_RE = re.compile(r'"([^"]*)"')
MAX_TERMS = 12


@dataclass
class ParsedQuery:
    terms: list[str]
    phrases: list[str]

    @property
    def empty(self) -> bool:
        return not self.terms and not self.phrases


def parse(q: str) -> ParsedQuery:
    """Split user input into words and "quoted phrases". Everything else is discarded, so no
    user input can inject FTS5 syntax."""
    phrases: list[str] = []

    def grab(m: re.Match[str]) -> str:
        words = TOKEN_RE.findall(m.group(1).lower())
        if words:
            phrases.append(" ".join(words))
        return " "

    rest = PHRASE_RE.sub(grab, q)
    terms = [t.lower() for t in TOKEN_RE.findall(rest)][:MAX_TERMS]
    return ParsedQuery(terms, phrases[:MAX_TERMS])


def _prefix(term: str) -> str:
    return f'"{term}"*'


def match_expression(p: ParsedQuery, alternatives: dict[str, list[str]] | None = None) -> str:
    """FTS5 MATCH string: every term must match (as a prefix); phrases must match exactly."""
    parts: list[str] = []
    for t in p.terms:
        alts = (alternatives or {}).get(t)
        if alts:
            parts.append("(" + " OR ".join(_prefix(x) for x in [t, *alts]) + ")")
        else:
            parts.append(_prefix(t))
    parts += [f'"{ph}"' for ph in p.phrases]
    return " AND ".join(parts)


def suggest(session: Session, p: ParsedQuery) -> tuple[dict[str, list[str]], str] | None:
    """Typo correction. For each query term that is not an indexed word, find similar indexed
    words. Returns (alternatives per term, corrected query text), or None if nothing is close."""
    vocab = [r[0] for r in session.execute(text("SELECT term FROM prompt_terms_vocab"))]
    known = set(vocab)
    alternatives: dict[str, list[str]] = {}
    corrected: list[str] = []
    for t in p.terms:
        if len(t) < 3 or t in known or any(v.startswith(t) for v in known if len(v) <= len(t) + 6):
            corrected.append(t)
            continue
        pool = [v for v in vocab if abs(len(v) - len(t)) <= 3]
        close = difflib.get_close_matches(t, pool, n=3, cutoff=0.75)
        if close:
            alternatives[t] = close
            corrected.append(close[0])
        else:
            corrected.append(t)
    if not alternatives:
        return None
    corrected += [f'"{ph}"' for ph in p.phrases]
    return alternatives, " ".join(corrected)
