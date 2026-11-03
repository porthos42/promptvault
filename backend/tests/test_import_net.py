"""GitHub, web page and Hugging Face importers, through the pipeline, API and CLI (fake network)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.net_helpers import Net, make_net
from typer.testing import CliRunner

from promptvault.cli import app
from promptvault.config import Settings, get_settings
from promptvault.importers import github, huggingface, net
from promptvault.importers import url as url_importer
from promptvault.services.errors import DomainError, ValidationFailed

DATA = Path(__file__).parent / "data" / "import" / "net"
API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
HUB = "https://huggingface.co"
SRV = "https://datasets-server.huggingface.co"


def md(title: str, body: str, license_: str | None = None) -> str:
    lic = f"license: {license_}\n" if license_ else ""
    return f"---\ntitle: {title}\n{lic}---\n{body}\n"


def tree(*items: tuple[str, int]) -> dict[str, Any]:
    return {"truncated": False, "tree": [{"path": p, "type": "blob", "size": s} for p, s in items]}


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Iterator[Net]:
    n = make_net()
    net.set_fetcher(n.fetcher)
    yield n
    net.set_fetcher(None)


def repo(
    n: Net,
    files: dict[str, str],
    *,
    license_: str | None = "CC0-1.0",
    owner: str = "o/r",
    branch: str = "main",
) -> None:
    lic = {"spdx_id": license_} if license_ else None
    n.transport.add(f"{API}/repos/{owner}", {"default_branch": branch, "license": lic})
    n.transport.add(
        f"{API}/repos/{owner}/git/trees/{branch}?recursive=1",
        tree(*[(p, len(c)) for p, c in files.items()]),
    )
    for path, content in files.items():
        n.transport.add(f"{RAW}/{owner}/{branch}/{path}", content)


# --- URL parsing -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/o/r", ("o", "r", None, ())),
        ("https://github.com/o/r/", ("o", "r", None, ())),
        ("https://github.com/o/r.git", ("o", "r", None, ())),
        ("http://www.github.com/o/r", ("o", "r", None, ())),
        ("https://github.com/o/r/tree/main/seed", ("o", "r", "tree", ("main", "seed"))),
        (
            "https://github.com/o/r/tree/feature/x/sub/dir",
            ("o", "r", "tree", ("feature", "x", "sub", "dir")),
        ),
        ("https://github.com/o/r/blob/main/a/b.md", ("o", "r", "blob", ("main", "a", "b.md"))),
        ("https://github.com/o/r/tree/main/seed?tab=x#frag", ("o", "r", "tree", ("main", "seed"))),
    ],
)
def test_parse_repo_urls(url: str, expected: tuple[Any, ...]) -> None:
    t = github.parse_url(url)
    assert isinstance(t, github.RepoTarget)
    assert (t.owner, t.repo, t.kind, t.rest) == expected


def test_parse_gist_urls() -> None:
    gid = "a" * 32
    for url in (
        f"https://gist.github.com/user/{gid}",
        f"https://gist.github.com/{gid}",
        f"https://gist.github.com/user/{gid}/raw/x.md",
    ):
        assert github.parse_url(url) == github.GistTarget(gid)


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/",
        "https://github.com/onlyowner",
        "https://github.com/o/r/issues/3",
        "https://github.com/o/r/tree",
        "https://example.com/o/r",
        "https://github.com.evil.example/o/r",
        "https://gist.github.com/user/not-an-id",
        "ftp://github.com/o/r",
        "https://github.com/o/../r",
        "https://github.com/o%20x/r",
    ],
)
def test_parse_rejects_bad_github_urls(url: str) -> None:
    with pytest.raises(ValidationFailed):
        github.parse_url(url)


# --- GitHub ----------------------------------------------------------------------------------


def test_github_repo_license_filters_and_provenance(fake: Net) -> None:
    repo(
        fake,
        {
            "README.md": "# readme",
            "LICENSE": "x",
            "docs/CODE_OF_CONDUCT.md": "# coc",
            ".github/guide.md": "# hidden",
            "package.json": "{}",
            "a.md": md("Alpha", "Say alpha about {{x}}"),
            "sub/b.md": md("Beta", "Say beta about {{y}}", license_="MIT"),
            "sub/c.txt": "ignored by extension",
            "sub/d.yaml": "title: Delta\nbody: Say delta about {{z}}\nsource_url: https://origin.example/d\n",
            "sub/e.csv": "title,body\nEcho,Say echo about {{w}}\n",
            "sub/f.json": json.dumps([{"title": "Foxtrot", "body": "Say foxtrot about {{v}}"}]),
        },
    )
    drafts = github.GithubImporter().parse("https://github.com/o/r")
    got = {d.title: d for d in drafts}
    assert set(got) == {"Alpha", "Beta", "Delta", "Echo", "Foxtrot"}
    assert got["Alpha"].license == "CC0-1.0" and got["Beta"].license == "MIT"
    assert got["Alpha"].source_url == "https://github.com/o/r/blob/main/a.md"
    assert got["Delta"].source_url == "https://origin.example/d"  # the file's own value wins
    assert got["Foxtrot"].source_url == "https://github.com/o/r/blob/main/sub/f.json"
    urls = fake.transport.urls()
    assert not any(
        "README" in u or "LICENSE" in u or "/.github/" in u or "package.json" in u or "c.txt" in u
        for u in urls
    )


@pytest.mark.parametrize("spdx", ["NOASSERTION", None, "other"])
def test_github_unclear_license_is_left_empty_and_noted(fake: Net, spdx: str | None) -> None:
    repo(fake, {"a.md": md("Alpha", "Say alpha about {{x}}")}, license_=spdx)
    drafts = github.GithubImporter().parse("https://github.com/o/r")
    assert drafts[0].license in (None, "")
    assert any("no clear license" in w for w in drafts[0].warnings)


def test_github_path_filter_and_explicit_file(fake: Net) -> None:
    files = {
        "seed/a.md": md("Alpha", "Say alpha about {{x}}"),
        "seed/README.md": "# seed readme",
        "other/b.md": md("Beta", "Say beta about {{y}}"),
        "seedling/c.md": md("Gamma", "Say gamma about {{z}}"),
    }
    repo(fake, files)
    drafts = github.GithubImporter().parse("https://github.com/o/r/tree/main/seed")
    assert [d.title for d in drafts] == ["Alpha"]  # prefix match is by folder, README skipped
    drafts = github.GithubImporter().parse("https://github.com/o/r/blob/main/seed/README.md")
    assert drafts[0].title == "seed readme"  # an explicitly named file is kept


def test_github_branch_names_with_slashes(fake: Net) -> None:
    fake.transport.add(
        f"{API}/repos/o/r", {"default_branch": "main", "license": {"spdx_id": "MIT"}}
    )
    fake.transport.add(f"{API}/repos/o/r/git/trees/feature%2Fx?recursive=1", tree(("a/p.md", 5)))
    fake.transport.add(f"{RAW}/o/r/feature/x/a/p.md", md("Slashy", "Say slash about {{x}}"))
    drafts = github.GithubImporter().parse("https://github.com/o/r/tree/feature/x/a")
    assert [d.title for d in drafts] == ["Slashy"]
    assert (
        fake.transport.urls().count(
            "https://api.github.com/repos/o/r/git/trees/feature?recursive=1"
        )
        == 1
    )  # shorter ref tried first


def test_github_unknown_ref_is_a_clear_error(fake: Net) -> None:
    fake.transport.add(f"{API}/repos/o/r", {"default_branch": "main", "license": None})
    with pytest.raises(ValidationFailed, match="branch, tag or commit"):
        github.GithubImporter().parse("https://github.com/o/r/tree/nope/seed")


def test_github_file_cap_and_truncated_tree_warnings(fake: Net) -> None:
    files = {f"p{i:02d}.md": md(f"T{i}", f"Body number {i} about {{{{x}}}}") for i in range(6)}
    repo(fake, files)
    fake.fetcher.config = net.NetConfig(github_max_files=4)
    body = tree(*[(p, len(c)) for p, c in files.items()])
    body["truncated"] = True
    fake.transport.add(f"{API}/repos/o/r/git/trees/main?recursive=1", body)
    drafts = github.GithubImporter().parse("https://github.com/o/r")
    assert len(drafts) == 4
    text = " | ".join(drafts[0].warnings)
    assert "2 more file(s) beyond the limit of 4" in text and "truncated by GitHub" in text


def test_github_oversize_files_and_bad_files_are_skipped_with_notes(fake: Net) -> None:
    files = {
        "good.md": md("Good", "Say good about {{x}}"),
        "huge.md": "x",
        "bad.json": "{not json",
        "plain.json": "[1, 2]",
    }
    repo(fake, files)
    fake.fetcher.config = net.NetConfig(max_bytes=1000)
    fake.transport.add(
        f"{API}/repos/o/r/git/trees/main?recursive=1",
        tree(("good.md", 50), ("huge.md", 5000), ("bad.json", 9), ("plain.json", 6)),
    )
    drafts = github.GithubImporter().parse("https://github.com/o/r")
    assert [d.title for d in drafts] == ["Good"]
    text = " ".join(drafts[0].warnings)
    assert (
        "huge.md (larger than 1000 bytes)" in text and "bad.json" in text and "plain.json" in text
    )


def test_github_nothing_importable_is_an_error(fake: Net) -> None:
    repo(fake, {"README.md": "# r", "src/app.py": "print()"})
    with pytest.raises(ValidationFailed, match="No importable prompt files"):
        github.GithubImporter().parse("https://github.com/o/r")


def test_github_invalid_row_errors_name_the_file(fake: Net) -> None:
    repo(fake, {"x/bad.md": "---\ntitle: [unclosed\n---\nbody text here\n"})
    drafts = github.GithubImporter().parse("https://github.com/o/r")
    assert drafts[0].errors and drafts[0].errors[0].startswith("x/bad.md: ")


def test_github_rate_limit_message_mentions_the_token(fake: Net) -> None:
    fake.transport.add(
        f"{API}/repos/o/r",
        {"message": "API rate limit exceeded"},
        status=403,
        headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1700000000"},
    )
    with pytest.raises(net.FetchError, match="PV_GITHUB_TOKEN") as exc:
        github.GithubImporter().parse("https://github.com/o/r")
    assert "rate limit" in exc.value.detail and "60 requests" in exc.value.detail
    fake.transport.add(f"{API}/repos/o/r", "{}", status=429)
    with pytest.raises(net.FetchError, match="rate limit"):
        github.GithubImporter().parse("https://github.com/o/r")
    fake.fetcher.config = net.NetConfig(github_token="tkn")
    with pytest.raises(net.FetchError, match="also limited"):
        github.GithubImporter().parse("https://github.com/o/r")


def test_github_not_found_and_bad_credentials(fake: Net) -> None:
    with pytest.raises(net.FetchError, match="not found"):
        github.GithubImporter().parse("https://github.com/o/missing")
    fake.transport.add(f"{API}/repos/o/r", "{}", status=401)
    with pytest.raises(net.FetchError, match="credentials"):
        github.GithubImporter().parse("https://github.com/o/r")


def test_github_token_is_sent_to_github_hosts_only(fake: Net) -> None:
    fake.fetcher.config = net.NetConfig(github_token="tkn")
    repo(fake, {"a.md": md("Alpha", "Say alpha about {{x}}")})
    github.GithubImporter().parse("https://github.com/o/r")
    assert {r.host for r in fake.transport.requests} == {
        "api.github.com",
        "raw.githubusercontent.com",
    }
    assert all(r.headers.get("Authorization") == "Bearer tkn" for r in fake.transport.requests)


def test_github_gist(fake: Net) -> None:
    gid = "b" * 32
    fake.transport.add(
        f"{API}/gists/{gid}",
        {
            "html_url": f"https://gist.github.com/u/{gid}",
            "files": {
                "one.md": {"filename": "one.md", "content": md("One", "Say one about {{x}}")},
                "two.json": {
                    "filename": "two.json",
                    "content": json.dumps({"title": "Two", "body": "Say two about {{y}}"}),
                },
                "notes.py": {"filename": "notes.py", "content": "print()"},
                "big.md": {
                    "filename": "big.md",
                    "truncated": True,
                    "raw_url": "https://gist.githubusercontent.com/u/x/raw/big.md",
                },
            },
        },
    )
    fake.transport.add(
        "https://gist.githubusercontent.com/u/x/raw/big.md", md("Big", "Say big about {{z}}")
    )
    drafts = github.GithubImporter().parse(f"https://gist.github.com/u/{gid}")
    assert [d.title for d in drafts] == ["Big", "One", "Two"]
    assert all(d.source_url == f"https://gist.github.com/u/{gid}" and not d.license for d in drafts)
    assert any("no license information" in w for w in drafts[0].warnings)


def test_github_gist_raw_url_must_be_a_gist_host(fake: Net) -> None:
    gid = "c" * 32
    fake.transport.add(
        f"{API}/gists/{gid}",
        {
            "files": {
                "a.md": {
                    "filename": "a.md",
                    "truncated": True,
                    "raw_url": "https://internal.example/a.md",
                },
                "b.md": {"filename": "b.md", "content": md("B", "Say bee about {{x}}")},
            }
        },
    )
    drafts = github.GithubImporter().parse(f"https://gist.github.com/{gid}")
    assert [d.title for d in drafts] == ["B"]
    assert "internal.example" not in " ".join(fake.transport.urls())


# --- Hugging Face ----------------------------------------------------------------------------


def hf(
    n: Net, rows: list[dict[str, Any]], *, card: dict[str, Any] | None = None, ident: str = "org/ds"
) -> None:
    n.transport.add(
        f"{HUB}/api/datasets/{ident}",
        card if card is not None else {"cardData": {"license": "cc0-1.0"}},
    )
    n.transport.add(
        f"{SRV}/splits?dataset=org%2Fds",
        {
            "splits": [
                {"config": "default", "split": "test"},
                {"config": "default", "split": "train"},
                {"config": "alt", "split": "train"},
            ]
        },
    )
    features = [{"name": k} for k in rows[0]] if rows else []
    for config in ("default", "alt"):
        for split in ("train", "test"):
            for offset in range(0, max(len(rows), 1), 100):
                chunk = rows[offset : offset + 100]
                n.transport.add(
                    f"{SRV}/rows?dataset=org%2Fds&config={config}&split={split}&offset={offset}&length=100",
                    {
                        "features": features,
                        "num_rows_total": len(rows),
                        "rows": [
                            {"row_idx": offset + i, "row": r, "truncated_cells": []}
                            for i, r in enumerate(chunk)
                        ],
                    },
                )


def rows_of(count: int) -> list[dict[str, Any]]:
    # distinct random-looking bodies: similar bodies would be fuzzy duplicates of each other
    return [
        {"act": f"Act {i}", "prompt": f"{hashlib.sha256(str(i).encode()).hexdigest()} {{{{task}}}}"}
        for i in range(count)
    ]


def test_hf_url_parsing() -> None:
    assert huggingface.parse_dataset_id("https://huggingface.co/datasets/org/ds") == "org/ds"
    assert (
        huggingface.parse_dataset_id("https://huggingface.co/datasets/org/ds/viewer/default/train")
        == "org/ds"
    )
    assert huggingface.parse_dataset_id("https://huggingface.co/datasets/squad") == "squad"
    assert huggingface.parse_dataset_id("https://huggingface.co/datasets/squad/viewer") == "squad"
    for bad in (
        "https://huggingface.co/org/model",
        "https://huggingface.co/datasets",
        "https://example.com/datasets/a/b",
        "https://huggingface.co/datasets/a/..",
        "ftp://huggingface.co/datasets/a/b",
    ):
        with pytest.raises(ValidationFailed):
            huggingface.parse_dataset_id(bad)


def test_hf_rows_mapping_license_and_defaults(fake: Net) -> None:
    hf(fake, rows_of(3))
    src = {"url": f"{HUB}/datasets/org/ds", "mapping": {"title": "act", "body": "prompt"}}
    drafts = huggingface.HuggingFaceImporter().parse(src)
    assert [d.title for d in drafts] == ["Act 0", "Act 1", "Act 2"]
    assert drafts[0].license == "cc0-1.0" and drafts[0].source_url == f"{HUB}/datasets/org/ds"
    notes = " | ".join(drafts[0].warnings)
    assert (
        "config 'default', split 'train', 3 of 3 rows" in notes
    )  # train preferred over the first split
    assert any(
        "rows?dataset=org%2Fds&config=default&split=train" in u for u in fake.transport.urls()
    )


def test_hf_needs_a_mapping_when_no_title_column(fake: Net) -> None:
    hf(fake, rows_of(2))
    with pytest.raises(ValidationFailed, match="mapping"):
        huggingface.HuggingFaceImporter().parse(f"{HUB}/datasets/org/ds")


def test_hf_config_split_and_limit_options(fake: Net) -> None:
    hf(fake, rows_of(5))
    fake.transport.add(
        f"{SRV}/rows?dataset=org%2Fds&config=alt&split=test&offset=0&length=2",
        {
            "features": [{"name": "act"}, {"name": "prompt"}],
            "num_rows_total": 5,
            "rows": [{"row": r} for r in rows_of(5)[:2]],
        },
    )
    src = {
        "url": f"{HUB}/datasets/org/ds",
        "config": "alt",
        "split": "test",
        "limit": 2,
        "mapping": {"title": "act", "body": "prompt"},
    }
    drafts = huggingface.HuggingFaceImporter().parse(src)
    assert len(drafts) == 2
    assert any("only the first 2 rows" in w for w in drafts[0].warnings)
    assert not any("/splits" in u for u in fake.transport.urls())  # both options given: no lookup
    for bad in ({"limit": 0}, {"limit": "x"}):
        with pytest.raises(ValidationFailed, match="limit"):
            huggingface.HuggingFaceImporter().parse({"url": f"{HUB}/datasets/org/ds", **bad})
    with pytest.raises(ValidationFailed, match="Split 'nope'"):
        huggingface.HuggingFaceImporter().parse(
            {
                "url": f"{HUB}/datasets/org/ds",
                "split": "nope",
                "mapping": {"title": "act", "body": "prompt"},
            }
        )
    with pytest.raises(ValidationFailed, match="no splits"):
        huggingface.HuggingFaceImporter().parse({"url": f"{HUB}/datasets/org/ds", "config": "zzz"})


def test_hf_pages_of_100_and_row_cap(fake: Net) -> None:
    rows = rows_of(250)
    fake.fetcher.config = net.NetConfig(max_rows=230)
    fake.transport.add(f"{HUB}/api/datasets/org/ds", {"cardData": {"license": ["mit"]}})
    fake.transport.add(
        f"{SRV}/splits?dataset=org%2Fds", {"splits": [{"config": "c", "split": "train"}]}
    )
    for offset, length in ((0, 100), (100, 100), (200, 30)):
        fake.transport.add(
            f"{SRV}/rows?dataset=org%2Fds&config=c&split=train&offset={offset}&length={length}",
            {
                "features": [{"name": "act"}, {"name": "prompt"}],
                "num_rows_total": 250,
                "rows": [{"row": r} for r in rows[offset : offset + length]],
            },
        )
    drafts = huggingface.HuggingFaceImporter().parse(
        {
            "url": f"{HUB}/datasets/org/ds",
            "limit": 9999,
            "mapping": {"title": "act", "body": "prompt"},
        }
    )
    assert len(drafts) == 230 and drafts[0].license == "mit"  # capped by PV_IMPORT_MAX_ROWS
    assert sum("/rows?" in u for u in fake.transport.urls()) == 3


@pytest.mark.parametrize(
    "card",
    [
        {"cardData": {}},
        {"tags": []},
        {"cardData": {"license": "other"}},
        {"cardData": {"license": "unknown"}},
    ],
)
def test_hf_unclear_license(fake: Net, card: dict[str, Any]) -> None:
    hf(fake, rows_of(1), card=card)
    drafts = huggingface.HuggingFaceImporter().parse(
        {"url": f"{HUB}/datasets/org/ds", "mapping": {"title": "act", "body": "prompt"}}
    )
    assert not drafts[0].license and any("no clear license" in w for w in drafts[0].warnings)


def test_hf_renamed_dataset_follows_the_card_id(fake: Net) -> None:
    hf(fake, rows_of(1), card={"id": "org/ds", "cardData": {"license": "mit"}}, ident="old/name")
    d = huggingface.HuggingFaceImporter().parse(
        {"url": f"{HUB}/datasets/old/name", "mapping": {"title": "act", "body": "prompt"}}
    )
    assert d[0].source_url == f"{HUB}/datasets/org/ds"
    assert any("renamed" in w for w in d[0].warnings)


def test_hf_foreign_type_column_is_ignored_unless_mapped(fake: Net) -> None:
    rows = [{**r, "type": "TEXT", "level": "easy"} for r in rows_of(2)]
    rows[1]["type"] = "system"
    hf(fake, rows)
    src = {"url": f"{HUB}/datasets/org/ds", "mapping": {"title": "act", "body": "prompt"}}
    d = huggingface.HuggingFaceImporter().parse(src)
    assert [x.errors for x in d] == [[], []] and [x.prompt_type for x in d] == [None, "system"]
    assert any("ignored 1 prompt_type" in w for w in d[0].warnings)
    assert any("ignored 2 difficulty" in w for w in d[0].warnings)
    strict = huggingface.HuggingFaceImporter().parse(
        {**src, "mapping": {**src["mapping"], "prompt_type": "type"}}
    )
    assert strict[0].prompt_type == "TEXT"  # explicit mapping is validated later by the pipeline


def test_hf_license_from_tag(fake: Net) -> None:
    hf(fake, rows_of(1), card={"tags": ["task:x", "license:apache-2.0"]})
    d = huggingface.HuggingFaceImporter().parse(
        {"url": f"{HUB}/datasets/org/ds", "mapping": {"title": "act", "body": "prompt"}}
    )
    assert d[0].license == "apache-2.0"


@pytest.mark.parametrize("card", [{"gated": "auto"}, {"gated": "manual"}, {"private": True}])
def test_hf_gated_and_private_datasets_are_refused(fake: Net, card: dict[str, Any]) -> None:
    hf(fake, rows_of(1), card=card)
    with pytest.raises(ValidationFailed, match="gated or private"):
        huggingface.HuggingFaceImporter().parse(f"{HUB}/datasets/org/ds")
    assert not any("datasets-server" in u for u in fake.transport.urls())


def test_hf_http_errors(fake: Net) -> None:
    fake.transport.add(f"{HUB}/api/datasets/org/ds", "{}", status=401)
    with pytest.raises(ValidationFailed, match="gated or private"):
        huggingface.HuggingFaceImporter().parse(f"{HUB}/datasets/org/ds")
    with pytest.raises(ValidationFailed, match="was not found"):
        huggingface.HuggingFaceImporter().parse(f"{HUB}/datasets/org/other")
    fake.transport.add(f"{HUB}/api/datasets/org/ds", {})
    fake.transport.add(
        f"{SRV}/splits?dataset=org%2Fds",
        {"error": "The dataset viewer is not available"},
        status=501,
    )
    with pytest.raises(net.FetchError, match="viewer is not available"):
        huggingface.HuggingFaceImporter().parse(f"{HUB}/datasets/org/ds")


def test_hf_truncated_cells_make_the_row_invalid(fake: Net) -> None:
    fake.transport.add(f"{HUB}/api/datasets/org/ds", {"cardData": {"license": "mit"}})
    fake.transport.add(
        f"{SRV}/splits?dataset=org%2Fds", {"splits": [{"config": "c", "split": "train"}]}
    )
    fake.transport.add(
        f"{SRV}/rows?dataset=org%2Fds&config=c&split=train&offset=0&length=100",
        {
            "features": [{"name": "act"}, {"name": "prompt"}],
            "num_rows_total": 2,
            "rows": [
                {"row": {"act": "A", "prompt": "cut off"}, "truncated_cells": ["prompt"]},
                {"row": {"act": "B", "prompt": "whole prompt text {{x}}"}, "truncated_cells": []},
            ],
        },
    )
    d = huggingface.HuggingFaceImporter().parse(
        {"url": f"{HUB}/datasets/org/ds", "mapping": {"title": "act", "body": "prompt"}}
    )
    assert "truncated" in d[0].errors[0] and not d[1].errors


def test_hf_empty_split(fake: Net) -> None:
    fake.transport.add(f"{HUB}/api/datasets/org/ds", {})
    fake.transport.add(
        f"{SRV}/splits?dataset=org%2Fds", {"splits": [{"config": "c", "split": "train"}]}
    )
    fake.transport.add(
        f"{SRV}/rows?dataset=org%2Fds&config=c&split=train&offset=0&length=100",
        {"features": [], "num_rows_total": 0, "rows": []},
    )
    with pytest.raises(ValidationFailed, match="no rows"):
        huggingface.HuggingFaceImporter().parse(f"{HUB}/datasets/org/ds")


# --- web pages -------------------------------------------------------------------------------


def page(
    n: Net, name: str, url: str = "https://site.example/p", ctype: str = "text/html; charset=utf-8"
) -> None:
    n.transport.add(url, (DATA / name).read_text(encoding="utf-8"), headers={"content-type": ctype})


def test_html_page_mode_golden(fake: Net) -> None:
    page(fake, "page.html")
    (d,) = url_importer.UrlImporter().parse("https://site.example/p")
    assert d.title == "Great Summary Prompt & Tips"
    assert d.body == (
        "You are an editor.\nSummarize {{text}} in three bullet points.\nKeep it neutral."
        "\n\nNow rewrite the summary for a {{audience}} audience.\n\nKeep every number."
    )
    assert d.license == "https://creativecommons.org/publicdomain/zero/1.0/"
    assert d.source_url == "https://site.example/p"
    assert "review before importing" in d.warnings[0]
    assert "script text" not in d.body and "noscript" not in d.body and "inline code" not in d.body


def test_html_blocks_mode_titles_from_headings(fake: Net) -> None:
    page(fake, "page.html")
    drafts = url_importer.UrlImporter().parse({"url": "https://site.example/p", "mode": "blocks"})
    assert [d.title for d in drafts] == ["Summary prompt", "Follow-up"]
    assert drafts[0].body.startswith("You are an editor.") and drafts[1].body.startswith(
        "Now rewrite"
    )
    assert all("review before importing" in d.warnings[0] for d in drafts)
    with pytest.raises(ValidationFailed, match="mode"):
        url_importer.UrlImporter().parse({"url": "https://site.example/p", "mode": "all"})


def test_html_without_candidates_is_a_clear_error(fake: Net) -> None:
    page(fake, "nocode.html")
    with pytest.raises(ValidationFailed, match="No prompt text found"):
        url_importer.UrlImporter().parse("https://site.example/p")


def test_html_spdx_in_visible_text_and_title_fallback(fake: Net) -> None:
    page(fake, "spdx.html")
    (d,) = url_importer.UrlImporter().parse("https://site.example/p")
    assert d.license == "MIT" and d.title == "T"
    fake.transport.add(
        "https://site.example/q",
        "<html><body><h1>Heading Title</h1><pre>Explain {{topic}} to a five year old.</pre></body></html>",
        headers={"content-type": "text/html"},
    )
    (d,) = url_importer.UrlImporter().parse("https://site.example/q")
    assert d.title == "Heading Title" and d.license is None


def test_html_charset_from_meta_and_long_inline_code(fake: Net) -> None:
    html = (
        "<html><head><meta charset='iso-8859-1'><title>caf\u00e9</title></head><body><code>"
        + "x " * 50
        + "</code></body></html>"
    )
    fake.transport.add(
        "https://site.example/p", html.encode("latin-1"), headers={"content-type": "text/html"}
    )
    (d,) = url_importer.UrlImporter().parse("https://site.example/p")
    assert d.title == "caf\u00e9" and d.body.startswith("x x")


def test_html_unclosed_and_nested_blocks_do_not_crash(fake: Net) -> None:
    html = "<html><body><blockquote><pre>Inner pre text that is long enough</pre> tail</blockquote><pre>never closed block text here"
    fake.transport.add("https://site.example/p", html, headers={"content-type": "text/html"})
    drafts = url_importer.UrlImporter().parse({"url": "https://site.example/p", "mode": "blocks"})
    assert (
        len(drafts) == 2
        and "Inner pre text" in drafts[0].body
        and drafts[1].body.startswith("never closed")
    )


def test_url_delegates_files_by_extension_and_content_type(fake: Net) -> None:
    fake.transport.add(
        "https://site.example/a.md",
        md("From MD", "Say md about {{x}}"),
        headers={"content-type": "text/markdown"},
    )
    (d,) = url_importer.UrlImporter().parse("https://site.example/a.md")
    assert (
        d.title == "From MD"
        and d.source_url == "https://site.example/a.md"
        and not any("web page" in w for w in d.warnings)
    )
    fake.transport.add(
        "https://site.example/data",
        json.dumps([{"title": "J", "body": "Say j about {{x}}"}]),
        headers={"content-type": "application/json"},
    )
    assert url_importer.UrlImporter().parse("https://site.example/data")[0].title == "J"
    fake.transport.add(
        "https://site.example/t.csv",
        "title,body\nC,Say c about {{x}}\n",
        headers={"content-type": "application/octet-stream"},
    )
    assert (
        url_importer.UrlImporter().parse("https://site.example/t.csv")[0].title == "C"
    )  # extension makes octet-stream acceptable
    fake.transport.add(
        "https://site.example/y",
        "title: Y\nbody: Say y about {{x}}\n",
        headers={"content-type": "application/x-yaml"},
    )
    assert url_importer.UrlImporter().parse("https://site.example/y")[0].title == "Y"
    fake.transport.add(
        "https://site.example/plain",
        "# Plain Title\nSay plain about {{x}}",
        headers={"content-type": "text/plain"},
    )
    assert url_importer.UrlImporter().parse("https://site.example/plain")[0].title == "Plain Title"
    fake.transport.add(
        "https://site.example/bin", b"\x00", headers={"content-type": "application/octet-stream"}
    )
    with pytest.raises(net.FetchError, match="content type"):
        url_importer.UrlImporter().parse("https://site.example/bin")


def test_url_importer_blocks_private_targets_without_a_request(fake: Net) -> None:
    for url in ("http://localhost/a", "file:///etc/passwd", "https://site.example:8443/a"):
        with pytest.raises(ValidationFailed):
            url_importer.UrlImporter().parse(url)
    assert fake.transport.requests == []


@pytest.mark.parametrize(
    "importer",
    [github.GithubImporter(), url_importer.UrlImporter(), huggingface.HuggingFaceImporter()],
)
def test_url_is_required(importer: Any) -> None:
    for bad in ({}, {"url": ""}, {"url": 5}, ""):
        with pytest.raises(DomainError):
            importer.parse(bad)


# --- API and CLI -------------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path, fake: Net) -> Iterator[TestClient]:
    from promptvault.main import create_app

    with TestClient(create_app(Settings(data_dir=tmp_path, _env_file=None))) as c:  # type: ignore[call-arg]
        net.set_fetcher(fake.fetcher)  # create_app configures the real fetcher; the fake wins
        yield c


def test_importers_are_listed(client: TestClient) -> None:
    names = {i["name"] for i in client.get("/api/v1/import/importers").json()}
    assert {"github", "url", "huggingface"} <= names


def test_api_github_preview_license_gate_and_dedupe(client: TestClient, fake: Net) -> None:
    repo(
        fake,
        {
            "a.md": md("Alpha", "Say alpha about {{x}} in detail"),
            "b.md": md("Beta", "Say beta about {{y}} in detail"),
        },
        license_=None,
    )
    src = {"url": "https://github.com/o/r"}
    pre = client.post("/api/v1/import/preview", json={"importer": "github", "source": src}).json()
    assert (pre["total"], pre["new"], pre["needs_license_confirm"]) == (2, 2, 2)
    assert pre["rows"][0]["draft"]["source_url"] == "https://github.com/o/r/blob/main/a.md"
    refused = client.post(
        "/api/v1/import/commit", json={"importer": "github", "source": src}
    ).json()
    assert refused["status"] == "done"
    assert [r["outcome"] for r in refused["results"]] == ["refused", "refused"]
    assert client.get("/api/v1/prompts").json()["total"] == 0
    ok = client.post(
        "/api/v1/import/commit", json={"importer": "github", "source": src, "confirm_license": True}
    )
    assert ok.status_code == 200, ok.text
    listing = client.get("/api/v1/prompts").json()
    assert listing["total"] == 2
    again = client.post("/api/v1/import/preview", json={"importer": "github", "source": src}).json()
    assert again["duplicate"] == 2 and again["rows"][0]["match"]["kind"] == "exact"
    shown = client.get(f"/api/v1/prompts/{listing['items'][0]['id']}").json()
    assert shown["source"] == "import:github" and shown["source_url"].startswith(
        "https://github.com/o/r/blob/main/"
    )


def test_api_preview_with_blocked_url_is_422_and_fetch_failure_is_502(
    client: TestClient, fake: Net
) -> None:
    r = client.post(
        "/api/v1/import/preview", json={"importer": "url", "source": {"url": "http://localhost/x"}}
    )
    assert r.status_code == 422 and "non-public" in r.text
    fake.transport.add("https://site.example/p", "boom", status=500)
    r = client.post(
        "/api/v1/import/preview",
        json={"importer": "url", "source": {"url": "https://site.example/p"}},
    )
    assert r.status_code == 502


def test_api_web_page_with_license_commits_without_confirmation(
    client: TestClient, fake: Net
) -> None:
    page(fake, "page.html")
    r = client.post(
        "/api/v1/import/commit",
        json={"importer": "url", "source": {"url": "https://site.example/p"}},
    )
    assert r.status_code == 200, r.text
    items = client.get("/api/v1/prompts").json()["items"]
    assert [i["title"] for i in items] == ["Great Summary Prompt & Tips"]


runner = CliRunner()


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("PV_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def run(*args: str, code: int = 0) -> str:
    r = runner.invoke(app, list(args))
    assert r.exit_code == code, (args, r.exit_code, r.output)
    return r.output


@pytest.mark.usefixtures("cli_env")
def test_cli_import_github_dry_run_then_commit(fake: Net) -> None:
    repo(fake, {"a.md": md("Alpha", "Say alpha about {{x}} in detail")}, license_="MIT")
    out = run("import", "github", "https://github.com/o/r", "--dry-run")
    assert "1 row(s): 1 new" in out
    assert "Imported: 1 created" in run("import", "github", "https://github.com/o/r", "--yes")
    assert "1 duplicate" in run("import", "github", "https://github.com/o/r", "--dry-run")


@pytest.mark.usefixtures("cli_env")
def test_cli_import_huggingface_options(fake: Net) -> None:
    hf(fake, rows_of(2))
    fake.transport.add(
        f"{SRV}/rows?dataset=org%2Fds&config=default&split=train&offset=0&length=2",
        {
            "features": [{"name": "act"}, {"name": "prompt"}],
            "num_rows_total": 2,
            "rows": [{"row": r} for r in rows_of(2)],
        },
    )
    out = run(
        "import",
        "huggingface",
        f"{HUB}/datasets/org/ds",
        "--mapping",
        "title=act",
        "--mapping",
        "body=prompt",
        "--limit",
        "2",
        "--config",
        "default",
        "--split",
        "train",
        "--dry-run",
        "--json",
    )
    data = json.loads(out)
    assert data["new"] == 2


@pytest.mark.usefixtures("cli_env")
def test_cli_import_url_mode_and_option_checks(fake: Net) -> None:
    page(fake, "page.html")
    data = json.loads(
        run("import", "url", "https://site.example/p", "--mode", "blocks", "--dry-run", "--json")
    )
    assert data["total"] == 2
    assert "needs an http(s) URL" in run("import", "url", "notes.txt", "--dry-run", code=1)
    run(
        "import", "url", "https://site.example/p", "--limit", "3", "--dry-run", code=1
    )  # limit is huggingface-only
    run(
        "import", "csv", "x.csv", "--mode", "blocks", "--dry-run", code=1
    )  # URL options on a file importer
