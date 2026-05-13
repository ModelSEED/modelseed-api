"""Smoke layer: every public page returns 2xx.

S02 + S03 from docs/E2E_TEST_PLAN.md. We don't execute JavaScript here —
that's Layer 4 (UI). This layer only confirms the server returns a non-error
HTML response for every documented public page.
"""

from __future__ import annotations

import httpx
import pytest

from tests.live.assertions.api import assert_status

# All non-auth public pages on modelseed.org. /plant is excluded per
# the user's instruction (not functional yet).
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


def test_landing_page_loads(ui_client: httpx.Client) -> None:
    """S02: GET / returns 200 and contains a recognizable marker."""
    r = ui_client.get("/")
    assert_status(r, 200)
    body = r.text.lower()
    assert "modelseed" in body, "landing page does not mention 'modelseed'"


@pytest.mark.parametrize("path", PUBLIC_PAGES, ids=lambda p: p.replace("/", "_") or "root")
def test_static_pages_all_load(ui_client: httpx.Client, path: str) -> None:
    """S03: every public page returns 200 (no 4xx/5xx)."""
    r = ui_client.get(path)
    # Some Next.js routes may legitimately redirect (308 → trailing slash);
    # treat any 2xx or follow-through to 2xx as pass.
    assert_status(r, range(200, 300))
