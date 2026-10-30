"""Opt-in benchmark (PV_PERF=1): search latency at 10k prompts. Target: p95 < 50 ms.

The corpus has a Zipf-like vocabulary (a few very common words, a long tail of rare ones), like
real text. "Realistic" queries use words that appear in roughly 1-30% of prompts. The "broad"
query uses a word present in nearly every prompt, the worst case for BM25 ranking; it is
reported but not gated.
"""

import os
import random
import statistics
import time
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from promptvault.db import make_engine, make_session_factory, run_migrations
from promptvault.services import prompts as svc

pytestmark = pytest.mark.skipif(not os.environ.get("PV_PERF"), reason="set PV_PERF=1 to run")


def _make_vocab(n: int) -> list[str]:
    """Distinct pseudo-words (4-9 letters), so prefix expansion is as small as in real text."""
    rnd = random.Random(7)
    seen: set[str] = set()
    while len(seen) < n:
        seen.add("".join(rnd.choices("abcdefghijklmnopqrstuvwxyz", k=rnd.randint(4, 9))))
    return sorted(seen, key=lambda w: rnd.random())


VOCAB = _make_vocab(5000)
WEIGHTS = [1 / (i + 1) for i in range(len(VOCAB))]
REALISTIC = [
    VOCAB[40],
    VOCAB[120],
    f"{VOCAB[300]} {VOCAB[60]}",
    VOCAB[80],
    f'"{VOCAB[20]} {VOCAB[21]}"',
    VOCAB[15][:5],
]
BROAD = [VOCAB[2]]


def _build(tmp_path: Path):  # type: ignore[no-untyped-def]
    url = f"sqlite:///{(tmp_path / 'perf.db').as_posix()}"
    run_migrations(url)
    engine = make_engine(url)
    rnd = random.Random(1)

    def words(k: int) -> str:
        return " ".join(rnd.choices(VOCAB, WEIGHTS, k=k))

    rows = [
        {
            "id": str(uuid.uuid4()),
            "title": words(4),
            "body": words(80),
            "description": words(12),
            "variables": "[]",
            "tags_text": words(3),
            "created_at": "2026-01-01 00:00:00",
            "updated_at": f"2026-01-01 00:{i // 600:02d}:00",
        }
        for i in range(10_000)
    ]
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO prompt (id, title, body, description, variables, tags_text, "
                "created_at, updated_at) VALUES (:id, :title, :body, :description, :variables, "
                ":tags_text, :created_at, :updated_at)"
            ),
            rows,
        )
    return make_session_factory(engine)()


def _measure(session, queries: list[str]) -> list[float]:  # type: ignore[no-untyped-def]
    timings = []
    for _ in range(10):
        for q in queries:
            t0 = time.perf_counter()
            res = svc.list_prompts(session, svc.ListFilters(q=q), 50)
            timings.append((time.perf_counter() - t0) * 1000)
            assert res.total > 0, q
    return sorted(timings)


def test_search_latency_10k(tmp_path: Path) -> None:
    session = _build(tmp_path)
    realistic = _measure(session, REALISTIC)
    broad = _measure(session, BROAD)
    p95 = realistic[int(len(realistic) * 0.95) - 1]
    print(
        f"\nrealistic queries over 10k prompts: median {statistics.median(realistic):.1f} ms, "
        f"p95 {p95:.1f} ms | broad query (term in ~all prompts): "
        f"median {statistics.median(broad):.1f} ms"
    )
    assert p95 < 50
