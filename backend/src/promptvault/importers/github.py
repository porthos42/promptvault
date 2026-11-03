"""GitHub importer: a repository (optionally one folder or file) or a gist, via the GitHub API.

Source: a URL string or {url, mapping?}. Repository URLs: `https://github.com/o/r`,
`.../tree/<ref>[/<folder>]`, `.../blob/<ref>/<file>`; gist URLs: `https://gist.github.com/[user/]<id>`.

Files with the extensions .md .markdown .json .yaml .yml .csv are fetched (repository files from
raw.githubusercontent.com) and parsed with the matching format importer. README, LICENSE and
similar files are skipped unless named explicitly. The repository license (SPDX id from the API)
is applied to rows that do not carry their own; a missing or `NOASSERTION` license leaves the row
unlabelled, so the license gate asks for confirmation. `PV_GITHUB_TOKEN` (env only) raises the
API rate limit and is sent only to api.github.com and raw.githubusercontent.com.
"""

from __future__ import annotations

import json
import posixpath
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

from promptvault.importers import files, net, sources
from promptvault.importers.base import PromptDraft
from promptvault.services.errors import DomainError, ValidationFailed

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
TOTAL_MAX_BYTES = 20 * 1024 * 1024  # all files of one import
FETCH_WORKERS = 4
MAX_REF_SEGMENTS = 6  # longest branch/tag name (in path segments) tried for tree/blob URLs
GITHUB_HOSTS = ("github.com", "www.github.com")
TEXT_TYPES = ("text/", "application/json", "application/octet-stream", "application/x-yaml")
SKIPPED_STEMS = frozenset(
    [
        "readme",
        "license",
        "licence",
        "copying",
        "notice",
        "authors",
        "maintainers",
        "codeowners",
        "contributing",
        "code_of_conduct",
        "security",
        "support",
        "governance",
        "changelog",
        "changes",
        "history",
    ]
)
SKIPPED_NAMES = frozenset(
    [
        "package.json",
        "package-lock.json",
        "tsconfig.json",
        "composer.json",
        "docker-compose.yml",
        "docker-compose.yaml",
        "mkdocs.yml",
        "pnpm-lock.yaml",
    ]
)
NAME_PART = re.compile(r"^[A-Za-z0-9_.-]+$")
GIST_ID = re.compile(r"^[0-9a-f]{20,40}$")
UNCLEAR_SPDX = frozenset({"", "noassertion", "other", "none"})


@dataclass(frozen=True)
class RepoTarget:
    owner: str
    repo: str
    kind: str | None  # "tree", "blob" or None
    rest: tuple[str, ...]  # path segments after tree/blob: ref and, maybe, a folder or file


@dataclass(frozen=True)
class GistTarget:
    gist_id: str


def parse_url(url: str) -> RepoTarget | GistTarget:
    try:
        parts = urlsplit(url.strip())
    except ValueError as exc:
        raise ValidationFailed("Not a valid GitHub URL") from exc
    host = (parts.hostname or "").lower()
    segs = [s for s in parts.path.split("/") if s]
    if parts.scheme.lower() not in ("http", "https") or parts.username or parts.password:
        raise ValidationFailed("GitHub URLs must be plain http(s) URLs")
    if host == "gist.github.com":
        for seg in segs:
            if GIST_ID.match(seg.lower()):
                return GistTarget(seg.lower())
        raise ValidationFailed("Gist URL needs a gist id: https://gist.github.com/<user>/<id>")
    if host not in GITHUB_HOSTS:
        raise ValidationFailed(
            "The github importer takes github.com or gist.github.com URLs "
            "(use the url importer for other sites)"
        )
    if len(segs) < 2:
        raise ValidationFailed(
            "GitHub URL needs an owner and a repository: github.com/<owner>/<repo>"
        )
    owner, repo = segs[0], segs[1].removesuffix(".git")
    if not NAME_PART.match(owner) or not NAME_PART.match(repo) or repo in (".", ".."):
        raise ValidationFailed("Not a valid GitHub repository URL")
    if len(segs) == 2:
        return RepoTarget(owner, repo, None, ())
    if segs[2] in ("tree", "blob") and len(segs) >= 4:
        return RepoTarget(owner, repo, segs[2], tuple(segs[3:]))
    raise ValidationFailed(
        "Unsupported GitHub URL: use a repository, /tree/<branch>[/<folder>] "
        "or /blob/<branch>/<file> URL"
    )


def _skipped_file(path: str) -> bool:
    parts = path.split("/")
    name = parts[-1]
    if any(p.startswith(".") or p == "node_modules" for p in parts):
        return True
    if name.lower() in SKIPPED_NAMES:
        return True
    stem, ext = posixpath.splitext(name)
    return ext.lower() in files.MARKDOWN_EXTS and stem.lower() in SKIPPED_STEMS


class GithubClient:
    """GitHub API and raw file access on top of the SSRF-safe fetcher."""

    def __init__(self, fetcher: net.Fetcher) -> None:
        self.fetcher = fetcher
        self.token = fetcher.config.github_token

    def api(self, path: str, *, ok_404: bool = False) -> Any:
        url = f"{API}{path}"
        res = self.fetcher.get(
            url,
            accept="application/vnd.github+json",
            allowed_types=("application/json",),
            bearer=self.token,
            raise_for_status=False,
        )
        if res.status == 200:
            try:
                return json.loads(res.body)
            except ValueError as exc:
                raise net.FetchError("GitHub returned invalid JSON") from exc
        if res.status == 404 and ok_404:
            return None
        self._raise(res)
        raise AssertionError  # pragma: no cover

    def _raise(self, res: net.Fetched) -> None:
        h = res.headers
        limited = res.status == 429 or (
            res.status == 403
            and (h.get("x-ratelimit-remaining") == "0" or b"rate limit" in res.body[:2000].lower())
        )
        if limited:
            hint = (
                "the configured PV_GITHUB_TOKEN is also limited; wait for the reset"
                if self.token
                else "set PV_GITHUB_TOKEN to raise the limit (60 requests/hour without one)"
            )
            reset = (
                f" (resets at unix time {h['x-ratelimit-reset']})"
                if "x-ratelimit-reset" in h
                else ""
            )
            raise net.FetchError(f"GitHub API rate limit reached{reset}; {hint}")
        if res.status == 401:
            raise net.FetchError("GitHub rejected the credentials (check PV_GITHUB_TOKEN)")
        if res.status == 404:
            raise net.FetchError(
                "GitHub repository, branch or file not found "
                "(private repositories need PV_GITHUB_TOKEN)"
            )
        raise net.FetchError(f"GitHub answered {res.status}")

    def raw(self, url: str) -> str:
        res = self.fetcher.get(url, allowed_types=TEXT_TYPES, bearer=self.token)
        return sources.decode_text(res.body)


@dataclass
class _Candidate:
    path: str
    size: int


@dataclass
class _Item:
    """One file to parse: fetched from `url`, or given inline as `text` (small gist files)."""

    name: str
    html_url: str
    url: str | None = None
    text: str | None = None


class GithubImporter:
    name = "github"
    description = (
        "GitHub repository (optionally a folder or file) or gist: .md .json .yaml .csv files"
    )

    def parse(self, source: Any) -> list[PromptDraft]:
        url = source if isinstance(source, str) else sources.option(source, "url")
        if not isinstance(url, str) or not url.strip():
            raise ValidationFailed("GitHub source needs a `url`")
        mapping = None
        if isinstance(source, dict) and source.get("mapping") is not None:
            from promptvault.importers import tabular

            mapping = tabular.parse_mapping(source["mapping"])
        target = parse_url(url)
        client = GithubClient(net.get_fetcher())
        cfg = client.fetcher.config
        if isinstance(target, GistTarget):
            items, license_, notes = self._gist(client, target, cfg)
        else:
            items, license_, notes = self._repo(client, target, cfg)
        drafts = self._parse_files(items, license_, mapping, notes)
        if not drafts:
            detail = " ".join(notes[:3]) or "No .md, .json, .yaml or .csv files found at that URL."
            raise ValidationFailed(f"No importable prompt files found. {detail}")
        drafts[0].warnings[:0] = notes
        return drafts

    # -- repository

    def _repo(
        self, client: GithubClient, t: RepoTarget, cfg: net.NetConfig
    ) -> tuple[list[_Item], str | None, list[str]]:
        base = f"/repos/{quote(t.owner)}/{quote(t.repo)}"
        info = client.api(base)
        license_ = _spdx((info.get("license") or {}).get("spdx_id"))
        notes: list[str] = []
        if license_ is None:
            notes.append(
                "the repository has no clear license (none or NOASSERTION): rows need confirmation"
            )
        ref, folder, tree = self._resolve_tree(
            client, t, base, str(info.get("default_branch") or "main")
        )
        if tree.get("truncated"):
            notes.append("the repository tree was truncated by GitHub: some files were not seen")
        want_exact = t.kind == "blob"
        picked, skipped = self._select(tree.get("tree") or [], folder, want_exact, cfg)
        if skipped:
            notes.append(_skipped_note(skipped))
        html = f"https://github.com/{t.owner}/{t.repo}/blob/{quote(ref, safe='/')}/"
        raw = f"{RAW}/{quote(t.owner)}/{quote(t.repo)}/{quote(ref, safe='/')}/"
        items = [_Item(c.path, html + quote(c.path), url=raw + quote(c.path)) for c in picked]
        return items, license_, notes

    def _resolve_tree(
        self, client: GithubClient, t: RepoTarget, base: str, default_branch: str
    ) -> tuple[str, str, dict[str, Any]]:
        """(ref, folder-or-file path, tree). Branch names may contain slashes, so each split of
        the URL path into ref + path is tried, shortest ref first."""
        if not t.rest:
            candidates = [(default_branch, "")]
        else:
            candidates = [
                ("/".join(t.rest[:i]), "/".join(t.rest[i:]))
                for i in range(1, min(len(t.rest), MAX_REF_SEGMENTS) + 1)
                if i < len(t.rest) or t.kind == "tree"
            ]
        for ref, folder in candidates:
            tree = client.api(f"{base}/git/trees/{quote(ref, safe='')}?recursive=1", ok_404=True)
            if tree is not None:
                return ref, folder, tree
        raise ValidationFailed("Could not find that branch, tag or commit in the URL")

    def _select(
        self, entries: list[dict[str, Any]], folder: str, exact: bool, cfg: net.NetConfig
    ) -> tuple[list[_Candidate], list[str]]:
        prefix = folder.rstrip("/")
        found: list[_Candidate] = []
        skipped: list[str] = []
        for e in sorted(entries, key=lambda x: str(x.get("path"))):
            path = str(e.get("path") or "")
            if e.get("type") != "blob" or files.extension(path) not in files.SUPPORTED_EXTS:
                continue
            if prefix and not (path == prefix or (not exact and path.startswith(prefix + "/"))):
                continue
            if path != prefix and _skipped_file(path):
                continue  # an explicitly named file is never skipped
            size = int(e.get("size") or 0)
            if size > cfg.max_bytes:
                skipped.append(f"{path} (larger than {cfg.max_bytes} bytes)")
                continue
            found.append(_Candidate(path, size))
        kept: list[_Candidate] = []
        total = 0
        for c in found:
            if len(kept) >= cfg.github_max_files:
                skipped.append(
                    f"{len(found) - len(kept)} more file(s) beyond the limit of "
                    f"{cfg.github_max_files} (PV_IMPORT_GITHUB_MAX_FILES)"
                )
                break
            if total + c.size > TOTAL_MAX_BYTES:
                skipped.append(f"{len(found) - len(kept)} more file(s) beyond the total size limit")
                break
            total += c.size
            kept.append(c)
        return kept, skipped

    # -- gist

    def _gist(
        self, client: GithubClient, t: GistTarget, cfg: net.NetConfig
    ) -> tuple[list[_Item], str | None, list[str]]:
        data = client.api(f"/gists/{t.gist_id}")
        html = str(data.get("html_url") or f"https://gist.github.com/{t.gist_id}")
        notes = ["gists carry no license information: rows need license confirmation"]
        skipped: list[str] = []
        items: list[_Item] = []
        entries = sorted((data.get("files") or {}).values(), key=lambda f: str(f.get("filename")))
        for f in entries:
            name = str(f.get("filename") or "")
            if files.extension(name) not in files.SUPPORTED_EXTS:
                continue
            if len(items) >= cfg.github_max_files:
                skipped.append(f"more files beyond the limit of {cfg.github_max_files}")
                break
            if f.get("truncated") or "content" not in f:
                raw_url = str(f.get("raw_url") or "")
                if urlsplit(raw_url).hostname != "gist.githubusercontent.com":
                    skipped.append(f"{name} (no content available)")
                    continue
                items.append(_Item(name, html, url=raw_url))
            else:
                items.append(_Item(name, html, text=str(f["content"])))
        if skipped:
            notes.append(_skipped_note(skipped))
        return items, None, notes

    # -- parsing

    def _parse_files(
        self,
        items: list[_Item],
        license_: str | None,
        mapping: dict[str, str] | None,
        notes: list[str],
    ) -> list[PromptDraft]:
        client = GithubClient(net.get_fetcher())

        def load(item: _Item) -> tuple[str | None, str | None]:
            if item.text is not None:
                return item.text, None
            try:
                return client.raw(str(item.url)), None
            except (
                net.FetchError,
                ValidationFailed,
            ) as exc:  # one bad file does not fail the import
                return None, exc.detail

        with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
            loaded = list(pool.map(load, items))

        drafts: list[PromptDraft] = []
        skipped: list[str] = []
        for (text, error), item in zip(loaded, items, strict=True):
            name = item.name
            if text is None:
                skipped.append(f"{name} ({error})")
                continue
            try:
                parsed = files.parse_text(name, text, mapping)
            except DomainError as exc:
                skipped.append(f"{name} ({exc.detail})")
                continue
            for d in parsed:
                if not (d.source_url or "").strip():
                    d.source_url = item.html_url
                if license_ and not (d.license or "").strip():
                    d.license = license_
                d.errors = [f"{name}: {e}" for e in d.errors]
                drafts.append(d)
            if len(drafts) > sources.MAX_PARSE_ROWS:
                raise ValidationFailed(f"Too many rows (limit {sources.MAX_PARSE_ROWS})")
        if skipped:
            notes.append(_skipped_note(skipped))
        return drafts


def _spdx(value: Any) -> str | None:
    text = str(value or "").strip()
    return None if text.lower() in UNCLEAR_SPDX else text


def _skipped_note(skipped: list[str]) -> str:
    shown = "; ".join(skipped[:5])
    more = f"; and {len(skipped) - 5} more" if len(skipped) > 5 else ""
    return f"skipped {len(skipped)} item(s): {shown}{more}"
