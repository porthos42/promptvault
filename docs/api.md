# REST API

Interactive docs are served at `/docs` (OpenAPI / Swagger UI) by any running server. Errors are RFC 7807 `application/problem+json`. Everything is under `/api/v1`.

| | |
|---|---|
| `GET/POST /api/v1/prompts` | list + search / create. Search: `q` (words, prefixes, `"phrases"`; typos are corrected and reported in `corrected_query`). Sort: `sort=relevance\|newest\|updated\|recent\|popular\|rating\|title`. Filters (combinable): `category`, `tags`, `tags_mode`, `difficulty`, `prompt_type`, `favorite`, `source`, `model`, `has_variables`, `created_after/before`, `updated_after`, `trash`. Cursor pagination. Prompt bodies accept a `variations` field: `[{name, values: {variable: value}}]` — named presets that prefill variables in the UI |
| `GET/PUT/PATCH/DELETE /api/v1/prompts/{id}` | read / replace / partial update / move to Trash (`?permanent=true` for trashed). `variations` (the named presets) round-trip on every write |
| `GET/POST/PATCH/DELETE /api/v1/categories[/{slug}]` | hierarchical categories. `POST` creates (`name`, optional `slug`, `parent`, `icon`, `sort_order`), `PATCH` renames / re-parents, `DELETE` removes one (prompts and subcategories are kept; they become uncategorised / top-level). See also the **Categories** tab on the Data page in the UI |
| `POST /api/v1/prompts/{id}/restore`, `/duplicate`, `/render`, `/use` | restore from Trash, copy, fill variables, record a use (drives `popular` / `recent` sorts) |
| `GET /api/v1/prompts/{id}/revisions`, `POST .../revisions/{n}/restore` | history |
| `POST /api/v1/prompts/bulk` | add/remove tags, set category, favorite, delete, restore |
| `POST /api/v1/prompts/{id}/reset` | restore a seeded prompt to the shipped content (new revision). `seed_modified` on a prompt tells the UI when to offer it |
| `POST /api/v1/categories/{slug}/reset-seed` | reset every seeded prompt in a category
| `GET /api/v1/tags`, `PUT/DELETE /api/v1/tags/{name}` | list, rename (merges), delete |
| `GET /api/v1/import/importers` | registered importers and whether they can run (XLSX needs the extra) |
| `POST /api/v1/import/preview`, `/import/commit` | dry run / import. Body: `{importer, source, default_license?, default_source_url?}` (commit also `default_action`, `actions`, `confirm_license`, `confirmed_rows`). File content goes in `source` as `content` (text) or `content_base64`; tabular sources take `mapping`, `sheet`, `delimiter`; the `github`, `url` and `huggingface` importers take `{url, ...options}` and fetch it server-side. Blocked URLs answer 422, remote failures 502. Up to 25 rows run inline (200), more as a job (202) |
| `GET /api/v1/jobs/{id}`, `/jobs/{id}/events` | import job status; server-sent events (`progress`, then `done` or `failed`) |
| `GET /api/v1/export?format=json\|csv\|xlsx\|markdown` | download the library (streamed; `markdown` is a ZIP). Same filters as `GET /prompts` plus `ids`, `include_trashed`, `pretty` (JSON), `bom`, `raw` (CSV/XLSX formula guard off). Headers: `Content-Disposition`, `X-Export-Count`, `X-Export-Missing`, `X-Export-Warnings`. 413 above `PV_EXPORT_MAX_ROWS`, 404 for XLSX without the extra |
| `POST /api/v1/export`, `GET /api/v1/export/formats` | same with a JSON body `{format, ids?, filters?, include_trashed, ...}` (up to 500 ids); formats and whether they can run |
| `GET /api/v1/prompts/{id}/export?format=...`, `/prompts/{id}/share?format=markdown\|text\|json&values=name=value` | one prompt (markdown is a plain `.md`); copy-paste snippet `{format, text, missing}`. 404 for unknown or trashed ids |
| `DELETE /api/v1/trash` | purge Trash (`?older_than_days=N`); items older than `PV_TRASH_RETENTION_DAYS` (30) are purged at start |
