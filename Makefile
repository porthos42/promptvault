.PHONY: install dev backend frontend test lint build docker

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
