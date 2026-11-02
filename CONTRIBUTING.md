# Contributing

1. Fork, branch from `main`, open a PR. CI must be green.
2. Use [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:` ...).
3. Backend: `cd backend && uv sync && uv run pytest && uv run ruff check . && uv run mypy`.
4. Frontend: `cd frontend && npm ci && npm test && npm run lint && npm run typecheck`.
5. Seed prompts: see below.

## Adding a seed prompt

1. Copy `seed/resume-writing/resume-bullet-rewriter.yaml` to `seed/<category>/<seed_id>.yaml`. The file name is the `seed_id` (lowercase, hyphens), and the folder is the category slug from `seed/categories.yaml`.
2. Fill in every field (format: [SPEC Appendix A](docs/SPEC.md)). Declare each `{{placeholder}}` in `variables` with a label. The body needs a role, a task, constraints (a `Rules:` list), the output format, and an example or quality check.
3. Legal, finance, tax, health and similar prompts need a `disclaimer` ("Not professional advice ...").
4. Content must be your own or permissively licensed. Your own work is `license: CC0-1.0`. Third-party content needs `license`, `source` and `source_url`.
5. No real names, emails, phone numbers, keys or other secrets. Use `{{placeholders}}` and example.com addresses.
6. Check it: `cd backend && uv run python ../tools/lint_seed.py`, then `uv run pytest`.

Once a prompt ships, keep its `seed_id` stable: users' copies are matched by it. Change the text freely; unedited copies are upgraded, edited ones are kept.
See [docs/SPEC.md](docs/SPEC.md) for the product and technical spec.
