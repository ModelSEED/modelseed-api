"""Biochemistry service - compound/reaction lookup and search.

Uses ModelSEEDpy to load the ModelSEEDDatabase and provide
compound/reaction queries. Data comes from local TSV/JSON files,
not from Solr or workspace.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from modelseed_api.config import settings

logger = logging.getLogger(__name__)

_db = None


def init_db():
    """Load the ModelSEED biochemistry database. Call during app startup.

    We load directly from JSON files to avoid modelseedpy's circular import
    chain (biochem -> compound -> core -> fbapkg -> msmodelutl -> biochem).
    """
    global _db
    if _db is not None:
        return

    import json
    import os

    db_path = settings.modelseed_db_path
    biochem_dir = os.path.join(db_path, "Biochemistry")
    logger.info("Loading ModelSEED database from %s...", db_path)

    # Load compounds from compound_*.json files
    compounds = {}
    for f in sorted(os.listdir(biochem_dir)):
        if f.startswith("compound_") and f.endswith(".json"):
            with open(os.path.join(biochem_dir, f)) as fh:
                for obj in json.load(fh):
                    if obj.get("id"):
                        compounds[obj["id"]] = obj

    # Load reactions from reaction_*.json files
    reactions = {}
    for f in sorted(os.listdir(biochem_dir)):
        if f.startswith("reaction_") and f.endswith(".json"):
            with open(os.path.join(biochem_dir, f)) as fh:
                for obj in json.load(fh):
                    if obj.get("id"):
                        reactions[obj["id"]] = obj

    _db = {"compounds": compounds, "reactions": reactions}
    logger.info(
        "Loaded %d compounds, %d reactions",
        len(compounds),
        len(reactions),
    )


def _get_db():
    """Get the loaded database, initializing if needed."""
    global _db
    if _db is None:
        init_db()
    return _db


def _clean_compound(cpd: dict) -> dict[str, Any]:
    """Clean a compound dict for API response."""
    return {
        "id": cpd.get("id"),
        "name": cpd.get("name"),
        "formula": cpd.get("formula"),
        "charge": cpd.get("charge"),
        "mass": cpd.get("mass"),
        "deltag": cpd.get("deltag"),
        "abbreviation": cpd.get("abbreviation"),
        "is_obsolete": cpd.get("is_obsolete"),
        "source": cpd.get("source"),
    }


def _clean_reaction(rxn: dict) -> dict[str, Any]:
    """Clean a reaction dict for API response."""
    return {
        "id": rxn.get("id"),
        "name": rxn.get("name"),
        "abbreviation": rxn.get("abbreviation"),
        "deltag": rxn.get("deltag"),
        "direction": rxn.get("direction"),
        "reversibility": rxn.get("reversibility"),
        "status": rxn.get("status"),
        "equation": rxn.get("equation"),
        "definition": rxn.get("definition"),
        "source": rxn.get("source"),
    }


def get_compound(compound_id: str) -> Optional[dict]:
    """Get a compound by ModelSEED ID."""
    db = _get_db()
    cpd = db["compounds"].get(compound_id)
    return _clean_compound(cpd) if cpd else None


def get_reaction(reaction_id: str) -> Optional[dict]:
    """Get a reaction by ModelSEED ID."""
    db = _get_db()
    rxn = db["reactions"].get(reaction_id)
    return _clean_reaction(rxn) if rxn else None


def get_compounds(ids: list[str]) -> list[dict]:
    """Get multiple compounds by ID."""
    return [c for cid in ids if (c := get_compound(cid))]


def get_reactions(ids: list[str]) -> list[dict]:
    """Get multiple reactions by ID."""
    return [r for rid in ids if (r := get_reaction(rid))]


def search_compounds(query: str, limit: int = 50) -> list[dict]:
    """Search compounds by name or ID."""
    db = _get_db()
    query_lower = query.lower()
    results = []
    for cpd in db["compounds"].values():
        if len(results) >= limit:
            break
        name = cpd.get("name", "") or ""
        if query_lower in cpd["id"].lower() or query_lower in name.lower():
            results.append(_clean_compound(cpd))
    return results


def search_reactions(query: str, limit: int = 50) -> list[dict]:
    """Search reactions by name or ID."""
    db = _get_db()
    query_lower = query.lower()
    results = []
    for rxn in db["reactions"].values():
        if len(results) >= limit:
            break
        name = rxn.get("name", "") or ""
        if query_lower in rxn["id"].lower() or query_lower in name.lower():
            results.append(_clean_reaction(rxn))
    return results


def get_stats() -> dict:
    """Get database statistics."""
    db = _get_db()
    return {
        "database_path": settings.modelseed_db_path,
        "total_compounds": len(db["compounds"]),
        "total_reactions": len(db["reactions"]),
    }
