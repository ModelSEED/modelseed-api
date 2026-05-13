"""Smoke layer: API health endpoint.

S01 from docs/E2E_TEST_PLAN.md.
"""

from __future__ import annotations

import httpx

from tests.live.assertions.api import assert_json_keys, assert_status


def test_health_endpoint(public_client: httpx.Client) -> None:
    """S01: /api/health returns {status: ok, version: ...}."""
    r = public_client.get("/api/health")
    assert_status(r, 200)
    payload = r.json()
    assert_json_keys(payload, ["status", "version"], context="/api/health")
    assert payload["status"] == "ok", f"health status not ok: {payload}"
