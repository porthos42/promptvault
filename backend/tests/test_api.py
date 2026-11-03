import pytest
from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_version(client: TestClient) -> None:
    r = client.get("/api/v1/version")
    assert r.status_code == 200
    assert r.json()["version"]


def test_version_reports_build_revision(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PV_REVISION", raising=False)
    assert "revision" not in client.get("/api/v1/version").json()
    monkeypatch.setenv("PV_REVISION", "unknown")
    assert "revision" not in client.get("/api/v1/version").json()
    monkeypatch.setenv("PV_REVISION", "abc1234")
    assert client.get("/api/v1/version").json()["revision"] == "abc1234"


def test_openapi_docs(client: TestClient) -> None:
    assert client.get("/openapi.json").status_code == 200
