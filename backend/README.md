# Prompt Vault

A self-hosted, searchable prompt engineering library: 233 ready-to-use prompts across 39
categories (finance nests investing, stock-market, tax and retirement subcategories), full create/edit/delete, full-text search, variable fill-in, import (JSON, CSV, XLSX,
Markdown, GitHub, web pages, Hugging Face) and export. Single-user and local-first; the data is a
SQLite file in `~/.promptvault`.

```bash
pipx install prompt-vault          # or: uvx --from prompt-vault promptvault serve
promptvault serve                  # http://localhost:8080
```

Excel import/export needs an extra: `pipx install 'prompt-vault[xlsx]'`.

The PyPI package is called `prompt-vault`; the command and the Python package are `promptvault`.
Version 1 has no authentication: it listens on the loopback interface by default, so do not expose
it to a network without a reverse proxy that adds authentication and TLS.

Docker image, configuration, CLI and API reference: <https://github.com/porthos42/promptvault#readme>

MIT licensed. Source and issues: <https://github.com/porthos42/promptvault>
