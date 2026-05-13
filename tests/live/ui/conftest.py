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
    """Pre-bake the auth token into the browser context so the frontend
    sees the user as logged in without scripting the BV-BRC login form.

    THE EXACT STORAGE LOCATION IS CURRENTLY UNKNOWN. Vibhav's Next.js app
    likely stores the PATRIC token in one of these places. To find out:

      1. Open https://modelseed.org in Chrome
      2. Log in with your real PATRIC account
      3. DevTools → Application → Storage
      4. Inspect: Cookies, Local Storage, Session Storage
      5. Find the entry that contains the `un=...|tokenid=...|sig=...` string
      6. Update the storage_keys list below with the actual key name(s)

    Until that's filled in, every authenticated UI test will skip with the
    `auth_storage_unknown` message rather than silently testing as logged-out.
    """
    storage_keys = [
        # (kind, key) — kind is "cookie" or "localStorage" or "sessionStorage"
        # ("localStorage", "patric.token"),
        # ("cookie", "P3Auth"),
    ]
    custom = os.environ.get("MODELSEED_TEST_UI_AUTH_KEY")
    if custom:
        # Format: "kind:key" e.g. "localStorage:patric.token" or "cookie:P3Auth"
        try:
            kind, key = custom.split(":", 1)
            storage_keys.append((kind.strip(), key.strip()))
        except ValueError:
            pytest.fail(
                f"Invalid MODELSEED_TEST_UI_AUTH_KEY={custom!r}. "
                "Expected format: 'kind:key' e.g. 'localStorage:patric.token'"
            )

    if not storage_keys:
        pytest.skip(
            "auth_storage_unknown: don't know where to inject the PATRIC token "
            "for the live frontend. Set MODELSEED_TEST_UI_AUTH_KEY=kind:key "
            "(e.g. 'localStorage:patric.token') after inspecting where Vibhav's "
            "app stores the token. See conftest._auth_via_storage docstring."
        )

    # Inject by visiting a blank page on the same origin first (required
    # to set localStorage) then setting cookies/storage.
    page = context.new_page()
    page.goto(base_url)
    for kind, key in storage_keys:
        if kind == "localStorage":
            page.evaluate(
                "([k, v]) => window.localStorage.setItem(k, v)",
                [key, token],
            )
        elif kind == "sessionStorage":
            page.evaluate(
                "([k, v]) => window.sessionStorage.setItem(k, v)",
                [key, token],
            )
        elif kind == "cookie":
            from urllib.parse import urlparse

            host = urlparse(base_url).hostname or "modelseed.org"
            context.add_cookies([{
                "name": key,
                "value": token,
                "domain": host,
                "path": "/",
                "httpOnly": False,
                "secure": True,
            }])
        else:
            pytest.fail(f"Unknown auth-storage kind: {kind!r}")
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
