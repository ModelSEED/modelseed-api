"""RAST legacy endpoints: list annotation jobs and fetch annotated genomes.

Two endpoints:
- `GET /jobs`: lists the user's RAST annotation jobs (still wraps MSSS;
  filesystem-based replacement deferred to a follow-up PR).
- `GET /genome`: fetches a RAST-annotated genome directly from the
  FIGV-format filesystem at `MODELSEED_RAST_JOBS_DIR`.

Both endpoints are config-gated: production deployments set
`MODELSEED_RAST_JOBS_DIR` (and `MODELSEED_MSSS_URL`); local/standalone
users leave them empty and get a clean 503 explaining the endpoint isn't
configured for this deployment.
"""

import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from modelseed_api.auth.dependencies import AuthUser, get_current_user
from modelseed_api.config import settings

router = APIRouter()
logger = logging.getLogger("modelseed_api.routes.rast")


@router.get("/jobs")
async def list_rast_jobs(
    user: AuthUser = Depends(get_current_user),
) -> Any:
    """List the authenticated user's RAST annotation jobs.

    Reads from the persistent FIGV-on-disk index at
    `MODELSEED_RAST_INDEX_PATH` (built once at container startup).
    Username is extracted from the token's `un=` field.

    Status codes:
      200: list of job dicts
      401: missing/invalid token (handled by auth dependency)
      503: RAST integration not configured for this deployment, OR the
           job index is still being built (try again in a few minutes)
    """
    if not settings.rast_jobs_dir:
        raise HTTPException(
            status_code=503,
            detail=(
                "RAST integration not configured for this deployment "
                "(MODELSEED_RAST_JOBS_DIR is unset)"
            ),
        )

    from modelseed_api.services.rast_service import RastService

    svc = RastService()
    try:
        return svc.list_jobs(rast_token=user.token)
    except FileNotFoundError as e:
        # Index file doesn't exist yet (still building at startup, or
        # never built). Surface as 503 so clients know to retry.
        raise HTTPException(
            status_code=503,
            detail=f"RAST job index not ready yet, please retry shortly: {e}",
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/genome")
async def get_rast_genome(
    genome_id: str = Query(
        ...,
        description="The RAST genome ID inside the job (e.g. '85962.43').",
        min_length=1,
    ),
    job_id: str | None = Query(
        default=None,
        description=(
            "Optional RAST job ID for traceability. If omitted, derived "
            "from the RAST response's `source` field."
        ),
    ),
    user: AuthUser = Depends(get_current_user),
) -> Any:
    """Fetch a RAST-annotated genome and return it as a KBase Genome dict.

    Reads the RAST job's annotation files directly from the
    FIGV-format filesystem at `MODELSEED_RAST_JOBS_DIR`, then translates
    the result into the KBase Genome shape that our reconstruction
    pipeline expects (mirrors what BV-BRC genome lookup produces; see
    `BVBRCUtils.build_kbase_genome_from_api()`).

    Auth: any valid RAST or PATRIC token works (we no longer call MSSS
    so the "RAST tokens only" restriction is gone). The token is still
    used by the auth dependency for identification, even though file
    access is gated by the operating-system-level NFS mount permissions
    (read-only at the kernel + bind level).

    Status codes:
      200: KBase Genome dict
      401: missing/invalid token (handled by auth dependency)
      404: job_id or genome_id not found on disk
      503: MODELSEED_RAST_JOBS_DIR not configured for this deployment
    """
    if job_id is None:
        raise HTTPException(
            status_code=400,
            detail="job_id query parameter is required (filesystem reader needs it)",
        )
    if not settings.rast_jobs_dir or not os.path.isdir(settings.rast_jobs_dir):
        raise HTTPException(
            status_code=503,
            detail=(
                "RAST integration not configured for this deployment "
                "(MODELSEED_RAST_JOBS_DIR is unset or path does not exist)"
            ),
        )

    from modelseed_api.services.rast_service import RastService

    svc = RastService()
    try:
        return svc.get_genome(
            rast_token=user.token,
            genome_id=genome_id,
            job_id=job_id,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=502, detail=f"RAST translator error: {e}")
