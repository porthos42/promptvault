# Prompt Vault

[![CI](https://github.com/porthos42/promptvault/actions/workflows/ci.yml/badge.svg)](https://github.com/porthos42/promptvault/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A self-hosted, searchable prompt engineering library. The goal is hundreds of ready-to-use prompts across careers, marketing, coding, STEM, 3D printing, image/video generation and more, with full create/edit/delete, search, filtering and import. Single-user and local-first. Free and open source.

> **Status: early development (M3c done).** The backend API, CLI, full-text search, the library UI (decluttered in M2f: grouped collapsible sidebar, one Filters control with removable chips, calmer list rows, tidier detail pane, mobile drawer) and the seed-library machinery (schema, linter, loader, reset) work. The seed library is complete for v1 (213 prompts across all 35 categories, 6-7 each), and importing works from the API and the CLI: JSON, CSV, XLSX (optional extra), Markdown (files, folders, ZIP) pasted text, GitHub repos/gists, web pages and Hugging Face datasets (all fetched through an SSRF-safe fetcher), with validation, exact and fuzzy dedupe, a dry-run preview, skip, replace or keep-both, a license gate and background jobs with SSE progress. Export and the import UI are not built yet. See [Roadmap](#roadmap) and the [full spec](docs/SPEC.md).

**Stack:** Python 3.11+ (FastAPI, SQLAlchemy 2, Alembic, Typer), React 19 + TypeScript (Vite), SQLite with FTS5 by default.

## Features

Available now:

- Prompt, category and tag CRUD through the REST API and the CLI
- Soft delete with Trash (restore, permanent delete, auto-purge after 30 days)
- Revision history per prompt, with restore
- `{{variable}}` detection from the prompt text, and a render endpoint that fills them in
- Duplicate and bulk actions (tags, category, favorite, delete, restore)
- Hierarchical categories, normalized tags, filters and cursor pagination
- Full-text search (SQLite FTS5): BM25 ranking with title/tag boosts, prefix and stemmed matching, "exact phrases", automatic typo correction, combinable with every filter, seven sort orders
- Index kept in sync by triggers; trashed prompts are excluded from search
- Library UI: category sidebar, URL-persisted filter bar (search, category, tags, difficulty, sort, favorites), virtualized infinite list, prompt detail with variable form, live preview and one-click copy, CodeMirror editor, Trash view, Ctrl+K palette, `/` to focus search, light/dark theme
- Seed library machinery: YAML prompt files, a CI linter, an idempotent loader that never overwrites your edits, and "Reset to original" per prompt or per category
- Docker image, CI on Linux and Windows

Planned: see [Roadmap](#roadmap).

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Node 20+ (Node is only needed to build the UI).

```bash
git clone https://github.com/porthos42/promptvault.git
cd promptvault
cd frontend && npm install && npm run build && cd ..   # builds the UI into the Python package
cd backend && uv sync
uv run promptvault serve                                # http://localhost:8080  (API docs at /docs)
```

Open the UI at the same address. The CLI and `/docs` remain available for scripting.

### Development (hot reload)

```bash
# terminal 1: API on :8080
cd backend && uv run promptvault serve --reload
# terminal 2: UI on :5173 (proxies /api to :8080)
cd frontend && npm run dev
```

`make dev` runs both if you have `make`.

### Docker

```bash
docker compose -f docker/docker-compose.yml up --build
# or
docker build -f docker/Dockerfile -t promptvault . && docker run -p 8080:8080 -v pv-data:/data promptvault
```

Data lives in `/data` (a named volume). The CLI works inside the container: `docker exec -it <container> promptvault list`. Published images and PyPI packages arrive in M4.

## CLI

```
promptvault serve [--host H] [--port P] [--reload]
promptvault init | doctor | version
promptvault seed [--reset ID ...] [--reset-category SLUG ...]   # load seed prompts / reset to original

promptvault add --title T --body "Rewrite {{bullet}}" -c category-slug -t tag -t tag
promptvault list [-c slug] [-t tag] [--favorite] [--json]
promptvault search "cold email" [-c slug] [-t tag] [--sort relevance|newest|updated|recent|popular|rating|title] [--json]
promptvault show <id-or-prefix> [--json]
promptvault edit <id-or-prefix> [--title ..] [--body-file f.md | --editor] [-t tag ...] [--favorite]
promptvault rm <id> [--permanent]      # to Trash; --permanent only for trashed prompts
promptvault restore <id>
promptvault trash list | purge [--older-than-days N]
promptvault category list | add NAME [--parent slug] | rm SLUG
promptvault tag list | rename OLD NEW | rm NAME

promptvault import <json|csv|xlsx|markdown|clipboard> <file | folder | -> [--dry-run] [--yes]
promptvault import <github|url|huggingface> <https://...> [--config C] [--split S] [--limit N] [--mode page|blocks]
    [-m field=column ...] [--sheet N] [--delimiter X] [--on-duplicate skip|replace|keep_both]
    [--license L] [--source-url U] [--confirm-license] [--json]
```

**Import.** `--dry-run` previews and writes nothing; otherwise you see the preview and confirm (`--yes` skips the question; `-` reads stdin and needs `--yes` or `--dry-run`). Columns are matched to prompt fields by name (title/name, body/prompt/text, tags, category, license, source_url, ...); `-m body=Prompt` overrides. Rows with no clear license are refused unless you pass `--confirm-license` or a `--license` for the whole file. A Markdown folder or ZIP is one prompt per file with optional YAML front-matter. XLSX needs the optional extra: `pip install 'promptvault[xlsx]'` (not included in the Docker image yet). Exit code 1 means nothing was imported because of errors.

**Import from a URL.** `github` takes a repo (`github.com/o/r`, `/tree/<branch>/<folder>`, `/blob/<branch>/<file>`) or a gist and reads `.md .json .yaml .yml .csv` files (README, LICENSE and similar are skipped); the repo license is applied to rows without their own, and a missing or `NOASSERTION` license trips the license gate. `huggingface` reads a public dataset through the datasets-server JSON API (`--config`, `--split`, `--limit`; use `-m title=act -m body=prompt` when the dataset has no title column; gated/private datasets and parquet-only access are not supported). `url` takes a Markdown/JSON/CSV/YAML file or an HTML page (best effort: text from `<pre>`, `<code>`, `<blockquote>`; `--mode blocks` makes one prompt per block; no JavaScript, no crawling) and flags pages for review. Fetching only allows http(s) on ports 80/443 to public addresses (private, loopback, link-local and metadata addresses are blocked, also after redirects); see `PV_IMPORT_ALLOW_PRIVATE_HOSTS` to open an intranet host.

## API

Interactive docs at `/docs` (OpenAPI). Errors are RFC 7807 `application/problem+json`.

| | |
|---|---|
| `GET/POST /api/v1/prompts` | list + search / create. Search: `q` (words, prefixes, `"phrases"`; typos are corrected and reported in `corrected_query`). Sort: `sort=relevance\|newest\|updated\|recent\|popular\|rating\|title`. Filters (combinable): `category`, `tags`, `tags_mode`, `difficulty`, `prompt_type`, `favorite`, `source`, `model`, `has_variables`, `created_after/before`, `updated_after`, `trash`. Cursor pagination |
| `GET/PUT/PATCH/DELETE /api/v1/prompts/{id}` | read / replace / partial update / move to Trash (`?permanent=true` for trashed) |
| `POST /api/v1/prompts/{id}/restore`, `/duplicate`, `/render`, `/use` | restore from Trash, copy, fill variables, record a use (drives `popular` / `recent` sorts) |
| `GET /api/v1/prompts/{id}/revisions`, `POST .../revisions/{n}/restore` | history |
| `POST /api/v1/prompts/bulk` | add/remove tags, set category, favorite, delete, restore |
| `POST /api/v1/prompts/{id}/reset` | restore a seeded prompt to the shipped content (new revision). `seed_modified` on a prompt tells the UI when to offer it |
| `GET/POST/PATCH/DELETE /api/v1/categories[/{slug}]` | hierarchical categories |
| `POST /api/v1/categories/{slug}/reset-seed` | reset every seeded prompt in a category (also restores trashed or deleted ones) |
| `GET /api/v1/tags`, `PUT/DELETE /api/v1/tags/{name}` | list, rename (merges), delete |
| `GET /api/v1/import/importers` | registered importers and whether they can run (XLSX needs the extra) |
| `POST /api/v1/import/preview`, `/import/commit` | dry run / import. Body: `{importer, source, default_license?, default_source_url?}` (commit also `default_action`, `actions`, `confirm_license`, `confirmed_rows`). File content goes in `source` as `content` (text) or `content_base64`; tabular sources take `mapping`, `sheet`, `delimiter`; the `github`, `url` and `huggingface` importers take `{url, ...options}` (`config`, `split`, `limit`, `mode`, `mapping`) and fetch it server-side. Blocked URLs answer 422, remote failures 502. Up to 25 rows run inline (200), more as a job (202) |
| `GET /api/v1/jobs/{id}`, `/jobs/{id}/events` | import job status; server-sent events (`progress`, then `done` or `failed`) |
| `DELETE /api/v1/trash` | purge Trash (`?older_than_days=N`); items older than `PV_TRASH_RETENTION_DAYS` (30) are purged at start |

## Configuration

Environment variables (prefix `PV_`) or a `.env` file. See [.env.example](.env.example).

| Variable | Default | Notes |
|---|---|---|
| `PV_HOST` | loopback only | The Docker image sets all interfaces; there is no auth in v1, so do not expose it publicly |
| `PV_PORT` | `8080` | |
| `PV_DATA_DIR` | `~/.promptvault` | Holds the SQLite database |
| `PV_DATABASE_URL` | SQLite in the data dir | Any SQLAlchemy URL (Postgres support is planned, not yet tested) |
| `PV_TRASH_RETENTION_DAYS` | `30` | Trashed prompts older than this are purged at start |
| `PV_SEED_ON_START` | `true` | Load/upgrade the seed library at start and on `promptvault init` (idempotent) |
| `PV_SEED_DIR` | bundled `seed/` | Alternative seed folder |
| `PV_IMPORT_MAX_ROWS` | `2000` | Rows per import request |
| `PV_IMPORT_MAX_PAYLOAD_BYTES` | `5242880` | Import request body cap (base64 adds a third) |
| `PV_GITHUB_TOKEN` | none | Optional GitHub token (env only, never accepted in a request); sent only to api.github.com and raw.githubusercontent.com to raise the rate limit |
| `PV_IMPORT_ALLOW_PRIVATE_HOSTS` | empty | Comma separated host names, IPs or CIDRs that URL importers may reach even if private (exact match, any port) |
| `PV_IMPORT_FETCH_TIMEOUT` | `30` | Seconds per fetched URL |
| `PV_IMPORT_FETCH_MAX_BYTES` | `5242880` | Max bytes per fetched response (after decompression) |
| `PV_IMPORT_GITHUB_MAX_FILES` | `200` | Files fetched per GitHub repo or gist import |
| `PV_LOG_LEVEL` | `info` | |
| `PV_CORS_ORIGINS` | none | JSON list, for a separately hosted UI |

## Seed library

Seed prompts are YAML files at `seed/<category>/<seed_id>.yaml` in the format of [SPEC Appendix A](docs/SPEC.md), and `seed/categories.yaml` declares the category tree (8 groups, 35 categories). Content is CC0.

- **Loading** is keyed by `seed_id` and idempotent. A prompt you have not edited is upgraded when a new version ships its newer text; one you have edited (content, tags, category) is never overwritten, and a prompt you moved to Trash is not brought back. Favorites, ratings and use counts do not count as edits. Categories that already exist are never renamed or moved.
- **Reset to original**: `promptvault seed --reset <id>`, `--reset-category <slug>`, or the API above. The reset becomes a new revision, so your version stays in history.
- **Linter**: `cd backend && uv run python ../tools/lint_seed.py` checks required fields, variable declarations against `{{placeholders}}`, duplicate ids and titles, length limits, licence/source, the quality bar (role, task, constraints, output format, an example or quality check), a disclaimer for legal/finance/medical-adjacent prompts, and PII/secret patterns. CI runs it.
- **Per-category minimum**: `min_per_category` in `seed/categories.yaml` makes the linter fail when any category has fewer prompts than that. It is `5`, so CI fails if any category drops below five prompts. Override it for one run with `--min-per-category N`.
- A seed prompt you permanently delete is recreated by the next load; move it to Trash instead.

## Roadmap

| Milestone | Scope | Status |
|---|---|---|
| M0 | Repo, CI, schema, API/UI skeletons, Docker | Done |
| M1a | Prompt/category/tag CRUD API + CLI | Done |
| M1b | FTS5 search, filters, sorting | Done |
| M1c | Library UI: browse, filter, detail, variable fill, copy | Done |
| M2a | Seed schema, linter, idempotent loader, reset to original, CI check | Done |
| M2b | Seed prompts: Career and Growth (10 categories, 6-7 each) | Done |
| M2c | Seed prompts: Business and Professional (9 categories, 6 each, disclaimers on legal, finance and real estate) | Done |
| M2d | Seed prompts: Creative and Technical (9 categories, 6 each, safety rules in the prompt bodies) | Done |
| M2e | Seed prompts: Education and Prompt Engineering (7 categories, 213 prompts in total), per-category minimum of 5 enforced | Done |
| M2f | UI declutter: design tokens, grouped sidebar, Filters control and chips, calmer rows and detail pane, responsive layout (frontend only) | Done |
| M3a | Importer framework: plugin interface, validation, dedupe (exact + difflib fuzzy), preview, commit, jobs + SSE, provenance and license gate (backend only) | Done |
| M3b | Importers: JSON, CSV/XLSX, Markdown folder/ZIP, clipboard, plus the `promptvault import` CLI | Done |
| M3c | Importers: GitHub repo/gist, web URL, Hugging Face datasets, with an SSRF guard | Done |
| M3d | Export: JSON, CSV, XLSX, Markdown ZIP | Next |
| M4 | Published Docker image (GHCR), PyPI package, start scripts, release automation | Planned |
| M5 | Polish and v1.0: accessibility, performance, end-to-end tests | Planned |
| v1.5 | Run panel (test prompts against an LLM), semantic search, executables | Backlog |

## Project layout

```
backend/    FastAPI app, models, services, CLI, Alembic migrations, tests   (src/promptvault)
frontend/   Vite + React + TypeScript UI
docker/     Dockerfile and compose file
docs/       Product and technical spec
seed/       Seed prompts (YAML) and categories.yaml
tools/      Build-time tooling (lint_seed.py)
.github/    CI workflow, Dependabot, PR template
```

The frontend builds into `backend/src/promptvault/static`, so a single process serves both the API and the UI.

## Tests

```bash
cd backend && uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy
PV_PERF=1 uv run pytest tests/test_search_perf.py -s   # optional: search latency at 10k prompts
cd frontend && npm test && npm run lint && npm run typecheck
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Issues and PRs welcome.

## License

MIT. See [LICENSE](LICENSE).
