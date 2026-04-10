"""Shared fixtures for route tests — TestClient with local storage."""

import json
import os

import pytest
from fastapi.testclient import TestClient

from tests.integration.conftest import SAMPLE_MODEL


@pytest.fixture
def local_client(tmp_path, monkeypatch):
    """TestClient with local storage backend and real biochem DB."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    from modelseed_api.config import settings

    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "local_data_dir", str(data_dir))
    monkeypatch.setattr(settings, "job_store_dir", str(tmp_path / "jobs"))
    (tmp_path / "jobs").mkdir()

    from modelseed_api.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def seeded_client(tmp_path, monkeypatch):
    """TestClient with a pre-populated model for GET/export/edit tests."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    from modelseed_api.config import settings

    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "local_data_dir", str(data_dir))
    monkeypatch.setattr(settings, "job_store_dir", str(tmp_path / "jobs"))
    (tmp_path / "jobs").mkdir()

    from modelseed_api.services.local_storage_service import LocalStorageService

    storage = LocalStorageService(token="test-token", data_dir=str(data_dir))
    storage.create({
        "objects": [["/local/modelseed/TestModel", "modelfolder", {
            "id": "TestModel",
            "name": "TestModel",
            "num_reactions": "1",
            "num_compounds": "2",
            "num_genes": "0",
            "num_compartments": "2",
            "num_biomasses": "1",
        }, None]],
    })
    storage.create({
        "objects": [["/local/modelseed/TestModel/model", "model", {},
                     json.dumps(SAMPLE_MODEL)]],
        "overwrite": True,
    })

    from modelseed_api.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def auth_headers():
    """Auth headers for local mode (any token works)."""
    return {"Authorization": "un=testuser|tokenid=test123"}
