"""Async job tools — build, gapfill, FBA, merge, and status checking.

Jobs are dispatched via subprocess and polled via JobStore.
"""

import time

from modelseed_mcp.server import mcp

LOCAL_TOKEN = "local-mcp-token"
LOCAL_USER = "local"


def _get_dispatcher():
    from modelseed_api.jobs.dispatcher import JobDispatcher
    from modelseed_api.jobs.store import JobStore

    store = JobStore()
    return JobDispatcher(store), store


def _poll_job(store, job_id: str, timeout: int = 600, interval: int = 3) -> dict:
    """Poll a job until completion or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        jobs = store.get_jobs(LOCAL_USER, [job_id])
        if job_id not in jobs:
            return {"error": f"Job {job_id} not found"}
        job = jobs[job_id]
        status = job.get("status", "unknown")
        if status == "completed":
            return {
                "status": "completed",
                "job_id": job_id,
                "result": job.get("result", {}),
            }
        if status == "failed":
            return {
                "status": "failed",
                "job_id": job_id,
                "error": job.get("error", "Unknown error"),
            }
        time.sleep(interval)

    return {
        "status": "timeout",
        "job_id": job_id,
        "message": f"Job did not complete within {timeout}s. Use check_job to poll later.",
    }


@mcp.tool()
def build_model(
    genome: str,
    genome_fasta: str | None = None,
    template_type: str = "auto",
    gapfill: bool = False,
    media: str | None = None,
    output_path: str | None = None,
    wait: bool = True,
    timeout: int = 600,
) -> dict:
    """Build a genome-scale metabolic model from a BV-BRC genome or protein FASTA.

    Args:
        genome: BV-BRC genome ID (e.g. "83333.1") or a name for the model when using fasta
        genome_fasta: Protein FASTA content (optional — skips BV-BRC genome lookup)
        template_type: Template type — "auto" (classify), "gn" (gram-negative),
                       "gp" (gram-positive), or "core"
        gapfill: Also gapfill the model after building (default False)
        media: Media name for gapfilling (e.g. "Complete"). Only used if gapfill=True
        output_path: Custom output path (default: /local/modelseed/{genome})
        wait: Wait for completion (default True). If False, returns job_id immediately.
        timeout: Max seconds to wait (default 600)

    Returns job status with model stats (reactions, genes, etc.) on completion.
    """
    dispatcher, store = _get_dispatcher()

    params = {
        "genome": genome,
        "template_type": template_type,
        "atp_safe": True,
        "gapfill": gapfill,
        "media": _resolve_media(media) if media else None,
        "output_path": output_path or f"/local/modelseed/{genome}",
    }
    if genome_fasta:
        params["genome_fasta"] = genome_fasta

    job_id = dispatcher.dispatch("ModelReconstruction", params, LOCAL_USER, LOCAL_TOKEN)

    if not wait:
        return {"job_id": job_id, "status": "queued", "message": "Use check_job to poll status."}

    return _poll_job(store, job_id, timeout=timeout)


@mcp.tool()
def gapfill_model(
    model: str,
    media: str | None = None,
    template_type: str = "gn",
    wait: bool = True,
    timeout: int = 600,
) -> dict:
    """Gapfill a metabolic model to enable growth on a given media.

    Args:
        model: Model reference path (e.g. "/local/modelseed/83333.1")
        media: Media name (e.g. "Complete", "Carbon-D-Glucose") or full path.
               Use list_media to see available options.
        template_type: Template type — "gn" (gram-negative) or "gp" (gram-positive)
        wait: Wait for completion (default True)
        timeout: Max seconds to wait (default 600)

    Returns gapfill results with added reaction count and IDs.
    """
    dispatcher, store = _get_dispatcher()

    params = {
        "model": model,
        "template_type": template_type,
        "media": _resolve_media(media) if media else None,
    }

    job_id = dispatcher.dispatch("GapfillModel", params, LOCAL_USER, LOCAL_TOKEN)

    if not wait:
        return {"job_id": job_id, "status": "queued"}

    return _poll_job(store, job_id, timeout=timeout)


@mcp.tool()
def run_fba(
    model: str,
    media: str | None = None,
    wait: bool = True,
    timeout: int = 600,
) -> dict:
    """Run Flux Balance Analysis on a metabolic model.

    Args:
        model: Model reference path (e.g. "/local/modelseed/83333.1")
        media: Media name (e.g. "Complete") or full path
        wait: Wait for completion (default True)
        timeout: Max seconds to wait (default 600)

    Returns objective value, flux counts, and FBA solution ID.
    """
    dispatcher, store = _get_dispatcher()

    params = {
        "model": model,
        "media": _resolve_media(media) if media else None,
    }

    job_id = dispatcher.dispatch("FluxBalanceAnalysis", params, LOCAL_USER, LOCAL_TOKEN)

    if not wait:
        return {"job_id": job_id, "status": "queued"}

    return _poll_job(store, job_id, timeout=timeout)


@mcp.tool()
def merge_models(
    models: list[dict],
    output_file: str,
    output_path: str,
    wait: bool = True,
    timeout: int = 600,
) -> dict:
    """Merge multiple metabolic models into a community model.

    Args:
        models: List of models to merge. Each dict: {model_ref: str, abundance: float}
        output_file: Name for the output model file
        output_path: Workspace path for the merged model
        wait: Wait for completion (default True)
        timeout: Max seconds to wait (default 600)
    """
    dispatcher, store = _get_dispatcher()

    model_tuples = [(m["model_ref"], m["abundance"]) for m in models]
    params = {
        "models": model_tuples,
        "output_file": output_file,
        "output_path": output_path,
    }

    job_id = dispatcher.dispatch("MergeModels", params, LOCAL_USER, LOCAL_TOKEN)

    if not wait:
        return {"job_id": job_id, "status": "queued"}

    return _poll_job(store, job_id, timeout=timeout)


@mcp.tool()
def check_job(job_id: str) -> dict:
    """Check the status of an async job.

    Args:
        job_id: The job ID returned by build_model, gapfill_model, run_fba, or merge_models

    Returns current job status, progress info, and results if completed.
    """
    from modelseed_api.jobs.store import JobStore

    store = JobStore()
    jobs = store.get_jobs(LOCAL_USER, [job_id])

    if job_id not in jobs:
        return {"error": f"Job '{job_id}' not found", "suggestions": [
            "Check the job_id is correct",
            "Jobs are stored in /tmp/modelseed-jobs/ and may be cleared on restart",
        ]}

    job = jobs[job_id]
    return {
        "job_id": job_id,
        "app": job.get("app", "unknown"),
        "status": job.get("status", "unknown"),
        "submit_time": job.get("submit_time"),
        "start_time": job.get("start_time"),
        "completed_time": job.get("completed_time"),
        "progress": job.get("progress"),
        "result": job.get("result"),
        "error": job.get("error"),
    }


def _resolve_media(media_name: str) -> str:
    """Resolve a media name to a workspace-style path.

    If already a path (starts with /), return as-is.
    Otherwise, look up in bundled media directory.
    """
    if media_name.startswith("/"):
        return media_name

    from modelseed_api.config import settings

    return f"{settings.public_media_path}/{media_name}"
