---
title: "PromptVault — Prompt Engineering Library: Product & Technical Spec"
subtitle: "Draft v0.1"
---

# 1. Overview

**PromptVault** is a self-hostable prompt library. It ships with a curated seed set of prompts across ~30 professional and technical categories. Users can create, edit, delete, search, filter, import and export prompts.

**Stack:** Python (FastAPI) backend, React (Vite + TypeScript) frontend, SQLite by default (Postgres optional), GitHub for source, CI and releases.

**Goals**

- Local-first. Works offline with one command and no account.
- Fast full-text search over thousands of prompts.
- Prompts are first-class structured objects (variables, versions, tags), not loose text blobs.
- Several install paths: Docker, pip/pipx, terminal script, desktop-style launcher.

**Non-goals (v1):** multi-tenant SaaS, billing, built-in LLM chat UI (a "Run" panel is a v1.5 stretch), real-time collaboration.

# 2. Users & Use Cases

| Persona | Need |
|---|---|
| Professional (HR, lawyer, marketer) | Find a good starting prompt fast, fill variables, copy |
| Maker / engineer | Store and iterate domain prompts (3D printing, electronics, coding) |
| Student | Browse by subject and difficulty |
| Power user | Bulk import, version history, API/CLI access |

# 3. Functional Requirements

## 3.1 Prompt CRUD

- **Create / edit / delete / duplicate** a prompt through UI, REST API and CLI.
- **Soft delete** with a Trash view (30-day purge, configurable). Hard delete is available from Trash.
- **Version history:** every save creates a revision (diff view, restore). The prompt table keeps the current version, and `prompt_revision` holds the history.
- **Bulk actions:** multi-select to tag, move category, favorite, export, delete.

## 3.2 Prompt Data Model

| Field | Type | Notes |
|---|---|---|
| id | UUID | stable across export/import |
| title | text | required |
| body | text (Markdown) | supports `{{variable}}` placeholders |
| description | text | what it does, when to use it |
| category_id | FK | one primary category |
| tags | many-to-many | free-form, lowercase |
| variables | JSON | `[{name, label, default, type, options}]`, auto-detected from body |
| model_hints | JSON | recommended models/params (e.g. "Claude, GPT-4o, temp 0.3") |
| output_format | text | optional, e.g. "table", "JSON", "email" |
| difficulty | enum | beginner / intermediate / advanced |
| prompt_type | enum | system / user / template / chain (multi-step) |
| source | text | "seed", "user", "import:<name>", with source URL and license |
| license | text | SPDX id or "user-owned" |
| is_favorite | bool | |
| rating, use_count | int | local usage stats |
| created_at, updated_at, deleted_at | timestamps | |

**Categories** are hierarchical (category → subcategory) with an icon and sort order.

## 3.3 Variable Fill & Copy

- The prompt detail view renders a form from `variables`.
- Live preview shows the rendered prompt. One-click Copy, plus "Copy as system / user / JSON messages".
- Fill values can be saved as presets per prompt.

## 3.4 Search & Filter

- **Full-text search** across title, body, description and tags.
  - SQLite FTS5 with BM25 ranking and prefix matching. Postgres `tsvector` + GIN is the equivalent.
  - Typo tolerance via trigram fallback.
- **Filters** (combinable, URL-persisted): category/subcategory, tags (AND/OR), difficulty, prompt type, source, model hint, favorites, date range, has-variables.
- **Sort:** relevance, newest, recently used, most used, rating, A–Z.
- **Saved searches** and collections ("My Resume Kit").
- **Command palette** (Ctrl/Cmd+K) for instant search and jump.
- **Stretch (v1.5):** optional semantic search using local embeddings (sentence-transformers or Ollama) stored in sqlite-vec, merged with BM25 results (hybrid).

## 3.5 Import

An importer plugin interface (`Importer.parse(source) -> list[PromptDraft]`) feeds a common pipeline: **parse → normalize → dedupe → preview → commit**.

| Source | Format |
|---|---|
| JSON / CSV / XLSX | Column-mapping UI |
| Markdown files / folder / ZIP | One prompt per file; YAML front-matter is mapped to fields |
| GitHub repo / gist URL | Fetches `.md/.json/.yaml/.csv` via the GitHub API |
| Public datasets | e.g. Hugging Face prompt datasets (CSV/Parquet) via URL |
| Web page URL | Extract a prompt from a page (best-effort) |
| Clipboard paste | Single or multiple, split by delimiter |
| Other tools | LangChain Hub / PromptLayer / Langfuse-style JSON exports (adapters added over time) |
| PromptVault export | Lossless round-trip |

Pipeline rules:

- **Dedupe:** exact match on a hash of the normalized body, plus fuzzy match (MinHash or rapidfuzz ≥ 0.92). The user chooses skip / replace / keep both.
- **Dry run preview** with per-row validation errors before commit.
- **Provenance:** source URL and license are stored per prompt. Imports from repos without a clear license are flagged for the user to confirm.
- Imports run as background jobs with progress (SSE).

**Implementation notes (M3a, deviations from the text above):**

- **Fuzzy matching uses stdlib `difflib`, not MinHash or rapidfuzz** (no new dependency). It lives behind one function, `importers/dedupe.similarity(a, b)`, so rapidfuzz can replace it in that one file. Order: exact hash of the normalized body (the stored `body_hash`), then cheap prefilters (length ratio, token overlap, character multiset), then `SequenceMatcher`. Threshold `FUZZY_THRESHOLD = 0.92`, untuned. Only the first 8000 characters of a body are compared. Revisit rapidfuzz as an optional extra once real large imports exist and a benchmark shows difflib is too slow.
- Duplicates are only ever matched against live prompts. A body that equals a trashed prompt is imported as a new prompt (with a warning); the trashed prompt is never restored or changed.
- Commit actions per duplicate are `skip` (default), `replace` (the normal update path, so the old version stays as a revision) and `keep_both`. A duplicate of an earlier row in the same batch can only be skipped or kept.
- Rows with a missing or unclear license (`needs_license_confirm`) are refused at commit unless the request sets `confirm_license` or lists the row in `confirmed_rows`; other rows still import.
- Commits up to 25 rows run inside the request (200); larger ones return a pending job (202) with `GET /jobs/{id}` and `GET /jobs/{id}/events` (SSE: `progress`, then `done` or `failed`). A job is one transaction, so a failure leaves no partial import.
- **M3b importers.** `json`, `csv`, `xlsx`, `markdown` and `clipboard` are registered importers; `GET /import/importers` lists them. Files travel inside the JSON request (`content` for text, `content_base64` for binary), not as multipart uploads, so no upload dependency is needed. XLSX needs the optional extra `promptvault[xlsx]` (openpyxl, read-only, cached values only: formulas are never evaluated) and reports itself as unavailable without it.
- Column mapping is a backend feature in M3b: headers are matched by alias and an explicit `mapping` ({field: column}) overrides; the applied mapping and ignored columns appear as warnings on the first row of the preview. The mapping UI is a later card.
- ZIP sources are checked (entry count, expanded size, member size, path traversal, symlinks) and never extracted to disk. Request-level `default_license` and `default_source_url` fill only rows that have none.
- CLI: `promptvault import <importer> <file|folder|->` runs the same pipeline in-process (no job), with `--dry-run`, `--on-duplicate`, `--confirm-license` and a confirmation step.
- Request caps: `PV_IMPORT_MAX_ROWS` (2000) and `PV_IMPORT_MAX_PAYLOAD_BYTES` (5 MiB), answered with 413 problem+json.

**Implementation notes (M3c, deviations):**

- **Fetcher (`importers/net.py`, the only network code).** Stdlib `http.client`, no new dependency. http(s) only, ports 80/443, no userinfo; the host is resolved and refused if ANY address is not globally routable (odd IPv4 literals are parsed in code; IPv4-mapped, compatible, 6to4 and NAT64 forms are unwrapped). The connection is pinned to the validated address (Host header and SNI keep the name), redirects are followed by hand (max 3, each hop re-validated, no https to http), bodies are streamed under a byte cap that also bounds decompressed size (gzip bombs), with connect/total timeouts, a content-type allowlist, no cookies and a fixed User-Agent. Small 5-minute cache so preview then commit fetch once. Policy refusals are 422, remote failures 502.
- **Escape hatch:** `PV_IMPORT_ALLOW_PRIVATE_HOSTS` (host names, IPs, CIDRs; empty by default). Entries match exactly (no subdomain wildcard); an allowed host may use any port. Cloud-metadata addresses stay blocked unless listed explicitly.
- **GitHub:** the repo response's `license.spdx_id` is used instead of a separate `/license` call (saves one of 60 unauthenticated requests per hour); `NOASSERTION`/none leaves rows unlabelled so the license gate asks. README, LICENSE and similar files, dot-folders and a few config files are skipped; non-prompt JSON/YAML/CSV files are skipped with a warning. Raw files are fetched by 4 worker threads. `PV_GITHUB_TOKEN` is read from the environment only and sent only to api.github.com and raw.githubusercontent.com. Branch names with slashes are resolved by trying each split of the URL path, shortest ref first.
- **Web page:** `mode: page` (default) joins the blocks of a page into one prompt; `mode: blocks` gives one prompt per block, titled by the closest heading. Files are delegated to the format importers by extension, then by content type. The license is set only from a rel=license link, a license meta tag or a visible SPDX id.
- **Hugging Face:** datasets-server JSON API only (rows in pages of 100, `limit` capped by `PV_IMPORT_MAX_ROWS`); parquet is deferred. License from the dataset card; renamed datasets follow the card's `id`; gated/private datasets are refused (no HF token). Auto-matched `type`/`level` columns whose values are not valid prompt types or difficulties are dropped with a warning (unless mapped explicitly), because datasets often use those names for something else.
- The fetcher is process-wide (built from settings at app start; tests install a fake with `net.set_fetcher`). A repository import is not bounded by one overall deadline, only per request.

**Implementation notes (M3f, frontend deviations):**

- **Wizard.** The Data page's Import tab is a four-step wizard (source → mapping → preview → result) with the step in the URL (`?tab=import&step=`), Back/Next on every step and "Start over" (confirm when a preview exists). The source stays in memory, so re-preview and commit re-send it — the server re-parses on commit, nothing is trusted from the preview. A `useBlocker` confirm guards navigation away from `/data` while a preview is loaded (skipped on the result step); switching to the Export tab does not destroy the state.
- **Source step.** Importer cards (unavailable ones disabled with the server's reason, e.g. the XLSX install hint); a file input plus a drag-and-drop zone for the file importers, a paste box plus an optional delimiter for clipboard; default license (SPDX suggestions via datalist) and default source URL fields. The file size is checked in the browser against the 5 MiB payload cap before reading — binary files (xlsx, zip) against 4/3 of their size, since base64 inflates them. Files travel as text or base64 in the JSON request, as in the API.
- **Mapping (decision 1a: no backend inspect endpoint).** There is no `POST /import/inspect`; the wizard learns the applied columns from the first preview row's warnings ("columns mapped: title<-Name, ...", "columns ignored: ..."). If the importer produced such notes (CSV/XLSX/JSON tabular shapes), the wizard lands on a mapping step: an editable field → column table (the backend's twelve mappable fields), "Re-run preview" applies the chosen mapping (empty selections are dropped, so `''` never reaches the backend's Literal fields) and lands on the preview; "Skip" and Back behave sanely, and the step is hidden entirely when there are no notes.
- **Preview.** Counters and status filter chips (all/new/duplicate/invalid/license as toggle buttons, `aria-pressed`), a virtualized table (`@tanstack/react-virtual`, spacers above and below the window; the scroll element stays mounted so the virtualizer recovers from an empty first paint) with per-row expand: errors, warnings, duplicate match (exact/fuzzy with score, link to the matched prompt, in-batch duplicates show "row N of this batch" and no per-row action because the backend only allows skip/keep-both there), a draft body preview, a per-row duplicate action override and a per-row license confirmation checkbox. A default action selector sets skip/replace/keep-both; the Commit button states exactly what will happen ("Import: 2 new, 0 replaced, 1 skipped") and is disabled while any actionable row still needs a license confirmation (a grouped gate with per-row checkboxes and "Confirm all" → `confirm_license`).
- **Commit and result.** Up to 25 rows commit inline (200 with a finished job); larger ones answer 202 and the wizard polls `GET /jobs/{id}` every 500 ms, showing a live-region progress bar (processed/total, `role=progressbar`). A failed job shows the error and keeps the preview for a retry. On success the shell's categories/prompts version bumps so sidebar counts update, and the result step shows job counters, per-row outcomes (created/replaced/skipped/invalid/refused with reasons), links to the created prompts and to `/?source=import:<importer>` (the library's filter set now supports `source`), plus "Import another".
- **Tests and budget.** 22 new vitest/jsdom tests (wizard flows with a mocked API, mapping override in the commit body, license gate, duplicate override `actions`, unavailable importer, 413/422 errors, job polling to done and failed, empty state, step persistence/reset, clipboard source shape; pure helper units for size guard, base64, mapping parsing/building and action summaries). Bundle: the wizard lives in the lazy `/data` chunk (2 → 7.5 KB gzip); the main chunk grew from 117.6 to 117.9 KB gzip. Real-server check done on Windows (Chrome): the flow committed real rows, the library filter link works, no horizontal scroll at 390/1024/1440, light and dark verified by screenshot; new color pairs measure ≥ 4.5:1 in both themes. Not checked: Safari/Firefox, real screen readers, a native file-dialog keyboard path (dialog is OS UI).

**Implementation notes (M3g, frontend only — no backend change):**

- **URL source step (decision 1a).** One address field: typing re-runs the detection (`github.com`/`*.github.com` → github, `huggingface.co`/`hf.co` or a bare `org/name` dataset id → huggingface, any other parseable address → url, junk → keep the current importer); the importer cards are the manual override and survive importer switches along with the URL and its options. An "Options" section carries the per-importer fields: config / split / row limit for Hugging Face (a non-numeric or non-positive limit is dropped, never sent), `mode: page|blocks` for web pages; for GitHub a note that the folder or file is part of the URL. Each importer shows one sentence on what it reads and one on what it cannot do (no JavaScript pages, no crawling, no gated datasets, no parquet-only), the SSRF rule in one sentence, and the private-host hint pointing at `PV_IMPORT_ALLOW_PRIVATE_HOSTS` — never a UI for it.
- **Progress (decision 1b).** The commit flow no longer hand-rolls the polling loop: a `useJobWatcher` hook seeds the job state with one `GET /jobs/{id}` (which also answers immediately for a job that already finished inline), then opens an `EventSource` on `/jobs/{id}/events` for `progress` / `done` / `failed`; a stream error closes it and falls back to the 500 ms polling, shown as "Live updates dropped — checking every half second instead." The progress block adds live counters (created/replaced/skipped/invalid/refused) and says that the API has no cancel. The job id is kept in the URL (`?job=`), so a reload resumes watching: the seed GET restores the state, a running job shows the progress block with a note that the loaded preview itself does not survive a reload, a finished job lands on the result, and an unknown id says the server may have restarted. There is no jobs-list endpoint, so no "leave and come back" promise.
- **Remote notes and errors (decisions 1c/1d).** Preview failures from the network importers are mapped to plain text: a private-host/blocked 422 explains the public-hosts-only rule and names `PV_IMPORT_ALLOW_PRIVATE_HOSTS`; a rate-limit 502 carries the "60 anonymous GitHub requests per hour; set PV_GITHUB_TOKEN on the server" hint; a 502 otherwise says it is usually temporary; a 504/timeout says the remote took too long. Any URL a message echoes has its query string stripped before display. The preview shows a collapsible "What was fetched" block for remote imports, built from the first preview row's warnings (skipped files, truncation, other remote notes; the column-mapping notes stay with the mapping step). For network imports the license gate gains an explanation: GitHub labels rows with the repository license, a missing or NOASSERTION license leaves rows unlabelled and trips the gate.
- **Tests and budget (M3g).** 40 new vitest/jsdom tests, all network-free: a URL detection table (repo/tree/blob/gist, HF dataset URL and bare id, plain page, junk), request bodies per importer's options, the 422/502/504 message mapping incl. query-string stripping, fetched-notes parsing, and an `EventSource` double covering progress→done (stream closed, no polling), a `failed` event (preview kept), a stream error falling back to polling, resume from the `?job=` id and the unknown-job message. Bundle: the new code stays in the lazy `/data` chunk (7.5 → 10.4 KB gzip); the main chunk is unchanged at 117.9 KB gzip.
- **Real-browser check (Chrome, Windows).** Auto-detection live (typing an HF URL switches the picked card), a real `huggingface.co` preview and a real raw-GitHub-YAML `url` import (mapped to the mapping step), a real private-address refusal mapped to the `PV_IMPORT_ALLOW_PRIVATE_HOSTS` message, a 30-row clipboard commit through the real pipeline, a reload of a finished `?job=` URL landing on the result, tab order through the source step (sidebar → tabs → importer cards → URL field → options → defaults → nav), no horizontal scroll at 390/1024/1440 in light and dark, and the new color pairs ≥ 4.5:1 in both themes. Not checked: Safari/Firefox, real screen readers, a visually slow job (the real commits finished before the first view, so live SSE progress was observed only in jsdom).
- **Known gap (report, not fixed — no new import semantics).** A dataset whose columns do not auto-map (e.g. `fka/prompts.chat`, columns act/prompt) fails the first preview with 422 "No column for: title" before the mapping step exists, and the wizard has no way to send a `mapping` for such sources yet; the message names the needed mapping. A later card could offer a manual mapping entry on the source step.

## 3.6 Export

JSON (lossless), CSV, XLSX, a Markdown folder or ZIP, and a single-prompt "share" snippet.

**Implementation notes (M3d, deviations):**

- **Scope.** A full export is the live prompts, ordered by title then id; Trash is included only with `include_trashed` / `--include-trashed`. The selection reuses the list filters (`q`, `category` with children, `tags`, `favorite`, `difficulty`, `prompt_type`, `source`, `model`, `has_variables`) or an explicit id list (up to 500). Revision history is not exported (deferred).
- **What is in a file.** JSON carries every field the API shows, including personal state (`is_favorite`, `rating`, `use_count`, `last_used_at`), timestamps, `version`, `source` and `deleted_at`, in an envelope `{format: "promptvault-export", version: 1, exported_at, app_version, count, filters, categories, prompts}`. `categories` lists every category, parents first, because importers never create categories: restoring into an empty install means creating those first (the seed library does it at start). CSV and XLSX carry the same columns (header names are importer aliases); a Markdown file carries the content fields as YAML front-matter.
- **Round trip is lossless for content and provenance only (decision 3).** The importers are unchanged apart from undoing the formula guard (below). Re-importing restores `title, body, description, category, tags, difficulty, prompt_type, model_hints, output_format, disclaimer, license, source_url`; ids, personal state, timestamps and versions stay export-only and `source` becomes `import:<format>`. Also not restored: variable label, type, default and options (the pipeline rebuilds variables from the body), and text is normalized like any import (LF line endings, trailing spaces, three or more newlines, outer whitespace). CSV and XLSX split a tag that contains `,` `;` or `|` on re-import. A restore needs `--on-duplicate keep_both` when a library holds near-duplicate bodies and `--confirm-license` when prompts have no license; the 213 seed prompts re-import with the defaults. `tests/test_export_roundtrip.py` checks all four formats and asserts these losses explicitly.
- **Spreadsheet formula guard.** CSV and XLSX cells that start with `=`, `+`, `-`, `@`, tab or CR get a leading apostrophe (CLI/API `raw` turns it off). The csv and xlsx importers strip that apostrophe again (`tabular.unguard`), so a guarded file reads back unchanged; JSON and Markdown are untouched. XLSX text is always written as a typed string, never as a formula, even with `raw`.
- **CSV:** UTF-8 with BOM (`bom=false` / `--no-bom`; the CLI writes no BOM to stdout), CRLF line endings, RFC 4180 quoting, `tags` joined with `, `, `variables` as a JSON string, booleans as `true`/`false`.
- **XLSX** (optional extra; installed in the Docker image since M4a; the format reports itself unavailable with the install hint, 404 on use): write-only openpyxl, sheet `Prompts` with bold frozen header, column widths and wrapped body/description. Cells over 32767 characters are cut with a visible marker, control characters that XLSX forbids are removed and line endings are written as LF; each case is listed on a `Notes` sheet and counted in the `X-Export-Warnings` header.
- **Markdown:** a ZIP (or, in the CLI, a folder) with `<category-slug>/<title-slug>.md`, `uncategorised/` for prompts without a category. Names are ASCII slugs capped at 60 characters; Windows reserved names (`con`, `nul`, `com1` ...) get `-prompt`, names that slug to nothing become `prompt-<id8>`, clashes (compared case-insensitively) get `-2`, `-3`. ZIP entries have a fixed timestamp and attributes, so equal data gives equal bytes. One prompt via `GET /prompts/{id}/export?format=markdown` is a plain `.md` file.
- **Streaming and limits.** Records are read in batches of 500, each in its own short database session. JSON and CSV stream; XLSX and ZIP are built in a spooled temporary file (memory up to 8 MiB, then disk) and streamed afterwards. `PV_EXPORT_MAX_ROWS` (50000) caps an API export (413, checked before the first byte); the CLI has no cap. JSON `count` is the planned count. A large export is bounded by the import limits when it comes back: `PV_IMPORT_MAX_ROWS` (2000), the 5 MiB API payload cap, and for ZIP 5000 entries and 20 MiB expanded.
- **API:** `GET /export?format=json|csv|xlsx|markdown` (`md` is accepted) with the filters above, `POST /export` with `{format, ids?, filters?, include_trashed, pretty, bom, raw}`, `GET /export/formats`, `GET /prompts/{id}/export`, `GET /prompts/{id}/share?format=markdown|text|json&values=name=value`. Downloads carry `Content-Disposition` (`promptvault-export-YYYYMMDD.<ext>`), `X-Export-Count` and, when relevant, `X-Export-Missing` and `X-Export-Warnings`. An empty selection is an empty export (200, count 0). Share returns `{format, text, missing}`; with `values` the variables are filled in and only the unfilled ones are listed; an unknown variable name is a 422. Single-prompt export and share answer 404 for unknown or trashed ids.
- **CLI:** `promptvault export <json|csv|xlsx|markdown> [PATH|-]` with `--category`, `--tag`, `--favorite`, `-q`, `--id`, `--include-trashed`, `--zip`, `--force`, `--no-bom`, `--raw`, `--pretty`, `--json`; `-` (stdout) is json or csv only; an existing file or non-empty folder needs `--force`; files are written through a `.part` file; an empty selection exits 1. `promptvault share <id> [--format] [--values k=v ...]`.
- **Measured** (real server, Windows, localhost; docs only, not in CI): the 213 seed prompts export in 0.19 s (JSON, 582 KB), 0.08 s (CSV, 505 KB), 0.72 s (XLSX, 173 KB) and 0.36 s (ZIP, 220 KB); every format re-imports into an empty install with an identical content hash. 5000 generated prompts: JSON 3.3 s (16.8 MB), CSV 1.7 s (15.0 MB), XLSX 5.4 s (7.7 MB), ZIP 5.1 s (8.7 MB); server memory grew by about 10 to 30 MB during an export.

**Implementation notes (M3e, frontend deviations from the original choices):**

- **Entry point.** A `Data` link in the sidebar footer opens the lazy route `/data` with Export and Import tabs (`?tab=`, default export); the Import tab is a placeholder for M3f. Filters from the library URL carry over (`/data?tab=export&q=...`), so "Export" launched with active filters starts from the current filters scope; a radio switches to the whole library. The scope count is the list endpoint's `total` (one cheap call with `limit=1`, no rows loaded).
- **Download.** `POST /export` with fetch + Blob + object URL (the server's `Content-Disposition` name, `X-Export-Count` / `X-Export-Missing` / `X-Export-Warnings` in the result line). Empty-string filter values are dropped before sending — the backend's literal fields (`difficulty` etc.) reject `''` with 422. Errors (413 too many rows, 404, 422) show the problem+json `detail` verbatim in a `role=alert` region.
- **Per prompt.** The detail toolbar has an Export menu (Markdown `.md` or JSON, using `GET /prompts/{id}/export`) and a Share popover next to Copy: markdown/text/json switch, a call to `/share?values=name=value` with the current variable values (unset variables are omitted; baked-in defaults are not sent), the `missing` list as a hint, and clipboard copy with a "Copied ✓" toast. The Ctrl+K palette gained "Export library" (navigates to `/data?tab=export`) and "Share prompt" (opens the share popover of the open prompt via a window event; disabled with a hint when no prompt is open).
- **Deviations.** No bulk selection exists in the list, so there is no "Export selected" trigger; the id-based export stays API/CLI only. `sort` is not sent (exports are ordered by title server-side). The share popover is not an item in the kebab menu (decision d chose the visible button). Bundle: the Data page lazy-loads at ~2 KB gzip; the main chunk grew from 116.2 to 117.6 KB gzip (the api client, toolbar actions and palette commands), the library view itself unchanged.

## 3.7 Obsidian (out of scope for the app)

Obsidian is used only to store **project documents** (this spec, plans, notes) while building PromptVault. The app has **no Obsidian integration**: no vault sync, no plugin, no vault path setting. Prompts and code are never stored in the vault; prompts live in the app database and in the GitHub repo (`seed/`).


## 3.8 Seed Library

Ship **5–10 prompts per category** (v1.0 target: 5–10 per category, ≈ 250 total; more can be added in later releases), stored as versioned YAML in the repo at `seed/<category>/<slug>.yaml`.

**Categories (v1):**

| Group | Categories |
|---|---|
| Career | Resume Writing · Job Interviews · Job Searching · Networking & LinkedIn |
| Growth | Marketing · Sales · SEO · Social Media · Branding · E-commerce |
| Business | Business Strategy · HR · Finance · Project Management · Customer Support |
| Professional | Legal · Real Estate · Writing & Editing · Research |
| Creative | Image Generation · Video Generation · Design · Music & Audio |
| Technical | Coding · DevOps · Data & Analytics · Embedded/Electronics · 3D Printing |
| Education | Students · STEM · Physics · Math · Science · Engineering |
| Meta | Prompt Engineering (meta-prompts, evaluators, chain-of-thought templates) |

Users can add their own categories. Categories are data, not code.

**Seed quality bar:**

1. Each prompt has a role, task, context variables, constraints, output format, and at least one example or quality check.
2. Written by us or generated and then human-reviewed. Only content we own, or that is licensed permissively with attribution, is included. Third-party prompts carry their source and license.
3. A CI linter checks: required fields, variable declarations match the body, no duplicate slugs, length limits, no PII or secrets.
4. **Legal/finance/medical-adjacent prompts** carry a disclaimer field ("Not professional advice") shown in the UI.
5. Seed loading is idempotent (keyed by `seed_id`). User edits to a seeded prompt are never overwritten by an upgrade. A "Reset to original" action is available per prompt.

**Seed generation workflow (build-time tooling, in `tools/seedgen/`):** a script drafts prompts per category from an outline file using an LLM, outputs YAML, then the linter and a human review PR gate it. Generated content is committed to the repo, not generated at runtime.

## 3.9 Other Features

- Favorites, collections, ratings, "recently used".
- Light/dark theme, keyboard shortcuts, responsive layout.
- Single-user and local only in v1: no auth, no accounts. The server binds to loopback only.
- Optional "Run" panel (v1.5): bring-your-own-key to call OpenAI/Anthropic/OpenRouter or a local Ollama endpoint with the rendered prompt. Keys are stored only in env/config, never in the DB.

# 4. Architecture

```
┌──────────────┐   REST/JSON + SSE   ┌─────────────────────────────┐
│ React SPA    │ ──────────────────► │ FastAPI app                 │
│ (Vite, TS)   │ ◄────────────────── │  routers: prompts, search,  │
└──────────────┘                     │  categories, import, export,│
                                     │  settings, jobs             │
 CLI (Typer) ──► same service layer  │  services / repositories    │
                                     │  importers (plugins)        │
                                     └──────────┬──────────────────┘
                                                │ SQLAlchemy 2 + Alembic
                                       ┌────────▼────────┐
                                       │ SQLite (FTS5)   │
                                       │ or Postgres     │
                                       └─────────────────┘
```

In production, FastAPI serves the built React assets as static files, so there is **one process and one port** (default 8080).

## 4.1 Backend

| Concern | Choice |
|---|---|
| Framework | FastAPI + Uvicorn |
| Validation | Pydantic v2 |
| ORM / migrations | SQLAlchemy 2.0, Alembic |
| DB | SQLite (WAL mode, FTS5) default; Postgres (experimental, section 6) through `DATABASE_URL` |
| Background jobs | In-process `asyncio` task queue with a jobs table (no Redis needed) |
| CLI | Typer (`promptvault ...`) |
| Packaging | `pyproject.toml`, managed with `uv`; distribution `prompt-vault` for PyPI (built and verified in M4b, uploaded by the owner) |
| Quality | ruff, mypy, pytest, pytest-asyncio, httpx test client |

Layering: `routers → services → repositories → models`. Importers are pure services, testable without HTTP.

## 4.2 Frontend

| Concern | Choice |
|---|---|
| Build | Vite + React 18 + TypeScript |
| Routing | TanStack Router (or React Router) |
| Server state | TanStack Query |
| UI | Tailwind CSS + shadcn/ui (Radix) |
| Editor | CodeMirror 6 (Markdown mode, `{{var}}` highlighting) |
| Lists | TanStack Virtual for large result sets |
| Forms | React Hook Form + Zod |
| API client | Generated from FastAPI's OpenAPI schema (openapi-typescript) |
| Tests | Vitest, React Testing Library, Playwright (e2e) |

**Performance targets:** initial JS ≤ 200 KB gzip (route-level code splitting), search results render < 100 ms after response, search API p95 < 50 ms at 10k prompts, debounced input (150 ms), optimistic updates on edit/favorite.

**Main screens:** Library (sidebar categories, filter bar, result list/grid) · Prompt detail (variable form, preview, copy) · Editor · Import wizard · Trash · Settings.

**Implementation note (M3f):** the frontend uses React 19 + React Router + plain CSS tokens (not Tailwind/Radix as in the table above; deviated since M1c). M3f completes the Import tab: the four-step import wizard (files/paste, mapping from the preview, preview table, results) lives in the lazy `/data` chunk (~7.5 KB gzip); the main chunk is 117.9 KB gzip against the 200 KB target. M3g keeps that split: the URL source step, the job watcher (SSE + polling fallback) and their tests grow the `/data` chunk to ~10.4 KB gzip; the main chunk is unchanged at 117.9 KB gzip.

## 4.3 REST API (v1, `/api/v1`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/prompts` | list + search + filter (`q`, `category`, `tags`, `difficulty`, `sort`, `cursor`) |
| POST | `/prompts` | create |
| GET / PUT / PATCH / DELETE | `/prompts/{id}` | read / replace / partial update / soft delete |
| GET | `/prompts/{id}/revisions` | history; `POST .../restore/{rev}` |
| POST | `/prompts/{id}/render` | render with variable values |
| POST | `/prompts/bulk` | bulk tag/move/delete (export of a selection: `POST /export`) |
| GET / POST / PUT / DELETE | `/categories`, `/tags`, `/collections` | taxonomy |
| POST | `/import/preview`, `/import/commit` | import pipeline; `GET /jobs/{id}` (+ SSE stream) |
| GET / POST | `/export?format=json|csv|xlsx|markdown` | export (download); `GET /export/formats`, `/prompts/{id}/export`, `/prompts/{id}/share` |
| GET | `/health`, `/version` | ops |

Auto-generated docs at `/docs`. Errors follow RFC 7807 problem+json. Cursor pagination.

## 4.4 CLI

```
promptvault serve [--host 0.0.0.0 --port 8080 --data-dir ~/.promptvault]
promptvault init                      # create DB, run migrations, load seed
promptvault seed --reset-category "SEO"
promptvault add / edit / rm / show <id>
promptvault search "cold email" --category sales --tag b2b
promptvault import <path|url> --type markdown|json|csv|github
promptvault export markdown ./out        # json|csv|xlsx|markdown, PATH or - for stdout
promptvault share <id> --format text --values name=Ada
promptvault doctor                    # diagnose paths and DB
```

# 5. Repository (GitHub)

```
promptvault/
├─ backend/
│  ├─ src/promptvault/{api,services,repos,models,importers,cli}/
│  ├─ tests/  pyproject.toml  hatch_build.py  README.md  LICENSE   (PyPI metadata, seed bundling; migrations live in src/promptvault/migrations)
├─ frontend/
│  ├─ src/  public/  package.json  vite.config.ts
├─ seed/<category>/<slug>.yaml
├─ tools/{seedgen,lint_seed.py,check_dist.py,dist_smoke.py,docker_smoke.sh,pg_smoke.py}
├─ docker/{Dockerfile,docker-compose.yml,compose.postgres.yml}
├─ scripts/{start.sh,start.ps1}          (network installers install.sh/install.ps1 were dropped in M4b, see section 6)
├─ docs/  (MkDocs Material site: install, CLI, API, import/export, config, service setup; SPEC)
├─ mkdocs.yml  release-please-config.json  .release-please-manifest.json  CHANGELOG.md (generated)
├─ .github/{workflows,ISSUE_TEMPLATE,PULL_REQUEST_TEMPLATE.md}
├─ Makefile  README.md  LICENSE  CONTRIBUTING.md  CODE_OF_CONDUCT.md  SECURITY.md
```

- **Branching:** trunk-based, with `main` protected and PRs requiring green CI.
- **Versioning:** SemVer, Conventional Commits, release-please for changelogs and tags.
- **License:** MIT or Apache-2.0 for code. The seed prompts are CC BY 4.0 or CC0 (decide before launch).
- **Community seed contributions:** a PR template and the seed linter make adding prompts a YAML-file PR.

**GitHub Actions**

| Workflow | Trigger | Does |
|---|---|---|
| `ci.yml` | PR / push | ruff, mypy, pytest (SQLite + Postgres matrix); eslint, tsc, vitest; seed lint; Playwright smoke |
| `docker-publish.yml` | push to main, tag `v*`, PR (build only), manual | Runs `ci.yml` as a gate, then a multi-arch (amd64/arm64) build and push to **GHCR** (`edge`; `X.Y.Z`, `X.Y`, `latest` on a tag), SBOM + provenance, smoke test of the pushed digest (M4a) |
| `package` and `package-windows` jobs in `ci.yml` | PR / push | Build UI + wheel + sdist, inspect contents, `twine check`, rebuild the wheel from the sdist, install into fresh venvs (py3.11 and 3.13 on Linux, 3.12 on Windows) and run `tools/dist_smoke.py`, run `start.sh` and `start.ps1` (M4b). Never uploads |
| `release.yml` | push to `main` | release-please: keeps a release PR open that bumps `CHANGELOG.md`, `backend/pyproject.toml` and `promptvault/__init__.py`; **merging the PR pushes the `v*` tag**. Never uploads to PyPI and never pushes a tag itself (M4c) |
| `docs.yml` | push to `main` | MkDocs Material site from `docs/` + `mkdocs.yml`, published to GitHub Pages (`mkdocs build --strict` first) (M4c) |
| `bundle.yml` | tag `v*` | PyInstaller single-file executables for Windows/macOS/Linux attached to the release |
| `codeql.yml` + Dependabot | scheduled | Security scanning, dependency updates |

# 6. Distribution & Deployment

| Method | Command / Artifact | Audience |
|---|---|---|
| **Docker (single container)** | `docker run -p 127.0.0.1:8080:8080 -v pv-data:/data ghcr.io/porthos42/promptvault:edge` | Most users |
| **Docker Compose** | `docker compose up -d` (SQLite) or `-f compose.postgres.yml` | Homelab / teams |
| **pipx / pip** | `pipx install 'prompt-vault[xlsx]' && promptvault serve` (the PyPI name `promptvault` belongs to another project) | Python users |
| **uvx (zero install)** | `uvx --from 'prompt-vault[xlsx]' promptvault serve` | Quick try |
| **From source (terminal)** | `git clone … && make dev` (installs, runs backend + Vite with hot reload) | Contributors |
| **Start scripts** | `./scripts/start.sh` or `.\scripts\start.ps1` (from a checkout: creates `backend/.venv`, installs editable, builds the UI if Node is present, serves) | Non-Docker users |
| **Standalone executable** | Download from GitHub Releases (PyInstaller) | Non-technical users |
| **systemd / Windows service** | Sample unit file and NSSM instructions in docs | Always-on server |
| **Cloud one-click** | Fly.io, Railway, Render config files (`fly.toml`, `railway.json`, `render.yaml`) | Remote access |
| **Kubernetes (stretch)** | Helm chart or plain manifests | Teams |
| **Desktop wrapper (stretch)** | Tauri shell around the local server | Polished desktop |

**Docker details**

- Multi-stage build: Node stage builds the frontend, Python stage installs the wheel plus static assets. Final image is `python:3.12-slim`, non-root user, `HEALTHCHECK` on `/health`, target size under 200 MB.
- Volumes: `/data` (DB, config) (a named volume, or a bind mount on Windows).
- Env config (12-factor): `PV_DATABASE_URL`, `PV_DATA_DIR`, `PV_PORT`, `PV_SEED_ON_START=true`, `PV_LOG_LEVEL`, `PV_CORS_ORIGINS`.
- Container startup runs migrations, then seeds (idempotent), then starts Uvicorn.

**Implementation notes (M4a, deviations):**

- **Decisions (confirmed with the owner, all proposed defaults).** Image `ghcr.io/porthos42/promptvault`; PostgreSQL compose file shipped as EXPERIMENTAL after a migration check; openpyxl in the image; platforms linux/amd64 + linux/arm64; tags `edge` on push to main and `X.Y.Z`, `X.Y`, `latest` on a `v*` tag (PRs build amd64 only and never push); base `python:3.12-slim` (Node stage on `node:22-slim`).
- **Dockerfile** (`docker/Dockerfile`): three stages. (1) Node builds the UI on the build platform (`--platform=$BUILDPLATFORM`; output is architecture independent). (2) A Python stage runs `pip wheel` for the app (with UI and seed library) and all dependencies. (3) The runtime stage installs only those wheels through a bind mount (`pip install --no-index`; the wheels never enter a layer), uninstalls pip and setuptools, creates uid 10001, `/data` (volume, workdir) and sets `STOPSIGNAL SIGTERM`, a health check on `/api/v1/health` (interpreter, 30 s start period) and `CMD ["promptvault", "serve"]` (exec form: uvicorn is PID 1 and shuts down cleanly, exit code 0 in about a second). Nothing writes outside `/data` and `/tmp`, so the image runs with `read_only: true` + tmpfs `/tmp`, `cap_drop: [ALL]` and `no-new-privileges` (compose files and the smoke test use all three). OCI labels: title, description, source, licenses, revision, version. Build args: `EXTRAS` (default `xlsx`), `PV_REVISION`, `PV_VERSION`. `PV_REVISION` is also exposed as `revision` by `GET /api/v1/version` (absent in non-image runs). The tag/version match is enforced by the publish workflow (a `vX.Y.Z` tag must equal the `backend/pyproject.toml` version).
- **Size budget (< 200 MB), measured** with `docker image ls` (uncompressed, Docker Desktop): 187 MB without extras, **189 MB with openpyxl (shipped)**, 211 MB with openpyxl and psycopg. The ceiling holds only because the image removes `uvloop`, `watchfiles` and `websockets` (pulled in by `uvicorn[standard]`, 19 MB; the server runs on asyncio, there is no WebSocket code and `--reload` is a development feature). Without that, openpyxl alone gave 209 MB. The `.dockerignore` keeps tests, docs, tools and the git history out of the build context.
- **Deviation: the PostgreSQL driver is not in the published image.** psycopg adds 22 MB (over the ceiling), so `docker/compose.postgres.yml` builds a local variant with `EXTRAS=xlsx,postgres`. The extra is `promptvault[postgres]` (`psycopg[binary]`).
- **PostgreSQL check (experimental, exercised).** Migrations against postgres 16: the chain failed at 0002 on `group_concat` (SQLite only). Fixed with `string_agg` for non-SQLite (the SQLite statement is unchanged). The FTS5 virtual tables and triggers were already SQLite-only. After that: migrations OK, and a smoke run (`tools/pg_smoke.py`, 36 checks, also a CI job) passed: seed library loaded, list, filters (`has_variables` uses `json_array_length`, which PostgreSQL provides for JSON), all sorts, create, update, revisions, use, render, trash/restore, export (json, csv, markdown, xlsx), import preview/commit, and a 60-row import running as a background job. **Gaps:** search is the LIKE fallback (substring, unranked, no typo correction, no FTS), not tsvector; the `relevance` sort has nothing to rank by; behaviour of real data upgrades, concurrency under load, backups and large libraries is untested; the shipped CI check is a smoke test, not the SQLite + Postgres matrix of section 8. `tsvector` + GIN search stays future work.
- **Compose** (`docker/docker-compose.yml`, `docker/compose.postgres.yml`): the host side of the port mapping defaults to the loopback address through `${PV_BIND}`; deviation from the card: Compose needs an IP there, not a host name. `PV_HOST_PORT` sets the host port (not `PV_PORT`, which is the app setting). The default tag is `edge` until the first release exists (`latest` does not exist before that); change the default in M4c. Named volumes `pv-data` and `pg-data`. The PostgreSQL file refuses to start without `POSTGRES_PASSWORD`, waits for the database health check, and needs a URL-safe password.
- **Publish workflow** (`docker-publish.yml`): `ci.yml` is also a reusable workflow (`workflow_call`) and runs as the gate before every push to GHCR, so CI runs twice for a push to main (once per workflow; their concurrency groups include the workflow name so they do not cancel each other). Permissions are `contents: read` and `packages: write` on the image job only. Build cache is GitHub Actions cache; provenance (`mode=max`) and SBOM attestations are on. After pushing, the job inspects the manifest and runs `tools/docker_smoke.sh` against the pushed digest. The CI docker job builds amd64 only and also runs that script (health, seed library, non-root, create + restart persistence, `export json -`, `export xlsx`, graceful stop, size ceiling) plus an informational Trivy scan (HIGH/CRITICAL with a fix, never fails the build).
- **First publish.** A first push to GHCR can create the package as private; here it was public after the first publish (verified anonymously), so no settings change was needed. A `v*` tag is only pushed with the owner's go-ahead.
- **Not checked locally.** Running the arm64 image natively (the arm64 build runs only in CI under QEMU, and the published digest is smoke-tested on amd64 only); `docker scout` needs a Docker login and trivy is not installed here, so the image scan only runs in CI.

**Implementation notes (M4b, deviations):**

- **Decisions (confirmed with the owner, all proposed defaults).** Distribution name `prompt-vault`; Python `>=3.11`; seed library bundled from `../seed`; sdist includes the built UI; start scripts `start.sh` + `start.ps1` only; version kept in `pyproject.toml` and `promptvault/__init__.py` with a test that they match; `xlsx` stays an extra and `all` is added.
- **Name.** `promptvault` on PyPI (and TestPyPI) belongs to an unrelated project (0.0.4 by another author), so nothing is published under it. `prompt-vault` and `prompt_vault` returned 404 (free) when checked on 2026-11-02 and again before the build; re-check right before the first upload, because names can be taken at any time. The import package (`promptvault`), the CLI command (`promptvault`), the Docker image name and the repository keep their names, so `pipx install prompt-vault` gives the `promptvault` command. User-facing install hints say `prompt-vault[xlsx]`.
- **Nothing is uploaded.** No upload step, token, trusted-publisher setup or release workflow exists in the repository, and no `v*` tag was pushed. Uploading is a manual step of the owner (README and the card result describe it); automating it is an M4c question.
- **Metadata** (`backend/pyproject.toml`): SPDX `license = "MIT"` with `license-files` (needs hatchling 1.27 or newer, pinned in `build-system`), readme `backend/README.md` (a short PyPI page; `../README.md` would break the Docker build, which runs from `backend/`), classifiers (3.11 to 3.13, FastAPI, Alpha), project URLs, extras `xlsx`, `postgres` (experimental) and `all`. `backend/LICENSE` is a copy of the root license, kept equal by a test.
- **Seed library and UI inside the artifacts.** The seed folder is outside `backend/`, and the UI is gitignored, so a naive build would silently ship an empty library and no UI. `backend/hatch_build.py` (a hatch build hook) adds `../seed` as `promptvault/seed` (wheel) or `src/promptvault/seed` (sdist), does nothing when the package folder already holds a copy, fails when the library is missing, and fails when `static/index.html` is missing (editable installs and `PV_ALLOW_NO_UI=1` are exempt). A hook was used instead of a static `force-include` because `uv build` builds the wheel from the sdist, where `../seed` does not exist. The Dockerfile now copies `README.md`, `LICENSE` and `hatch_build.py` next to `pyproject.toml` and the seed to `/seed` (the sibling folder the hook reads), instead of copying it into `src/`.
- **sdist policy.** The sdist contains `src/promptvault` (with the built UI and the seed library), `hatch_build.py`, `README.md`, `LICENSE` and `pyproject.toml`, and no tests, so it builds a complete wheel without Node and without the rest of the repository (CI rebuilds a wheel from the unpacked sdist and inspects it). Because the UI is a build product, the sdist is only as current as the UI built before `uv build`; the guard above refuses to build without it.
- **Sizes (measured):** wheel 704 KiB, sdist 543 KiB. A clean venv holds only the declared dependencies (no pytest, ruff or mypy); `uvicorn[standard]` still brings `uvloop` (on Linux and macOS), `watchfiles` and `websockets`, unlike the Docker image, which removes them for its size budget.
- **Checks** (`tools/check_dist.py`, `make check-dist`, CI): wheel and sdist contain `static/index.html` and assets, 213 seed prompts plus `categories.yaml`, the migrations, the license, the console script and the expected metadata, and no tests, `.pyc`, `.db` or `node_modules`. `tools/dist_smoke.py` runs against an installed package: `promptvault version`, serve on a spare port, health, `/` and an SPA route serve the UI, the library has 213 prompts, create and list, `export json`, XLSX unavailable (and naming the extra) or working, then it stops the server and confirms the port is closed.
- **Start scripts.** `scripts/start.sh` (bash, `set -euo pipefail`, bash 3.2 safe) and `scripts/start.ps1` (Windows PowerShell 5.1 and PowerShell 7, ASCII, CRLF) run from a checkout. They use uv when present (`uv sync --extra xlsx`, then `uv run --no-sync promptvault serve`), otherwise Python 3.11+ with `venv` and `pip install -e backend[xlsx]`. The UI is built (`npm ci` when `node_modules` is missing, then `npm run build`) when Node and npm exist and `static/index.html` is missing or older than `frontend/src` (`--rebuild-ui` forces it, `--no-ui-build` skips it); without Node the API starts alone and the script says so. `--port` and `--host` override `PV_PORT` and `PV_HOST`, a non-loopback host prints a no-authentication warning, a bad port is exit code 2, a failing step exit code 1. Nothing is written outside the repository and the data directory, and nothing uses `sudo`. The PowerShell flags are `-Port`, `-BindHost` (`$Host` is a reserved name), `-NoUiBuild`, `-RebuildUi`; a blocked execution policy needs `powershell -ExecutionPolicy Bypass -File`. The network installers `install.sh` and `install.ps1` from the original tree were dropped.
- **Makefile:** `make dist` (UI build, `uv build`, `check-dist`), `make check-dist` (inspection + `twine check`), `make start`; `make dev` is unchanged.
- **CI:** the `package` job (Linux) builds, inspects, runs `twine check`, rebuilds a wheel from the sdist, proves that a build without the UI fails, installs the wheel into fresh venvs (3.11 and 3.13, with and without `xlsx`) and runs the smoke, and runs `start.sh`. `package-windows` installs the wheel on Windows (3.12), parses `start.ps1` with Windows PowerShell 5.1 and PowerShell 7 and runs it. The `docker` job is unchanged apart from the Dockerfile edit above.
- **Checked locally (Windows 11).** Wheel and sdist built from a clean copy of the working tree (identical file list to the in-place build); `twine check` passed; install and smoke with `uv pip` on Python 3.11, 3.12 and 3.13, each with and without `xlsx`; plain `venv` + `pip` (Python 3.14, which CI does not cover); `uv tool install` (used instead of pipx, which is not installed on this machine); `uvx --from <wheel>` with and without the extra; a data directory created by M4a code (the same migration chain, so the upgrade is a no-op) opened by the new wheel; `start.ps1` with uv (it built the UI by itself) and without uv on PATH (venv + pip), `start.sh` through Git Bash.
- **Not checked.** `pipx` itself; macOS and native Linux (covered only by CI); any real browser against the installed package (the smoke fetches `/` and checks the HTML); PowerShell 7 running `start.ps1` end to end (only parsed); `start.sh` on bash 3.2 (written to be compatible); building on Python 3.14 in CI; installing from a real PyPI index (nothing is uploaded). The Docker image still builds from the same sources, which CI proves.

**Implementation notes (M4c, deviations):**

- **Decisions (confirmed with the owner, all proposed defaults).** release-please bootstrapped at the current version; release PRs are the owner's to review and merge (the merge creates the `v*` tag — no automation pushes a tag); the PyPI upload stays manual forever; an MkDocs Material docs site published to GitHub Pages by CI on main; service setup as docs only (no packaged unit files).
- **release-please** (`release-please-config.json` + `.release-please-manifest.json`, run by `.github/workflows/release.yml` on pushes to `main` with `contents: write` and `pull-requests: write`; gated to `refs/heads/main` and to non-Dependabot actors — Dependabot pushes land on branches anyway). Manifest config must be **JSON**, not YAML: release-please parses the manifest config with `JSON.parse` regardless of the file extension, and a `.yml` config fails the run with "Failed to parse manifest config JSON". Manifest config with `release-type: simple`, root package, `include-component-in-tag: false`, so tags are plain `vX.Y.Z`. Besides the root `CHANGELOG.md` it keeps two version files in sync: `backend/pyproject.toml` (a `toml` update at `$.project.version`) and `backend/src/promptvault/__init__.py` (a `generic` matcher on `__version__ = "..."`) — the same pair `backend/tests/test_packaging.py` asserts to match, so a bot edit that leaves them inconsistent fails CI on the release PR itself. Conventional Commits drive the bump (`feat:` → minor, `fix:` → patch).
- **Tag path already wired (verified by reading, not by tagging).** `docker-publish.yml` already runs on `tags: ["v*"]`, checks that the tag equals `backend/pyproject.toml`'s version, and tags the image `X.Y.Z`, `X.Y` and — through metadata-action's default `latest=auto` flavor — `latest` for non-prerelease tags. The compose default stays `edge`; a documented follow-up (comment in the compose file, note in the docs) flips it to `latest` after the first release-PR merge.
- **PyPI stays untouched.** The existing `package`/`package-windows` CI jobs build and verify the wheel and sdist on every push and every tag; there is no upload step, token or trusted publisher anywhere. The exact manual publish steps are in the README ("How releases happen") and docs/install.md.
- **Docs site.** `mkdocs.yml` at the repo root (MkDocs Material, light/dark palettes, repo links) with pages written for the site: `docs/index.md`, `install.md` (with per-method verify steps and the release story), `cli.md`, `api.md`, `import-export.md`, `configuration.md`, `serve.md`, plus `docs/SPEC.md` in the nav. Local gate: `uv run --no-project --with mkdocs-material mkdocs build --strict` (strict: warnings fail). `.github/workflows/docs.yml` builds the same command and publishes with the official Pages actions (`upload-pages-artifact` + `deploy-pages`, `pages: write` + `id-token: write`); it needs the repository's Pages source set to "GitHub Actions" — if the first deploy fails on permissions/settings, that is the check, not the workflow.
- **Service notes** (`docs/serve.md`): a hardened systemd unit example (dedicated non-root user, `PV_DATA_DIR` + `PV_HOST=localhost`, `NoNewPrivileges`, `ProtectSystem=strict` with `ReadWritePaths` for the data dir, `ProtectHome`, `PrivateTmp`, restricted address families and more), Windows notes (Task Scheduler task or NSSM wrapping `promptvault serve`), and the Docker-compose-with-`restart: unless-stopped` option. Documentation only — nothing is packaged or installed by the repo.
- **README:** the status line, the install section (one table, then per-method bullets each ending in a verify-after-install step), a "How releases happen" section stating what the automation does and does not do, the roadmap row, the project layout and the test commands were updated.
- **Not checked:** the tag path end to end (a `v*` tag does not exist until the owner merges the first release PR), the GitHub Pages publish (needs the Pages setting on the repository; watch the first `Docs` run), and the release-please version-file edits themselves (the bot's PR is where the toml/generic updates are proven).

**Config precedence:** CLI flags > env vars > `config.toml` in the data dir > defaults.

# 7. Non-Functional Requirements

- **Performance:** see 4.2. Cold start under 3 s on SQLite. Handles 50k prompts.
- **Security:** bind to `127.0.0.1` by default (explicit opt-in for `0.0.0.0`). Sanitize Markdown rendering (no raw HTML/script). Path-traversal guards on all import and export paths. GitHub tokens and API keys come from env only. SSRF protections on URL importers (block private IP ranges unless configured).
- **Reliability:** DB backup command (`promptvault backup`) and automatic daily snapshot (keep 7). Migrations are forward-only and tested.
- **Privacy:** no telemetry by default. Fully offline except for user-initiated imports and the optional Run panel.
- **Accessibility:** WCAG 2.1 AA, full keyboard navigation.
- **Compatibility:** Python 3.11+, Node 20+ for builds, modern evergreen browsers. Windows, macOS and Linux are all first-class (note path and line-ending handling).
- **Observability:** structured JSON logs and an optional Prometheus `/metrics` endpoint.
- **i18n:** English first. All strings go through i18n keys. Seed content is English only in v1.

# 8. Testing & Quality

- **Unit:** services, importers (golden-file fixtures per format), variable parser, dedupe logic.
- **Integration:** API against SQLite and Postgres.
- **E2E:** Playwright covering create → search → fill variables → copy → export.
- **Seed CI:** the linter plus a check that each category has ≥ 5 prompts.
- **Coverage gate:** 85% backend, 70% frontend.

# 9. Milestones

| Phase | Scope | Est. (solo, 5–15 hrs/wk) |
|---|---|---|
| **M0 – Foundations** | Repo, CI, schema + migrations, FastAPI skeleton, Vite skeleton, Docker dev setup | 1–2 wks |
| **M1 – Core CRUD + Search** | Prompt/category/tag CRUD, FTS5 search, filters, library UI, variable fill + copy | 3–4 wks |
| **M2 – Seed library** | Seed schema, linter, seedgen tooling, 5–10 prompts in each category (≈ 250 total) | 2–3 wks (parallel with M1) |
| **M3 – Import/Export** | Importer framework, JSON/CSV/MD/GitHub, dedupe, preview, export | 2–3 wks |
| **M4 – Distribution** | Dockerfile + GHCR, PyPI, start scripts, release automation, docs | 1–2 wks |
| **M5 – Polish & v1.0** | Versioning/trash UX, a11y pass, perf pass, README, demo GIF | 1–2 wks |
| **v1.5** | Semantic search, Run panel (test prompts against an LLM), executables, one-click cloud, Tauri | later |

Rough total to v1.0: **9–14 weeks** at the stated pace. Using AI coding agents should compress this.

# 10. Acceptance Criteria (v1.0)

1. `docker run` of the published image gives a working app with seed data in under 60 seconds.
2. Every category has ≥ 5 prompts, and the library holds about 250 prompts, all passing the linter.
3. A user can add, edit, delete (with restore) and duplicate a prompt from the UI, API and CLI.
4. Search returns ranked results across 10k prompts in < 50 ms p95. Any combination of filters works and persists in the URL.
5. Importing from JSON, CSV, a Markdown folder, and a public GitHub repo URL works, with dedupe preview.
6. Installation works via Docker, pipx, and from-source terminal script on Windows, macOS and Linux.
7. CI is green and the release workflow publishes the image and the wheel from a tag.

# 11. Risks & Decisions

| Risk / Question | Mitigation / Proposal |
|---|---|
| Licensing of third-party prompt collections | Seed with original content. Imports record source and license. Never bundle unlicensed prompts. |
| Seed quality at ~250 prompts | LLM draft + linter + human review; ship in waves, with core categories first |
| Legal/medical/finance misuse | Disclaimer field, shown in UI |
| Windows path and line-ending edge cases | Windows CI runner, normalize to LF on write, `pathlib` everywhere |
| Scope creep (Run panel, semantic search) | Held to v1.5 |

**Decisions made**

| # | Decision |
|---|---|
| 1 | Name: **Prompt Vault** (repo `promptvault`) |
| 2 | Free and open source for now. Proposed: MIT for code, CC0 for seed prompts (confirm before first release) |
| 3 | Obsidian holds project documents only. No prompts or code, and no app integration |
| 4 | v1 is single-user and local only |
| 5 | Seed target is 5–10 prompts per category |
| 6 | The "Run" panel moves to v1.5 |

# Appendix A — Seed Prompt File Format

```yaml
seed_id: resume-bullet-rewriter
title: Resume Bullet Rewriter
category: resume-writing
tags: [resume, ats, career]
difficulty: beginner
type: template
description: Turns a vague duty into a quantified, achievement-style bullet.
variables:
  - { name: job_title, label: Target job title, type: text }
  - { name: bullet, label: Original bullet, type: textarea }
  - { name: metrics, label: Known numbers (optional), type: textarea, default: "" }
output_format: "3 alternative bullets, each under 25 words"
model_hints: "Any chat model; temperature 0.4"
disclaimer: null
license: CC0-1.0
body: |
  You are an expert resume writer who specializes in ATS-friendly resumes.

  Rewrite the bullet below for a {{job_title}} application.

  Original bullet: {{bullet}}
  Known metrics: {{metrics}}

  Rules:
  - Start with a strong past-tense verb.
  - Quantify impact; if no numbers are given, suggest placeholders like [X%].
  - Keep each under 25 words.
  - Do not invent facts.

  Return 3 alternatives, then one sentence on which is strongest and why.
```

# Appendix B — Example Seed Outline (per category, for seedgen)

```
Resume Writing (target 30): summary writer, bullet rewriter, ATS keyword matcher,
  tailor resume to JD, cover letter, career-change narrative, gap explainer,
  skills section builder, LinkedIn headline, resume critique, ...
Job Interviews (target 30): STAR story builder, mock interviewer, behavioral Q bank,
  technical screen simulator, salary negotiation script, "tell me about yourself", ...
3D Printing (target 25): slicer settings advisor, print failure diagnosis,
  OpenSCAD generator, filament selection, tolerance/fit planner, ...
```
