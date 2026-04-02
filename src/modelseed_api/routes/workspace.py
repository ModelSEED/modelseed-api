"""Workspace proxy routes.

Proxies all workspace operations through the API.
Frontend never talks directly to the Workspace service.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from modelseed_api.auth.dependencies import AuthUser, get_current_user
from modelseed_api.schemas.workspace import (
    WSCopyRequest,
    WSCreateRequest,
    WSDeleteRequest,
    WSDownloadUrlRequest,
    WSGetRequest,
    WSListRequest,
    WSPermissionsRequest,
    WSUpdateMetadataRequest,
)
from modelseed_api.services.storage_factory import get_storage_service
from modelseed_api.services.workspace_service import WorkspaceError

router = APIRouter()


def _get_ws(user: AuthUser):
    return get_storage_service(user.token)


def _handle_ws_error(e: WorkspaceError):
    msg = e.message.lower()
    if "permission" in msg or "not authorized" in msg or e.code == 403:
        status = 403
    elif "not found" in msg or "does not exist" in msg or e.code == 404:
        status = 404
    else:
        status = 502
    raise HTTPException(status_code=status, detail=f"Workspace error: {e.message}")


@router.post("/ls")
async def workspace_ls(
    request: WSListRequest,
    user: AuthUser = Depends(get_current_user),
) -> Any:
    """List workspace contents."""
    ws = _get_ws(user)
    try:
        return ws.ls(request.model_dump(exclude_none=True))
    except WorkspaceError as e:
        _handle_ws_error(e)


@router.post("/get")
async def workspace_get(
    request: WSGetRequest,
    user: AuthUser = Depends(get_current_user),
) -> Any:
    """Get workspace objects or metadata."""
    ws = _get_ws(user)
    try:
        params = {"objects": request.objects}
        if request.metadata_only:
            params["metadata_only"] = 1
        return ws.get(params)
    except WorkspaceError as e:
        _handle_ws_error(e)


@router.post("/create")
async def workspace_create(
    request: WSCreateRequest,
    user: AuthUser = Depends(get_current_user),
) -> Any:
    """Create workspace objects."""
    ws = _get_ws(user)
    try:
        return ws.create(request.model_dump(exclude_none=True))
    except WorkspaceError as e:
        _handle_ws_error(e)


@router.post("/copy")
async def workspace_copy(
    request: WSCopyRequest,
    user: AuthUser = Depends(get_current_user),
) -> Any:
    """Copy or move workspace objects.

    When recursive=True, uses manual copy that fetches and re-creates
    inner objects. PATRIC workspace copy doesn't reliably copy
    Shock-stored data within folders.
    """
    ws = _get_ws(user)
    try:
        if request.recursive and request.objects:
            from modelseed_api.services.model_service import ModelService
            svc = ModelService(user.token)
            results = []
            for pair in request.objects:
                if len(pair) >= 2:
                    svc.copy_model(pair[0], pair[1])
                    results.append({"copied": f"{pair[0]} -> {pair[1]}"})
            return results
        return ws.copy(request.model_dump(exclude_none=True))
    except WorkspaceError as e:
        _handle_ws_error(e)


@router.post("/delete")
async def workspace_delete(
    request: WSDeleteRequest,
    user: AuthUser = Depends(get_current_user),
) -> Any:
    """Delete workspace objects."""
    ws = _get_ws(user)
    try:
        return ws.delete(request.model_dump(exclude_none=True))
    except WorkspaceError as e:
        _handle_ws_error(e)


@router.post("/metadata")
async def workspace_update_metadata(
    request: WSUpdateMetadataRequest,
    user: AuthUser = Depends(get_current_user),
) -> Any:
    """Update workspace object metadata."""
    ws = _get_ws(user)
    try:
        return ws.update_metadata(request.model_dump(exclude_none=True))
    except WorkspaceError as e:
        _handle_ws_error(e)


@router.post("/download-url")
async def workspace_download_url(
    request: WSDownloadUrlRequest,
    user: AuthUser = Depends(get_current_user),
) -> Any:
    """Get download URLs for workspace objects."""
    ws = _get_ws(user)
    try:
        return ws.get_download_url(request.model_dump(exclude_none=True))
    except WorkspaceError as e:
        _handle_ws_error(e)


@router.post("/permissions")
async def workspace_permissions(
    request: WSPermissionsRequest,
    user: AuthUser = Depends(get_current_user),
) -> Any:
    """List permissions on workspace objects."""
    ws = _get_ws(user)
    try:
        return ws.list_permissions(request.model_dump(exclude_none=True))
    except WorkspaceError as e:
        _handle_ws_error(e)
