.PHONY: install dev backend frontend test lint build docker dist check-dist start

install:
	cd backend && uv sync
	cd frontend && npm install

# Run API (:8080) and Vite dev server (:5173) together
dev:
	$(MAKE) -j2 backend frontend

backend:
	cd backend && uv run promptvault serve --reload

frontend:
	cd frontend && npm run dev

test:
	cd backend && uv run pytest
	cd frontend && npm test

lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy
	cd frontend && npm run lint && npm run typecheck

build:
	cd frontend && npm run build

docker:
	docker build -f docker/Dockerfile -t promptvault .

# Build the UI, then the sdist and wheel into backend/dist (never uploaded by this repo's tooling)
dist: build
	cd backend && rm -rf dist && uv build
	$(MAKE) check-dist

# Inspect backend/dist: UI, seed library, migrations, license in; tests out
check-dist:
	cd backend && uv run --no-sync python ../tools/check_dist.py dist
	cd backend && uv run --no-project --with twine twine check dist/*

# From-source start script (creates backend/.venv, builds the UI if Node is there, serves)
start:
	bash scripts/start.sh
