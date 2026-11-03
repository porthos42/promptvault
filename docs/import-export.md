# Import & export

Import and export work from the REST API, the CLI, and a four-step wizard in the web UI's Data page.

## Import

Formats: JSON, CSV, XLSX (optional `xlsx` extra), Markdown (a folder or ZIP of files, one prompt per file with optional YAML front-matter), pasted text, plus network importers **GitHub** (repos, folders, gists; `.md .json .yaml .yml .csv` files), **Hugging Face** datasets (public, through the datasets-server JSON API) and **web URL** (Markdown/JSON/CSV/YAML files or HTML pages, best effort).

- `--dry-run` previews and writes nothing; otherwise you confirm (the UI shows the preview; `--yes` skips the CLI question; `-` reads stdin and needs `--yes` or `--dry-run`).
- Columns are matched to prompt fields by name (title/name, body/prompt/text, tags, category, license, source_url, ...); `-m body=Prompt` overrides.
- Duplicates are detected exactly and fuzzily (difflib similarity); on commit you choose `skip`, `replace` or `keep_both` per row or globally.
- Rows with no clear license are refused unless you pass `--confirm-license` or a `--license` for the whole file; a repository's license fills rows without their own, and a missing or `NOASSERTION` license trips the gate.
- Up to 25 rows import inline; more run as a background job with live progress over server-sent events (`GET /api/v1/jobs/{id}/events`), polling fallback, and resume-from-reload via the `?job=` URL parameter in the UI.
- Fetching is SSRF-guarded: http(s) on ports 80/443 to public addresses only (private, loopback, link-local and metadata addresses are blocked, also after redirects). `PV_IMPORT_ALLOW_PRIVATE_HOSTS` opens an intranet host. No JavaScript pages, crawling, parquet-only access, gated datasets, or GitLab/Bitbucket.
- Exit code 1 means nothing was imported because of errors.

## Export

Formats: JSON, CSV, XLSX (extra), Markdown — a folder, or one ZIP of `<category>/<title>.md` with YAML front-matter — and a per-prompt copy-paste share snippet.

- The same filters as `list` and `search` narrow an export; `--id` picks single prompts (up to 500 through `POST /api/v1/export`); `--include-trashed` adds Trash.
- `csv` and `xlsx` open in Excel (UTF-8 BOM; cells that start with `=`, `+`, `-` or `@` get a leading apostrophe so Excel cannot run them; `--raw` turns that off).
- Existing files and non-empty folders are only overwritten with `--force`; an empty selection exits 1. `-` sends JSON or CSV to stdout.
- Every format re-imports through the matching importer and restores content and provenance (title, body, description, category, tags, difficulty, type, model hints, output format, disclaimer, license, source URL). Ids, favorites, ratings, use counts, timestamps and variable labels/defaults are in the file but are **not** restored, and importers never create categories.
- Restoring into an empty install: use `--on-duplicate keep_both` if you have near-duplicate prompts and `--confirm-license` if some have no license.

## Round trip

Export → import into an empty database → export again produces identical content for all four formats (tested in CI). The round trip is intentionally *content and provenance* lossless, not state-lossless.
