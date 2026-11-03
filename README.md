# Prompt Vault

[![CI](https://github.com/porthos42/promptvault/actions/workflows/ci.yml/badge.svg)](https://github.com/porthos42/promptvault/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A self-hosted, searchable prompt engineering library. The goal is hundreds of ready-to-use prompts across careers, marketing, coding, STEM, 3D printing, image/video generation and more, with full create/edit/delete, search, filtering and import. Single-user and local-first. Free and open source.

> **Status: early development (M3e done).** The backend API, CLI, full-text search, the library UI (decluttered in M2f: grouped collapsible sidebar, one Filters control with removable chips, calmer list rows, tidier detail pane, mobile drawer) and the seed-library machinery (schema, linter, loader, reset) work. The seed library is complete for v1 (213 prompts across all 35 categories, 6-7 each), and importing works from the API and the CLI: JSON, CSV, XLSX (optional extra), Markdown (files, folders, ZIP) pasted text, GitHub repos/gists, web pages and Hugging Face datasets (all fetched through an SSRF-safe fetcher), with validation, exact and fuzzy dedupe, a dry-run preview, skip, replace or keep-both, a license gate and background jobs with SSE progress. Export works from the API and the CLI: JSON, CSV, XLSX (optional extra), a Markdown ZIP or folder, and a copy-paste share snippet for one prompt. A production Docker image (multi-arch, non-root, GHCR) and compose files ship in M4a, and M4b adds the PyPI package `prompt-vault` (built and verified, not yet uploaded to PyPI), `pipx`/`uvx` support and start scripts. The export UI ships in M3e (a Data page with format cards, filters-scope downloads and a Share popover); the import UI is not built yet. See [Roadmap](#roadmap) and the [full spec](docs/SPEC.md).

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
- Export UI (M3e): a Data page with an Export tab — format cards (unavailable formats disabled with the server's reason), a live scope count from the active URL filters, include-trash, advanced options, fetch + Blob downloads with the server's file name, count and warnings — plus per-prompt export (Markdown/JSON) and a Share popover in the detail pane, and "Export library" / "Share prompt" palette commands
- Seed library machinery: YAML prompt files, a CI linter, an idempotent loader that never overwrites your edits, and "Reset to original" per prompt or per category
- Production Docker image on GHCR (linux/amd64 + arm64, non-root, XLSX included), compose files for SQLite and an experimental PostgreSQL variant, CI on Linux and Windows

Planned: see [Roadmap](#roadmap).

## Install

| Method | Command | Needs | Status |
|---|---|---|---|
| **Docker** | `docker run -d --name promptvault -p 127.0.0.1:8080:8080 -v pv-data:/data ghcr.io/porthos42/promptvault:edge` | Docker | Available ([details](#docker)) |
| **Start script** (from a checkout) | `./scripts/start.sh` (Linux, macOS, Git Bash) or `.\scripts\start.ps1` (Windows PowerShell) | uv or Python 3.11+; Node 20+ to build the UI | Available ([details](#start-scripts)) |
| **From source** | `cd frontend && npm ci && npm run build`, then `cd backend && uv sync && uv run promptvault serve` | uv, Node 20+ | Available |
| **pipx** | `pipx install 'prompt-vault[xlsx]'` then `promptvault serve` | pipx, Python 3.11+ | After the first PyPI release |
| **uvx** (no install) | `uvx --from 'prompt-vault[xlsx]' promptvault serve` | uv | After the first PyPI release |
| **pip** | `pip install 'prompt-vault[xlsx]'` then `promptvault serve` | Python 3.11+ | After the first PyPI release |
| **Local wheel** | `make dist` (or `cd frontend && npm ci && npm run build && cd ../backend && uv build`), then `pipx install 'backend/dist/prompt_vault-0.1.0-py3-none-any.whl[xlsx]'` | uv, Node 20+ | Available |

The PyPI distribution is named **`prompt-vault`** because `promptvault` belongs to an unrelated project; the command and the Python package are still `promptvault`. The package has not been uploaded yet, so the pipx, uvx and pip rows start working with the first release (M4c); the wheel and sdist are built and tested in CI (`package` job) and the pipx, uvx and pip commands were verified against the locally built wheel.

The wheel includes the web UI and the 213 seed prompts. XLSX import/export needs the `xlsx` extra (`prompt-vault[xlsx]`; the Docker image already has it); the other extras are `postgres` (experimental) and `all` (both). Open <http://localhost:8080> after `promptvault serve` (API docs at `/docs`); data lives in `~/.promptvault` (`PV_DATA_DIR`). Upgrade with `pipx upgrade prompt-vault` (migrations run at start).

### Start scripts

```bash
./scripts/start.sh [--port N] [--host H] [--no-ui-build] [--rebuild-ui]
```

```powershell
.\scripts\start.ps1 [-Port N] [-BindHost H] [-NoUiBuild] [-RebuildUi]
# if the execution policy blocks it: powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

They run from a checkout: use `uv` when present (otherwise Python 3.11+ with `venv` and `pip`), install the app editable into `backend/.venv` with the `xlsx` extra, build the UI with Node and npm when `static/` is missing or older than `frontend/src` (skip with `--no-ui-build`; without Node the API runs on its own and the script says so), and run `promptvault serve`. `--port` beats `PV_PORT`, `--host` beats `PV_HOST`; a non-loopback host prints a warning because v1 has no authentication. They write only inside the repository and the data directory and never use `sudo`. `make start` runs the shell script.

### Development (hot reload)

```bash
# terminal 1: API on :8080
cd backend && uv run promptvault serve --reload
# terminal 2: UI on :5173 (proxies /api to :8080)
cd frontend && npm run dev
```

`make dev` runs both if you have `make`.

### Docker

The image is `ghcr.io/porthos42/promptvault` (linux/amd64 and linux/arm64). Tags: `edge` (latest commit on main) now; `X.Y.Z`, `X.Y` and `latest` once the first release is tagged.

```bash
docker run -d --name promptvault -p 127.0.0.1:8080:8080 -v pv-data:/data ghcr.io/porthos42/promptvault:edge
# open http://localhost:8080
```

Or with Compose (SQLite, named volume `pv-data`, read-only root filesystem, no capabilities):

```bash
docker compose -f docker/docker-compose.yml up -d            # pulls the published image
docker compose -f docker/docker-compose.yml up -d --build    # builds it from this checkout instead
# from a downloaded copy of the file: docker compose up -d
```

`PV_TAG` (image tag, default `edge`), `PV_BIND` (host address, default loopback) and `PV_HOST_PORT` (default `8080`) can be set in a `.env` file next to the compose file or exported. **Prompt Vault v1 has no authentication, so the port is published on the loopback interface only.** Do not bind it to all interfaces or forward it to the internet without a reverse proxy that adds authentication and TLS.

- Data lives in `/data` (database and nothing else). The container runs as uid 10001; a bind mount must be writable by that user (`chown 10001 <dir>`). Migrations and the seed library run at every start, so updating is `docker compose pull && docker compose up -d`; your data volume is upgraded in place (tested from the M1b and M2f databases).
- The CLI works inside the container, e.g. a backup: `docker exec promptvault promptvault export json - > backup.json`, or `promptvault list`, `promptvault import ...`.
- XLSX import and export work in the image (openpyxl is installed). The image is about 190 MB uncompressed (`docker image ls`; much less to download) and has a health check on `/api/v1/health`.
- Build it yourself from the repo root: `docker build -f docker/Dockerfile -t promptvault .` (build args: `EXTRAS`, default `xlsx`; `PV_REVISION`, shown by `/api/v1/version`).
- **PostgreSQL (experimental).** `docker/compose.postgres.yml` runs the app against postgres 16: set `POSTGRES_PASSWORD` in `.env` (see [.env.example](.env.example)), then `docker compose -f docker/compose.postgres.yml --env-file .env up -d --build`. It builds a local image variant with the PostgreSQL driver (the published image has none, to stay under the size budget). Tested: the migration chain, list, filters, create, update, revisions, trash, export in all four formats and imports including background jobs. Not available on PostgreSQL: full-text ranking and typo correction (search is an unranked substring match). Not tested: upgrading real data, backups, large libraries. SQLite stays the supported default.

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

promptvault export <json|csv|xlsx|markdown> [PATH | -] [-c slug] [-t tag ...] [--favorite] [-q QUERY] [--id ID ...]
    [--include-trashed] [--zip] [--force] [--no-bom] [--raw] [--pretty] [--json]
promptvault share <id-or-prefix> [--format markdown|text|json] [--values name=value ...]
```

**Import.** `--dry-run` previews and writes nothing; otherwise you see the preview and confirm (`--yes` skips the question; `-` reads stdin and needs `--yes` or `--dry-run`). Columns are matched to prompt fields by name (title/name, body/prompt/text, tags, category, license, source_url, ...); `-m body=Prompt` overrides. Rows with no clear license are refused unless you pass `--confirm-license` or a `--license` for the whole file. A Markdown folder or ZIP is one prompt per file with optional YAML front-matter. XLSX needs the optional extra: `pip install 'prompt-vault[xlsx]'` (already included in the Docker image). Exit code 1 means nothing was imported because of errors.

**Export.** `promptvault export json backup.json` writes every live prompt (add `--include-trashed` for Trash); the same filters as `list` and `search` narrow it, `--id` picks single prompts. `csv` and `xlsx` open in Excel (CSV has a UTF-8 BOM; cells that start with `=`, `+`, `-` or `@` get a leading apostrophe so Excel cannot run them, `--raw` turns that off); `markdown` writes a folder, or one ZIP with `--zip`, of `<category>/<title>.md` files with YAML front-matter. `-` sends json or csv to stdout. Existing files and non-empty folders are only overwritten with `--force`; an empty selection exits 1. XLSX needs the optional extra (`pip install 'prompt-vault[xlsx]'`, already in the Docker image). Every format re-imports through the matching importer and restores content and provenance (title, body, description, category, tags, difficulty, type, model hints, output format, disclaimer, license, source URL). Ids, favorites, ratings, use counts, timestamps and variable labels/defaults are in the file but are not restored, and importers never create categories. Restoring into an empty install: use `--on-duplicate keep_both` if you have near-duplicate prompts and `--confirm-license` if some have no license. `promptvault share <id>` prints one prompt as a snippet to paste anywhere; `--values name=value` fills the variables.

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
| `GET /api/v1/export?format=json\|csv\|xlsx\|markdown` | download the library (streamed; `markdown` is a ZIP). Filters as for `GET /prompts` (`q`, `category`, `tags`, `favorite`, ...) plus `ids`, `include_trashed`, `pretty` (JSON), `bom`, `raw` (CSV/XLSX formula guard off). Headers: `Content-Disposition`, `X-Export-Count`, `X-Export-Missing`, `X-Export-Warnings`. 413 above `PV_EXPORT_MAX_ROWS`, 404 for XLSX without the extra |
| `POST /api/v1/export`, `GET /api/v1/export/formats` | same with a JSON body `{format, ids?, filters?, include_trashed, ...}` (up to 500 ids); formats and whether they can run |
| `GET /api/v1/prompts/{id}/export?format=...`, `/prompts/{id}/share?format=markdown\|text\|json&values=name=value` | one prompt (markdown is a plain `.md`); copy-paste snippet `{format, text, missing}`. 404 for unknown or trashed ids |
| `DELETE /api/v1/trash` | purge Trash (`?older_than_days=N`); items older than `PV_TRASH_RETENTION_DAYS` (30) are purged at start |

## Configuration

Environment variables (prefix `PV_`) or a `.env` file. See [.env.example](.env.example).

| Variable | Default | Notes |
|---|---|---|
| `PV_HOST` | loopback only | The Docker image sets all interfaces; there is no auth in v1, so do not expose it publicly |
| `PV_PORT` | `8080` | |
| `PV_DATA_DIR` | `~/.promptvault` | Holds the SQLite database |
| `PV_DATABASE_URL` | SQLite in the data dir | Any SQLAlchemy URL. PostgreSQL is experimental (`postgresql+psycopg://...`, needs the `postgres` extra, see Docker above) |
| `PV_TRASH_RETENTION_DAYS` | `30` | Trashed prompts older than this are purged at start |
| `PV_SEED_ON_START` | `true` | Load/upgrade the seed library at start and on `promptvault init` (idempotent) |
| `PV_SEED_DIR` | bundled `seed/` | Alternative seed folder |
| `PV_IMPORT_MAX_ROWS` | `2000` | Rows per import request |
| `PV_IMPORT_MAX_PAYLOAD_BYTES` | `5242880` | Import request body cap (base64 adds a third) |
| `PV_EXPORT_MAX_ROWS` | `50000` | Prompts per API export; a larger selection answers 413 (the CLI has no cap) |
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
| M3d | Export: JSON, CSV, XLSX, Markdown ZIP/folder, share snippet, `promptvault export` and `share` CLI | Done |
| M3e | Export UI: Data page with Export tab, format cards, filters-scope downloads, per-prompt export, Share popover (frontend only) | Done |
| M3f | Import UI: Data page Import tab with mapping wizard | Next |
| M4a | Production Docker image, compose files (SQLite, experimental PostgreSQL), GHCR publish for `edge` and version tags | Done |
| M4b | PyPI package `prompt-vault` (wheel + sdist built and verified, not uploaded), pipx/uvx, start scripts, `package` CI job | Done |
| M4c | Release automation, changelog, docs site (card t_ce5dd0c4) | Planned |
| M5 | Polish and v1.0: accessibility, performance, end-to-end tests | Planned |
| v1.5 | Run panel (test prompts against an LLM), semantic search, executables | Backlog |

## Project layout

```
backend/    FastAPI app, models, services, CLI, Alembic migrations, tests   (src/promptvault)
frontend/   Vite + React + TypeScript UI
docker/     Dockerfile and compose files (SQLite, PostgreSQL)
scripts/    start.sh and start.ps1 (run from a checkout)
docs/       Product and technical spec
seed/       Seed prompts (YAML) and categories.yaml
tools/      Tooling: lint_seed.py, docker_smoke.sh (image smoke test), pg_smoke.py, check_dist.py and dist_smoke.py (package checks)
.github/    CI and Docker publish workflows, Dependabot, PR template
```

The frontend builds into `backend/src/promptvault/static`, so a single process serves both the API and the UI.

## Tests

```bash
cd backend && uv run pytest && uv run ruff check . && uv run ruff format --check . && uv run mypy
# package: build the UI first, then
make dist        # = uv build + tools/check_dist.py + twine check; artifacts in backend/dist (not committed)
PV_PERF=1 uv run pytest tests/test_search_perf.py -s   # optional: search latency at 10k prompts
cd frontend && npm test && npm run lint && npm run typecheck
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Issues and PRs welcome.

## License

MIT. See [LICENSE](LICENSE).
