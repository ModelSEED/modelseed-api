"""Media routes - list public/user media, export."""

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from modelseed_api.auth.dependencies import AuthUser, get_current_user
from modelseed_api.config import settings
from modelseed_api.services.workspace_service import WorkspaceError, WorkspaceService

router = APIRouter()


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
        raise HTTPException(status_code=502, detail=f"Workspace error: {e.message}")


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
        # User may not have a media folder yet
        if "not found" in e.message.lower() or "does not exist" in e.message.lower():
            return {media_path: []}
        raise HTTPException(status_code=502, detail=f"Workspace error: {e.message}")


@router.get("/export")
async def export_media(
    ref: str = Query(..., description="Workspace reference to the media"),
    user: AuthUser = Depends(get_current_user),
) -> Any:
    """Export a media condition as TSV."""
    ws = WorkspaceService(user.token)
    try:
        result = ws.get({"objects": [ref]})
        if not result or len(result) == 0:
            raise HTTPException(status_code=404, detail=f"Media not found: {ref}")
        return result
    except WorkspaceError as e:
        raise HTTPException(status_code=502, detail=f"Workspace error: {e.message}")
