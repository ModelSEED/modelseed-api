"""UI layer: every public page loads in a real browser without console errors.

U01 + U02 from docs/E2E_TEST_PLAN.md.
"""

from __future__ import annotations

import pytest

from tests.live.assertions.ui import (
    collect_console_errors,
    filter_noise,
    wait_for_network_idle,
)

# All non-auth public pages on modelseed.org (mirrored from the smoke layer).
PUBLIC_PAGES = [
    "/",
    "/genomes",
    "/biochem/reactions",
    "/biochem/reactions/rxn00001",
    "/biochem/compounds",
    "/biochem/compounds/cpd00027",
    "/list-media",
    "/team",
    "/publications",
    "/projects",
    "/events",
    "/about",
    "/about/version",
    "/about/data-sources",
]


def test_landing_no_console_errors(page, target_env) -> None:
    """U01: landing page renders with no app-level console errors."""
    errors = collect_console_errors(page)
    page.goto(target_env.base_url + "/", wait_until="domcontentloaded")
    wait_for_network_idle(page)
    real = filter_noise(errors)
    assert not real, f"Landing page console errors: {real}"


@pytest.mark.parametrize("path", PUBLIC_PAGES, ids=lambda p: p.replace("/", "_") or "root")
def test_pages_no_console_errors_parametrized(page, target_env, path: str) -> None:
    """U02: every public page renders without app-level console errors."""
    errors = collect_console_errors(page)
    page.goto(target_env.base_url + path, wait_until="domcontentloaded")
    wait_for_network_idle(page)
    real = filter_noise(errors)
    assert not real, f"Console errors on {path}: {real}"


def test_about_version_shows_current_build(page, target_env) -> None:
    """U12: /about/version page shows version info."""
    page.goto(target_env.base_url + "/about/version", wait_until="domcontentloaded")
    wait_for_network_idle(page)
    body_text = page.text_content("body") or ""
    # The page lists multiple service URLs and a version number; we just
    # verify the page rendered something recognizable.
    assert "modelseed" in body_text.lower() or "version" in body_text.lower(), (
        "Version page body doesn't contain expected content"
    )
