"""Shared test fixtures for the ModelSEED API test suite."""

import pytest
from fastapi.testclient import TestClient

from modelseed_api.main import app


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """Sample PATRIC auth headers for testing."""
    return {
        "Authorization": "un=testuser|tokenid=test123|expiry=9999999999|client_id=test|token_type=Bearer|SigningSubject=https://user.patricbrc.org/|sig=testsig"
    }


@pytest.fixture
def rast_auth_headers():
    """Sample RAST auth headers for testing."""
    return {
        "Authorization": "un=testuser|tokenid=test456|expiry=9999999999|SigningSubject=http://rast.nmpdr.org/goauth/keys/|sig=testsig"
    }
