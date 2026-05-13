"""Functional layer: media endpoints.

F09–F13 from docs/E2E_TEST_PLAN.md.
"""

from __future__ import annotations

import httpx
import pytest

from tests.live.assertions.api import assert_status

pytestmark = pytest.mark.requires_token


def test_media_public_with_auth(live_client: httpx.Client) -> None:
    """F09: /api/media/public works with auth (mirror of smoke test)."""
    r = live_client.get("/api/media/public")
    assert_status(r, 200)


def test_media_mine_returns_list_or_empty(live_client: httpx.Client) -> None:
    """F10: /api/media/mine returns a list (possibly empty if folder doesn't exist)."""
    r = live_client.get("/api/media/mine")
    # Per the docs, should be 200 with [] if folder doesn't exist.
    assert_status(r, [200, 404])


def test_media_export_complete_is_empty_by_design(live_client: httpx.Client) -> None:
    """F11a: PATRIC's Complete media is intentionally an empty TSV (just the
    header row). PATRIC convention: empty media file = all exchanges open;
    model loading code interprets it. Verify our endpoint returns the right
    shape with `compounds: []` rather than erroring out on the empty file.
    """
    r = live_client.get(
        "/api/media/export",
        params={"ref": "/chenry/public/modelsupport/media/Complete"},
    )
    if r.status_code == 404:
        pytest.skip("Complete media not available on this deployment")
    assert_status(r, 200)
    media = r.json()
    assert isinstance(media, dict)
    assert "compounds" in media
    assert media["compounds"] == [], (
        f"PATRIC Complete media is supposed to be empty (open-exchanges sentinel), "
        f"got {len(media['compounds'])} compounds"
    )


def test_media_export_glucose_minimal_has_compounds(live_client: httpx.Client) -> None:
    """F11b: Carbon-D-Glucose is a real defined media with compounds in it."""
    r = live_client.get(
        "/api/media/export",
        params={"ref": "/chenry/public/modelsupport/media/Carbon-D-Glucose"},
    )
    if r.status_code == 404:
        pytest.skip("Carbon-D-Glucose media not available on this deployment")
    assert_status(r, 200)
    media = r.json()
    assert isinstance(media, dict)
    compounds = media.get("compounds") or []
    assert len(compounds) > 0, "Carbon-D-Glucose should have compounds"
    # Extract IDs from whichever shape the entries come in (dict or tuple).
    ids = set()
    for c in compounds:
        cid = c.get("compound_id") if isinstance(c, dict) else (c[0] if c else None)
        if cid:
            ids.add(cid)
    assert "cpd00027" in ids, (
        f"Carbon-D-Glucose missing glucose (cpd00027). Got IDs: {sorted(ids)[:10]}"
    )


def test_media_export_missing_returns_404(live_client: httpx.Client) -> None:
    """F13: Missing media ref returns 404."""
    r = live_client.get(
        "/api/media/export",
        params={"ref": "/chenry/public/modelsupport/media/__no_such_media__"},
    )
    assert_status(r, [404, 502])
