"""RAST legacy endpoints — list annotation jobs from the RAST database."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

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
