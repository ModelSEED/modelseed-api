"""UI assertion helpers for Playwright-driven tests."""

from __future__ import annotations

from typing import Callable


def collect_console_errors(page) -> list:
    """Attach a listener and return a list that will be populated with any
    `console.error` (or page errors) that fire during the test.

    Usage::

        errors = collect_console_errors(page)
        page.goto(url)
        assert not errors, f"Console errors on {url}: {errors}"
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


def wait_for_network_idle(page, timeout_ms: int = 5000) -> None:
    """Wait until network activity quiets down. Useful after navigation
    when the page fires multiple async fetches before settling."""
    page.wait_for_load_state("networkidle", timeout=timeout_ms)


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
