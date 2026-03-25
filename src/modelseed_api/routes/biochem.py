"""Biochemistry routes - reactions, compounds, search.

Replaces the ms_fba support service for biochemistry queries.
Data comes from ModelSEEDDatabase (local files) via ModelSEEDpy.
"""

from fastapi import APIRouter, HTTPException, Query
from modelseed_api.services import biochem_service

router = APIRouter()


@router.get("/stats")
async def get_stats() -> dict:
    """Get biochemistry database statistics (no auth required)."""
    return biochem_service.get_stats()


@router.get("/reactions")
async def get_reactions(
    ids: str = Query(..., description="Comma-separated reaction IDs (e.g. rxn00001,rxn00002)"),
) -> list[dict]:
    """Get details for specific reactions by ID."""
    id_list = [i.strip() for i in ids.split(",") if i.strip()]
    if not id_list:
        raise HTTPException(status_code=400, detail="No IDs provided")
    return biochem_service.get_reactions(id_list)


@router.get("/compounds")
async def get_compounds(
    ids: str = Query(..., description="Comma-separated compound IDs (e.g. cpd00001,cpd00002)"),
) -> list[dict]:
    """Get details for specific compounds by ID."""
    id_list = [i.strip() for i in ids.split(",") if i.strip()]
    if not id_list:
        raise HTTPException(status_code=400, detail="No IDs provided")
    return biochem_service.get_compounds(id_list)


@router.get("/search")
async def search_biochem(
    query: str = Query(..., description="Search term (name or ID)"),
    type: str = Query("compounds", description="Type to search: 'compounds' or 'reactions'"),
    limit: int = Query(50, description="Max results", le=200),
) -> list[dict]:
    """Search compounds or reactions by name or ID."""
    if type == "compounds":
        return biochem_service.search_compounds(query, limit=limit)
    elif type == "reactions":
        return biochem_service.search_reactions(query, limit=limit)
    else:
        raise HTTPException(status_code=400, detail="type must be 'compounds' or 'reactions'")


