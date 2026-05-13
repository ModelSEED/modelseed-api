"""Biological layer: full reconstruct pipeline starting from a RAST job.

Submits a real reconstruct job using the rast_job_id input mode, polls
until completion (~6-10 min), fetches the resulting model, and runs the
full structural assertion suite (21 checks from `tests/live/assertions/bio.py`).

This is the integration test that proves the translator + endpoint +
reconstruct branch all work together against real data, end-to-end.

SLOW: this test takes 6-10 minutes per run. Marked `slow` so it's opt-in.
"""

from __future__ import annotations

import httpx
import pytest

from tests.live.assertions import bio
from tests.live.assertions.api import (
    assert_job_succeeded,
    assert_status,
    poll_job_until_done,
)

# Helicobacter pylori 26695 from jplfaria's RAST job 297911. Matches
# both the unit-test fixture and the live functional test target so all
# layers are testing the same real data.
HELICOBACTER = {"job_id": "297911", "genome_id": "85962.43"}

pytestmark = [
    pytest.mark.requires_token,
    pytest.mark.requires_modeling,
    pytest.mark.slow,
]


@pytest.fixture
def rast_client(target_env, live_rast_token) -> httpx.Client:
    """Authenticated client using the RAST token."""
    return httpx.Client(
        base_url=target_env.api_url,
        headers={"Authorization": live_rast_token},
        timeout=httpx.Timeout(180.0, connect=10.0),
        follow_redirects=True,
    )


def test_reconstruct_from_rast_job_full_pipeline(
    rast_client: httpx.Client, workspace_sandbox: str
) -> None:
    """Submit reconstruct with rast_job_id, poll, fetch model, run all
    21 structural biological assertions on the result.
    """
    output_path = f"{workspace_sandbox}helicobacter_pylori_from_rast"

    submit = rast_client.post(
        "/api/jobs/reconstruct",
        json={
            "genome": "Helicobacter pylori 26695",  # display name only
            "rast_job_id": HELICOBACTER["job_id"],
            "rast_genome_id": HELICOBACTER["genome_id"],
            "template_type": "auto",
            "atp_safe": True,
            "gapfill": False,
            "output_path": output_path,
        },
        timeout=30.0,
    )
    assert_status(submit, 200)
    job_id = submit.json()
    assert isinstance(job_id, str), f"expected job ID string, got {job_id!r}"

    record = poll_job_until_done(rast_client, job_id, timeout_s=1500)
    assert_job_succeeded(record)

    model_resp = rast_client.get(
        "/api/models/data", params={"ref": output_path}
    )
    assert_status(model_resp, 200)
    model = model_resp.json()

    # Full 21-check structural assertion suite (same as the BV-BRC path
    # gets in test_reconstruct_template_matrix.py)
    bio.assert_model_has_minimum_reactions(model, min_count=500)
    bio.assert_model_has_minimum_compounds(model)
    bio.assert_model_has_minimum_compartments(model)
    bio.assert_extracellular_compartment_present(model)
    bio.assert_cytosol_compartment_present(model)
    bio.assert_at_least_one_biomass(model)
    bio.assert_biomass_has_minimum_compounds(model)
    bio.assert_biomass_includes_essential_cofactors(model)
    bio.assert_no_orphan_reactions(model)
    bio.assert_all_reactions_have_directions(model)
    bio.assert_gpr_coverage(model)
    bio.assert_genes_referenced(model)
    bio.assert_compound_charges_are_numeric(model)
    bio.assert_no_duplicate_reaction_ids(model)
    bio.assert_no_duplicate_compound_ids(model)
    bio.assert_exchange_reactions_exist(model)
    bio.assert_extracellular_biomass_compounds_have_exchange(model)
    bio.assert_atp_maintenance_present(model)
    bio.assert_compartment_pH_set(model)

    # Soft warnings: collect but don't fail
    soft = bio.collect_warnings(
        bio.warn_orphan_compounds(model),
        bio.warn_unbalanced_reactions(model),
    )
    if soft:
        print("\n[soft warnings on RAST-built H. pylori model]:")
        for w in soft:
            print(f"  - {w}")
