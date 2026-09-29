"""Smoke layer: API health endpoint.

S01 from docs/E2E_TEST_PLAN.md.
"""

from __future__ import annotations

import httpx

from tests.live.assertions.api import assert_json_keys, assert_status
from tests.live.conftest import TargetEnv


def test_health_endpoint(public_client: httpx.Client) -> None:
    """S01: /api/health returns {status: ok, version: ...}."""
    r = public_client.get("/api/health")
    assert_status(r, 200)
    payload = r.json()
    assert_json_keys(payload, ["status", "version"], context="/api/health")
    assert payload["status"] == "ok", f"health status not ok: {payload}"


def test_openapi_uses_deployment_prefix(
    public_client: httpx.Client, target_env: TargetEnv
) -> None:
    """Swagger and ReDoc must resolve OpenAPI through the deployed API prefix."""
    r = public_client.get("/openapi.json")
    assert_status(r, 200)
    payload = r.json()
    assert payload.get("openapi"), "OpenAPI document is missing its version"
    assert "/api/health" in payload.get("paths", {})

    api_prefix = httpx.URL(target_env.api_url).path.rstrip("/")
    if api_prefix:
        assert {server.get("url") for server in payload.get("servers", [])} == {
            api_prefix
        }, f"OpenAPI servers do not identify deployment prefix {api_prefix!r}"

    for page in ("/docs", "/redoc"):
        docs = public_client.get(page)
        assert_status(docs, 200)
        assert f"{api_prefix}/openapi.json" in docs.text, (
            f"{page} does not load OpenAPI through {api_prefix or '/'}"
        )


def test_demo_uses_deployment_prefix(
    public_client: httpx.Client, target_env: TargetEnv
) -> None:
    """The development dashboard must load and call the prefixed API."""
    demo = public_client.get("/demo/")
    assert_status(demo, 200)
    assert "ModelSEED API" in demo.text
    assert "fetch(API + '/api/health')" in demo.text

    api_prefix = httpx.URL(target_env.api_url).path.rstrip("/")
    if api_prefix:
        assert f"{api_prefix}/demo/" in str(demo.url)
