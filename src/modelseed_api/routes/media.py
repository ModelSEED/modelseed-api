"""Media routes - list public/user media, export."""

from typing import Any, Optional
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Query

from modelseed_api.auth.dependencies import AuthUser, get_current_user
from modelseed_api.config import settings
from modelseed_api.services.workspace_service import WorkspaceError, WorkspaceService

router = APIRouter()


def _ws_status(e: WorkspaceError) -> int:
    msg = e.message.lower()
    if "permission" in msg or "not authorized" in msg or e.code == 403:
        return 403
    if "not found" in msg or "does not exist" in msg or e.code == 404:
        return 404
    return 502


@router.get("/public")
async def list_public_media(
    user: AuthUser = Depends(get_current_user),
) -> Any:
    """List public media from the shared media path.

    Media are listed from /chenry/public/modelsupport/media.
    """
    ws = WorkspaceService(user.token)
    try:
        return ws.ls({"paths": [settings.public_media_path]})
    except WorkspaceError as e:
        raise HTTPException(status_code=_ws_status(e), detail=f"Workspace error: {e.message}")


@router.get("/mine")
async def list_my_media(
    user: AuthUser = Depends(get_current_user),
) -> Any:
    """List the authenticated user's custom media."""
    ws = WorkspaceService(user.token)
    media_path = f"/{user.username}/media"
    try:
        return ws.ls({"paths": [media_path]})
    except WorkspaceError as e:
        # User may not have a media folder yet — workspace returns 404 or
        # 403 ("permission to /") depending on path format (e.g., @ in username)
        msg = e.message.lower()
        if ("not found" in msg or "does not exist" in msg
                or "permission" in msg):
            return {media_path: []}
        raise HTTPException(status_code=_ws_status(e), detail=f"Workspace error: {e.message}")


@router.get("/export")
async def export_media(
    ref: str = Query(..., description="Workspace reference to the media"),
    user: AuthUser = Depends(get_current_user),
) -> Any:
    """Export a media condition as TSV."""
    ref = unquote(ref)
    ws = WorkspaceService(user.token)
    try:
        result = ws.get({"objects": [ref]})
        if not result or len(result) == 0:
            raise HTTPException(status_code=404, detail=f"Media not found: {ref}")
        return result
    except WorkspaceError as e:
        raise HTTPException(status_code=_ws_status(e), detail=f"Workspace error: {e.message}")
