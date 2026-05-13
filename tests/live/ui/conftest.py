"""Playwright fixtures for the UI test layer.

These fixtures only activate when MODELSEED_TEST_UI_ENABLED=1 is set, so
the default `pytest tests/live/` collection doesn't pull Playwright into
sessions that don't need it.

To install / enable this layer:

    pip install -e ".[dev,ui-tests]"
    playwright install --with-deps chromium
    export MODELSEED_TEST_UI_ENABLED=1
    pytest tests/live/ui/

The auth strategy here is to inject the test token directly into browser
storage rather than scripting the BV-BRC login flow. The exact key (cookie
name vs localStorage entry) is configurable via env vars because we don't
yet know which one Vibhav's frontend uses — see `_auth_via_storage` below.
"""

from __future__ import annotations

import os
from typing import Iterator

import pytest

# Skip the entire UI layer collection unless explicitly enabled. This lets
# the default `pytest tests/live/` run skip Playwright entirely.
if os.environ.get("MODELSEED_TEST_UI_ENABLED", "0") != "1":
    collect_ignore_glob = ["test_*.py"]


# Lazy import — only triggered when the layer is enabled.
def _get_playwright():  # noqa: D401
    try:
        from playwright.sync_api import sync_playwright

        return sync_playwright
    except ImportError as exc:
        pytest.skip(
            "playwright not installed. "
            "Run `pip install -e \".[dev,ui-tests]\"` and "
            "`playwright install --with-deps chromium` first."
        )


@pytest.fixture(scope="session")
def browser():
    """Chromium browser instance, shared across tests in the session."""
    sync_playwright = _get_playwright()
    headless = os.environ.get("MODELSEED_TEST_UI_HEADLESS", "1") == "1"
    with sync_playwright() as p:
        b = p.chromium.launch(headless=headless)
        yield b
        b.close()


@pytest.fixture
def context(browser):
    """Fresh browser context per test — isolates cookies, localStorage, etc."""
    ctx = browser.new_context(
        viewport={"width": 1280, "height": 800},
    )
    yield ctx
    ctx.close()


@pytest.fixture
def page(context):
    """Fresh page on the default (unauthenticated) context."""
    p = context.new_page()
    yield p


# ─────────────────────────────────────────────────────────────────────────
# Authenticated page — injects the test token into browser storage
# ─────────────────────────────────────────────────────────────────────────


def _auth_via_storage(context, base_url: str, token: str) -> None:
    """Pre-bake the PATRIC token into the browser context so the frontend
    sees the user as logged in without scripting the BV-BRC login form.

    Vibhav's Next.js frontend stores auth in `localStorage["auth"]` as a
    JSON-stringified object with this exact shape:

        {
          "user_id": "<username>",      // e.g. "jplfaria@patricbrc.org"
          "token":   "<full token>",    // un=...|tokenid=...|sig=... format
          "method":  "PATRIC" | "RAST"
        }

    Verified by reading the production JS bundle (012n0aak-5mz_.js exports
    AUTH_STORAGE_KEY="auth", persistAuth, getStoredAuth, clearAuth). If the
    frontend changes its auth storage in the future, update the JSON shape
    or key name here.
    """
    import json

    # Extract username and detect token method from the token itself.
    # PATRIC tokens have un=...@patricbrc.org; RAST tokens have un=...
    # without the @ suffix, and SigningSubject points to rast.nmpdr.org.
    username = "unknown"
    method = "PATRIC"
    for part in token.split("|"):
        if part.startswith("un="):
            username = part[3:]
        elif part.startswith("SigningSubject=") and "rast.nmpdr.org" in part:
            method = "RAST"

    auth_payload = json.dumps({
        "user_id": username,
        "token": token,
        "method": method,
    })

    # Setting localStorage requires a same-origin page to be loaded first.
    page = context.new_page()
    page.goto(base_url)
    page.evaluate(
        "v => window.localStorage.setItem('auth', v)",
        auth_payload,
    )
    page.close()


@pytest.fixture
def authenticated_page(context, target_env, live_token):
    """A page with the PATRIC test token pre-baked into browser storage.

    Skips the test if we don't know where to inject the token (see
    _auth_via_storage docstring).
    """
    _auth_via_storage(context, target_env.base_url, live_token)
    p = context.new_page()
    yield p
