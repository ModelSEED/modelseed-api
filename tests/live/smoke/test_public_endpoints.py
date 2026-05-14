"""Smoke layer: public API endpoints (no auth required).

S04–S11 from docs/E2E_TEST_PLAN.md. These are the fastest possible signal
that the API is up, the biochem DB is loaded, and known-good objects can
be retrieved by ID.
"""

from __future__ import annotations

import httpx

from tests.live.assertions.api import (
    assert_json_keys,
    assert_list_of_dicts_with_keys,
    assert_status,
)


def test_biochem_stats_shape(public_client: httpx.Client) -> None:
    """S04: /api/biochem/stats returns numeric reaction/compound counts > 0."""
    r = public_client.get("/api/biochem/stats")
    assert_status(r, 200)
    payload = r.json()
    assert_json_keys(
        payload, ["total_compounds", "total_reactions"], context="/api/biochem/stats"
    )
    assert int(payload["total_compounds"]) > 0
    assert int(payload["total_reactions"]) > 0


def test_known_compound_glucose(public_client: httpx.Client) -> None:
    """S05: cpd00027 returns glucose with formula C6H12O6."""
    r = public_client.get("/api/biochem/compounds", params={"ids": "cpd00027"})
    assert_status(r, 200)
    payload = r.json()
    assert_list_of_dicts_with_keys(
        payload, ["id", "formula"], context="/api/biochem/compounds?ids=cpd00027",
        min_len=1,
    )
    glucose = next((c for c in payload if c["id"] == "cpd00027"), None)
    assert glucose is not None, f"cpd00027 not in response: {payload}"
    # Formula may include charge variants; require the C6H12O6 substring.
    assert "C6H12O6" in (glucose.get("formula") or ""), (
        f"glucose formula unexpected: {glucose.get('formula')}"
    )


def test_known_compound_water_proton(public_client: httpx.Client) -> None:
    """S06: cpd00001 is water, cpd00067 is H+."""
    r = public_client.get("/api/biochem/compounds", params={"ids": "cpd00001,cpd00067"})
    assert_status(r, 200)
    payload = r.json()
    by_id = {c["id"]: c for c in payload}
    assert "cpd00001" in by_id, f"cpd00001 missing: {by_id.keys()}"
    assert "cpd00067" in by_id, f"cpd00067 missing: {by_id.keys()}"
    # Sanity-check the formulae are right.
    assert "H2O" in (by_id["cpd00001"].get("formula") or "")
    assert "H" in (by_id["cpd00067"].get("formula") or "")


def test_known_reaction_rxn00001(public_client: httpx.Client) -> None:
    """S07: rxn00001 returns a reaction with a name and equation."""
    r = public_client.get("/api/biochem/reactions", params={"ids": "rxn00001"})
    assert_status(r, 200)
    payload = r.json()
    assert_list_of_dicts_with_keys(
        payload, ["id", "name"], context="/api/biochem/reactions?ids=rxn00001",
        min_len=1,
    )
    assert payload[0]["id"] == "rxn00001"
    assert payload[0].get("name"), "rxn00001 missing name"


def test_search_compounds_glucose(public_client: httpx.Client) -> None:
    """S08: searching for 'glucose' returns ≥1 hit including cpd00027."""
    r = public_client.get(
        "/api/biochem/search",
        params={"query": "glucose", "type": "compounds", "limit": 50},
    )
    assert_status(r, 200)
    payload = r.json()
    assert isinstance(payload, list) and len(payload) >= 1, "no glucose hits"
    ids = {c.get("id") for c in payload}
    assert "cpd00027" in ids, f"cpd00027 not in glucose search results: {sorted(ids)[:10]}"


def test_search_reactions_atpase(public_client: httpx.Client) -> None:
    """S09: searching for 'ATPase' returns ≥1 reaction."""
    r = public_client.get(
        "/api/biochem/search",
        params={"query": "ATPase", "type": "reactions", "limit": 50},
    )
    assert_status(r, 200)
    payload = r.json()
    assert isinstance(payload, list) and len(payload) >= 1, "no ATPase hits"


def test_public_media_list_nonempty(public_client: httpx.Client) -> None:
    """S10: /api/media/public returns the public media list with multiple entries.

    The endpoint returns a workspace ls response; we just verify it has ≥10
    entries (the public media folder contains hundreds of formulations).
    """
    r = public_client.get("/api/media/public")
    assert_status(r, 200)
    payload = r.json()
    # The shape may be a dict {path: [items...]} (workspace ls) or a flat list.
    if isinstance(payload, dict):
        # Find any value that's a list and count it.
        count = max(
            (len(v) for v in payload.values() if isinstance(v, list)), default=0
        )
    elif isinstance(payload, list):
        count = len(payload)
    else:
        raise AssertionError(f"/api/media/public returned unexpected shape: {type(payload)}")
    assert count >= 10, f"public media list too small: {count} entries"


def test_rast_jobs_endpoint_reachable(public_client: httpx.Client) -> None:
    """S11: /api/rast/jobs is reachable and returns a sensible status code.

    The endpoint wraps MSSS over JSON-RPC, so behavior depends on:
      - 503 if MODELSEED_MSSS_URL is unset on the deploy
      - 401 if MSSS rejects our placeholder token (the most common case)
      - 502 if MSSS itself errors
      - 200 if MSSS happens to accept our placeholder (unlikely)
    All four are valid responses; what we're verifying is that the route
    is registered and doesn't crash with a 404 or 500.
    """
    headers = {"Authorization": "un=smoke-test|tokenid=placeholder"}
    r = public_client.get("/api/rast/jobs", headers=headers)
    assert_status(r, [200, 401, 502, 503])
