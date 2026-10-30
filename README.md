# Prompt Vault

[![CI](https://github.com/porthos42/promptvault/actions/workflows/ci.yml/badge.svg)](https://github.com/porthos42/promptvault/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A self-hosted, searchable prompt engineering library. The goal is hundreds of ready-to-use prompts across careers, marketing, coding, STEM, 3D printing, image/video generation and more, with full create/edit/delete, search, filtering and import. Single-user and local-first. Free and open source.

> **Status: early development (M1b done).** The backend API and CLI work, including full-text search. The library UI, seed prompts and importers are not built yet. See [Roadmap](#roadmap) and the [full spec](docs/SPEC.md).

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

The web UI is currently a status page only. Use the CLI or `/docs` to work with prompts until the library UI lands (M1c).

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
```

## API

Interactive docs at `/docs` (OpenAPI). Errors are RFC 7807 `application/problem+json`.

| | |
|---|---|
| `GET/POST /api/v1/prompts` | list + search / create. Search: `q` (words, prefixes, `"phrases"`; typos are corrected and reported in `corrected_query`). Sort: `sort=relevance\|newest\|updated\|recent\|popular\|rating\|title`. Filters (combinable): `category`, `tags`, `tags_mode`, `difficulty`, `prompt_type`, `favorite`, `source`, `model`, `has_variables`, `created_after/before`, `updated_after`, `trash`. Cursor pagination |
| `GET/PUT/PATCH/DELETE /api/v1/prompts/{id}` | read / replace / partial update / move to Trash (`?permanent=true` for trashed) |
| `POST /api/v1/prompts/{id}/restore`, `/duplicate`, `/render`, `/use` | restore from Trash, copy, fill variables, record a use (drives `popular` / `recent` sorts) |
| `GET /api/v1/prompts/{id}/revisions`, `POST .../revisions/{n}/restore` | history |
| `POST /api/v1/prompts/bulk` | add/remove tags, set category, favorite, delete, restore |
| `GET/POST/PATCH/DELETE /api/v1/categories[/{slug}]` | hierarchical categories |
| `GET /api/v1/tags`, `PUT/DELETE /api/v1/tags/{name}` | list, rename (merges), delete |
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
| `PV_LOG_LEVEL` | `info` | |
| `PV_CORS_ORIGINS` | none | JSON list, for a separately hosted UI |

## Roadmap

| Milestone | Scope | Status |
|---|---|---|
| M0 | Repo, CI, schema, API/UI skeletons, Docker | Done |
| M1a | Prompt/category/tag CRUD API + CLI | Done |
| M1b | FTS5 search, filters, sorting | Done |
| M1c | Library UI: browse, filter, detail, variable fill, copy | Next |
| M2 | Seed schema and linter, then 5-10 prompts in each category (about 250) | Planned |
| M3 | Importers (JSON, CSV/XLSX, Markdown, GitHub, URL), dedupe, export | Planned |
| M4 | Published Docker image (GHCR), PyPI package, start scripts, release automation | Planned |
| M5 | Polish and v1.0: accessibility, performance, end-to-end tests | Planned |
| v1.5 | Run panel (test prompts against an LLM), semantic search, executables | Backlog |

## Project layout

```
backend/    FastAPI app, models, services, CLI, Alembic migrations, tests   (src/promptvault)
frontend/   Vite + React + TypeScript UI
docker/     Dockerfile and compose file
docs/       Product and technical spec
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
