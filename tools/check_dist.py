#!/usr/bin/env python3
"""Inspect the built wheel and sdist: the UI, the seed library, migrations and the license must be
in, tests and node_modules must not. Stdlib only.

    python tools/check_dist.py [DIST_DIR]        # default: backend/dist
"""

from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MIN_SEED = 213


def seed_count(names: list[str], prefix: str) -> int:
    return sum(
        1
        for n in names
        if n.startswith(prefix)
        and n.endswith(".yaml")
        and n != prefix + "categories.yaml"
        and n.count("/") == prefix.count("/") + 1
    )


def check(names: list[str], pkg: str, label: str, errors: list[str]) -> None:
    def need(cond: bool, msg: str) -> None:
        print(("ok:   " if cond else "FAIL: ") + f"{label}: {msg}")
        if not cond:
            errors.append(f"{label}: {msg}")

    need(pkg + "static/index.html" in names, "static/index.html")
    need(sum(n.startswith(pkg + "static/assets/") for n in names) >= 2, "static/assets/*")
    n_seed = seed_count(names, pkg + "seed/")
    need(n_seed >= MIN_SEED, f"seed prompts ({n_seed}, want >= {MIN_SEED})")
    need(pkg + "seed/categories.yaml" in names, "seed/categories.yaml")
    need(any(n.startswith(pkg + "migrations/versions/") and n.endswith(".py") for n in names),
         "migrations/versions/*.py")
    need(pkg + "migrations/env.py" in names, "migrations/env.py")
    need(pkg + "cli.py" in names and pkg + "main.py" in names, "app modules")
    need(not any("/tests/" in n or n.startswith("tests/") for n in names), "no tests")
    need(not any("node_modules" in n for n in names), "no node_modules")
    need(not any(n.endswith((".pyc", ".db")) for n in names), "no .pyc / .db files")


def main() -> int:
    dist = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "backend" / "dist"
    wheels = sorted(dist.glob("*.whl"))
    sdists = sorted(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        print(f"FAIL: expected one wheel and one sdist in {dist}, found {len(wheels)}/{len(sdists)}")
        return 1
    errors: list[str] = []

    with zipfile.ZipFile(wheels[0]) as zf:
        names = zf.namelist()
        check(names, "promptvault/", "wheel", errors)
        meta = [n for n in names if n.endswith(".dist-info/METADATA")]
        lic = [n for n in names if "/licenses/" in n and n.endswith("LICENSE")]
        ok = bool(lic)
        print(("ok:   " if ok else "FAIL: ") + "wheel: license file in dist-info")
        if not ok:
            errors.append("wheel: license file")
        text = zf.read(meta[0]).decode("utf-8")
        for needle in ("Name: prompt-vault", "License-Expression: MIT", "Provides-Extra: xlsx",
                       "Provides-Extra: all", "Requires-Python: >=3.11"):
            ok = needle in text
            print(("ok:   " if ok else "FAIL: ") + f"wheel metadata: {needle}")
            if not ok:
                errors.append(f"wheel metadata: {needle}")
        entry = [n for n in names if n.endswith("entry_points.txt")]
        ok = bool(entry) and "promptvault = promptvault.cli:app" in zf.read(entry[0]).decode()
        print(("ok:   " if ok else "FAIL: ") + "wheel: console script promptvault")
        if not ok:
            errors.append("wheel: console script")

    with tarfile.open(sdists[0]) as tf:
        raw = tf.getnames()
        top = raw[0].split("/")[0]
        names = [n[len(top) + 1 :] for n in raw if n.startswith(top + "/")]
        check(names, "src/promptvault/", "sdist", errors)
        for must in ("LICENSE", "README.md", "pyproject.toml", "hatch_build.py", "PKG-INFO"):
            ok = must in names
            print(("ok:   " if ok else "FAIL: ") + f"sdist: {must}")
            if not ok:
                errors.append(f"sdist: {must}")

    print(f"wheel {wheels[0].stat().st_size / 1024:.0f} KiB, sdist {sdists[0].stat().st_size / 1024:.0f} KiB")
    if errors:
        print(f"{len(errors)} check(s) failed")
        return 1
    print("dist OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
