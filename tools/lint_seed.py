#!/usr/bin/env python3
"""Lint the seed prompt library (docs/SPEC.md section 3.8).

Run from the repo root with the backend environment, which provides the linter:

    cd backend && uv run python ../tools/lint_seed.py [SEED_DIR] [--min-per-category N]

Exit code 0 = clean, 1 = problems found, 2 = seed directory missing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from promptvault.services.seedlint import lint_dir

REPO = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("seed_dir", nargs="?", type=Path, default=REPO / "seed")
    ap.add_argument(
        "--min-per-category",
        type=int,
        default=None,
        help="Override min_per_category from categories.yaml (the v1 target is 5)",
    )
    args = ap.parse_args()
    if not args.seed_dir.is_dir():
        print(f"seed directory not found: {args.seed_dir}", file=sys.stderr)
        return 2

    res = lint_dir(args.seed_dir, args.min_per_category)
    for e in res.errors:
        print(f"ERROR {e}")
    for n in res.notes:
        print(f"note: {n}")
    cats = len(res.counts)
    print(f"{res.files} prompt file(s) in {cats} categor{'y' if cats == 1 else 'ies'}: ", end="")
    print("OK" if res.ok else f"{len(res.errors)} problem(s)")
    return 0 if res.ok else 1


if __name__ == "__main__":
    sys.exit(main())
