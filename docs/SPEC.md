---
title: "PromptVault — Prompt Engineering Library: Product & Technical Spec"
subtitle: "Draft v0.1"
---

# 1. Overview

**PromptVault** is a self-hostable prompt library. It ships with a curated seed set of prompts across ~30 professional and technical categories. Users can create, edit, delete, search, filter, import and export prompts.

**Stack:** Python (FastAPI) backend, React (Vite + TypeScript) frontend, SQLite by default (Postgres optional), GitHub for source, CI and releases.

**Goals**

- Local-first. Works offline with one command and no account.
- Fast full-text search over thousands of prompts.
- Prompts are first-class structured objects (variables, versions, tags), not loose text blobs.
- Several install paths: Docker, pip/pipx, terminal script, desktop-style launcher.

**Non-goals (v1):** multi-tenant SaaS, billing, built-in LLM chat UI (a "Run" panel is a v1.5 stretch), real-time collaboration.

# 2. Users & Use Cases

| Persona | Need |
|---|---|
| Professional (HR, lawyer, marketer) | Find a good starting prompt fast, fill variables, copy |
| Maker / engineer | Store and iterate domain prompts (3D printing, electronics, coding) |
| Student | Browse by subject and difficulty |
| Power user | Bulk import, version history, API/CLI access |

# 3. Functional Requirements

## 3.1 Prompt CRUD

- **Create / edit / delete / duplicate** a prompt through UI, REST API and CLI.
- **Soft delete** with a Trash view (30-day purge, configurable). Hard delete is available from Trash.
- **Version history:** every save creates a revision (diff view, restore). The prompt table keeps the current version, and `prompt_revision` holds the history.
- **Bulk actions:** multi-select to tag, move category, favorite, export, delete.

## 3.2 Prompt Data Model

| Field | Type | Notes |
|---|---|---|
| id | UUID | stable across export/import |
| title | text | required |
| body | text (Markdown) | supports `{{variable}}` placeholders |
| description | text | what it does, when to use it |
| category_id | FK | one primary category |
| tags | many-to-many | free-form, lowercase |
| variables | JSON | `[{name, label, default, type, options}]`, auto-detected from body |
| model_hints | JSON | recommended models/params (e.g. "Claude, GPT-4o, temp 0.3") |
| output_format | text | optional, e.g. "table", "JSON", "email" |
| difficulty | enum | beginner / intermediate / advanced |
| prompt_type | enum | system / user / template / chain (multi-step) |
| source | text | "seed", "user", "import:<name>", with source URL and license |
| license | text | SPDX id or "user-owned" |
| is_favorite | bool | |
| rating, use_count | int | local usage stats |
| created_at, updated_at, deleted_at | timestamps | |

**Categories** are hierarchical (category → subcategory) with an icon and sort order.

## 3.3 Variable Fill & Copy

- The prompt detail view renders a form from `variables`.
- Live preview shows the rendered prompt. One-click Copy, plus "Copy as system / user / JSON messages".
- Fill values can be saved as presets per prompt.

## 3.4 Search & Filter

- **Full-text search** across title, body, description and tags.
  - SQLite FTS5 with BM25 ranking and prefix matching. Postgres `tsvector` + GIN is the equivalent.
  - Typo tolerance via trigram fallback.
- **Filters** (combinable, URL-persisted): category/subcategory, tags (AND/OR), difficulty, prompt type, source, model hint, favorites, date range, has-variables.
- **Sort:** relevance, newest, recently used, most used, rating, A–Z.
- **Saved searches** and collections ("My Resume Kit").
- **Command palette** (Ctrl/Cmd+K) for instant search and jump.
- **Stretch (v1.5):** optional semantic search using local embeddings (sentence-transformers or Ollama) stored in sqlite-vec, merged with BM25 results (hybrid).

## 3.5 Import

An importer plugin interface (`Importer.parse(source) -> list[PromptDraft]`) feeds a common pipeline: **parse → normalize → dedupe → preview → commit**.

| Source | Format |
|---|---|
| JSON / CSV / XLSX | Column-mapping UI |
| Markdown files / folder / ZIP | One prompt per file; YAML front-matter is mapped to fields |
| GitHub repo / gist URL | Fetches `.md/.json/.yaml/.csv` via the GitHub API |
| Public datasets | e.g. Hugging Face prompt datasets (CSV/Parquet) via URL |
| Web page URL | Extract a prompt from a page (best-effort) |
| Clipboard paste | Single or multiple, split by delimiter |
| Other tools | LangChain Hub / PromptLayer / Langfuse-style JSON exports (adapters added over time) |
| PromptVault export | Lossless round-trip |

Pipeline rules:

- **Dedupe:** exact match on a hash of the normalized body, plus fuzzy match (MinHash or rapidfuzz ≥ 0.92). The user chooses skip / replace / keep both.
- **Dry run preview** with per-row validation errors before commit.
- **Provenance:** source URL and license are stored per prompt. Imports from repos without a clear license are flagged for the user to confirm.
- Imports run as background jobs with progress (SSE).

## 3.6 Export

JSON (lossless), CSV, XLSX, a Markdown folder or ZIP, and a single-prompt "share" snippet.

## 3.7 Obsidian (out of scope for the app)

Obsidian is used only to store **project documents** (this spec, plans, notes) while building PromptVault. The app has **no Obsidian integration**: no vault sync, no plugin, no vault path setting. Prompts and code are never stored in the vault; prompts live in the app database and in the GitHub repo (`seed/`).


## 3.8 Seed Library

Ship **5–10 prompts per category** (v1.0 target: 5–10 per category, ≈ 250 total; more can be added in later releases), stored as versioned YAML in the repo at `seed/<category>/<slug>.yaml`.

**Categories (v1):**

| Group | Categories |
|---|---|
| Career | Resume Writing · Job Interviews · Job Searching · Networking & LinkedIn |
| Growth | Marketing · Sales · SEO · Social Media · Branding · E-commerce |
| Business | Business Strategy · HR · Finance · Project Management · Customer Support |
| Professional | Legal · Real Estate · Writing & Editing · Research |
| Creative | Image Generation · Video Generation · Design · Music & Audio |
| Technical | Coding · DevOps · Data & Analytics · Embedded/Electronics · 3D Printing |
| Education | Students · STEM · Physics · Math · Science · Engineering |
| Meta | Prompt Engineering (meta-prompts, evaluators, chain-of-thought templates) |

Users can add their own categories. Categories are data, not code.

**Seed quality bar:**

1. Each prompt has a role, task, context variables, constraints, output format, and at least one example or quality check.
2. Written by us or generated and then human-reviewed. Only content we own, or that is licensed permissively with attribution, is included. Third-party prompts carry their source and license.
3. A CI linter checks: required fields, variable declarations match the body, no duplicate slugs, length limits, no PII or secrets.
4. **Legal/finance/medical-adjacent prompts** carry a disclaimer field ("Not professional advice") shown in the UI.
5. Seed loading is idempotent (keyed by `seed_id`). User edits to a seeded prompt are never overwritten by an upgrade. A "Reset to original" action is available per prompt.

**Seed generation workflow (build-time tooling, in `tools/seedgen/`):** a script drafts prompts per category from an outline file using an LLM, outputs YAML, then the linter and a human review PR gate it. Generated content is committed to the repo, not generated at runtime.

## 3.9 Other Features

- Favorites, collections, ratings, "recently used".
- Light/dark theme, keyboard shortcuts, responsive layout.
- Single-user and local only in v1: no auth, no accounts. The server binds to loopback only.
- Optional "Run" panel (v1.5): bring-your-own-key to call OpenAI/Anthropic/OpenRouter or a local Ollama endpoint with the rendered prompt. Keys are stored only in env/config, never in the DB.

# 4. Architecture

```
┌──────────────┐   REST/JSON + SSE   ┌─────────────────────────────┐
│ React SPA    │ ──────────────────► │ FastAPI app                 │
│ (Vite, TS)   │ ◄────────────────── │  routers: prompts, search,  │
└──────────────┘                     │  categories, import, export,│
                                     │  settings, jobs             │
 CLI (Typer) ──► same service layer  │  services / repositories    │
                                     │  importers (plugins)        │
                                     └──────────┬──────────────────┘
                                                │ SQLAlchemy 2 + Alembic
                                       ┌────────▼────────┐
                                       │ SQLite (FTS5)   │
                                       │ or Postgres     │
                                       └─────────────────┘
```

In production, FastAPI serves the built React assets as static files, so there is **one process and one port** (default 8080).

## 4.1 Backend

| Concern | Choice |
|---|---|
| Framework | FastAPI + Uvicorn |
| Validation | Pydantic v2 |
| ORM / migrations | SQLAlchemy 2.0, Alembic |
| DB | SQLite (WAL mode, FTS5) default; Postgres supported through `DATABASE_URL` |
| Background jobs | In-process `asyncio` task queue with a jobs table (no Redis needed) |
| CLI | Typer (`promptvault ...`) |
| Packaging | `pyproject.toml`, managed with `uv`; published to PyPI |
| Quality | ruff, mypy, pytest, pytest-asyncio, httpx test client |

Layering: `routers → services → repositories → models`. Importers are pure services, testable without HTTP.

## 4.2 Frontend

| Concern | Choice |
|---|---|
| Build | Vite + React 18 + TypeScript |
| Routing | TanStack Router (or React Router) |
| Server state | TanStack Query |
| UI | Tailwind CSS + shadcn/ui (Radix) |
| Editor | CodeMirror 6 (Markdown mode, `{{var}}` highlighting) |
| Lists | TanStack Virtual for large result sets |
| Forms | React Hook Form + Zod |
| API client | Generated from FastAPI's OpenAPI schema (openapi-typescript) |
| Tests | Vitest, React Testing Library, Playwright (e2e) |

**Performance targets:** initial JS ≤ 200 KB gzip (route-level code splitting), search results render < 100 ms after response, search API p95 < 50 ms at 10k prompts, debounced input (150 ms), optimistic updates on edit/favorite.

**Main screens:** Library (sidebar categories, filter bar, result list/grid) · Prompt detail (variable form, preview, copy) · Editor · Import wizard · Trash · Settings.

## 4.3 REST API (v1, `/api/v1`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/prompts` | list + search + filter (`q`, `category`, `tags`, `difficulty`, `sort`, `cursor`) |
| POST | `/prompts` | create |
| GET / PUT / PATCH / DELETE | `/prompts/{id}` | read / replace / partial update / soft delete |
| GET | `/prompts/{id}/revisions` | history; `POST .../restore/{rev}` |
| POST | `/prompts/{id}/render` | render with variable values |
| POST | `/prompts/bulk` | bulk tag/move/delete/export |
| GET / POST / PUT / DELETE | `/categories`, `/tags`, `/collections` | taxonomy |
| POST | `/import/preview`, `/import/commit` | import pipeline; `GET /jobs/{id}` (+ SSE stream) |
| GET | `/export?format=json|csv|xlsx|md` | export |
| GET | `/health`, `/version` | ops |

Auto-generated docs at `/docs`. Errors follow RFC 7807 problem+json. Cursor pagination.

## 4.4 CLI

```
promptvault serve [--host 0.0.0.0 --port 8080 --data-dir ~/.promptvault]
promptvault init                      # create DB, run migrations, load seed
promptvault seed --reset-category "SEO"
promptvault add / edit / rm / show <id>
promptvault search "cold email" --category sales --tag b2b
promptvault import <path|url> --type markdown|json|csv|github
promptvault export --format md --out ./out
promptvault doctor                    # diagnose paths and DB
```

# 5. Repository (GitHub)

```
promptvault/
├─ backend/
│  ├─ src/promptvault/{api,services,repos,models,importers,cli}/
│  ├─ alembic/  tests/  pyproject.toml
├─ frontend/
│  ├─ src/  public/  package.json  vite.config.ts
├─ seed/<category>/<slug>.yaml
├─ tools/{seedgen,lint_seed.py}
├─ docker/{Dockerfile,docker-compose.yml,compose.postgres.yml}
├─ scripts/{start.sh,start.ps1,install.sh,install.ps1}
├─ docs/  (architecture, import formats, seed guide, API)
├─ .github/{workflows,ISSUE_TEMPLATE,PULL_REQUEST_TEMPLATE.md}
├─ Makefile  README.md  LICENSE  CONTRIBUTING.md  CODE_OF_CONDUCT.md  SECURITY.md
```

- **Branching:** trunk-based, with `main` protected and PRs requiring green CI.
- **Versioning:** SemVer, Conventional Commits, release-please for changelogs and tags.
- **License:** MIT or Apache-2.0 for code. The seed prompts are CC BY 4.0 or CC0 (decide before launch).
- **Community seed contributions:** a PR template and the seed linter make adding prompts a YAML-file PR.

**GitHub Actions**

| Workflow | Trigger | Does |
|---|---|---|
| `ci.yml` | PR / push | ruff, mypy, pytest (SQLite + Postgres matrix); eslint, tsc, vitest; seed lint; Playwright smoke |
| `docker.yml` | tag `v*` | Multi-arch (amd64/arm64) build, push to **GHCR** (and optionally Docker Hub) |
| `release.yml` | tag `v*` | Build wheel/sdist → PyPI (trusted publishing); attach artifacts; GitHub Release notes |
| `bundle.yml` | tag `v*` | PyInstaller single-file executables for Windows/macOS/Linux attached to the release |
| `codeql.yml` + Dependabot | scheduled | Security scanning, dependency updates |

# 6. Distribution & Deployment

| Method | Command / Artifact | Audience |
|---|---|---|
| **Docker (single container)** | `docker run -p 8080:8080 -v pv-data:/data ghcr.io/<org>/promptvault` | Most users |
| **Docker Compose** | `docker compose up -d` (SQLite) or `-f compose.postgres.yml` | Homelab / teams |
| **pipx / pip** | `pipx install promptvault && promptvault serve` | Python users |
| **uvx (zero install)** | `uvx promptvault serve` | Quick try |
| **From source (terminal)** | `git clone … && make dev` (installs, runs backend + Vite with hot reload) | Contributors |
| **Start scripts** | `./scripts/start.sh` or `.\scripts\start.ps1` (creates venv, installs, builds, serves) | Non-Docker users |
| **Standalone executable** | Download from GitHub Releases (PyInstaller) | Non-technical users |
| **systemd / Windows service** | Sample unit file and NSSM instructions in docs | Always-on server |
| **Cloud one-click** | Fly.io, Railway, Render config files (`fly.toml`, `railway.json`, `render.yaml`) | Remote access |
| **Kubernetes (stretch)** | Helm chart or plain manifests | Teams |
| **Desktop wrapper (stretch)** | Tauri shell around the local server | Polished desktop |

**Docker details**

- Multi-stage build: Node stage builds the frontend, Python stage installs the wheel plus static assets. Final image is `python:3.12-slim`, non-root user, `HEALTHCHECK` on `/health`, target size under 200 MB.
- Volumes: `/data` (DB, config) (a named volume, or a bind mount on Windows).
- Env config (12-factor): `PV_DATABASE_URL`, `PV_DATA_DIR`, `PV_PORT`, `PV_SEED_ON_START=true`, `PV_LOG_LEVEL`, `PV_CORS_ORIGINS`.
- Container startup runs migrations, then seeds (idempotent), then starts Uvicorn.

**Config precedence:** CLI flags > env vars > `config.toml` in the data dir > defaults.

# 7. Non-Functional Requirements

- **Performance:** see 4.2. Cold start under 3 s on SQLite. Handles 50k prompts.
- **Security:** bind to `127.0.0.1` by default (explicit opt-in for `0.0.0.0`). Sanitize Markdown rendering (no raw HTML/script). Path-traversal guards on all import and export paths. GitHub tokens and API keys come from env only. SSRF protections on URL importers (block private IP ranges unless configured).
- **Reliability:** DB backup command (`promptvault backup`) and automatic daily snapshot (keep 7). Migrations are forward-only and tested.
- **Privacy:** no telemetry by default. Fully offline except for user-initiated imports and the optional Run panel.
- **Accessibility:** WCAG 2.1 AA, full keyboard navigation.
- **Compatibility:** Python 3.11+, Node 20+ for builds, modern evergreen browsers. Windows, macOS and Linux are all first-class (note path and line-ending handling).
- **Observability:** structured JSON logs and an optional Prometheus `/metrics` endpoint.
- **i18n:** English first. All strings go through i18n keys. Seed content is English only in v1.

# 8. Testing & Quality

- **Unit:** services, importers (golden-file fixtures per format), variable parser, dedupe logic.
- **Integration:** API against SQLite and Postgres.
- **E2E:** Playwright covering create → search → fill variables → copy → export.
- **Seed CI:** the linter plus a check that each category has ≥ 5 prompts.
- **Coverage gate:** 85% backend, 70% frontend.

# 9. Milestones

| Phase | Scope | Est. (solo, 5–15 hrs/wk) |
|---|---|---|
| **M0 – Foundations** | Repo, CI, schema + migrations, FastAPI skeleton, Vite skeleton, Docker dev setup | 1–2 wks |
| **M1 – Core CRUD + Search** | Prompt/category/tag CRUD, FTS5 search, filters, library UI, variable fill + copy | 3–4 wks |
| **M2 – Seed library** | Seed schema, linter, seedgen tooling, 5–10 prompts in each category (≈ 250 total) | 2–3 wks (parallel with M1) |
| **M3 – Import/Export** | Importer framework, JSON/CSV/MD/GitHub, dedupe, preview, export | 2–3 wks |
| **M4 – Distribution** | Dockerfile + GHCR, PyPI, start scripts, release automation, docs | 1–2 wks |
| **M5 – Polish & v1.0** | Versioning/trash UX, a11y pass, perf pass, README, demo GIF | 1–2 wks |
| **v1.5** | Semantic search, Run panel (test prompts against an LLM), executables, one-click cloud, Tauri | later |

Rough total to v1.0: **9–14 weeks** at the stated pace. Using AI coding agents should compress this.

# 10. Acceptance Criteria (v1.0)

1. `docker run` of the published image gives a working app with seed data in under 60 seconds.
2. Every category has ≥ 5 prompts, and the library holds about 250 prompts, all passing the linter.
3. A user can add, edit, delete (with restore) and duplicate a prompt from the UI, API and CLI.
4. Search returns ranked results across 10k prompts in < 50 ms p95. Any combination of filters works and persists in the URL.
5. Importing from JSON, CSV, a Markdown folder, and a public GitHub repo URL works, with dedupe preview.
6. Installation works via Docker, pipx, and from-source terminal script on Windows, macOS and Linux.
7. CI is green and the release workflow publishes the image and the wheel from a tag.

# 11. Risks & Decisions

| Risk / Question | Mitigation / Proposal |
|---|---|
| Licensing of third-party prompt collections | Seed with original content. Imports record source and license. Never bundle unlicensed prompts. |
| Seed quality at ~250 prompts | LLM draft + linter + human review; ship in waves, with core categories first |
| Legal/medical/finance misuse | Disclaimer field, shown in UI |
| Windows path and line-ending edge cases | Windows CI runner, normalize to LF on write, `pathlib` everywhere |
| Scope creep (Run panel, semantic search) | Held to v1.5 |

**Decisions made**

| # | Decision |
|---|---|
| 1 | Name: **Prompt Vault** (repo `promptvault`) |
| 2 | Free and open source for now. Proposed: MIT for code, CC0 for seed prompts (confirm before first release) |
| 3 | Obsidian holds project documents only. No prompts or code, and no app integration |
| 4 | v1 is single-user and local only |
| 5 | Seed target is 5–10 prompts per category |
| 6 | The "Run" panel moves to v1.5 |

# Appendix A — Seed Prompt File Format

```yaml
seed_id: resume-bullet-rewriter
title: Resume Bullet Rewriter
category: resume-writing
tags: [resume, ats, career]
difficulty: beginner
type: template
description: Turns a vague duty into a quantified, achievement-style bullet.
variables:
  - { name: job_title, label: Target job title, type: text }
  - { name: bullet, label: Original bullet, type: textarea }
  - { name: metrics, label: Known numbers (optional), type: textarea, default: "" }
output_format: "3 alternative bullets, each under 25 words"
model_hints: "Any chat model; temperature 0.4"
disclaimer: null
license: CC0-1.0
body: |
  You are an expert resume writer who specializes in ATS-friendly resumes.

  Rewrite the bullet below for a {{job_title}} application.

  Original bullet: {{bullet}}
  Known metrics: {{metrics}}

  Rules:
  - Start with a strong past-tense verb.
  - Quantify impact; if no numbers are given, suggest placeholders like [X%].
  - Keep each under 25 words.
  - Do not invent facts.

  Return 3 alternatives, then one sentence on which is strongest and why.
```

# Appendix B — Example Seed Outline (per category, for seedgen)

```
Resume Writing (target 30): summary writer, bullet rewriter, ATS keyword matcher,
  tailor resume to JD, cover letter, career-change narrative, gap explainer,
  skills section builder, LinkedIn headline, resume critique, ...
Job Interviews (target 30): STAR story builder, mock interviewer, behavioral Q bank,
  technical screen simulator, salary negotiation script, "tell me about yourself", ...
3D Printing (target 25): slicer settings advisor, print failure diagnosis,
  OpenSCAD generator, filament selection, tolerance/fit planner, ...
```
