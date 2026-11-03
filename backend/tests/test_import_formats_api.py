"""Import API with the concrete importers: base64 sources, mapping, defaults, license gate."""

from __future__ import annotations

import base64
import io
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.helpers import make

from promptvault import importers
from promptvault.config import Settings
from promptvault.main import create_app

PREVIEW = "/api/v1/import/preview"
COMMIT = "/api/v1/import/commit"
DATA = Path(__file__).parent / "data" / "import"


def req(importer: str, source: Any, **extra: Any) -> dict[str, Any]:
    return {"importer": importer, "source": source, **extra}


def b64(data: bytes, **extra: Any) -> dict[str, Any]:
    return {"content_base64": base64.b64encode(data).decode("ascii"), **extra}


def total(client: TestClient) -> int:
    return int(client.get("/api/v1/prompts", params={"limit": 1}).json()["total"])


def test_importer_list(client: TestClient) -> None:
    r = client.get("/api/v1/import/importers")
    assert r.status_code == 200
    by_name = {i["name"]: i for i in r.json()}
    assert {"json", "csv", "markdown", "clipboard", "xlsx", "passthrough"} <= set(by_name)
    assert by_name["csv"]["available"] and by_name["csv"]["reason"] is None


def test_unavailable_importer_is_a_clear_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved = importers.registry.get("xlsx") if "xlsx" in importers.names() else None
    importers.registry.unregister("xlsx")
    importers.registry.mark_unavailable("xlsx", "Excel", "install the optional extra")
    try:
        r = client.post(PREVIEW, json=req("xlsx", b64(b"x")))
        assert r.status_code == 404 and "optional extra" in r.json()["detail"]
        listed = {i["name"]: i for i in client.get("/api/v1/import/importers").json()}
        assert listed["xlsx"]["available"] is False
    finally:
        importers.registry._unavailable.pop("xlsx", None)  # noqa: SLF001
        if saved is not None:
            importers.registry.register(saved)


def test_json_file_preview_and_commit(client: TestClient) -> None:
    make(client, title="Existing", body="Rate the tone of this email from 1 to 5 and explain.")
    source = {"content": (DATA / "prompts.json").read_text(encoding="utf-8")}
    pv = client.post(PREVIEW, json=req("json", source)).json()
    assert [r["status"] for r in pv["rows"]] == ["new", "duplicate", "invalid", "invalid"]
    assert pv["rows"][0]["warnings"][0].startswith("columns mapped")
    job = client.post(COMMIT, json=req("json", source)).json()
    assert (job["created"], job["skipped"], job["invalid"], job["refused"]) == (1, 1, 2, 0)
    made = client.get(f"/api/v1/prompts/{job['results'][0]['prompt_id']}").json()
    assert made["source"] == "import:json" and made["license"] == "MIT"
    assert made["source_url"] == "https://example.com/p/1" and made["tags"] == [
        "meetings",
        "summary",
    ]
    assert [v["name"] for v in made["variables"]] == ["notes"]


def test_csv_base64_with_bom_and_mapping_override(client: TestClient) -> None:
    raw = (DATA / "messy.csv").read_bytes()
    pv = client.post(PREVIEW, json=req("csv", b64(raw))).json()
    assert [r["status"] for r in pv["rows"]] == ["new", "new", "invalid"]
    assert pv["rows"][0]["draft"]["body"].startswith("Review this diff.\nList bugs")
    assert pv["rows"][0]["draft"]["tags"] == ["code", "review"]
    text = "name,stuff\nA prompt,Do {{thing}} well\n"
    bad = client.post(PREVIEW, json=req("csv", {"content": text}))
    assert bad.status_code == 422 and "No column for: body" in bad.json()["detail"]
    ok = client.post(PREVIEW, json=req("csv", {"content": text, "mapping": {"body": "stuff"}}))
    assert ok.status_code == 200 and ok.json()["rows"][0]["draft"]["body"] == "Do {{thing}} well"


def test_default_license_and_source_url_fill_only_missing_values(client: TestClient) -> None:
    csv = "title,body,license\nHas license,First body about gardening in spring,Apache-2.0\nNone,Second body about sailing in winter,\n"
    src = {"content": csv}
    pv = client.post(PREVIEW, json=req("csv", src)).json()
    assert [r["needs_license_confirm"] for r in pv["rows"]] == [False, True]
    extra = {"default_license": "CC0-1.0", "default_source_url": "https://example.com/pack"}
    pv = client.post(PREVIEW, json=req("csv", src, **extra)).json()
    assert [r["needs_license_confirm"] for r in pv["rows"]] == [False, False]
    assert [r["draft"]["license"] for r in pv["rows"]] == ["Apache-2.0", "CC0-1.0"]
    job = client.post(COMMIT, json=req("csv", src, **extra)).json()
    assert job["created"] == 2 and job["refused"] == 0
    got = [client.get(f"/api/v1/prompts/{r['prompt_id']}").json() for r in job["results"]]
    assert [p["license"] for p in got] == ["Apache-2.0", "CC0-1.0"]
    assert {p["source_url"] for p in got} == {"https://example.com/pack"}


def test_license_gate_for_markdown_without_license(client: TestClient) -> None:
    files = {"files": [{"name": "a.md", "content": "Body about tea"}]}
    job = client.post(COMMIT, json=req("markdown", files)).json()
    assert (job["created"], job["refused"]) == (0, 1)
    job = client.post(COMMIT, json=req("markdown", files, confirm_license=True)).json()
    assert job["created"] == 1


def test_markdown_zip_and_front_matter(client: TestClient) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("p/one.md", "---\ntitle: One\nlicense: MIT\ntags: a, b\n---\nBody one {{x}}")
        zf.writestr("p/two.md", "---\nlicense: MIT\n---\n# Two\nBody two")
        zf.writestr("p/broken.md", "---\ntitle: [oops\n---\nBody")
    job = client.post(COMMIT, json=req("markdown", b64(buf.getvalue()))).json()
    assert (job["created"], job["invalid"]) == (2, 1)
    titles = sorted(
        client.get(f"/api/v1/prompts/{r['prompt_id']}").json()["title"]
        for r in job["results"]
        if r["prompt_id"]
    )
    assert titles == ["One", "Two"]
    assert total(client) == 2


def test_clipboard_multiple_prompts(client: TestClient) -> None:
    text = "Alpha prompt body\n---\nBeta prompt body\n---\nGamma prompt body"
    job = client.post(COMMIT, json=req("clipboard", text, confirm_license=True)).json()
    assert job["created"] == 3 and total(client) == 3


def test_xlsx_through_the_api(client: TestClient) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Title", "Body", "License"])
    ws.append(["Sheet prompt", "Plan a trip to {{place}}", "MIT"])
    buf = io.BytesIO()
    wb.save(buf)
    job = client.post(COMMIT, json=req("xlsx", b64(buf.getvalue()))).json()
    assert job["created"] == 1
    assert (
        client.get(f"/api/v1/prompts/{job['results'][0]['prompt_id']}").json()["source"]
        == "import:xlsx"
    )


@pytest.fixture
def small_client(tmp_path: Path) -> Iterator[TestClient]:
    s = Settings(data_dir=tmp_path, import_max_payload_bytes=2000, _env_file=None)  # type: ignore[call-arg]
    with TestClient(create_app(s)) as c:
        yield c


def test_base64_payload_is_capped(small_client: TestClient) -> None:
    r = small_client.post(PREVIEW, json=req("csv", b64(b"title,body\n" + b"x," * 3000)))
    assert r.status_code == 413
    assert r.headers["content-type"].startswith("application/problem+json")
