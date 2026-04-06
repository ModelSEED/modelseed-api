"""Media tools — list and inspect available growth media formulations.

Reads directly from bundled JSON files in data/media/public/.
"""

import json
from pathlib import Path

from modelseed_mcp.server import mcp

_MEDIA_DIR = Path(__file__).resolve().parents[3] / "data" / "media" / "public"


@mcp.tool()
def list_media() -> dict:
    """List all available growth media formulations.

    Returns media names and compound counts. Use get_media for full details.
    """
    if not _MEDIA_DIR.is_dir():
        return {"error": f"Media directory not found: {_MEDIA_DIR}", "media": []}

    media_list = []
    for f in sorted(_MEDIA_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            media_list.append({
                "name": data.get("name", f.stem),
                "file": f.name,
                "num_compounds": len(data.get("mediacompounds", [])),
            })
        except (json.JSONDecodeError, OSError):
            continue

    return {"media": media_list, "count": len(media_list)}


@mcp.tool()
def get_media(media_name: str) -> dict:
    """Get full details of a growth media formulation.

    Args:
        media_name: Media name (e.g. "Complete", "Carbon-D-Glucose").
                    Can also be the filename with or without .json extension.

    Returns the media compounds with IDs, names, concentrations, and flux bounds.
    """
    # Try exact filename match first
    candidates = [
        _MEDIA_DIR / f"{media_name}.json",
        _MEDIA_DIR / media_name,
    ]

    media_file = None
    for c in candidates:
        if c.is_file():
            media_file = c
            break

    # Case-insensitive fallback
    if media_file is None:
        lower = media_name.lower().removesuffix(".json")
        for f in _MEDIA_DIR.glob("*.json"):
            if f.stem.lower() == lower:
                media_file = f
                break

    if media_file is None:
        return {
            "error": f"Media '{media_name}' not found",
            "suggestions": ["Use list_media to see available media formulations"],
        }

    try:
        data = json.loads(media_file.read_text())
        return {
            "name": data.get("name", media_file.stem),
            "compounds": data.get("mediacompounds", []),
            "num_compounds": len(data.get("mediacompounds", [])),
        }
    except (json.JSONDecodeError, OSError) as e:
        return {"error": f"Failed to read media file: {e}"}
