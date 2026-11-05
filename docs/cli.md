# CLI

`promptvault` is the command for every install method (the PyPI distribution is named `prompt-vault`; see [Install](install.md)).

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
promptvault clear [-c slug] [--purge] [--yes]   # trash every prompt (or one category); --purge deletes for good
promptvault category list | add NAME [--parent slug] | rm SLUG
promptvault tag list | rename OLD NEW | rm NAME

promptvault import <json|csv|xlsx|markdown|clipboard> <file | folder | -> [--dry-run] [--yes]
promptvault import <github|url|huggingface> <https://...> [--config C] [--split S] [--limit N] [--mode page|blocks]
    [-m field=column ...] [--sheet N] [--delimiter X] [--on-duplicate skip|replace|keep_both]
    [--license L] [--source-url U] [--confirm-license] [--json]

promptvault export <json|csv|xlsx|markdown> [PATH | -] [-c slug] [-t tag ...] [--favorite] [-q QUERY] [--id ID ...]
    [--include-trashed] [--zip] [--force] [--no-bom] [--raw] [--pretty] [--json]
promptvault share <id-or-prefix> [--format markdown|text|json] [--values name=value ...]

promptvault backup [--dir D] [--keep N]     # timestamped SQLite snapshot into PV_BACKUP_DIR, keeps last 7
```

See [Import & export](import-export.md) for the options in detail. Configuration is via `PV_*` environment variables — see [Configuration](configuration.md).

- `serve` runs the API and the UI on one port (default 8080, loopback). `--reload` is for development.
- `init` creates the data directory and runs migrations plus the seed library; `doctor` checks the installation; `version` prints the version.
- Deleting is soft: `rm` moves to Trash, `restore` brings back, `purge` deletes permanently (items older than 30 days are purged at start).
- Every command that lists accepts the same filters (`-c`, `-t`, `--favorite`) and has a `--json` mode for scripts.
