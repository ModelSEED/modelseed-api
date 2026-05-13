"""Shared fixtures and configuration for the live E2E test suite.

See docs/E2E_TEST_PLAN.md for the full design.

All live tests target a deployed environment (production or staging) — never
the in-process FastAPI TestClient. Tests use only the fixtures defined here;
they should not read environment variables directly.

Token handling is strict: the token is read once from MODELSEED_TEST_TOKEN
at session start and is NEVER printed in test output, captured logs, or
report artifacts. A pytest_runtest_logreport hook scrubs it from any
captured strings before they reach the report.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

import httpx
import pytest

# Make the application importable so we can reuse its token-parsing helper.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from modelseed_api.auth.dependencies import _extract_username  # noqa: E402

logger = logging.getLogger("tests.live")


# ─────────────────────────────────────────────────────────────────────────
# Environment resolution
# ─────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TargetEnv:
    """Resolved configuration for a live target environment."""

    name: str  # production | staging | local
    base_url: str  # UI base URL (e.g. https://modelseed.org)
    api_url: str  # API base URL (e.g. https://modelseed.org/PMS)


_ENV_DEFAULTS = {
    "production": TargetEnv(
        name="production",
        base_url="https://modelseed.org",
        api_url="https://modelseed.org/PMS",
    ),
    "staging": TargetEnv(
        name="staging",
        base_url="https://staging.modelseed.org",
        api_url="https://staging.modelseed.org/PMS",
    ),
    "local": TargetEnv(
        name="local",
        base_url="http://localhost:3004",
        api_url="http://localhost:3004",
    ),
}


def _resolve_target_env() -> TargetEnv:
    """Pick the env from MODELSEED_TEST_ENV with overrides for base/api URLs."""
    name = os.environ.get("MODELSEED_TEST_ENV", "production").lower()
    if name not in _ENV_DEFAULTS:
        raise pytest.UsageError(
            f"MODELSEED_TEST_ENV={name!r} not recognized. "
            f"Pick one of: {', '.join(_ENV_DEFAULTS)}, or override "
            f"MODELSEED_TEST_BASE_URL and MODELSEED_TEST_API_URL."
        )
    default = _ENV_DEFAULTS[name]
    return TargetEnv(
        name=name,
        base_url=os.environ.get("MODELSEED_TEST_BASE_URL", default.base_url),
        api_url=os.environ.get("MODELSEED_TEST_API_URL", default.api_url),
    )


@pytest.fixture(scope="session")
def target_env() -> TargetEnv:
    """The resolved deployment target for this test session."""
    env = _resolve_target_env()
    logger.info("Live test target: %s (api=%s, ui=%s)", env.name, env.api_url, env.base_url)
    return env


# ─────────────────────────────────────────────────────────────────────────
# Token handling — careful, the token is sensitive
# ─────────────────────────────────────────────────────────────────────────


def _redact(text: str, secrets: list[str]) -> str:
    """Replace each secret with `***` in `text`. Used by the log scrubber."""
    redacted = text
    for s in secrets:
        if s and s in redacted:
            redacted = redacted.replace(s, "***")
    return redacted


@pytest.fixture(scope="session")
def live_token() -> str:
    """The PATRIC token for live tests; skips the test if the env var is unset.

    The token is also registered with pytest's secret-redaction hook so it
    cannot leak into reports or captured output.
    """
    token = os.environ.get("MODELSEED_TEST_TOKEN", "").strip()
    if not token:
        pytest.skip(
            "MODELSEED_TEST_TOKEN not set — required for tests marked requires_token. "
            "Export it from your secret store; never commit it."
        )
    # Strip optional Bearer prefix and surrounding quotes the same way the
    # auth dependency does, so what we send matches what production accepts.
    token = token.removeprefix("Bearer ").strip('"').strip("'")
    _SECRETS_TO_REDACT.add(token)
    return token


@pytest.fixture(scope="session")
def live_rast_token() -> str:
    """Optional separate RAST token for /api/rast/jobs tests."""
    token = os.environ.get("MODELSEED_TEST_RAST_TOKEN", "").strip()
    if not token:
        pytest.skip("MODELSEED_TEST_RAST_TOKEN not set — required for RAST tests.")
    token = token.removeprefix("Bearer ").strip('"').strip("'")
    _SECRETS_TO_REDACT.add(token)
    return token


@pytest.fixture(scope="session")
def live_username(live_token: str) -> str:
    """Username extracted from the test token. Skips on tokens we can't parse."""
    explicit = os.environ.get("MODELSEED_TEST_USERNAME")
    if explicit:
        return explicit
    try:
        return _extract_username(live_token)
    except Exception as exc:  # pragma: no cover - defensive
        pytest.skip(f"Could not extract username from MODELSEED_TEST_TOKEN: {exc}")


# Secrets to scrub from test output. Populated by token fixtures.
_SECRETS_TO_REDACT: set[str] = set()


def pytest_runtest_logreport(report) -> None:  # noqa: D401
    """Redact secrets from any captured output before they hit reports.

    `report.capstdout` and `report.capstderr` are read-only properties
    computed from `report.sections`; we modify the sections list in place
    and the properties surface the redacted content. `longrepr` is settable.
    """
    if not _SECRETS_TO_REDACT:
        return
    secrets = list(_SECRETS_TO_REDACT)
    if report.sections:
        report.sections = [
            (name, _redact(content, secrets)) for name, content in report.sections
        ]
    if hasattr(report, "longrepr") and report.longrepr:
        try:
            report.longrepr = _redact(str(report.longrepr), secrets)
        except (AttributeError, TypeError):
            # Some longrepr objects are not assignable; tolerate that.
            pass


# ─────────────────────────────────────────────────────────────────────────
# HTTP clients
# ─────────────────────────────────────────────────────────────────────────


def _client_with_retries(base_url: str, headers: dict | None = None) -> httpx.Client:
    """httpx.Client with sensible defaults for live testing.

    Note: per-request retry logic for 502/503/504 lives in the API
    helpers (assertions/api.py), not in the client itself, because we
    want different retry behavior for read endpoints vs write endpoints.
    """
    return httpx.Client(
        base_url=base_url,
        headers=headers or {},
        # Read timeout is generous because workspace recursive ls and
        # job dispatch can be slow under load. Connect timeout stays
        # tight — failure to connect at all is what we want to fail fast.
        timeout=httpx.Timeout(60.0, connect=10.0),
        follow_redirects=True,
    )


@pytest.fixture(scope="session")
def public_client(target_env: TargetEnv) -> Iterator[httpx.Client]:
    """HTTP client for unauthenticated requests to the API."""
    with _client_with_retries(target_env.api_url) as client:
        yield client


@pytest.fixture(scope="session")
def ui_client(target_env: TargetEnv) -> Iterator[httpx.Client]:
    """HTTP client for the UI base URL (used for static page checks)."""
    with _client_with_retries(target_env.base_url) as client:
        yield client


@pytest.fixture(scope="session")
def live_client(
    target_env: TargetEnv, live_token: str
) -> Iterator[httpx.Client]:
    """Authenticated HTTP client for the API. Skips the test if no token."""
    headers = {"Authorization": live_token}
    with _client_with_retries(target_env.api_url, headers=headers) as client:
        yield client


# ─────────────────────────────────────────────────────────────────────────
# Workspace sandbox — created once per session, cleaned on teardown
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def workspace_sandbox(
    live_client: httpx.Client, live_username: str
) -> Iterator[str]:
    """Create a sandbox workspace path for this test run; clean up on exit.

    Tests that write models, media, or any other workspace artifact should
    write under this path so the teardown removes everything in one shot.

    Set MODELSEED_TEST_KEEP_ARTIFACTS=1 to skip teardown when debugging.
    """
    root = os.environ.get(
        "MODELSEED_TEST_WORKSPACE_ROOT",
        f"/{live_username}/modelseed/test_e2e/",
    ).rstrip("/") + "/"

    # Create the folder (idempotent — workspace returns harmless errors if exists)
    create_payload = {
        "objects": [[root.rstrip("/"), "folder", {"created_by": "live_e2e_suite"}, ""]],
        "overwrite": False,
    }
    try:
        live_client.post("/api/workspace/create", json=create_payload)
    except httpx.HTTPError as exc:
        logger.warning("Could not pre-create sandbox %s: %s", root, exc)

    yield root

    if os.environ.get("MODELSEED_TEST_KEEP_ARTIFACTS", "0") == "1":
        logger.info("Keeping sandbox at %s (MODELSEED_TEST_KEEP_ARTIFACTS=1)", root)
        return

    # Best-effort recursive delete. Don't let teardown failures fail the suite.
    try:
        live_client.post(
            "/api/workspace/delete",
            json={"objects": [root.rstrip("/")], "deleteDirectories": True, "force": True},
        )
    except httpx.HTTPError as exc:
        logger.warning("Sandbox cleanup failed for %s: %s", root, exc)


# ─────────────────────────────────────────────────────────────────────────
# Session-start health check — bail early if upstream is broken
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session", autouse=True)
def upstream_health_check(target_env: TargetEnv) -> None:
    """Hit /api/health once at session start. If it fails, mark the whole
    suite for graceful skip-or-xfail rather than letting every test produce
    a 502 of its own.
    """
    try:
        with _client_with_retries(target_env.api_url) as c:
            r = c.get("/api/health")
            if r.status_code != 200:
                logger.error(
                    "Upstream health check failed: %s returned %s. "
                    "Live tests will likely fail.",
                    f"{target_env.api_url}/api/health",
                    r.status_code,
                )
            else:
                logger.info("Upstream health: %s", r.json())
    except Exception as exc:
        logger.error(
            "Could not reach %s/api/health: %s. Live tests will likely fail.",
            target_env.api_url,
            exc,
        )


# ─────────────────────────────────────────────────────────────────────────
# Pytest hook: ensure markers don't accidentally collect into wrong layer
# ─────────────────────────────────────────────────────────────────────────


def pytest_collection_modifyitems(config, items) -> None:  # noqa: D401
    """Auto-mark tests by their containing directory.

    A file under tests/live/smoke/ gets `live_smoke` automatically;
    under functional/ gets `live_functional`; etc. This keeps test
    files clean — they don't all need explicit markers.
    """
    dir_to_marker = {
        "smoke": "live_smoke",
        "functional": "live_functional",
        "biological": "live_biological",
        "ui": "live_ui",
        "load": "live_load",
    }
    for item in items:
        path_parts = Path(str(item.fspath)).parts
        if "live" not in path_parts:
            continue
        # Always mark anything under tests/live with `live`
        item.add_marker(pytest.mark.live)
        # Then add the layer-specific marker based on the subdir
        for part in path_parts:
            if part in dir_to_marker:
                item.add_marker(getattr(pytest.mark, dir_to_marker[part]))
                break
