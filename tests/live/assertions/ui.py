"""UI assertion helpers for Playwright-driven tests."""

from __future__ import annotations

from typing import Callable, Iterable

# Console-error patterns we treat as noise. These are environmental, not
# bugs in the app:
#   - NotSameOrigin: cross-origin resource blocks (browser security policy
#     for opaque responses); the page still works in real browsers.
#   - googletagmanager / fonts.googleapis: third-party scripts whose CDN
#     occasionally 404s or rate-limits.
#   - status of 401: auth-required subrequests fired by pages that have
#     auth-aware widgets but render fine without auth (the test session
#     is unauthenticated for public-page checks).
#   - status of 404: third-party assets (favicons, sourcemaps) that the
#     deployed frontend doesn't ship; not material to whether the page
#     functions.
_NOISE_PATTERNS: tuple[str, ...] = (
    "ERR_BLOCKED_BY_RESPONSE.NotSameOrigin",
    "googletagmanager",
    "fonts.googleapis",
    "status of 401",
    "status of 404",
)


def filter_noise(errors: Iterable[str]) -> list[str]:
    """Return only the console errors that look like real app bugs.

    See `_NOISE_PATTERNS` for the patterns that are dropped and why.
    """
    return [e for e in errors if not any(p in e for p in _NOISE_PATTERNS)]


def collect_console_errors(page) -> list:
    """Attach a listener and return a list that will be populated with any
    `console.error` (or page errors) that fire during the test.

    Apply `filter_noise()` before asserting to drop environmental noise.

    Usage::

        errors = collect_console_errors(page)
        page.goto(url)
        assert not filter_noise(errors), f"Console errors on {url}: {errors}"
    """
    errors: list = []

    def _on_console(msg) -> None:
        if msg.type == "error":
            errors.append(f"console.error: {msg.text}")

    def _on_pageerror(exc) -> None:
        errors.append(f"page error: {exc}")

    page.on("console", _on_console)
    page.on("pageerror", _on_pageerror)
    return errors


def wait_for_network_idle(page, timeout_ms: int = 15000) -> None:
    """Best-effort wait for network activity to quiet down.

    `networkidle` can never fire on pages with continuous polling or
    long-tail third-party requests (analytics, sentry, etc). Timing out
    is expected and not a test failure on its own; callers usually just
    want a bounded settling window before asserting on DOM content.
    """
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass


def get_response_count_to(page, url_substring: str) -> Callable[[], int]:
    """Return a closure that counts responses whose URL contains `url_substring`.

    Useful for asserting "the search box typed into the API at least once."

    Usage::

        count_searches = get_response_count_to(page, "/api/biochem/search")
        # ... do interactions ...
        assert count_searches() >= 1
    """
    counter = {"n": 0}

    def _on_response(response) -> None:
        if url_substring in response.url:
            counter["n"] += 1

    page.on("response", _on_response)
    return lambda: counter["n"]
