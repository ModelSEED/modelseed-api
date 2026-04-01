"""Media routes - list public/user media, export."""

import json
from typing import Any, Optional
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Query

from modelseed_api.auth.dependencies import AuthUser, get_current_user, get_optional_user
from modelseed_api.config import settings
from modelseed_api.services.storage_factory import get_storage_service
from modelseed_api.services.workspace_service import WorkspaceError

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
    user: AuthUser | None = Depends(get_optional_user),
) -> Any:
    """List public media from the shared media path.

    Media are listed from /chenry/public/modelsupport/media.
    No authentication required — public media is world-readable.
    """
    token = user.token if user else ""
    ws = get_storage_service(token)
    try:
        return ws.ls({"paths": [settings.public_media_path]})
    except WorkspaceError as e:
        raise HTTPException(status_code=_ws_status(e), detail=f"Workspace error: {e.message}")


@router.get("/mine")
async def list_my_media(
    user: AuthUser = Depends(get_current_user),
) -> Any:
    """List the authenticated user's custom media."""
    ws = get_storage_service(user.token)
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
    """Export a media condition as a parsed object.

    Frontend reads: compounds[].{id, name, concentration, minFlux, maxFlux},
    isDefined, isMinimal, name, id.
    """
    ref = unquote(ref)
    ws = get_storage_service(user.token)
    try:
        result = ws.get({"objects": [ref]})
        if not result or len(result) == 0:
            raise HTTPException(status_code=404, detail=f"Media not found: {ref}")

        entry = result[0]
        metadata = entry[0] if entry else []
        raw = entry[1] if len(entry) > 1 else ""

        # Parse media data (JSON or TSV format)
        compounds = []
        if isinstance(raw, str):
            try:
                obj = json.loads(raw)
                if isinstance(obj, dict):
                    return obj  # Already a parsed media object
            except (json.JSONDecodeError, TypeError):
                pass
            # TSV format: id\tname\tconcentration\tminflux\tmaxflux
            lines = raw.strip().split("\n")
            for line in lines[1:]:
                cols = line.split("\t")
                if len(cols) >= 5:
                    compounds.append({
                        "id": cols[0],
                        "compound_id": cols[0],
                        "name": cols[1],
                        "compound_name": cols[1],
                        "concentration": float(cols[2]) if cols[2] else 0.001,
                        "minFlux": float(cols[3]) if cols[3] else -100,
                        "maxFlux": float(cols[4]) if cols[4] else 100,
                    })
        elif isinstance(raw, dict):
            return raw

        media_name = ref.rstrip("/").split("/")[-1]
        # Extract flags from workspace metadata
        meta_dict = metadata[7] if len(metadata) > 7 and isinstance(metadata[7], dict) else {}
        return {
            "id": media_name,
            "name": media_name,
            "compounds": compounds,
            "isDefined": meta_dict.get("isDefined", meta_dict.get("is_defined")),
            "isMinimal": meta_dict.get("isMinimal", meta_dict.get("is_minimal")),
        }
    except WorkspaceError as e:
        raise HTTPException(status_code=_ws_status(e), detail=f"Workspace error: {e.message}")
