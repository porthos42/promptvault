from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from promptvault.config import Settings
from promptvault.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path, _env_file=None)  # type: ignore[call-arg]


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as c:
        yield c
