# Contributing

1. Fork, branch from `main`, open a PR. CI must be green.
2. Use [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:` ...).
3. Backend: `cd backend && uv sync && uv run pytest && uv run ruff check . && uv run mypy`.
4. Frontend: `cd frontend && npm ci && npm test && npm run lint && npm run typecheck`.
5. Seed prompts (coming in M2) are YAML files under `seed/<category>/`; they must be original or permissively licensed.

See [docs/SPEC.md](docs/SPEC.md) for the product and technical spec.
