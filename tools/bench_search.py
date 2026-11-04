"""Search + filter performance benchmark (recorded, not gated) and cold-start check.

Seeds a synthetic library (default 10,000 prompts) into a temporary SQLite
database, then times the search service with and without filters and a cold
server start (serve -> health endpoint ready). Results are printed as JSON on
stdout so the Implementation Log can quote exact numbers.

Usage (from backend/):
    uv run --no-sync python ../tools/bench_search.py [--rows 10000] [--repeats 30]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from promptvault.config import Settings
from promptvault.db import run_migrations
from promptvault.services import categories as cat_svc
from promptvault.services import prompts as svc
from promptvault.services.prompts import ListFilters


def seed(session, rows: int) -> None:
    """Seed a synthetic library: varied titles/bodies, a few categories and tags."""
    words = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota", "kappa"]
    # The categories must exist before prompts can reference them.
    for i in range(8):
        cat_svc.create_category(session, {"name": f"cat-{i}", "slug": f"cat-{i}"})
    session.commit()
    created = 0
    for i in range(rows):
        w1, w2 = words[i % len(words)], words[(i * 7 + 3) % len(words)]
        body = (
            f"Benchmark prompt {i}: a synthetic row for the {w1} workload. "
            f"It carries a {{variable}} placeholder and enough body text to make "
            f"the FTS index realistic. The {w2} scenario is covered too."
        )
        data = {
            "title": f"{w1.title()} benchmark {i}",
            "body": body,
            "category": f"cat-{i % 8}",
            "tags": [w1, w2],
        }
        svc.create_prompt(session, data)
        created += 1
        if created % 1000 == 0:
            session.commit()
    session.commit()


def time_search(session, query: str, repeats: int, **filters) -> list[float]:
    """Run a search `repeats` times, returning per-call seconds."""
    times = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        svc.list_prompts(session, ListFilters(q=query, **filters), limit=20)
        times.append(time.perf_counter() - t0)
    return times


def stats(times: list[float]) -> dict[str, float]:
    xs = sorted(times)
    n = len(xs)
    return {
        "p50_ms": round(statistics.median(xs) * 1000, 1),
        "p95_ms": round(xs[int(n * 0.95)] * 1000, 1),
        "max_ms": round(xs[-1] * 1000, 1),
    }


def cold_start(data_dir: Path) -> float:
    """Start `promptvault serve`, time until the health endpoint answers."""
    t0 = time.perf_counter()
    # The package has no __main__; start the venv console script directly —
    # the real production path, without `uv run` resolver overhead.
    script = Path(sys.executable).parent / ("promptvault.exe" if os.name == "nt" else "promptvault")
    proc = subprocess.Popen(
        [str(script), "serve", "--host", "localhost", "--port", "8901"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        while time.perf_counter() - t0 < 30:
            try:
                with urllib.request.urlopen("http://localhost:8901/api/v1/health", timeout=1) as r:
                    if r.status == 200:
                        return time.perf_counter() - t0
            except OSError:
                time.sleep(0.05)
        return float("inf")
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=10_000)
    ap.add_argument("--repeats", type=int, default=30)
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="pv-bench-"))
    try:
        settings = Settings(data_dir=tmp, _env_file=None)
        engine = create_engine(settings.resolved_database_url)
        run_migrations(settings.resolved_database_url)
        Session = sessionmaker(engine)
        with Session() as session:
            t0 = time.perf_counter()
            seed(session, args.rows)
            seed_s = round(time.perf_counter() - t0, 1)
            session.commit()

            # Warm up the FTS machinery once, then measure.
            svc.list_prompts(session, ListFilters(q="alpha"), limit=20)
            results = {
                "rows": args.rows,
                "seed_seconds": seed_s,
                "search": stats(time_search(session, "alpha", args.repeats)),
                "search_wide": stats(time_search(session, "benchmark", args.repeats)),
                "search_plus_filter": stats(
                    time_search(session, "alpha", args.repeats, category="cat-1")
                ),
            }
        engine.dispose()
        results["cold_start_seconds"] = round(cold_start(tmp), 2)
        print(json.dumps(results, indent=2))
        ok = results["search_plus_filter"]["p95_ms"] < 50 and results["cold_start_seconds"] < 3
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
