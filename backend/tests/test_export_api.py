"""Export API: downloads, headers, streaming, caps, single-prompt export and the share snippet."""

from __future__ import annotations

import csv
import importlib.util
import io
import json
import random
import re
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.helpers import make

from promptvault.config import Settings
from promptvault.main import create_app
from promptvault.services import prompts as prompt_svc

EXPORT = "/api/v1/export"
DISPOSITION = re.compile(r'^attachment; filename="promptvault-export-\d{8}\.(json|csv|xlsx|zip)"$')


def get(client: TestClient, fmt: str, **params: Any) -> Any:
    return client.get(EXPORT, params={"format": fmt, **params})


@pytest.fixture
def small(client: TestClient) -> TestClient:
    client.post("/api/v1/categories", json={"name": "Top", "slug": "top"})
    make(client, title="Alpha", body="alpha body {{x}}", category="top", tags=["a"])
    make(client, title="Beta", body="beta body words", tags=["b"], is_favorite=True)
    gone = make(client, title="Gamma", body="gamma body text")
    client.delete(f"/api/v1/prompts/{gone['id']}")
    return client


def test_format_list(client: TestClient) -> None:
    r = client.get("/api/v1/export/formats")
    assert r.status_code == 200
    by_name = {f["name"]: f for f in r.json()}
    assert list(by_name) == ["json", "csv", "xlsx", "markdown"]
    assert by_name["markdown"]["extension"] == "zip" and by_name["json"]["available"]


@pytest.mark.parametrize(
    ("fmt", "media_type"),
    [
        ("json", "application/json"),
        ("csv", "text/csv; charset=utf-8"),
        ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("markdown", "application/zip"),
        ("md", "application/zip"),
    ],
)
def test_headers_per_format(small: TestClient, fmt: str, media_type: str) -> None:
    if fmt == "xlsx":
        pytest.importorskip("openpyxl")
    r = get(small, fmt)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == media_type
    assert DISPOSITION.match(r.headers["content-disposition"]), r.headers["content-disposition"]
    assert r.headers["x-export-count"] == "2"  # Gamma is in Trash
    assert (
        r.headers["cache-control"] == "no-store"
        and r.headers["x-content-type-options"] == "nosniff"
    )
    assert len(r.content) > 0


def test_contents_json_csv_zip(small: TestClient) -> None:
    doc = get(small, "json", pretty=True).json()
    assert [p["title"] for p in doc["prompts"]] == ["Alpha", "Beta"] and doc["count"] == 2
    assert doc["filters"] == {}
    rows = list(csv.DictReader(io.StringIO(get(small, "csv").content.decode("utf-8-sig"))))
    assert [r["title"] for r in rows] == ["Alpha", "Beta"]
    assert get(small, "csv", bom=False).content[:3] != b"\xef\xbb\xbf"
    z = zipfile.ZipFile(io.BytesIO(get(small, "markdown").content))
    assert sorted(z.namelist()) == ["top/alpha.md", "uncategorised/beta.md"]


def test_filters_trash_and_ids(small: TestClient) -> None:
    def titles(**params: Any) -> list[str]:
        r = get(small, "json", **params)
        assert r.status_code == 200, r.text
        return [p["title"] for p in r.json()["prompts"]]

    assert titles(category="top") == ["Alpha"]
    assert titles(tags=["b"]) == ["Beta"]
    assert titles(favorite=True) == ["Beta"]
    assert titles(q="gamma") == []
    assert titles(include_trashed="true") == ["Alpha", "Beta", "Gamma"]
    assert titles(q="gamma", include_trashed="true") == ["Gamma"]
    assert get(small, "json", category="top").json()["filters"] == {"category": "top"}
    ids = [p["id"] for p in get(small, "json").json()["prompts"]]
    assert titles(ids=ids[:1]) == ["Alpha"]
    r = get(small, "json", ids=[ids[0], "unknown-id"])
    assert r.json()["count"] == 1 and r.headers["x-export-missing"] == "1"
    assert get(small, "json", category="nope").status_code == 404
    assert get(small, "json", difficulty="expert").status_code == 422


def test_empty_selection_is_an_empty_export(client: TestClient) -> None:
    for fmt in ("json", "csv", "markdown"):
        r = get(client, fmt)
        assert r.status_code == 200 and r.headers["x-export-count"] == "0", fmt
    assert get(client, "json").json()["prompts"] == []
    assert zipfile.ZipFile(io.BytesIO(get(client, "markdown").content)).namelist() == []


def test_unknown_format_422_and_unavailable_xlsx_404(
    small: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    r = get(small, "pdf")
    assert r.status_code == 422 and "Unknown export format" in r.json()["detail"]
    assert r.headers["content-type"].startswith("application/problem+json")
    assert small.get(EXPORT).status_code == 422  # format is required
    real = importlib.util.find_spec
    monkeypatch.setattr(
        "importlib.util.find_spec", lambda n, *a: None if n == "openpyxl" else real(n, *a)
    )
    r = get(small, "xlsx")
    assert r.status_code == 404 and "promptvault[xlsx]" in r.json()["detail"]
    listed = {f["name"]: f for f in small.get("/api/v1/export/formats").json()}
    assert listed["xlsx"]["available"] is False and "xlsx" in listed["xlsx"]["reason"]
    assert get(small, "json").status_code == 200


def test_xlsx_warnings_header(client: TestClient) -> None:
    pytest.importorskip("openpyxl")
    make(client, title="Huge", body="x" * 40_000)
    r = get(client, "xlsx")
    assert r.status_code == 200 and r.headers["x-export-warnings"] == "1"


def test_post_export_with_ids_and_filters(small: TestClient) -> None:
    ids = [p["id"] for p in get(small, "json").json()["prompts"]]
    r = small.post(EXPORT, json={"format": "json", "ids": ids[::-1]})
    assert [p["title"] for p in r.json()["prompts"]] == ["Alpha", "Beta"]  # title order, not input
    r = small.post(EXPORT, json={"format": "csv", "filters": {"tags": ["a"]}, "bom": False})
    assert r.status_code == 200 and r.content.startswith(b"title,")
    r = small.post(EXPORT, json={"format": "json", "include_trashed": True})
    assert r.headers["x-export-count"] == "3"
    many = [f"id-{i}" for i in range(501)]
    r = small.post(EXPORT, json={"format": "json", "ids": many})
    assert r.status_code == 422
    assert small.post(EXPORT, json={"format": "json", "ids": []}).status_code == 422
    assert small.post(EXPORT, json={"format": "nope"}).status_code == 422


def test_row_cap_is_a_413(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, export_max_rows=2, _env_file=None)  # type: ignore[call-arg]
    with TestClient(create_app(settings)) as c:
        for i in range(3):
            make(c, title=f"p{i}", body=f"body {i} zebra")
        r = get(c, "json")
        assert r.status_code == 413 and "PV_EXPORT_MAX_ROWS" in r.json()["detail"]
        assert get(c, "json", tags=["none"]).status_code == 200  # a narrower selection fits
        assert get(c, "json", q="p1").status_code == 200
        assert c.post(EXPORT, json={"format": "csv"}).status_code == 413


def fill(client: TestClient, n: int) -> None:
    """n prompts with distinct random bodies, straight through the service (fast)."""
    rng = random.Random(3)
    with client.app.state.session_factory() as session:  # type: ignore[attr-defined]
        for i in range(n):
            words = " ".join(f"w{rng.getrandbits(32):08x}" for _ in range(30))
            prompt_svc.create_prompt(session, {"title": f"Prompt {i:05d}", "body": words})
        session.commit()


def test_two_thousand_prompts_stream_in_pieces(client: TestClient) -> None:
    fill(client, 2000)
    with client.stream("GET", EXPORT, params={"format": "json"}) as r:
        assert r.status_code == 200 and r.headers["x-export-count"] == "2000"
        assert "content-length" not in r.headers  # streamed, not buffered
        chunks = list(r.iter_bytes())
    assert len(chunks) > 3
    doc = json.loads(b"".join(chunks))
    assert doc["count"] == 2000 == len(doc["prompts"])
    assert [p["title"] for p in doc["prompts"]] == [f"Prompt {i:05d}" for i in range(2000)]
    rows = list(csv.DictReader(io.StringIO(get(client, "csv").content.decode("utf-8-sig"))))
    assert len(rows) == 2000 and rows[1999]["title"] == "Prompt 01999"
    z = zipfile.ZipFile(io.BytesIO(get(client, "markdown").content))
    assert len(z.namelist()) == 2000 and z.testzip() is None


# ---- one prompt ----------------------------------------------------------------------------


def one(client: TestClient, **over: Any) -> dict[str, Any]:
    return make(client, **over)


def test_single_prompt_export_in_every_format(client: TestClient) -> None:
    p = one(client, title="Résumé: Tips!", body="Body {{x}}", description="d", license="MIT")
    url = f"/api/v1/prompts/{p['id']}/export"
    r = client.get(url, params={"format": "json"})
    assert r.status_code == 200 and r.json()["count"] == 1
    assert r.headers["content-disposition"] == 'attachment; filename="promptvault-resume-tips.json"'
    r = client.get(url, params={"format": "csv"})
    assert r.headers["content-disposition"].endswith('resume-tips.csv"')
    assert r.content.decode("utf-8-sig").splitlines()[1].startswith("Résumé: Tips!,Body {{x}}")
    r = client.get(url, params={"format": "markdown"})  # one prompt: a plain .md file, no ZIP
    assert r.headers["content-type"] == "text/markdown; charset=utf-8"
    assert r.headers["content-disposition"] == 'attachment; filename="promptvault-resume-tips.md"'
    assert r.text.startswith("---\ntitle: 'Résumé: Tips!'\n") and r.text.endswith("Body {{x}}\n")
    if importlib.util.find_spec("openpyxl"):
        assert client.get(url, params={"format": "xlsx"}).content[:2] == b"PK"


def test_single_prompt_404_for_unknown_and_trashed(client: TestClient) -> None:
    p = one(client, title="Gone", body="going away")
    client.delete(f"/api/v1/prompts/{p['id']}")
    for pid in (p["id"], "no-such-id"):
        assert (
            client.get(f"/api/v1/prompts/{pid}/export", params={"format": "json"}).status_code
            == 404
        )
        assert client.get(f"/api/v1/prompts/{pid}/share").status_code == 404
    assert client.get("/api/v1/prompts/x/export").status_code == 422  # format missing


# ---- share ---------------------------------------------------------------------------------


def test_share_snippet_api(client: TestClient) -> None:
    p = one(
        client,
        title="Greeter",
        body="Say hi to {{name}} in {{lang}}.",
        license="MIT",
        source_url="https://example.org/g",
    )
    url = f"/api/v1/prompts/{p['id']}/share"
    r = client.get(url)
    assert r.status_code == 200
    out = r.json()
    assert out["format"] == "markdown" and out["missing"] == ["name", "lang"]
    assert out["text"].startswith("### Greeter\n\n```text\nSay hi to {{name}}")
    assert "_License: MIT | Source: https://example.org/g_" in out["text"]
    r = client.get(url, params={"format": "text", "values": ["name=Ada", "lang=a=b"]})
    out = r.json()
    assert out["missing"] == [] and "Say hi to Ada in a=b." in out["text"]
    out = client.get(url, params={"format": "json", "values": "name=Ada"}).json()
    assert (
        out["missing"] == ["lang"]
        and json.loads(out["text"])["body"] == "Say hi to Ada in {{lang}}."
    )
    assert client.get(url, params={"values": "nope=1"}).status_code == 422
    assert client.get(url, params={"values": "no-equals-sign"}).status_code == 422
    assert client.get(url, params={"format": "html"}).status_code == 422
