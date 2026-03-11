"""Shared utilities for job scripts."""

import json
import sys


def fetch_workspace_object(ws, ref, token):
    """Fetch a JSON object from workspace, handling Shock URLs and TSV media."""
    result = ws.get({"objects": [ref]})
    if not result or not result[0]:
        raise ValueError(f"Empty workspace response for {ref}")

    entry = result[0]

    # Workspace get returns: [metadata_array, data_or_shock_url]
    raw = entry[1] if len(entry) > 1 else None

    if raw is None or raw == "":
        meta = entry[0] if entry else []
        if len(meta) > 9 and meta[9] and str(meta[9]).startswith("http"):
            raw = str(meta[9])
        else:
            raise ValueError(f"No data found for {ref}")

    if isinstance(raw, dict):
        return raw

    if not isinstance(raw, str):
        raise ValueError(f"Unexpected data type for {ref}: {type(raw)}")

    # Check if it's a Shock URL
    if raw.startswith("http") and "shock" in raw:
        import requests as req
        download_url = raw.rstrip("/") + "?download"
        resp = req.get(
            download_url,
            headers={"Authorization": f"OAuth {token}"},
            timeout=60,
        )
        resp.raise_for_status()
        if not resp.text.strip():
            raise ValueError(f"Shock returned empty response for {ref}")
        return resp.json()

    # Try JSON first, fall back to TSV (workspace media is stored as TSV)
    if not raw.strip():
        raise ValueError(f"Empty data string for {ref}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # TSV format: id\tname\tconcentration\tminflux\tmaxflux
        lines = raw.strip().split("\n")
        if len(lines) > 1 and "\t" in lines[0]:
            compounds = []
            for line in lines[1:]:
                cols = line.split("\t")
                if len(cols) >= 5:
                    compounds.append({
                        "compound_ref": "~/compounds/" + cols[0],
                        "name": cols[1],
                        "concentration": float(cols[2]) if cols[2] else 0.001,
                        "minFlux": float(cols[3]) if cols[3] else -100,
                        "maxFlux": float(cols[4]) if cols[4] else 100,
                    })
            meta = entry[0] if entry else []
            media_name = meta[0] if meta else ref.split("/")[-1]
            return {"id": media_name, "name": media_name, "mediacompounds": compounds}
        raise ValueError(f"Could not parse workspace data for {ref}: {raw[:200]}")


def workspace_media_to_msmedia(media_obj):
    """Convert a workspace media dict to an MSMedia object."""
    from modelseedpy.core.msmedia import MSMedia, MediaCompound
    ms_media = MSMedia(media_obj.get("id", "media"),
                       name=media_obj.get("name", "media"))
    for mc in media_obj.get("mediacompounds", []):
        cpd_id = mc.get("compound_ref", "").split("/")[-1]
        if cpd_id:
            ms_media.mediacompounds.append(
                MediaCompound(
                    cpd_id,
                    -1 * mc.get("maxFlux", 100),
                    -1 * mc.get("minFlux", -100),
                    concentration=mc.get("concentration", 0.001),
                )
            )
    return ms_media
