"""Biological layer: RAST vs BV-BRC parity test.

The "bidirectional confirmation" the user emphasized: build the same organism
two different ways (BV-BRC genome ID path vs RAST job ID path) and verify
that the two resulting models are biologically equivalent within tolerance.

If parity fails, the translator is dropping or mistranslating annotation
data, OR one of the upstream paths (BV-BRC API or RAST/MSSS) has drifted.

VERY SLOW: 2 reconstructs at ~6-10 min each, ~20 minutes total.
"""

from __future__ import annotations

import httpx
import pytest

from tests.live.assertions.api import (
    assert_job_succeeded,
    assert_status,
    poll_job_until_done,
)

# Same organism (H. pylori 26695), two annotation sources:
# - BV-BRC: 85962.47 (1711 CDSs, current PATRIC annotation of the same strain)
# - RAST:   job 297911 / RAST genome 85962.43 (1687 PEGs, RAST annotation)
# These are the same biological organism (Helicobacter pylori 26695) annotated
# by independent pipelines at different times. The RAST genome ID 85962.43 is
# RAST-only (not in BV-BRC); BV-BRC's most current version is 85962.47.
ORGANISM = {
    "bvbrc_id": "85962.47",
    "rast_job_id": "297911",
    "rast_genome_id": "85962.43",
    "display_name": "Helicobacter pylori 26695",
}

pytestmark = [
    pytest.mark.requires_token,
    pytest.mark.requires_modeling,
    pytest.mark.slow,
]


@pytest.fixture
def patric_client(target_env, live_token) -> httpx.Client:
    """PATRIC-token client: required for BV-BRC genome lookup."""
    return httpx.Client(
        base_url=target_env.api_url,
        headers={"Authorization": live_token},
        timeout=httpx.Timeout(180.0, connect=10.0),
        follow_redirects=True,
    )


@pytest.fixture
def rast_client(target_env, live_rast_token) -> httpx.Client:
    """RAST-token client: required for RAST genome lookup via MSSS."""
    return httpx.Client(
        base_url=target_env.api_url,
        headers={"Authorization": live_rast_token},
        timeout=httpx.Timeout(180.0, connect=10.0),
        follow_redirects=True,
    )


def _build(client: httpx.Client, body: dict, output_path: str) -> dict:
    """Submit a reconstruct job, poll, return the resulting model dict."""
    submit = client.post("/api/jobs/reconstruct", json=body, timeout=30.0)
    assert_status(submit, 200)
    record = poll_job_until_done(client, submit.json(), timeout_s=1500)
    assert_job_succeeded(record)
    r = client.get("/api/models/data", params={"ref": output_path})
    assert_status(r, 200)
    return r.json()


def _within_pct(actual: int, expected: int, pct: float) -> bool:
    """abs(actual-expected) <= pct% * expected."""
    if expected == 0:
        return actual == 0
    return abs(actual - expected) <= pct * expected / 100


def test_rast_and_bvbrc_paths_produce_equivalent_models(
    patric_client: httpx.Client,
    rast_client: httpx.Client,
    workspace_sandbox: str,
) -> None:
    """Build H. pylori from BV-BRC and from RAST; compare the models."""
    bvbrc_path = f"{workspace_sandbox}h_pylori_bvbrc"
    rast_path = f"{workspace_sandbox}h_pylori_rast"

    bvbrc_model = _build(
        patric_client,
        {
            "genome": ORGANISM["bvbrc_id"],
            "template_type": "auto",
            "atp_safe": True,
            "gapfill": False,
            "output_path": bvbrc_path,
        },
        bvbrc_path,
    )

    rast_model = _build(
        rast_client,
        {
            "genome": ORGANISM["display_name"],
            "rast_job_id": ORGANISM["rast_job_id"],
            "rast_genome_id": ORGANISM["rast_genome_id"],
            "template_type": "auto",
            "atp_safe": True,
            "gapfill": False,
            "output_path": rast_path,
        },
        rast_path,
    )

    # Reaction count parity: ~20% tolerance (different annotation versions
    # can plausibly diverge by that much; any more is a translator bug)
    n_bvbrc = len(bvbrc_model.get("reactions") or [])
    n_rast = len(rast_model.get("reactions") or [])
    assert _within_pct(n_rast, n_bvbrc, 20.0), (
        f"reaction counts diverge by >20%: bvbrc={n_bvbrc}, rast={n_rast}"
    )

    # Biomass count: must be identical (1)
    assert len(bvbrc_model.get("biomasses") or []) == len(
        rast_model.get("biomasses") or []
    ), "biomass count must match between paths"

    # GPR coverage parity: within 10pp
    def _gpr_frac(m: dict) -> float:
        rxns = m.get("reactions") or []
        if not rxns:
            return 0.0
        return sum(1 for r in rxns if (r.get("gpr") or "").strip()) / len(rxns)

    g_bvbrc = _gpr_frac(bvbrc_model)
    g_rast = _gpr_frac(rast_model)
    assert abs(g_rast - g_bvbrc) <= 0.10, (
        f"GPR coverage diverges by >10pp: bvbrc={g_bvbrc:.2%}, rast={g_rast:.2%}"
    )

    # Common reaction set: at least 50% of the smaller model's reactions
    # should also appear in the larger one.
    bvbrc_ids = {r["id"] for r in (bvbrc_model.get("reactions") or [])}
    rast_ids = {r["id"] for r in (rast_model.get("reactions") or [])}
    common = bvbrc_ids & rast_ids
    smaller = min(len(bvbrc_ids), len(rast_ids))
    if smaller:
        overlap_frac = len(common) / smaller
        assert overlap_frac >= 0.50, (
            f"common reaction set too small: {overlap_frac:.1%} of smaller model "
            f"({len(common)} of {smaller}); translator may be dropping data."
        )
