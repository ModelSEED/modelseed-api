"""E2E fixtures — full stack with local storage, real biochem DB, no mocks."""

import json

import pytest
from fastapi.testclient import TestClient

from tests.integration.conftest import SAMPLE_MODEL


@pytest.fixture
def e2e_client(tmp_path, monkeypatch):
    """Full-stack TestClient with local storage and real biochem DB.

    No mocks anywhere — exercises routes → services → storage → filesystem.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    job_dir = tmp_path / "jobs"
    job_dir.mkdir()

    from modelseed_api.config import settings

    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "local_data_dir", str(data_dir))
    monkeypatch.setattr(settings, "job_store_dir", str(job_dir))

    from modelseed_api.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def auth_headers():
    return {"Authorization": "un=testuser|tokenid=test123"}


@pytest.fixture
def model_json():
    """Raw JSON string for creating a model via workspace API."""
    return json.dumps(SAMPLE_MODEL)
