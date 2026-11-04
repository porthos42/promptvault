# Changelog

## [0.2.0](https://github.com/porthos42/promptvault/compare/v0.1.0...v0.2.0) (2026-11-04)


### Features

* **api:** prompt/category/tag CRUD, trash, revisions, bulk, render + CLI (M1a) ([bbf59bd](https://github.com/porthos42/promptvault/commit/bbf59bd3a7762ade4c8c978101518f3af1319737))
* **dist:** PyPI package, pipx/uvx and start scripts (M4b) ([4dafd3b](https://github.com/porthos42/promptvault/commit/4dafd3bff42ecc33a9dbf921e61c3d2263f779bb))
* **docker:** production image, compose files and GHCR publish (M4a) ([3c54b74](https://github.com/porthos42/promptvault/commit/3c54b7416bc690a29d0a5622354b897e0c7186ac))
* **export:** JSON, CSV, XLSX and Markdown ZIP export with share snippet (M3d) ([8a559fc](https://github.com/porthos42/promptvault/commit/8a559fc8b105e4b63b31d906674068ad08b2f43a))
* **import:** GitHub, web URL and Hugging Face importers with SSRF guard (M3c) ([7954cad](https://github.com/porthos42/promptvault/commit/7954cad2b7434d96ca1717d17bf053e6d2f0b384))
* **import:** importer framework, dedupe and preview (M3a) ([491fad8](https://github.com/porthos42/promptvault/commit/491fad81232d490da34644b1d90d4fb015b9177d))
* **import:** JSON, CSV/XLSX, Markdown and clipboard importers and import CLI (M3b) ([74c0f8f](https://github.com/porthos42/promptvault/commit/74c0f8f837fd1d6b9be22130b2c727bd44202718))
* M0 foundations - FastAPI + React skeleton, schema/FTS5 migration, CLI, Docker, CI ([9a28fea](https://github.com/porthos42/promptvault/commit/9a28fea6212acd7b4d8256a15c62c24c814e8172))
* **search:** FTS5 search with BM25, typo correction, filters, sorts, /use (M1b) ([ba6fa94](https://github.com/porthos42/promptvault/commit/ba6fa94837c0795dc0139e4bc4da3612dfb0c817))
* **seed:** business and professional prompts (M2c) ([d3cdd41](https://github.com/porthos42/promptvault/commit/d3cdd4121d001529de571640f755e5f3ae800578))
* **seed:** career and growth prompts (M2b) ([9d76787](https://github.com/porthos42/promptvault/commit/9d767876b83b707410b3b8719ca020d2c7e084fa))
* **seed:** creative and technical prompts (M2d) ([6af43b1](https://github.com/porthos42/promptvault/commit/6af43b1c8a38b582c290c1d99bdaa4c6a5ee90bf))
* **seed:** education and meta prompts (M2e) ([8568b05](https://github.com/porthos42/promptvault/commit/8568b05d05fefe487fc0832a1d257694c2a1b64b))
* **seed:** seed schema, linter, idempotent loader, reset to original, CI check (M2a) ([432361c](https://github.com/porthos42/promptvault/commit/432361cb6748f3dc26eeecdd9c852c493b7b06fc))
* **seed:** technical screen simulator and employment gap explainer ([78e32da](https://github.com/porthos42/promptvault/commit/78e32da5784e06775fe80401c43a06af03ce5b9c))
* **ui:** declutter library layout and visual hierarchy (M2f) ([645fe1b](https://github.com/porthos42/promptvault/commit/645fe1bef0a53c0f4a1c3a1677c573880c8e9f28))
* **ui:** export dialog, per-prompt export and share snippet (M3e) ([1c4ff7f](https://github.com/porthos42/promptvault/commit/1c4ff7f2b7ea4d5f6b6cd36a26538649b9bca11e))
* **ui:** import wizard for files and pasted text (M3f) ([13ae637](https://github.com/porthos42/promptvault/commit/13ae637cc2042b11c30bd50691a757294c555b56))
* **ui:** library UI with filters, virtualized list, variable fill, editor, trash, Ctrl+K (M1c) ([ad585f1](https://github.com/porthos42/promptvault/commit/ad585f18ba113a09177c40d0a2b940b5a6cc42e6))
* **ui:** URL import sources and live job progress (M3g) ([51e9147](https://github.com/porthos42/promptvault/commit/51e9147baa73cbafaec97f6ebc3d630a69fc12a3))


### Bug Fixes

* **ci:** list all prompts in the Docker seed smoke test ([fffdf9e](https://github.com/porthos42/promptvault/commit/fffdf9eaa74465d3ac8f10f7bc6e34f35e28d5ea))
* **ci:** use a native wheel path in the Windows package smoke (M4b) ([f48da56](https://github.com/porthos42/promptvault/commit/f48da567add7196a057fe97a982be2fb75096bf1))
* **release:** annotate __version__ for the release-please generic updater (17.x has no start/end matcher) ([78cbb38](https://github.com/porthos42/promptvault/commit/78cbb3837f527d221237859267740ca7e14bb204))
* **release:** manifest config must be JSON (release-please parses it with JSON.parse) ([f661624](https://github.com/porthos42/promptvault/commit/f661624bf10d266018057710a8944489d9c3aace))
* **release:** point the workflow and docs at the JSON manifest config ([51de6db](https://github.com/porthos42/promptvault/commit/51de6db33a08a1ac74f0858fb887d610553cac6e))
* **seed:** clarify date rule in employment gap explainer ([66b7e5e](https://github.com/porthos42/promptvault/commit/66b7e5e28fd43bd84fea4f4ffd4447d79a83d0f4))


### Performance Improvements

* **import:** precompute token sets for fuzzy dedupe prefilter (M3a) ([f450086](https://github.com/porthos42/promptvault/commit/f4500865d32ca5741efe850b7779ae7b84aeb215))
