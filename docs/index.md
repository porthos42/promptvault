# Prompt Vault

A self-hosted, searchable prompt engineering library: hundreds of ready-to-use prompts across careers, marketing, coding, STEM, 3D printing, image/video generation and more, with full CRUD, full-text search (SQLite FTS5), filtering, import (files, pasted text, GitHub, web pages, Hugging Face) and export (JSON, CSV, XLSX, Markdown). Single-user and local-first. Free and open source ([MIT](https://github.com/porthos42/promptvault/blob/main/LICENSE)).

One process serves both the REST API and a React web UI. Data lives in a SQLite database you own.

| Start here | |
|---|---|
| [User guide](user-guide.md) | screenshots + worked examples |
| [Install](install.md) | pipx, uvx, pip, Docker/compose, start scripts |
| [CLI](cli.md) | `promptvault serve`, CRUD, import, export |
| [REST API](api.md) | `/api/v1` endpoints, search and filters |
| [Import & export](import-export.md) | formats, dedupe, license gate, round trip |
| [Configuration](configuration.md) | every `PV_*` environment variable |
| [Run as a service](serve.md) | systemd unit, Windows Task Scheduler / NSSM |
| [Spec](SPEC.md) | full product and technical specification |

- **Repository:** <https://github.com/porthos42/promptvault>
- **Docker image:** `ghcr.io/porthos42/promptvault` (`edge` tracks main; `X.Y.Z`, `X.Y` and `latest` exist once a release is tagged)
- **PyPI package:** `prompt-vault` (the name `promptvault` belongs to an unrelated project; the command and import package are still `promptvault`)
- **Status:** early development; releases happen through [release-please](https://github.com/googleapis/release-please) — see [How releases happen](install.md#how-releases-happen).
