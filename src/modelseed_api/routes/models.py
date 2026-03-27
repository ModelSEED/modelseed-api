"""Model routes - CRUD, gapfill listing, FBA listing, export."""

from typing import Any, Optional
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from modelseed_api.auth.dependencies import AuthUser, get_current_user
from modelseed_api.schemas.models import (
    CopyModelRequest,
    EditModelRequest,
    EditModelResponse,
    ManageGapfillsRequest,
)
from modelseed_api.services.export_service import export_cobra_json, export_sbml
from modelseed_api.services.model_service import ModelService
from modelseed_api.services.workspace_service import WorkspaceError

router = APIRouter()


def _ws_status(e: WorkspaceError) -> int:
    msg = e.message.lower()
    if "permission" in msg or "not authorized" in msg or e.code == 403:
        return 403
    if "not found" in msg or "does not exist" in msg or e.code == 404:
        return 404
    return 502


def _get_svc(user: AuthUser) -> ModelService:
    return ModelService(user.token)


@router.get("")
async def list_models(
    path: Optional[str] = Query(None, description="Workspace path to list models from"),
    user: AuthUser = Depends(get_current_user),
) -> list[dict]:
    """List all metabolic models for the authenticated user.

    If no path is provided, defaults to /{username}/modelseed/.
    Returns ModelStats-shaped objects.
    """
    svc = _get_svc(user)
    try:
        return svc.list_models(path=path, username=user.username)
    except WorkspaceError as e:
        raise HTTPException(status_code=_ws_status(e), detail=f"Workspace error: {e.message}")


@router.get("/data")
async def get_model(
    ref: str = Query(..., description="Workspace reference to the model folder"),
    user: AuthUser = Depends(get_current_user),
) -> dict:
    """Get full model data including reactions, compounds, genes, compartments, biomasses."""
    ref = unquote(ref)
    svc = _get_svc(user)
    try:
        return svc.get_model(ref)
    except WorkspaceError as e:
        raise HTTPException(status_code=_ws_status(e), detail=f"Workspace error: {e.message}")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("")
async def delete_model(
    ref: str = Query(..., description="Workspace reference to the model to delete"),
    user: AuthUser = Depends(get_current_user),
) -> Any:
    """Delete a model from the workspace."""
    ref = unquote(ref)
    svc = _get_svc(user)
    try:
        return svc.delete_model(ref)
    except WorkspaceError as e:
        raise HTTPException(status_code=_ws_status(e), detail=f"Workspace error: {e.message}")


@router.post("/copy")
async def copy_model(
    request: CopyModelRequest,
    user: AuthUser = Depends(get_current_user),
) -> Any:
    """Copy a model to a new location in the workspace."""
    svc = _get_svc(user)
    try:
        dest = request.destination or f"/{user.username}/modelseed/{request.destname or 'copy'}"
        return svc.copy_model(request.model, dest)
    except WorkspaceError as e:
        raise HTTPException(status_code=_ws_status(e), detail=f"Workspace error: {e.message}")


@router.get("/export")
async def export_model(
    ref: str = Query(..., description="Workspace reference to the model"),
    format: str = Query("json", description="Export format: json, sbml, cobrapy"),
    user: AuthUser = Depends(get_current_user),
) -> Any:
    """Export a model in the specified format.

    Supported formats: json, sbml, cobrapy.
    """
    ref = unquote(ref)
    svc = _get_svc(user)
    format = format.lower()
    try:
        if format == "json":
            return svc.get_model(ref)
        elif format == "sbml":
            raw = svc.get_model_raw(ref)
            model_id = ref.rstrip("/").split("/")[-1]
            sbml_str = export_sbml(raw, model_id=model_id)
            return Response(
                content=sbml_str,
                media_type="application/xml",
                headers={"Content-Disposition": f'attachment; filename="{model_id}.xml"'},
            )
        elif format in ("cobra-json", "cobrapy"):
            raw = svc.get_model_raw(ref)
            model_id = ref.rstrip("/").split("/")[-1]
            return export_cobra_json(raw, model_id=model_id)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported format '{format}'. Use: json, sbml, cobra-json",
            )
    except WorkspaceError as e:
        raise HTTPException(status_code=_ws_status(e), detail=f"Workspace error: {e.message}")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/gapfills")
async def list_gapfills(
    ref: str = Query(..., description="Workspace reference to the model"),
    user: AuthUser = Depends(get_current_user),
) -> list[dict]:
    """List gapfilling solutions for a model."""
    ref = unquote(ref)
    svc = _get_svc(user)
    try:
        return svc.list_gapfill_solutions(ref)
    except WorkspaceError as e:
        raise HTTPException(status_code=_ws_status(e), detail=f"Workspace error: {e.message}")


@router.post("/gapfills/manage")
async def manage_gapfills(
    request: ManageGapfillsRequest,
    user: AuthUser = Depends(get_current_user),
) -> Any:
    """Manage gapfilling solutions (integrate/unintegrate/delete)."""
    svc = _get_svc(user)
    try:
        return svc.manage_gapfill_solutions(
            request.model, request.commands, request.selected_solutions
        )
    except WorkspaceError as e:
        raise HTTPException(status_code=_ws_status(e), detail=f"Workspace error: {e.message}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/fba")
async def list_fba_studies(
    ref: str = Query(..., description="Workspace reference to the model"),
    user: AuthUser = Depends(get_current_user),
) -> list[dict]:
    """List FBA studies associated with a model."""
    ref = unquote(ref)
    svc = _get_svc(user)
    try:
        return svc.list_fba_studies(ref)
    except WorkspaceError as e:
        raise HTTPException(status_code=_ws_status(e), detail=f"Workspace error: {e.message}")


@router.get("/edits")
async def list_model_edits(
    ref: str = Query(..., description="Workspace reference to the model"),
    user: AuthUser = Depends(get_current_user),
) -> list[dict]:
    """List edit history for a model. Currently returns empty (history not tracked)."""
    return []


@router.post("/edit", response_model=EditModelResponse)
async def edit_model(
    request: EditModelRequest,
    user: AuthUser = Depends(get_current_user),
) -> EditModelResponse:
    """Edit a model (add/remove/modify reactions, compounds, biomass).

    All edits are applied atomically -- either all succeed or none.
    """
    svc = _get_svc(user)
    try:
        return svc.edit_model(request.model, request)
    except WorkspaceError as e:
        raise HTTPException(status_code=_ws_status(e), detail=f"Workspace error: {e.message}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
