"""PostgreSQL smoke test (EXPERIMENTAL support): migrations plus the main API paths.

    cd backend
    PV_PG_URL=postgresql+psycopg://user:pw@host:5432/db \
        uv run --extra postgres python ../tools/pg_smoke.py

Needs an empty database and the `postgres` extra. Search runs the substring fallback on
PostgreSQL (no FTS5), so only presence is checked, not ranking. Exits 1 on the first failure.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from promptvault.config import Settings
from promptvault.main import create_app

URL = os.environ.get("PV_PG_URL", "postgresql+psycopg://pv:pvtest@localhost:5432/pv")
checks = 0


def expect(name: str, cond: bool, detail: object = "") -> None:
    global checks
    checks += 1
    print(("ok:   " if cond else "FAIL: ") + name, detail if not cond else "")
    if not cond:
        sys.exit(1)


def main() -> None:
    settings = Settings(database_url=URL, data_dir=Path(tempfile.mkdtemp()))
    with TestClient(create_app(settings)) as c:
        api = "/api/v1"

        def get(path: str, **params: object) -> dict:
            r = c.get(api + path, params=params)
            expect(
                f"GET {path} {params or ''}", r.status_code == 200, (r.status_code, r.text[:200])
            )
            return r.json()

        expect("health", c.get(api + "/health").json() == {"status": "ok"})
        total = get("/prompts", limit=1)["total"]
        expect("seed library loaded", total >= 200, total)
        expect("substring search finds seeded prompts", get("/prompts", q="resume")["total"] > 0)
        expect("has_variables filter", get("/prompts", has_variables="true")["total"] > 0)
        for sort in ("newest", "updated", "recent", "popular", "rating", "title", "relevance"):
            get("/prompts", sort=sort, limit=3)
        get("/categories")
        get("/tags")

        r = c.post(
            api + "/prompts",
            json={"title": "PG smoke", "body": "Hello {{name}}", "tags": ["pgsmoke"]},
        )
        expect("create prompt", r.status_code == 201, r.text[:200])
        pid = r.json()["id"]
        expect("tag filter", get("/prompts", tags="pgsmoke")["total"] == 1)
        r = c.patch(f"{api}/prompts/{pid}", json={"title": "PG smoke 2"})
        expect("update prompt", r.status_code == 200, r.text[:200])
        revs = c.get(f"{api}/prompts/{pid}/revisions").json()
        expect("two revisions", len(revs) == 2, revs)
        expect("use", c.post(f"{api}/prompts/{pid}/use").status_code == 200)
        r = c.post(f"{api}/prompts/{pid}/render", json={"values": {"name": "x"}})
        expect("render", r.status_code == 200 and "Hello x" in r.text, r.text[:200])
        expect("trash", c.delete(f"{api}/prompts/{pid}").status_code == 204)
        expect("restore", c.post(f"{api}/prompts/{pid}/restore").status_code == 200)

        for fmt in ("json", "csv", "markdown"):
            r = c.get(api + "/export", params={"format": fmt})
            expect(f"export {fmt}", r.status_code == 200 and len(r.content) > 1000, r.status_code)
            expect(f"export {fmt} count", int(r.headers["x-export-count"]) == total + 1)
        r = c.get(api + "/export", params={"format": "xlsx"})
        expect("export xlsx (200, or 404 without the extra)", r.status_code in (200, 404))

        rows = [{"title": "PG import", "body": "A zebra-striped body", "license": "MIT"}]
        src = {"importer": "json", "source": {"content": json.dumps(rows)}}
        expect("import preview", c.post(api + "/import/preview", json=src).status_code == 200)
        r = c.post(api + "/import/commit", json=src)
        expect("import commit", r.status_code == 200 and r.json()["created"] == 1, r.text[:200])

        many = [
            {
                "title": f"Job {i}",
                "body": f"job body {i} zzyzx {i * 104729} lorem ipsum",
                "license": "MIT",
            }
            for i in range(60)
        ]
        r = c.post(
            api + "/import/commit",
            json={"importer": "json", "source": {"content": json.dumps(many)}},
        )
        expect("large import runs as a job", r.status_code == 202, r.text[:200])
        job = r.json()["id"]
        status = "running"
        for _ in range(100):
            status = c.get(f"{api}/jobs/{job}").json()["status"]
            if status != "running" and status != "pending":
                break
            time.sleep(0.2)
        expect("import job finishes", status == "done", status)
    print(f"PostgreSQL smoke test passed ({checks} checks)")


if __name__ == "__main__":
    main()
