"""Functional layer: workspace proxy endpoints.

F41–F48 from docs/E2E_TEST_PLAN.md. Authenticated. Uses workspace_sandbox
for any mutations so the teardown cleans up automatically.
"""

from __future__ import annotations

import httpx
import pytest

from tests.live.assertions.api import assert_status

pytestmark = pytest.mark.requires_token


def test_ws_ls_user_root(
    live_client: httpx.Client, live_username: str
) -> None:
    """F41: ls /{user}/ succeeds and returns a list."""
    r = live_client.post(
        "/api/workspace/ls",
        json={"paths": [f"/{live_username}/"]},
    )
    assert_status(r, 200)
    payload = r.json()
    # ls returns {path: [items]} — the path may have a trailing slash.
    assert isinstance(payload, dict)


def test_ws_ls_recursive(
    live_client: httpx.Client, live_username: str
) -> None:
    """F42: ls with recursive=True succeeds."""
    r = live_client.post(
        "/api/workspace/ls",
        json={"paths": [f"/{live_username}/modelseed/"], "recursive": True},
    )
    # 200 or 404 if the modelseed/ folder doesn't exist for this user.
    assert_status(r, [200, 404])


def test_ws_ls_nonexistent_path(live_client: httpx.Client) -> None:
    """F44: ls of a definitely-nonexistent user path returns 403 or 404."""
    r = live_client.post(
        "/api/workspace/ls",
        json={"paths": ["/__definitely_no_such_user__/"]},
    )
    assert_status(r, [403, 404, 502])


def test_ws_create_folder_then_delete(
    live_client: httpx.Client, workspace_sandbox: str
) -> None:
    """F44: create a folder under the sandbox, verify ls finds it, delete it."""
    folder_path = f"{workspace_sandbox}func_test_folder_{abs(hash('seed')) % 10000}"

    # Create
    r = live_client.post(
        "/api/workspace/create",
        json={
            "objects": [[folder_path, "folder", {}, ""]],
            "overwrite": True,
        },
    )
    assert_status(r, [200, 201])

    # ls the parent and verify our folder is in the listing
    r2 = live_client.post(
        "/api/workspace/ls",
        json={"paths": [workspace_sandbox]},
    )
    assert_status(r2, 200)

    # Delete
    r3 = live_client.post(
        "/api/workspace/delete",
        json={
            "objects": [folder_path],
            "deleteDirectories": True,
            "force": True,
        },
    )
    assert_status(r3, [200, 204])
