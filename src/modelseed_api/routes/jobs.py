"""Job routes - dispatch long-running operations and poll status.

The service only dispatches jobs. Actual computation runs in separate job scripts.
This is a deliberate architectural separation (per Chris Henry).
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from modelseed_api.auth.dependencies import AuthUser, get_current_user
from modelseed_api.jobs.dispatcher import JobDispatcher
from modelseed_api.jobs.store import JobStore
from modelseed_api.schemas.jobs import (
    FBARequest,
    GapfillRequest,
    ManageJobsRequest,
    MergeModelsRequest,
    ReconstructionRequest,
)

router = APIRouter()

# Singleton instances
_job_store = JobStore()
_dispatcher = JobDispatcher(_job_store)


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
    job_ids = ids.split(",") if ids else None
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
) -> str:
    """Dispatch model reconstruction to a job script.

    Returns the job ID.
    """
    job_id = _dispatcher.dispatch(
        app="ModelReconstruction",
        parameters={
            "genome": request.genome,
            "template_type": request.template_type,
            "atp_safe": request.atp_safe,
            "output_path": request.output_path,
        },
        user=user.username,
        token=user.token,
    )
    return job_id


@router.post("/gapfill")
async def gapfill_model(
    request: GapfillRequest,
    user: AuthUser = Depends(get_current_user),
) -> str:
    """Dispatch gapfilling to a job script.

    Returns the job ID.
    """
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
) -> str:
    """Dispatch FBA to a job script.

    Returns the job ID.
    """
    job_id = _dispatcher.dispatch(
        app="FluxBalanceAnalysis",
        parameters={"model": request.model, "media": request.media},
        user=user.username,
        token=user.token,
    )
    return job_id


@router.post("/merge")
async def merge_models(
    request: MergeModelsRequest,
    user: AuthUser = Depends(get_current_user),
) -> str:
    """Dispatch model merging to a job script.

    Returns the job ID.
    """
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
