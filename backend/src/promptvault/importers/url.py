"""Web page importer (best effort): one page or file by URL. No crawling, no JavaScript.

Source: a URL string or {url, mode?, mapping?}. Files are delegated to the format importers, by
extension first and then by content type: Markdown, plain text, JSON, YAML and CSV. HTML pages are
read with the stdlib parser: the title comes from <title> (else og:title, else the first heading)
and the prompt text from <pre>, <code> and <blockquote> blocks; script, style and similar
elements are ignored.

`mode: page` (default) makes ONE prompt per page by joining the blocks; `mode: blocks` makes one
prompt per block, titled by the closest heading above it. Pages are always flagged "review before
importing". The license is only set when the page says so (rel=license link, a license meta tag
or a visible `SPDX-License-Identifier:`); otherwise it stays unclear.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

from promptvault.importers import files, net, sources, tabular
from promptvault.importers.base import PromptDraft
from promptvault.services.errors import ValidationFailed

ACCEPT = "text/html,text/markdown,text/plain,application/json,text/csv;q=0.9,*/*;q=0.1"
HTML_TYPES = ("text/html", "application/xhtml+xml")
FILE_TYPES = (
    "text/markdown",
    "text/x-markdown",
    "text/plain",
    "application/json",
    "text/csv",
    "application/x-yaml",
    "text/yaml",
    "text/x-yaml",
    "application/yaml",
)
BY_CONTENT_TYPE = {
    "text/markdown": ".md",
    "text/x-markdown": ".md",
    "text/plain": ".md",
    "application/json": ".json",
    "text/csv": ".csv",
    "application/x-yaml": ".yaml",
    "text/yaml": ".yaml",
    "text/x-yaml": ".yaml",
    "application/yaml": ".yaml",
}
SKIP_TAGS = frozenset({"script", "style", "noscript", "template", "svg", "iframe", "object"})
BLOCK_TAGS = frozenset({"pre", "code", "blockquote"})
PARAGRAPH_TAGS = frozenset({"p", "div", "li", "ul", "ol", "tr", "h1", "h2", "h3", "h4", "h5", "h6"})
HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
BREAK, PARA = "\x00", "\x01"  # explicit line / paragraph breaks inside a blockquote
MIN_BLOCK_CHARS = 20
INLINE_CODE_MIN = 80  # a lone <code> counts only when it is multi-line or this long
MAX_TITLE = 120
SPDX = re.compile(
    r"SPDX-License-Identifier:\s*([A-Za-z0-9.+\-]+(?:\s+(?:OR|AND|WITH)\s+[A-Za-z0-9.+\-]+)*)"
)
CHARSET_META = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?([\w\-]+)""", re.IGNORECASE)
LICENSE_META_NAMES = frozenset({"license", "dc.rights", "dcterms.license", "dc.license"})


class _Page(HTMLParser):
    """Collects the title, license hints and the candidate text blocks of one HTML document."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.og_title = ""
        self.first_heading = ""
        self.license: str | None = None
        self.visible: list[str] = []  # all visible text, only searched for an SPDX id
        self.blocks: list[tuple[str, str, str]] = []  # (kind, text, closest heading)
        self._skip = 0
        self._in_title = False
        self._heading_tag: str | None = None
        self._heading_buf: list[str] = []
        self._heading = ""
        self._cap_tag: str | None = None  # outermost block being captured
        self._cap_depth = 0
        self._cap_buf: list[str] = []
        self._cap_heading = ""

    # -- helpers
    def _capturing(self) -> bool:
        return self._cap_tag is not None

    def _preformatted(self) -> bool:
        return self._cap_tag in ("pre", "code")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            self._meta(a)
            return
        if tag == "link" and "license" in a.get("rel", "").lower().split() and a.get("href"):
            self.license = self.license or a["href"].strip()
            return
        if tag in SKIP_TAGS:
            self._skip += 1
            return
        if self._skip:
            return
        if tag == "title":
            self._in_title = True
            return
        if tag in HEADINGS and not self._capturing():
            self._heading_tag, self._heading_buf = tag, []
        if tag in BLOCK_TAGS:
            if not self._capturing():
                self._cap_tag, self._cap_depth, self._cap_buf = tag, 1, []
                self._cap_heading = self._heading
            elif tag == self._cap_tag:
                self._cap_depth += 1
        elif self._capturing() and (
            tag == "br" or (tag in PARAGRAPH_TAGS and self._cap_tag == "blockquote")
        ):
            self._cap_buf.append(BREAK if tag == "br" else PARA)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in SKIP_TAGS and tag not in BLOCK_TAGS and tag != "title":
            self.handle_starttag(tag, attrs)  # <br/>, <meta .../>, <link .../>

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag == "title":
            self._in_title = False
        if tag == self._heading_tag:
            text = " ".join("".join(self._heading_buf).split())
            if text:
                self._heading = text
                self.first_heading = self.first_heading or text
            self._heading_tag = None
        if self._capturing():
            if tag == self._cap_tag:
                self._cap_depth -= 1
                if self._cap_depth == 0:
                    self._finish_block()
            elif tag in PARAGRAPH_TAGS and self._cap_tag == "blockquote":
                self._cap_buf.append(PARA)

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
            return
        if self._skip:
            return
        self.visible.append(data)
        if self._heading_tag:
            self._heading_buf.append(data)
        if self._capturing():
            self._cap_buf.append(data)

    def close(self) -> None:
        super().close()
        if self._capturing():
            self._finish_block()

    def _meta(self, a: dict[str, str]) -> None:
        key = (a.get("name") or a.get("property") or "").lower()
        content = a.get("content", "").strip()
        if key == "og:title" and content:
            self.og_title = content
        elif key in LICENSE_META_NAMES and content and self.license is None:
            self.license = content

    def _finish_block(self) -> None:
        kind = str(self._cap_tag)
        raw = "".join(self._cap_buf)
        self._cap_tag, self._cap_depth, self._cap_buf = None, 0, []
        if kind == "blockquote":  # source whitespace is layout; only <br> and <p> break lines
            flowed = re.sub(r"\s+", " ", raw).replace(PARA, "\n\n").replace(BREAK, "\n")
            text = "\n".join(line.strip() for line in flowed.split("\n"))
        else:
            text = raw.strip("\n")
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if len(text) < MIN_BLOCK_CHARS:
            return
        if kind == "code" and "\n" not in text and len(text) < INLINE_CODE_MIN:
            return
        self.blocks.append((kind, text, self._cap_heading))


def parse_html(html: str) -> _Page:
    page = _Page()
    page.feed(html)
    page.close()
    return page


def _decode(res: net.Fetched) -> str:
    if res.charset:
        return res.text()
    match = CHARSET_META.search(res.body[:2048])
    if match:
        try:
            return res.body.decode(match.group(1).decode("ascii"))
        except (UnicodeDecodeError, LookupError):
            pass
    return res.text()


def _clean_title(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_TITLE else text[: MAX_TITLE - 1].rstrip() + "\u2026"


class UrlImporter:
    name = "url"
    description = "Web page or file by URL: Markdown/JSON/CSV/YAML, or HTML (best effort, no JS)"

    def parse(self, source: Any) -> list[PromptDraft]:
        url = source if isinstance(source, str) else sources.option(source, "url")
        if not isinstance(url, str) or not url.strip():
            raise ValidationFailed("URL source needs a `url`")
        mode = sources.option(source, "mode") or "page"
        if mode not in ("page", "blocks"):
            raise ValidationFailed("mode must be 'page' or 'blocks'")
        mapping = tabular.parse_mapping(sources.option(source, "mapping"))

        path_ext = files.extension(urlsplit(url).path)
        by_extension = path_ext in files.SUPPORTED_EXTS or path_ext == ".txt"
        allowed = (
            *HTML_TYPES,
            *FILE_TYPES,
            *(("application/octet-stream",) if by_extension else ()),
        )
        res = net.get_fetcher().get(url, accept=ACCEPT, allowed_types=allowed)

        if res.content_type in HTML_TYPES:
            return self._page(res, str(mode))
        file_ext = path_ext if by_extension else BY_CONTENT_TYPE.get(res.content_type, ".md")
        return self._file(res, file_ext, mapping)

    @staticmethod
    def _file(res: net.Fetched, ext: str, mapping: dict[str, str] | None) -> list[PromptDraft]:
        name = urlsplit(res.url).path.rsplit("/", 1)[-1] or f"page{ext}"
        if files.extension(name) not in files.SUPPORTED_EXTS and files.extension(name) != ".txt":
            name = f"{name}{ext}"
        drafts = files.parse_text(name, sources.decode_text(res.body), mapping)
        for d in drafts:
            if not (d.source_url or "").strip():
                d.source_url = res.url
        if not drafts:
            raise ValidationFailed("No prompts found in that file")
        return drafts

    @staticmethod
    def _page(res: net.Fetched, mode: str) -> list[PromptDraft]:
        page = parse_html(_decode(res))
        if not page.blocks:
            raise ValidationFailed(
                "No prompt text found on that page: it has no <pre>, <code> or <blockquote> block. "
                "Pages built with JavaScript are not supported; try a raw Markdown/JSON URL, or "
                "paste the text with the clipboard importer."
            )
        page_title = _clean_title(page.title or page.og_title or page.first_heading) or (
            urlsplit(res.url).hostname or "Imported page"
        )
        license_ = page.license
        if not license_:
            m = SPDX.search(" ".join(page.visible))
            license_ = m.group(1) if m else None
        if license_:
            license_ = license_.strip()[:100]
        warning = "extracted from a web page, review before importing"
        drafts: list[PromptDraft] = []
        if mode == "page":
            body = "\n\n".join(text for _, text, _ in page.blocks)
            drafts.append(PromptDraft(title=page_title, body=body))
        else:
            seen: set[str] = set()
            blocks = []
            for b in page.blocks:
                if b[1] not in seen:
                    seen.add(b[1])
                    blocks.append(b)
            for i, (_, text, heading) in enumerate(blocks, 1):
                title = _clean_title(heading) or (
                    page_title if len(blocks) == 1 else f"{page_title} ({i})"
                )
                drafts.append(PromptDraft(title=title, body=text))
        for d in drafts:
            d.source_url = res.url
            d.license = license_
            d.warnings.append(warning)
        return drafts
