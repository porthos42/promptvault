"""Packaging guards: version consistency, metadata, and seed lookup from an installed layout."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

import promptvault
from promptvault.config import Settings
from promptvault.services import seed as seed_svc

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent


def _pyproject() -> dict[str, object]:
    with (BACKEND / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)


def test_version_matches_pyproject() -> None:
    project = _pyproject()["project"]
    assert isinstance(project, dict)
    assert project["version"] == promptvault.__version__
    assert re.fullmatch(r"\d+\.\d+\.\d+([abrc.]+\d+)?", promptvault.__version__)


def test_distribution_metadata() -> None:
    project = _pyproject()["project"]
    assert isinstance(project, dict)
    # "promptvault" on PyPI belongs to someone else; the CLI and import package keep the name
    assert project["name"] == "prompt-vault"
    assert project["scripts"] == {"promptvault": "promptvault.cli:app"}
    assert project["license"] == "MIT"
    assert project["readme"] == "README.md"  # inside backend/: the Docker build runs from there
    extras = project["optional-dependencies"]
    assert isinstance(extras, dict)
    assert {"xlsx", "postgres", "all"} <= set(extras)
    assert sorted(extras["all"]) == sorted(extras["xlsx"] + extras["postgres"])
    assert (BACKEND / project["readme"]).is_file()  # type: ignore[arg-type]


def test_backend_license_copy_matches_repo_license() -> None:
    def norm(p: Path) -> str:
        return p.read_text(encoding="utf-8").replace("\r\n", "\n").strip()

    assert norm(BACKEND / "LICENSE") == norm(REPO / "LICENSE")


def test_seed_dir_found_in_installed_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A wheel puts the seed library at <site-packages>/promptvault/seed."""
    pkg = tmp_path / "site-packages" / "promptvault"
    (pkg / "services").mkdir(parents=True)
    (pkg / "seed").mkdir()
    (pkg / "seed" / "categories.yaml").write_text("groups: []\n", encoding="utf-8")
    monkeypatch.setattr(seed_svc, "__file__", str(pkg / "services" / "seed.py"))
    found = seed_svc.find_seed_dir(Settings(data_dir=tmp_path))
    assert found is not None
    assert found.resolve() == (pkg / "seed").resolve()


def test_explicit_seed_dir_wins(tmp_path: Path) -> None:
    custom = tmp_path / "custom"
    custom.mkdir()
    (custom / "categories.yaml").write_text("groups: []\n", encoding="utf-8")
    assert seed_svc.find_seed_dir(Settings(data_dir=tmp_path, seed_dir=custom)) == custom


def test_seed_dir_found_from_checkout(tmp_path: Path) -> None:
    found = seed_svc.find_seed_dir(Settings(data_dir=tmp_path))
    assert found is not None and (found / "categories.yaml").is_file()
