"""Biological layer: FBA across (model × media) — biological correctness.

B16–B20 from docs/E2E_TEST_PLAN.md. Submits FBA jobs against pre-built
models on different media and asserts biologically reasonable outcomes:
growth on Complete media, growth on glucose-minimal for E. coli, no growth
on empty media, and an objective in the [0, 2.0] h^-1 range.

Depends on test_reconstruct_template_matrix.py having run first to populate
the workspace_sandbox with built models. If you run this layer in isolation,
the tests will skip when the prerequisite models aren't found.

These tests are SLOW (~10s per FBA, but with overhead/polling ~1–2 min each).
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
from tests.live.fixtures.genomes import ECOLI_K12_MG1655
from tests.live.fixtures.media import COMPLETE, EMPTY, GLUCOSE_MINIMAL

pytestmark = [
    pytest.mark.requires_token,
    pytest.mark.requires_modeling,
    pytest.mark.slow,
]


def _model_ref_for(workspace_sandbox: str, genome_short_name: str, template: str) -> str:
    return f"{workspace_sandbox}{genome_short_name}_{template}"


def _ensure_model_exists(client: httpx.Client, ref: str) -> None:
    """Skip the test if the prerequisite model from the reconstruct matrix hasn't been built."""
    r = client.get("/api/models/data", params={"ref": ref})
    if r.status_code == 404:
        pytest.skip(
            f"Prerequisite model {ref} not found. Run "
            "test_reconstruct_template_matrix.py first."
        )


def _run_fba_and_get_detail(
    client: httpx.Client, model_ref: str, media_ref: str | None
) -> dict:
    """Submit an FBA job, poll, and return the FBADetail dict."""
    body = {"model": model_ref}
    if media_ref:
        body["media"] = media_ref

    submit = client.post("/api/jobs/fba", json=body, timeout=30.0)
    assert_status(submit, 200)
    job_id = submit.json()
    record = poll_job_until_done(client, job_id, timeout_s=600)
    assert_job_succeeded(record)

    # Find the FBA result we just produced and fetch detail.
    fba_list_resp = client.get("/api/models/fba", params={"ref": model_ref})
    assert_status(fba_list_resp, 200)
    fba_list = fba_list_resp.json()
    if not fba_list:
        raise AssertionError(f"No FBA results found on model {model_ref} after job completed")
    # Latest entry by rundate.
    latest = max(fba_list, key=lambda f: f.get("rundate", ""))

    detail_resp = client.get(
        "/api/models/fba/data", params={"ref": model_ref, "fba_id": latest["id"]}
    )
    assert_status(detail_resp, 200)
    return detail_resp.json()


def test_fba_complete_media_grows_ecoli_auto(
    live_client: httpx.Client, workspace_sandbox: str
) -> None:
    """B16 (E. coli only): FBA on Complete media → growth above threshold."""
    model_ref = _model_ref_for(workspace_sandbox, ECOLI_K12_MG1655.short_name, "auto")
    _ensure_model_exists(live_client, model_ref)
    detail = _run_fba_and_get_detail(live_client, model_ref, COMPLETE.ref)
    bio.assert_grows_on_complete_media(detail)
    bio.assert_objective_within_range(detail)
    bio.assert_fluxes_finite(detail)


def test_fba_glucose_minimal_grows_ecoli(
    live_client: httpx.Client, workspace_sandbox: str
) -> None:
    """B17: E. coli grows on glucose-only minimal media."""
    model_ref = _model_ref_for(workspace_sandbox, ECOLI_K12_MG1655.short_name, "auto")
    _ensure_model_exists(live_client, model_ref)
    detail = _run_fba_and_get_detail(live_client, model_ref, GLUCOSE_MINIMAL.ref)
    bio.assert_growth_on_glucose_minimal(detail)
    bio.assert_objective_within_range(detail)
    bio.assert_fluxes_finite(detail)


def test_fba_empty_media_does_not_grow(
    live_client: httpx.Client, workspace_sandbox: str
) -> None:
    """B18: E. coli K-12 does not grow when no nutrients are available."""
    model_ref = _model_ref_for(workspace_sandbox, ECOLI_K12_MG1655.short_name, "auto")
    _ensure_model_exists(live_client, model_ref)
    detail = _run_fba_and_get_detail(live_client, model_ref, EMPTY.ref)
    bio.assert_no_growth_on_empty_media(detail)
