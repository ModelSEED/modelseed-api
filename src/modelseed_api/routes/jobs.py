"""Job routes - dispatch long-running operations and poll status.

The service only dispatches jobs. Actual computation runs in separate job scripts.
This is a deliberate architectural separation (per Chris Henry).
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from modelseed_api.auth.dependencies import AuthUser, get_current_user
from modelseed_api.jobs.dispatcher import JobDispatcher
from modelseed_api.jobs.store import JobStore
from modelseed_api.schemas.errors import StructuredValidationError
from modelseed_api.schemas.jobs import (
    BulkReconstructionRequest,
    FBARequest,
    GapfillRequest,
    ManageJobsRequest,
    MergeModelsRequest,
    ReconstructionRequest,
)
from modelseed_api.services.preflight import (
    validate_genome_exists,
    validate_media_exists,
    validate_model_exists,
)

router = APIRouter()

# Singleton instances
_job_store = JobStore()
_dispatcher = JobDispatcher(_job_store)


def _run_preflight(check_fn, *args) -> None:
    """Run a preflight validator and re-raise StructuredValidationError as
    HTTPException with the structured error body. Any other exception is
    swallowed and logged (preflight is best-effort; don't block on infra
    flakes during a submit).
    """
    import logging
    log = logging.getLogger(__name__)
    try:
        check_fn(*args)
    except StructuredValidationError as ve:
        raise HTTPException(
            status_code=ve.status_code,
            detail=ve.error.model_dump(),
        ) from ve
    except Exception as exc:
        log.warning("preflight %s raised non-validation error, skipping: %s",
                    check_fn.__name__, exc)


@router.get("")
async def check_jobs(
    ids: Optional[str] = Query(None, description="Comma-separated job IDs to filter"),
    include_completed: bool = Query(True),
    include_failed: bool = Query(True),
    include_running: bool = Query(True),
    include_queued: bool = Query(True),
    user: AuthUser = Depends(get_current_user),
) -> dict[str, dict]:
    """Check status of jobs.

    Returns a mapping of job_id -> Task for the authenticated user.
    Frontend polls this every 4 seconds.
    """
    job_ids = [x.strip() for x in ids.split(",") if x.strip()] if ids else None
    jobs = _job_store.get_jobs(user.username, job_ids=job_ids)

    # Filter by status
    filtered = {}
    for job_id, job in jobs.items():
        status = job.get("status", "")
        if status == "completed" and not include_completed:
            continue
        if status == "failed" and not include_failed:
            continue
        if status == "in-progress" and not include_running:
            continue
        if status == "queued" and not include_queued:
            continue
        filtered[job_id] = job

    return filtered


@router.post("/reconstruct")
async def reconstruct_model(
    request: ReconstructionRequest,
    user: AuthUser = Depends(get_current_user),
    skip_validation: bool = Query(
        default=False,
        description=(
            "Skip pre-flight validation against BV-BRC / workspace. Use only "
            "when upstream is known-slow and you want to fire-and-forget."
        ),
    ),
) -> str:
    """Dispatch model reconstruction to a job script.

    Pre-flight: validates the genome exists in BV-BRC (skipped when
    genome_fasta or rast_job_id is set, since those bypass BV-BRC) and
    the media exists in workspace (when gapfill is requested with a
    workspace media ref). Synchronous 4xx is returned for catchable
    user errors instead of dispatching a doomed job.

    Returns the job ID.
    """
    if not skip_validation:
        if not request.genome_fasta and not request.rast_job_id:
            _run_preflight(validate_genome_exists, request.genome, user.token)
        if request.gapfill and request.media:
            _run_preflight(validate_media_exists, request.media, user.token)

    params = {
        "genome": request.genome,
        "template_type": request.template_type,
        "atp_safe": request.atp_safe,
        "gapfill": request.gapfill,
        "media": request.media,
        "output_path": request.output_path,
    }
    if request.genome_fasta:
        params["genome_fasta"] = request.genome_fasta
    if request.rast_job_id:
        params["rast_job_id"] = request.rast_job_id
        params["rast_genome_id"] = request.rast_genome_id
    job_id = _dispatcher.dispatch(
        app="ModelReconstruction",
        parameters=params,
        user=user.username,
        token=user.token,
    )
    return job_id


@router.post("/gapfill")
async def gapfill_model(
    request: GapfillRequest,
    user: AuthUser = Depends(get_current_user),
    skip_validation: bool = Query(default=False),
) -> str:
    """Dispatch gapfilling to a job script.

    Pre-flight: validates model exists in workspace; validates media
    (if provided as a workspace path).

    Returns the job ID.
    """
    if not skip_validation:
        _run_preflight(validate_model_exists, request.model, user.token)
        if request.media:
            _run_preflight(validate_media_exists, request.media, user.token)

    job_id = _dispatcher.dispatch(
        app="GapfillModel",
        parameters={
            "model": request.model,
            "template_type": request.template_type,
            "media": request.media,
        },
        user=user.username,
        token=user.token,
    )
    return job_id


@router.post("/fba")
async def run_fba(
    request: FBARequest,
    user: AuthUser = Depends(get_current_user),
    skip_validation: bool = Query(default=False),
) -> str:
    """Dispatch FBA to a job script.

    Pre-flight: validates model exists in workspace; validates media
    (if provided as a workspace path).

    Returns the job ID.
    """
    if not skip_validation:
        _run_preflight(validate_model_exists, request.model, user.token)
        if request.media:
            _run_preflight(validate_media_exists, request.media, user.token)

    job_id = _dispatcher.dispatch(
        app="FluxBalanceAnalysis",
        parameters={"model": request.model, "media": request.media},
        user=user.username,
        token=user.token,
    )
    return job_id


@router.post("/bulk_reconstruct")
async def bulk_reconstruct_model(
    request: BulkReconstructionRequest,
    user: AuthUser = Depends(get_current_user),
    skip_validation: bool = Query(default=False),
) -> str:
    """Dispatch a bulk-reconstruction job.

    Submit N genomes (max 100) with probabilistic ontology annotations.
    The worker builds one COBRApy model per genome plus combined
    reactions.csv and genes.csv at the output path. See
    docs/BULK_RECONSTRUCT.md for the full contract.

    Pre-flight: validates gapfill_media exists in workspace (when
    gapfill=true with a workspace media ref). Per-genome validation
    happens inside the worker loop; one bad genome surfaces as a
    failed entry in result.per_genome without aborting the batch.
    """
    if not skip_validation:
        if request.gapfill and request.gapfill_media:
            _run_preflight(validate_media_exists, request.gapfill_media, user.token)

    params = {
        "genomes": [g.model_dump() for g in request.genomes],
        "template_type": request.template_type,
        "atp_safe": request.atp_safe,
        "gapfill": request.gapfill,
        "gapfill_media": request.gapfill_media,
        "fva": request.fva,
        "output_path": request.output_path,
    }
    job_id = _dispatcher.dispatch(
        app="BulkModelReconstruction",
        parameters=params,
        user=user.username,
        token=user.token,
    )
    return job_id


@router.post("/merge")
async def merge_models(
    request: MergeModelsRequest,
    user: AuthUser = Depends(get_current_user),
    skip_validation: bool = Query(default=False),
) -> str:
    """Dispatch model merging to a job script.

    Pre-flight: each input model must exist in workspace.

    Returns the job ID.
    """
    if not skip_validation:
        for model_ref, _abundance in request.models:
            _run_preflight(validate_model_exists, model_ref, user.token)

    job_id = _dispatcher.dispatch(
        app="MergeModels",
        parameters=request.model_dump(),
        user=user.username,
        token=user.token,
    )
    return job_id


@router.post("/manage")
async def manage_jobs(
    request: ManageJobsRequest,
    user: AuthUser = Depends(get_current_user),
) -> dict[str, dict]:
    """Manage jobs (cancel/delete/rerun)."""
    results = {}
    for job_id in request.jobs:
        if request.action == "d":
            _job_store.delete_job(job_id, user.username)
            results[job_id] = {"status": "deleted"}
        elif request.action == "r":
            # TODO: Implement rerun
            results[job_id] = {"status": "rerun not yet implemented"}
    return results
