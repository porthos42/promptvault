# Install

Every method below ends with a verification step. Prompt Vault serves the UI and the API from one process on port 8080 by default.

| Method | Command | Needs | Status |
|---|---|---|---|
| **Docker** | `docker run -d --name promptvault -p 8080:8080 -v pv-data:/data ghcr.io/porthos42/promptvault:edge` | Docker | Available ([details](#docker)) |
| **Compose** | `docker compose -f docker/docker-compose.yml up -d` | Docker | Available ([details](#docker-compose)) |
| **Start script** (from a checkout) | `./scripts/start.sh` or `.\scripts\start.ps1` | uv or Python 3.11+; Node 20+ to build the UI | Available ([details](#from-source-start-scripts)) |
| **From source** | `cd backend && uv sync && uv run promptvault serve` | uv, Node 20+ | Available |
| **pipx** | `pipx install 'prompt-vault[xlsx]'` then `promptvault serve` | pipx, Python 3.11+ | After the first PyPI release |
| **uvx** (no install) | `uvx --from 'prompt-vault[xlsx]' promptvault serve` | uv | After the first PyPI release |
| **pip** | `pip install 'prompt-vault[xlsx]'` then `promptvault serve` | Python 3.11+ | After the first PyPI release |

!!! warning "No authentication in v1"
    Prompt Vault binds to the loopback interface by default and has no login. Do not publish the port to the internet without a reverse proxy that adds authentication and TLS. The published Docker image sets all interfaces (it is meant to run in its own network namespace behind `-p`); everything else defaults to loopback.

## pipx (recommended for Python users)

```bash
pipx install 'prompt-vault[xlsx]'
promptvault serve
```

Verify: `promptvault version` prints the version, and `curl http://localhost:8080/api/v1/health` answers `ok` once the server is up. XLSX import/export needs the `[xlsx]` extra; `all` also adds the experimental PostgreSQL driver. Data lives in `~/.promptvault` (`PV_DATA_DIR`). Upgrade with `pipx upgrade prompt-vault`; migrations run at every start.

## uvx (no install)

```bash
uvx --from 'prompt-vault[xlsx]' promptvault serve
```

Verify: the same health check as above. uvx keeps the tool cached; `--refresh` picks up a newer release.

## pip

```bash
pip install 'prompt-vault[xlsx]'
promptvault serve
```

Verify: `promptvault doctor` checks the installation and the data directory.

## Docker

The image is `ghcr.io/porthos42/promptvault` (linux/amd64 and linux/arm64, non-root, about 190 MB uncompressed, XLSX included). Tags: `edge` (latest commit on main) today; `X.Y.Z`, `X.Y` and `latest` once the first release is tagged.

```bash
docker run -d --name promptvault -p 8080:8080 -v pv-data:/data ghcr.io/porthos42/promptvault:edge
```

Verify: `curl http://localhost:8080/api/v1/health`, and `docker inspect --format '{{.State.Health.Status}}' promptvault` says `healthy`.

Notes:

- The container runs as uid 10001; a bind mount must be writable by that user (`chown 10001 <dir>`).
- Data lives in `/data` (the SQLite database). Migrations and the seed library run at every start, so updating is `docker compose pull && docker compose up -d` (or `docker stop`, `docker rm`, re-`run`); your data volume is upgraded in place.
- The CLI works inside the container, e.g. a backup: `docker exec promptvault promptvault export json - > backup.json`.
- The container has no shell tools beyond what the app needs; use `docker exec` with the `promptvault` command.

### Docker Compose

```bash
docker compose -f docker/docker-compose.yml up -d            # pulls the published image
docker compose -f docker/compose.postgres.yml --env-file .env up -d --build   # experimental PostgreSQL variant
```

`PV_TAG` (image tag, default `latest`), `PV_BIND` (host address, default loopback) and `PV_HOST_PORT` (default `8080`) go in a `.env` file next to the compose file. The SQLite compose runs the container with a read-only root filesystem, no capabilities and `no-new-privileges`. Verify: `docker compose -f docker/docker-compose.yml ps` shows `healthy`.

!!! note "Pinning a specific version"
    Since release 0.2.0 the compose default is `latest` (the newest published release). Set `PV_TAG=edge` to track the latest main, or `PV_TAG=1.0.0` (any version) to pin a specific release.

## From source (start scripts)

From a checkout of the repository:

```bash
./scripts/start.sh [--port N] [--host H] [--no-ui-build] [--rebuild-ui]
```

```powershell
.\scripts\start.ps1 [-Port N] [-BindHost H] [-NoUiBuild] [-RebuildUi]
# if the execution policy blocks it: powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

They use `uv` when present (otherwise Python 3.11+ with `venv` and `pip`), install the app editable into `backend/.venv` with the `xlsx` extra, build the UI with Node and npm when `static/` is missing or older than `frontend/src` (`--no-ui-build` skips; without Node the API runs alone), and run `promptvault serve`. `--port`/`--host` override `PV_PORT`/`PV_HOST`; a non-loopback host prints a no-authentication warning. Nothing is written outside the repository and the data directory, and nothing uses `sudo`.

Verify: the script prints the URL it serves on; `curl http://localhost:8080/api/v1/health`.

## Development (hot reload)

```bash
# terminal 1: API on :8080
cd backend && uv run promptvault serve --reload
# terminal 2: UI on :5173 (proxies /api to :8080)
cd frontend && npm run dev
```

## How releases happen

- **[release-please](https://github.com/googleapis/release-please) automates the changelog, the version bump and the tag — nothing else.** Conventional Commits on `main` (`feat:`, `fix:`, ...) make the bot open a *release PR* that updates `CHANGELOG.md`, `backend/pyproject.toml` and `backend/src/promptvault/__init__.py` (a CI test fails if the two version files drift apart). **When the owner merges that PR, the bot pushes the `vX.Y.Z` tag.**
- The `v*` tag triggers the Docker publish workflow, which re-runs the whole CI workflow as a gate, checks that the tag equals the package version, builds a multi-arch image and pushes tags `X.Y.Z`, `X.Y` and `latest` to GHCR, then smoke-tests the pushed digest.
- **The PyPI upload is manual, by design.** CI builds the wheel and sdist on every push (and every tag) and verifies their contents and installability, but never uploads. The owner's steps: build the UI (`cd frontend && npm ci && npm run build`), build in `backend/` with `uv build`, check with `uv run --no-project --with twine twine check dist/*`, re-check that the name `prompt-vault` is still free on <https://pypi.org>, then `uv publish` (or `twine upload`) with the owner's own token. TestPyPI first is optional.
- release-please never pushes a `v*` tag directly; only the release-PR merge does.
