"""Tests for authentication middleware."""

from modelseed_api.auth.dependencies import _extract_username


def test_extract_username_patric():
    """Test username extraction from PATRIC token."""
    token = "un=chenry|tokenid=abc123|expiry=9999|sig=xyz"
    assert _extract_username(token) == "chenry"


def test_extract_username_rast():
    """Test username extraction from RAST token."""
    token = "un=rastuser|tokenid=def456|expiry=9999|SigningSubject=http://rast.nmpdr.org/goauth/keys/|sig=xyz"
    assert _extract_username(token) == "rastuser"


def test_health_check(client):
    """Test health check endpoint (no auth required)."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_list_models_no_auth(client):
    """Test that endpoints require authentication."""
    response = client.get("/api/models")
    assert response.status_code == 401


def test_list_models_with_auth(client, auth_headers):
    """Test that authentication header is accepted.

    Note: This will fail to connect to the workspace service
    since we're using a test token, but it should get past auth.
    """
    response = client.get("/api/models", headers=auth_headers)
    # Should not be 401 (auth should pass, may get 502 from workspace)
    assert response.status_code != 401
