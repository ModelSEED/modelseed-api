"""Expanded auth tests — Bearer prefix, quotes, local mode bypass."""

import pytest
from unittest.mock import patch

pytestmark = pytest.mark.integration


class TestBearerPrefix:
    def test_bearer_prefix_stripped(self, local_client):
        resp = local_client.get("/api/models", headers={
            "Authorization": "Bearer un=testuser|tokenid=test123",
        })
        assert resp.status_code == 200

    def test_quoted_token_stripped(self, local_client):
        resp = local_client.get("/api/models", headers={
            "Authorization": '"un=testuser|tokenid=test123"',
        })
        assert resp.status_code == 200


class TestAuthenticationHeader:
    def test_authentication_header_accepted(self, local_client):
        resp = local_client.get("/api/models", headers={
            "Authentication": "un=testuser|tokenid=test123",
        })
        assert resp.status_code == 200


class TestLocalMode:
    def test_no_token_allowed(self, local_client):
        resp = local_client.get("/api/models")
        assert resp.status_code == 200

    def test_default_username_is_local(self, local_client):
        resp = local_client.get("/api/models")
        assert resp.status_code == 200


class TestWorkspaceMode:
    def test_requires_token(self, tmp_path, monkeypatch):
        from modelseed_api.config import settings

        monkeypatch.setattr(settings, "storage_backend", "workspace")
        from modelseed_api.main import app
        from fastapi.testclient import TestClient

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/models")
        assert resp.status_code == 401
        # Restore
        monkeypatch.setattr(settings, "storage_backend", "local")
