# Prompt Vault

A self-hosted, searchable prompt engineering library: hundreds of ready-to-use prompts across careers, marketing, coding, STEM, 3D printing, image/video generation and more, with full create/edit/delete, search, filtering and import. Single-user and local-first. Free and open source (MIT).

> **Status: M0 (foundations).** The API skeleton, database schema (with SQLite FTS5 search index), CLI, React shell, Docker image and CI are in place. Prompt CRUD, search UI, seed prompts and importers are next. See the [spec](docs/SPEC.md).

**Stack:** Python 3.11+ (FastAPI, SQLAlchemy 2, Alembic, Typer), React 19 + TypeScript (Vite), SQLite by default.

## Quick start

### From source (terminal)

Requires [uv](https://docs.astral.sh/uv/) and Node 20+.

```bash
git clone https://github.com/porthos42/promptvault.git
cd promptvault
cd frontend && npm install && npm run build && cd ..   # builds the UI into the Python package
cd backend && uv sync
uv run promptvault serve                                # http://localhost:8080
```

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

Data lives in `/data` (a named volume). Published images and PyPI packages arrive in M4.

## CLI

```
promptvault serve [--host H] [--port P] [--reload]
promptvault init      # create data dir + database, run migrations
promptvault doctor    # check paths, DB, SQLite FTS5 support
promptvault version
```

Configuration is by environment variables (prefix `PV_`) or a `.env` file; see [.env.example](.env.example). The server binds to loopback by default.

## Tests

```bash
cd backend && uv run pytest && uv run ruff check . && uv run mypy
cd frontend && npm test && npm run lint && npm run typecheck
```

## License

MIT. See [LICENSE](LICENSE).
