"""RAST legacy endpoints: list annotation jobs and fetch annotated genomes."""

import logging
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
    """List the authenticated user's legacy RAST annotation jobs.

    Queries the RastProdJobCache MySQL database.
    Returns 503 if the RAST database is not configured.
    """
    if not settings.rast_db_host:
        raise HTTPException(
            status_code=503,
            detail="RAST database not configured (set MODELSEED_RAST_DB_HOST)",
        )

    from modelseed_api.services.rast_service import RastService

    try:
        svc = RastService()
        return svc.list_jobs(user.username)
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="pymysql not installed (pip install pymysql)",
        )
    except Exception as e:
        logger.error("RAST database error: %s", e)
        raise HTTPException(status_code=502, detail=f"RAST database error: {e}")


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

    Calls MSSeedSupportServer's `getRastGenomeData` over JSON-RPC, then
    translates the response into the KBase Genome shape that our
    reconstruction pipeline expects (mirrors what BV-BRC genome lookup
    produces; see `BVBRCUtils.build_kbase_genome_from_api()`).

    Auth: only RAST tokens are accepted by MSSS. PATRIC tokens fail
    upstream with "Username not found"; this endpoint forwards that
    failure as a 502.

    Status codes:
      200: KBase Genome dict
      401: missing/invalid token (handled by auth dependency)
      502: MSSS reachable but returned an error
      503: MODELSEED_MSSS_URL not configured
    """
    if not settings.modelseed_msss_url:
        raise HTTPException(
            status_code=503,
            detail="MSSS URL not configured (set MODELSEED_MSSS_URL)",
        )

    from modelseed_api.services.rast_service import RastService

    svc = RastService()
    try:
        return svc.get_genome(
            rast_token=user.token,
            genome_id=genome_id,
            job_id=job_id,
        )
    except ValueError as e:
        # Translator-level errors (malformed RAST response, missing genome id)
        raise HTTPException(status_code=502, detail=f"RAST translator error: {e}")
    except RuntimeError as e:
        msg = str(e)
        # "Username not found" is MSSS rejecting a non-RAST token
        if "Username not found" in msg:
            raise HTTPException(
                status_code=401,
                detail=(
                    "MSSS rejected token (use a RAST token, not a PATRIC token, "
                    "for /api/rast/genome)"
                ),
            )
        logger.error("MSSS getRastGenomeData failed: %s", msg)
        raise HTTPException(status_code=502, detail=f"MSSS error: {msg[:300]}")
