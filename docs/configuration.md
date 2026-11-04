# Configuration

Environment variables (prefix `PV_`) or a `.env` file. See [.env.example](https://github.com/porthos42/promptvault/blob/main/.env.example) in the repository.

| Variable | Default | Notes |
|---|---|---|
| `PV_HOST` | loopback only | The Docker image sets all interfaces; there is no auth in v1, so do not expose it publicly |
| `PV_PORT` | `8080` | |
| `PV_DATA_DIR` | `~/.promptvault` | Holds the SQLite database |
| `PV_DATABASE_URL` | SQLite in the data dir | Any SQLAlchemy URL. PostgreSQL is experimental (`postgresql+psycopg://...`, needs the `postgres` extra, see the compose file) |
| `PV_TRASH_RETENTION_DAYS` | `30` | Trashed prompts older than this are purged at start |
| `PV_SEED_ON_START` | `true` | Load/upgrade the seed library at start and on `promptvault init` (idempotent) |
| `PV_SEED_DIR` | bundled `seed/` | Alternative seed folder |
| `PV_IMPORT_MAX_ROWS` | `2000` | Rows per import request |
| `PV_IMPORT_MAX_PAYLOAD_BYTES` | `5242880` | Import request body cap (base64 adds a third) |
| `PV_EXPORT_MAX_ROWS` | `50000` | Prompts per API export; a larger selection answers 413 (the CLI has no cap) |
| `PV_BACKUP_DIR` | `<data>/backups` | Where `promptvault backup` writes its timestamped SQLite snapshots |
| `PV_BACKUP_KEEP` | `7` | How many backup snapshots `promptvault backup` keeps in the directory |
| `PV_IMPORT_JOB_RETENTION_DAYS` | `30` | Finished import jobs older than this are pruned at server start (negative disables) |
| `PV_GITHUB_TOKEN` | none | Optional GitHub token (env only, never accepted in a request); sent only to api.github.com and raw.githubusercontent.com to raise the rate limit |
| `PV_IMPORT_ALLOW_PRIVATE_HOSTS` | empty | Comma separated host names, IPs or CIDRs that URL importers may reach even if private (exact match, any port) |
| `PV_IMPORT_FETCH_TIMEOUT` | `30` | Seconds per fetched URL |
| `PV_IMPORT_FETCH_MAX_BYTES` | `5242880` | Max bytes per fetched response (after decompression) |
| `PV_IMPORT_GITHUB_MAX_FILES` | `200` | Files fetched per GitHub repo or gist import |
| `PV_LOG_LEVEL` | `info` | |
| `PV_CORS_ORIGINS` | none | JSON list, for a separately hosted UI |

Docker/Compose has three extra variables that the compose file consumes, not the app: `PV_TAG` (image tag), `PV_BIND` (host address for the published port) and `PV_HOST_PORT` (host port).

Precedence: CLI flags > environment variables > `config.toml` in the data directory > defaults.
