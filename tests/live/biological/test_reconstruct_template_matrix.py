"""Biological layer: reconstruction across the (template_type × genome) pairwise matrix.

B01–B09 from docs/E2E_TEST_PLAN.md. Each pair submits a real reconstruct job
and runs the structural assertion library against the resulting model.

These tests are SLOW (~6–10 min per reconstruct). The full matrix is ~75 min
serial → ~25 min with `pytest-xdist -n 4`. Marked @pytest.mark.slow.

Requires:
- MODELSEED_TEST_TOKEN (PATRIC token)
- The `[modeling]` extra installed (cobra, modelseedpy) for the bio assertions
"""

from __future__ import annotations

import time

import httpx
import pytest

from tests.live.assertions import bio
from tests.live.assertions.api import (
    assert_job_succeeded,
    assert_status,
    poll_job_until_done,
)
from tests.live.fixtures.genomes import TEMPLATE_GENOME_PAIRS, ReferenceGenome

pytestmark = [
    pytest.mark.requires_token,
    pytest.mark.requires_modeling,
    pytest.mark.slow,
]


@pytest.mark.parametrize(
    "template_type,genome",
    TEMPLATE_GENOME_PAIRS,
    ids=lambda v: v.short_name if isinstance(v, ReferenceGenome) else str(v),
)
def test_reconstruct_template_genome_pairwise(
    live_client: httpx.Client,
    workspace_sandbox: str,
    template_type: str,
    genome: ReferenceGenome,
) -> None:
    """B01–B09: For each pairwise (template_type, genome), build a model and run all
    21 structural assertions against it.
    """
    output_path = f"{workspace_sandbox}{genome.short_name}_{template_type}"

    # Submit
    submit = live_client.post(
        "/api/jobs/reconstruct",
        json={
            "genome": genome.genome_id,
            "template_type": template_type,
            "atp_safe": True,
            "gapfill": False,
            "output_path": output_path,
        },
        timeout=30.0,
    )
    assert_status(submit, 200)
    job_id = submit.json()
    assert isinstance(job_id, str), f"job submission did not return a string job ID: {job_id!r}"

    # Poll
    record = poll_job_until_done(live_client, job_id, timeout_s=1500)
    assert_job_succeeded(record)

    # Fetch and validate the resulting model.
    model_resp = live_client.get("/api/models/data", params={"ref": output_path})
    assert_status(model_resp, 200)
    model = model_resp.json()

    # Run the full structural assertion suite.
    bio.assert_model_has_minimum_reactions(model, min_count=genome.expected_min_reactions)
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

    # Soft warnings — collect but don't fail
    warnings = bio.collect_warnings(
        bio.warn_orphan_compounds(model),
        bio.warn_unbalanced_reactions(model),
    )
    if warnings:
        # Surface in the test report without failing.
        print(f"\n[soft warnings for {genome.short_name}/{template_type}]:")
        for w in warnings:
            print(f"  - {w}")
