"""Hatch build hook: bundle the seed library and make sure the UI is part of every artifact.

The seed library lives in ``seed/`` at the repository root, outside ``backend/``. A build from
``backend/`` alone would silently ship an empty library, so this hook

* adds ``../seed`` as ``promptvault/seed`` (wheel) or ``src/promptvault/seed`` (sdist) when the
  checkout has it and the package folder does not already hold a copy,
* does nothing when ``src/promptvault/seed`` exists (an unpacked sdist, or a Docker build that
  copied the seed there),
* fails the build when the library or ``static/index.html`` is missing, instead of shipping a
  package without them. Editable installs (``uv sync``) are exempt from the UI check so that
  development works before the frontend is built. Set ``PV_ALLOW_NO_UI=1`` to build an
  API-only wheel on purpose.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class BundleHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        root = Path(self.root)
        pkg = root / "src" / "promptvault"
        repo_seed = root.parent / "seed"
        editable = version == "editable"

        if not (pkg / "seed" / "categories.yaml").is_file():
            if (repo_seed / "categories.yaml").is_file():
                dest = "promptvault/seed" if self.target_name == "wheel" else "src/promptvault/seed"
                build_data["force_include"][str(repo_seed)] = dest
            elif not editable:
                raise RuntimeError(
                    "seed library not found: expected ../seed (repository checkout) or "
                    "src/promptvault/seed"
                )

        needs_ui = not editable and os.environ.get("PV_ALLOW_NO_UI") != "1"
        if needs_ui and not (pkg / "static" / "index.html").is_file():
            raise RuntimeError(
                "the built UI is missing (src/promptvault/static/index.html): run "
                "'npm ci && npm run build' in frontend/, or set PV_ALLOW_NO_UI=1 for an "
                "API-only build"
            )
