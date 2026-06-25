"""Functional layer: GET /api/rast/genome (MSSS-backed RAST genome fetch).

Hits the deployed endpoint with a real RAST token and validates the shape
+ content of the returned KBase Genome dict against the same assertions
the unit tests run against the saved fixture.
"""

from __future__ import annotations

import httpx
import pytest

from tests.live.assertions.api import assert_status

# These tests need:
#   - MODELSEED_TEST_RAST_TOKEN (RAST token; PATRIC token is rejected by MSSS)
#   - MSSS reachable from wherever pytest is running
pytestmark = pytest.mark.requires_token


# A known-good RAST job belonging to jplfaria (Helicobacter pylori 26695).
# Same job we use as the saved fixture for unit tests, so the contract is
# directly comparable.
KNOWN_JOB = {"job_id": "297911", "genome_id": "85962.43"}


@pytest.fixture
def rast_client(target_env, live_rast_token) -> httpx.Client:
    """Authenticated client using the RAST token (not the PATRIC one)."""
    return httpx.Client(
        base_url=target_env.api_url,
        headers={"Authorization": live_rast_token},
        timeout=httpx.Timeout(180.0, connect=10.0),
        follow_redirects=True,
    )


def test_rast_genome_returns_kbase_dict(rast_client: httpx.Client) -> None:
    """Happy path: known job returns a well-shaped KBase Genome dict."""
    r = rast_client.get(
        "/api/rast/genome",
        params={
            "genome_id": KNOWN_JOB["genome_id"],
            "job_id": KNOWN_JOB["job_id"],
        },
    )
    assert_status(r, 200)
    g = r.json()
    # Spot-check the most important fields. Full per-field assertions live
    # in the unit tests against the saved fixture.
    assert g["id"] == KNOWN_JOB["genome_id"]
    assert g["scientific_name"] == "Helicobacter pylori 26695"
    assert g["domain"] == "Bacteria"
    assert g["genetic_code"] == 11
    assert g["molecule_type"] == "DNA"
    assert isinstance(g["features"], list)
    assert isinstance(g["non_coding_features"], list)
    assert isinstance(g["cdss"], list)
    assert isinstance(g["feature_counts"], dict)


def test_rast_genome_returns_real_features(rast_client: httpx.Client) -> None:
    """The returned genome has the expected feature counts (real data)."""
    r = rast_client.get(
        "/api/rast/genome",
        params={"genome_id": KNOWN_JOB["genome_id"], "job_id": KNOWN_JOB["job_id"]},
    )
    assert_status(r, 200)
    g = r.json()
    # H. pylori 26695 has 1687 PEGs + 86 repeats + 40 RNAs in this annotation
    assert len(g["features"]) == 1687, f"expected 1687 PEGs, got {len(g['features'])}"
    assert (
        len(g["non_coding_features"]) == 126
    ), f"expected 126 non-coding, got {len(g['non_coding_features'])}"
    assert len(g["cdss"]) == 1687
    assert g["feature_counts"]["protein_encoding_gene"] == 1687
    assert g["feature_counts"]["repeat_region"] == 86
    assert g["feature_counts"]["rRNA"] == 40


def test_rast_genome_features_are_well_formed(rast_client: httpx.Client) -> None:
    """Spot-check that features have all the KBase-required fields populated."""
    r = rast_client.get(
        "/api/rast/genome",
        params={"genome_id": KNOWN_JOB["genome_id"], "job_id": KNOWN_JOB["job_id"]},
    )
    assert_status(r, 200)
    g = r.json()
    required_feature_keys = {
        "id",
        "type",
        "location",
        "functions",
        "aliases",
        "dna_sequence",
        "dna_sequence_length",
        "md5",
        "protein_translation",
        "protein_translation_length",
        "protein_md5",
    }
    for f in g["features"][:50]:  # spot-check first 50
        missing = required_feature_keys - f.keys()
        assert not missing, f"feature {f.get('id')} missing keys: {missing}"
        assert f["type"] == "gene"
        assert f["protein_translation"]  # PEGs always have a sequence
        assert f["protein_md5"], f"feature {f['id']} missing protein_md5"


def test_rast_genome_missing_genome_id_param(rast_client: httpx.Client) -> None:
    """Missing required query param yields 422."""
    r = rast_client.get("/api/rast/genome", params={"job_id": "297911"})
    assert_status(r, 422)


def test_rast_genome_unknown_genome_yields_5xx(rast_client: httpx.Client) -> None:
    """Bogus genome ID propagates as 502 (MSSS error) rather than crashing."""
    r = rast_client.get(
        "/api/rast/genome",
        params={"genome_id": "999999.999", "job_id": "999999"},
    )
    # Expect 5xx (502 from MSSS error, possibly 504 on timeout).
    assert r.status_code >= 500, (
        f"expected 5xx for unknown genome, got {r.status_code}: {r.text[:200]}"
    )


# Obsolete test removed: test_rast_genome_rejects_patric_token.
#
# Premise: "MSSS only accepts RAST tokens; PATRIC tokens get translated as
# 401." This held when /api/rast/genome proxied to MSSS. As of the MSSS
# retirement (memory: project_msss_retirement.md, 2026), the endpoint reads
# RAST job data directly from /vol/rast-prod/jobs via RastFigvReader. Any
# valid token's username is acceptable as long as it matches the RAST job's
# owner. PATRIC tokens for jplfaria@patricbrc.org succeed against known
# RAST jobs owned by jplfaria; the auth dependency does not gatekeep the
# token type.
#
# The auth-required behavior is still covered by test_rast_genome_no_auth_returns_401
# below. Token-type-specific routing assertions belong with MSSS-era code,
# which is no longer present.


def test_rast_genome_no_auth_returns_401(target_env) -> None:
    """No Authorization header gives 401 from the auth dependency."""
    with httpx.Client(
        base_url=target_env.api_url,
        timeout=httpx.Timeout(30.0, connect=10.0),
        follow_redirects=True,
    ) as c:
        r = c.get(
            "/api/rast/genome",
            params={
                "genome_id": KNOWN_JOB["genome_id"],
                "job_id": KNOWN_JOB["job_id"],
            },
        )
    assert_status(r, 401)
