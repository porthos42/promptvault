"""In-process import job runner: one worker thread, progress counters, restart recovery.

A job is one transaction. While it runs its counters live in memory (the open write transaction
would block progress commits on SQLite); the final counters, per-row outcomes and status are
persisted when it finishes. `view()` merges the two, so readers always see current progress.
"""

from __future__ import annotations

import copy
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, update
from sqlalchemy.orm import Session, sessionmaker

from promptvault.importers import pipeline
from promptvault.models import ImportJob
from promptvault.services.errors import NotFoundError

log = logging.getLogger(__name__)

TERMINAL = ("done", "failed")
COUNTERS = ("total", "processed", "created", "replaced", "skipped", "invalid", "refused")
_OUTCOME_COUNTER = {
    "created": "created",
    "replaced": "replaced",
    "skipped": "skipped",
    "invalid": "invalid",
    "refused": "refused",
}


def create_job(session: Session, importer: str, rows: list[dict[str, Any]]) -> ImportJob:
    job = ImportJob(importer=importer, status="pending", total=len(rows), drafts=rows)
    session.add(job)
    session.flush()
    return job


def prune_finished_jobs(session: Session, retention_days: int) -> int:
    """Drop finished (done/failed) jobs older than `retention_days` at startup.

    A negative value disables pruning. Running/pending jobs are never touched.
    """
    if retention_days < 0:
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    res = session.execute(
        delete(ImportJob).where(
            ImportJob.status.in_(TERMINAL),
            ImportJob.created_at < cutoff,
        )
    )
    return int(getattr(res, "rowcount", 0) or 0)


def fail_interrupted(session: Session) -> int:
    """Jobs left pending/running by a crash or restart can never finish; mark them failed."""
    res = session.execute(
        update(ImportJob)
        .where(ImportJob.status.in_(("pending", "running")))
        .values(status="failed", error="interrupted by a server restart")
    )
    return int(getattr(res, "rowcount", 0) or 0)


class JobRunner:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pv-import")
        self._live: dict[str, dict[str, int]] = {}
        self._lock = threading.Lock()

    # ---- running -----------------------------------------------------------------------

    def submit(self, job_id: str) -> None:
        """Run a committed (pending) job on the worker thread."""
        self._pool.submit(self._run_own_session, job_id)

    def run_now(self, session: Session, job_id: str) -> None:
        """Run a job synchronously on the caller's session (small imports)."""
        self._run(session, job_id)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=True, cancel_futures=True)

    def _run_own_session(self, job_id: str) -> None:
        with self._sf() as session:
            self._run(session, job_id)

    def _run(self, session: Session, job_id: str) -> None:
        job = session.get(ImportJob, job_id)
        if job is None:
            return
        counters: dict[str, int] = dict.fromkeys(COUNTERS, 0)
        counters["total"] = job.total
        with self._lock:
            self._live[job_id] = counters
        job.status = "running"
        session.commit()  # visible to readers before the write transaction starts
        rows = copy.deepcopy(job.drafts)

        def on_row(row: dict[str, Any]) -> None:
            with self._lock:
                counters["processed"] += 1
                counters[_OUTCOME_COUNTER[row["outcome"]]] += 1

        try:
            pipeline.execute(session, job.importer, rows, on_row)
            job.drafts = rows
            for key in COUNTERS:
                setattr(job, key, counters[key])
            job.status = "done"
            session.commit()
        except Exception as exc:
            log.exception("Import job %s failed", job_id)
            session.rollback()
            job = session.get(ImportJob, job_id)
            if job is not None:
                job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
                session.commit()
        finally:
            with self._lock:
                self._live.pop(job_id, None)

    # ---- reading -----------------------------------------------------------------------

    def view(self, job_id: str, *, results: bool = False) -> dict[str, Any]:
        """Current state of a job as a plain dict (live counters override stored ones)."""
        with self._sf() as session:
            job = session.get(ImportJob, job_id)
            if job is None:
                raise NotFoundError(f"Import job '{job_id}' not found")
            created_at: datetime = job.created_at
            out: dict[str, Any] = {
                "id": job.id,
                "importer": job.importer,
                "status": job.status,
                "error": job.error,
                "created_at": created_at,
                **{k: getattr(job, k) for k in COUNTERS},
            }
            if results:
                out["results"] = [
                    {k: r.get(k) for k in ("index", "outcome", "prompt_id", "reason")}
                    | {"title": r["draft"].get("title", "")}
                    for r in job.drafts
                    if r.get("outcome")
                ]
        with self._lock:
            live = self._live.get(job_id)
            if live is not None and out["status"] not in TERMINAL:
                out.update(live)
        return out
