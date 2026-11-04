"""Import API: preview (dry run), commit, jobs and the SSE progress stream."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from tests.helpers import make

from promptvault.config import Settings
from promptvault.main import create_app
from promptvault.models import ImportJob, Prompt, PromptRevision, Tag
from promptvault.services import prompts as svc

EDITOR = (
    "Review the following draft and point out unclear sentences, passive voice and weak verbs. "
    "Suggest a rewrite for each problem and explain why the change helps the reader. "
    "Keep the original meaning and the author's tone."
)
EDITOR_NEAR = EDITOR.replace("unclear", "unclean")
SQL = "Write a SQL query that returns the ten customers with the highest revenue in each region."
PREVIEW = "/api/v1/import/preview"
COMMIT = "/api/v1/import/commit"


def row(title: str, body: str, **extra: Any) -> dict[str, Any]:
    return {"title": title, "body": body, "license": "MIT", **extra}


def req(rows: list[Any], **extra: Any) -> dict[str, Any]:
    return {"importer": "passthrough", "source": rows, **extra}


def db_counts(client: TestClient) -> tuple[int, int, int, int]:
    with client.app.state.session_factory() as s:  # type: ignore[attr-defined]
        return (
            int(s.scalar(select(func.count()).select_from(Prompt)) or 0),
            int(s.scalar(select(func.count()).select_from(Tag)) or 0),
            int(s.scalar(select(func.count()).select_from(PromptRevision)) or 0),
            int(s.scalar(select(func.count()).select_from(ImportJob)) or 0),
        )


def sse_events(client: TestClient, job_id: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    with client.stream("GET", f"/api/v1/jobs/{job_id}/events") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        name = ""
        for line in r.iter_lines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                events.append((name, json.loads(line[6:])))
    return events


@pytest.fixture
def small_client(tmp_path: Path) -> Iterator[TestClient]:
    s = Settings(
        data_dir=tmp_path, import_max_rows=5, import_max_payload_bytes=2000, _env_file=None
    )  # type: ignore[call-arg]
    with TestClient(create_app(s)) as c:
        yield c


# ---- preview -----------------------------------------------------------------------------


def test_preview_reports_rows_and_writes_nothing(client: TestClient) -> None:
    existing = make(client, title="Editor", body=EDITOR)
    before = db_counts(client)
    r = client.post(
        PREVIEW,
        json=req(
            [
                row("Near copy", EDITOR_NEAR, tags=["New-Tag"]),
                row("Fresh", SQL, category="nope", tags=["Fresh-Tag"]),
                {"title": "No license", "body": "Some other body entirely about gardening."},
                row("", "no title"),
            ]
        ),
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert (out["total"], out["new"], out["duplicate"], out["invalid"]) == (4, 2, 1, 1)
    assert out["needs_license_confirm"] == 1
    near, fresh, nolic, bad = out["rows"]
    assert near["status"] == "duplicate"
    assert near["match"]["kind"] == "fuzzy" and near["match"]["prompt_id"] == existing["id"]
    assert fresh["status"] == "new" and fresh["draft"]["category"] is None
    assert "does not exist" in fresh["warnings"][0]
    assert nolic["needs_license_confirm"] is True
    assert bad["status"] == "invalid" and bad["errors"]
    assert db_counts(client) == before  # no prompts, tags, revisions or jobs


def test_preview_flags_in_batch_duplicates(client: TestClient) -> None:
    out = client.post(PREVIEW, json=req([row("One", SQL), row("Two", SQL)])).json()
    assert [r["status"] for r in out["rows"]] == ["new", "duplicate"]
    assert out["rows"][1]["match"] == {
        "kind": "exact",
        "score": 1.0,
        "title": "One",
        "prompt_id": None,
        "batch_index": 0,
    }


def test_errors_are_problem_json(client: TestClient, small_client: TestClient) -> None:
    r = client.post(PREVIEW, json=req([], importer="nope"))
    assert r.status_code == 404 and r.headers["content-type"].startswith("application/problem+json")
    assert client.post(PREVIEW, content=b"{not json").status_code == 422
    assert client.post(PREVIEW, json={"importer": "passthrough"}).status_code == 422
    assert (
        client.post(PREVIEW, json={"importer": "passthrough", "source": {"x": 1}}).status_code
        == 422
    )
    assert (
        client.post(COMMIT, json=req([row("A", SQL)], actions={"0": "explode"})).status_code == 422
    )
    r = client.post(COMMIT, json=req([row("A", SQL)], actions={"7": "skip"}))
    assert r.status_code == 422 and "does not exist" in r.json()["detail"]
    assert client.get("/api/v1/jobs/missing").status_code == 404
    assert client.get("/api/v1/jobs/missing/events").status_code == 404


def test_row_and_payload_caps(small_client: TestClient) -> None:
    rows = [row(f"T{i}", f"unique body number {i}") for i in range(6)]
    r = small_client.post(PREVIEW, json=req(rows))
    assert r.status_code == 413 and r.json()["title"] == "Payload too large"
    assert "Too many rows" in r.json()["detail"]
    big = req([row("Big", "x" * 5000)])
    for url in (PREVIEW, COMMIT):
        r = small_client.post(url, json=big)
        assert r.status_code == 413
        assert r.headers["content-type"].startswith("application/problem+json")
    assert small_client.post(PREVIEW, json=req(rows[:5])).status_code == 200


# ---- commit ------------------------------------------------------------------------------


def test_commit_creates_the_right_rows(client: TestClient) -> None:
    make(client, title="Editor", body=EDITOR)
    r = client.post(
        COMMIT,
        json=req(
            [
                row(
                    "Fresh",
                    SQL,
                    tags=["SQL"],
                    source_url="https://example.com/sql",
                    license="Apache-2.0",
                ),
                row("Dup", EDITOR_NEAR),
                row("", "bad"),
                {"title": "Unlicensed", "body": "Another body about sourdough starters."},
            ]
        ),
    )
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] == "done"
    assert (job["total"], job["processed"], job["created"]) == (4, 4, 1)
    assert (job["skipped"], job["invalid"], job["refused"], job["replaced"]) == (1, 1, 1, 0)
    assert [x["outcome"] for x in job["results"]] == ["created", "skipped", "invalid", "refused"]
    assert client.get(f"/api/v1/jobs/{job['id']}").json()["created"] == 1

    p = client.get(f"/api/v1/prompts/{job['results'][0]['prompt_id']}").json()
    assert p["source"] == "import:passthrough"
    assert p["source_url"] == "https://example.com/sql" and p["license"] == "Apache-2.0"
    assert p["tags"] == ["sql"] and p["version"] == 1
    assert client.get("/api/v1/prompts").json()["total"] == 2
    assert (
        client.get("/api/v1/prompts", params={"source": "import:passthrough"}).json()["total"] == 1
    )


def test_commit_license_confirmation(client: TestClient) -> None:
    rows = [{"title": "Unlicensed", "body": SQL}]
    assert client.post(COMMIT, json=req(rows)).json()["refused"] == 1
    assert client.get("/api/v1/prompts").json()["total"] == 0
    job = client.post(COMMIT, json=req(rows, confirm_license=True)).json()
    assert job["created"] == 1 and job["refused"] == 0


def test_replace_keeps_a_revision(client: TestClient) -> None:
    old = make(client, title="Old title", body=EDITOR, tags=["keep"])
    job = client.post(
        COMMIT,
        json=req([row("New title", EDITOR_NEAR)], actions={"0": "replace"}),
    ).json()
    assert job["replaced"] == 1 and job["results"][0]["prompt_id"] == old["id"]
    now = client.get(f"/api/v1/prompts/{old['id']}").json()
    assert (now["title"], now["body"], now["version"]) == ("New title", EDITOR_NEAR, 2)
    assert now["tags"] == ["keep"] and now["source"] == "import:passthrough"
    revs = client.get(f"/api/v1/prompts/{old['id']}/revisions").json()
    assert [r["version"] for r in revs] == [2, 1]
    assert revs[1]["snapshot"]["title"] == "Old title" and revs[1]["snapshot"]["body"] == EDITOR
    assert client.get("/api/v1/prompts").json()["total"] == 1


def test_keep_both_and_skip(client: TestClient) -> None:
    make(client, title="Editor", body=EDITOR)
    assert client.post(COMMIT, json=req([row("Copy", EDITOR)])).json()["skipped"] == 1
    assert client.get("/api/v1/prompts").json()["total"] == 1
    job = client.post(COMMIT, json=req([row("Copy", EDITOR)], default_action="keep_both")).json()
    assert job["created"] == 1
    assert client.get("/api/v1/prompts").json()["total"] == 2


def test_trashed_duplicates_are_not_resurrected(client: TestClient) -> None:
    gone = make(client, title="Gone", body=EDITOR)
    assert client.delete(f"/api/v1/prompts/{gone['id']}").status_code == 204
    for action in ("skip", "replace", "keep_both"):
        pv = client.post(PREVIEW, json=req([row("Back again", EDITOR)])).json()
        assert pv["rows"][0]["status"] == "new" and "Trash" in pv["rows"][0]["warnings"][0]
        job = client.post(
            COMMIT, json=req([row(f"Back {action}", EDITOR)], default_action=action)
        ).json()
        assert job["created"] == 1  # a new prompt, never the trashed one
        client.delete(f"/api/v1/prompts/{job['results'][0]['prompt_id']}")  # keep body reusable
    trash = client.get("/api/v1/prompts", params={"trash": True}).json()
    gone_now = next(p for p in trash["items"] if p["id"] == gone["id"])
    assert gone_now["title"] == "Gone" and gone_now["deleted_at"] is not None
    assert client.get(f"/api/v1/prompts/{gone['id']}/revisions").json()[0]["version"] == 1


# ---- jobs + SSE --------------------------------------------------------------------------


def test_small_commit_is_inline_and_large_commit_is_a_streamed_job(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = svc.create_prompt

    def slow(session: Any, data: dict[str, Any]) -> Any:
        time.sleep(0.04)
        return real(session, data)

    monkeypatch.setattr(svc, "create_prompt", slow)
    rows = [row(f"Prompt {i}", sha256(str(i).encode()).hexdigest() * 2) for i in range(30)]
    r = client.post(COMMIT, json=req(rows))
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["status"] in ("pending", "running") and job["total"] == 30

    events = sse_events(client, job["id"])
    names = [n for n, _ in events]
    assert names[-1] == "done" and names.count("done") == 1
    assert "progress" in names[:-1] and "failed" not in names
    processed = [d["processed"] for n, d in events if n == "progress"]
    assert processed == sorted(processed) and processed[-1] == 30
    assert any(0 < p < 30 for p in processed)  # saw it mid-flight
    final = events[-1][1]
    assert (final["status"], final["created"], final["processed"]) == ("done", 30, 30)

    again = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert again["status"] == "done" and len(again["results"]) == 30
    assert client.get("/api/v1/prompts", params={"limit": 1}).json()["total"] == 30
    # a finished job streams progress + done straight away
    assert [n for n, _ in sse_events(client, job["id"])] == ["progress", "done"]


def test_failed_job_ends_the_stream_with_failed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(session: Any, data: dict[str, Any]) -> Any:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(svc, "create_prompt", boom)
    rows = [row(f"P{i}", sha256(str(i).encode()).hexdigest() * 2) for i in range(30)]
    job = client.post(COMMIT, json=req(rows)).json()
    events = sse_events(client, job["id"])
    assert events[-1][0] == "failed" and "kaboom" in events[-1][1]["error"]
    assert client.get("/api/v1/prompts").json()["total"] == 0


class TestJobPruning:
    """`prune_finished_jobs` drops finished jobs older than N days at startup (M5)."""

    def test_prunes_old_finished_jobs_keeps_recent_and_running(self, client: TestClient) -> None:
        from datetime import UTC, datetime, timedelta

        from promptvault.importers.jobs import prune_finished_jobs

        with client.app.state.session_factory() as s:  # type: ignore[attr-defined]
            old_done = ImportJob(importer="passthrough", status="done", total=1)
            old_done.created_at = datetime.now(UTC) - timedelta(days=40)
            old_failed = ImportJob(importer="passthrough", status="failed", total=1)
            old_failed.created_at = datetime.now(UTC) - timedelta(days=40)
            fresh_done = ImportJob(importer="passthrough", status="done", total=1)
            running_old = ImportJob(importer="passthrough", status="running", total=1)
            running_old.created_at = datetime.now(UTC) - timedelta(days=40)
            s.add_all([old_done, old_failed, fresh_done, running_old])
            s.commit()

            assert prune_finished_jobs(s, 30) == 2
            s.commit()
            remaining = {j.status for j in s.scalars(select(ImportJob)).all()}
            assert remaining == {"done", "running"}

    def test_negative_retention_days_disables_pruning(self, client: TestClient) -> None:
        from promptvault.importers.jobs import prune_finished_jobs

        with client.app.state.session_factory() as s:  # type: ignore[attr-defined]
            s.add(ImportJob(importer="passthrough", status="done", total=0))
            s.commit()
            assert prune_finished_jobs(s, -1) == 0
            assert int(s.scalar(select(func.count()).select_from(ImportJob)) or 0) == 1
