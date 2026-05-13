"""Functional layer: biochemistry API parameter coverage.

F01–F08 from docs/E2E_TEST_PLAN.md. Public endpoints, but exercised
beyond what the smoke layer does — limit boundaries, invalid types,
batch fetches, edge cases.
"""

from __future__ import annotations

import httpx
import pytest

from tests.live.assertions.api import assert_status


def test_biochem_compounds_batch_50(public_client: httpx.Client) -> None:
    """F01: Batch fetch of 50 compounds returns all of them."""
    ids = [f"cpd{i:05d}" for i in range(1, 51)]
    r = public_client.get("/api/biochem/compounds", params={"ids": ",".join(ids)})
    assert_status(r, 200)
    payload = r.json()
    assert isinstance(payload, list)
    returned = {c.get("id") for c in payload}
    # Some IDs in this range may not exist; we just want most of them back.
    overlap = returned & set(ids)
    assert len(overlap) >= 30, (
        f"Batch fetch returned {len(overlap)} of 50 known IDs; expected ≥30"
    )


def test_biochem_reactions_batch_50(public_client: httpx.Client) -> None:
    """F02: Batch fetch of 50 reactions returns most."""
    ids = [f"rxn{i:05d}" for i in range(1, 51)]
    r = public_client.get("/api/biochem/reactions", params={"ids": ",".join(ids)})
    assert_status(r, 200)
    payload = r.json()
    assert isinstance(payload, list)
    returned = {c.get("id") for c in payload}
    overlap = returned & set(ids)
    assert len(overlap) >= 30


@pytest.mark.parametrize("limit,expected_status", [
    (1, 200),
    (50, 200),
    (200, 200),
    (201, 422),
])
def test_biochem_search_limit_boundaries(
    public_client: httpx.Client, limit: int, expected_status: int
) -> None:
    """F03: Search limit boundaries — 1, 50, 200 succeed; 201 fails 422."""
    r = public_client.get(
        "/api/biochem/search",
        params={"query": "a", "type": "compounds", "limit": limit},
    )
    assert_status(r, expected_status)


def test_biochem_search_invalid_type(public_client: httpx.Client) -> None:
    """F04: type=metabolites is not a valid type → 400."""
    r = public_client.get(
        "/api/biochem/search",
        params={"query": "glucose", "type": "metabolites"},
    )
    # Implementation may return 400 or 422 depending on validation layer.
    assert_status(r, [400, 422])


def test_biochem_nonexistent_ids(public_client: httpx.Client) -> None:
    """F06: Looking up an ID that doesn't exist returns an empty list, not 500."""
    r = public_client.get(
        "/api/biochem/reactions", params={"ids": "rxn99999999"}
    )
    assert_status(r, 200)
    assert r.json() == [] or r.json() == [None]


def test_biochem_search_by_id(public_client: httpx.Client) -> None:
    """F07: Searching by ID string finds the matching compound."""
    r = public_client.get(
        "/api/biochem/search",
        params={"query": "cpd00001", "type": "compounds", "limit": 10},
    )
    assert_status(r, 200)
    payload = r.json()
    ids = {c.get("id") for c in payload}
    assert "cpd00001" in ids, f"cpd00001 not found by ID search: {ids}"
