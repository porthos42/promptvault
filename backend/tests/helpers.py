from typing import Any

from fastapi.testclient import TestClient

BASE = {"title": "Resume Bullet Rewriter", "body": "Rewrite {{bullet}} for {{job_title}}"}


def make(client: TestClient, **over: object) -> dict[str, Any]:
    r = client.post("/api/v1/prompts", json={**BASE, **over})
    assert r.status_code == 201, r.text
    result: dict[str, Any] = r.json()
    return result
