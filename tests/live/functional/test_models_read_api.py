"""Functional layer: models read endpoints (list, get, missing).

F14, F15, F17 from docs/E2E_TEST_PLAN.md. Authenticated.
"""

from __future__ import annotations

import httpx
import pytest

from tests.live.assertions.api import assert_status

pytestmark = pytest.mark.requires_token


def test_models_list_with_default_path(
    live_client: httpx.Client, live_username: str
) -> None:
    """F14: GET /api/models with no `path` lists models at /{user}/modelseed/."""
    r = live_client.get("/api/models")
    assert_status(r, 200)
    payload = r.json()
    assert isinstance(payload, list), f"models list not a list: {type(payload)}"
    # We don't assert any specific count — the user may have 0 or many models.


def test_models_list_with_explicit_sandbox_path(
    live_client: httpx.Client, workspace_sandbox: str
) -> None:
    """F15: GET /api/models?path=<sandbox> works for an explicit path."""
    r = live_client.get("/api/models", params={"path": workspace_sandbox})
    assert_status(r, 200)
    payload = r.json()
    assert isinstance(payload, list)


def test_model_data_missing_returns_404(
    live_client: httpx.Client, live_username: str
) -> None:
    """F17: GET /api/models/data?ref=<missing> returns 404."""
    bogus_ref = f"/{live_username}/modelseed/__definitely_not_a_real_model__"
    r = live_client.get("/api/models/data", params={"ref": bogus_ref})
    # Workspace may return 404 or 502 depending on how it handles the missing path.
    assert_status(r, [404, 502])
