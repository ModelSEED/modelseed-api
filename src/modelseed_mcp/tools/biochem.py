"""Biochemistry tools — compound and reaction search/lookup.

No authentication required. Calls biochem_service directly.
"""

from modelseed_mcp.server import mcp


@mcp.tool()
def search_compounds(query: str, limit: int = 20) -> dict:
    """Search ModelSEED compounds by name or ID.

    Examples: search_compounds("glucose"), search_compounds("cpd00027")
    Returns matching compounds with ID, name, formula, charge.
    """
    from modelseed_api.services import biochem_service

    results = biochem_service.search_compounds(query, limit=min(limit, 200))
    return {"compounds": results, "count": len(results), "query": query}


@mcp.tool()
def search_reactions(query: str, limit: int = 20) -> dict:
    """Search ModelSEED reactions by name or ID.

    Examples: search_reactions("pyruvate kinase"), search_reactions("rxn00148")
    Returns matching reactions with ID, name, equation, direction, pathways.
    """
    from modelseed_api.services import biochem_service

    results = biochem_service.search_reactions(query, limit=min(limit, 200))
    return {"reactions": results, "count": len(results), "query": query}


@mcp.tool()
def get_compound(compound_id: str) -> dict:
    """Get a ModelSEED compound by its ID.

    Accepts a single ID (e.g. "cpd00027") or comma-separated IDs
    (e.g. "cpd00027,cpd00001,cpd00002").
    Returns compound details: ID, name, formula, charge, mass, deltag.
    """
    from modelseed_api.services import biochem_service

    ids = [cid.strip() for cid in compound_id.split(",") if cid.strip()]
    if len(ids) == 1:
        result = biochem_service.get_compound(ids[0])
        if result is None:
            return {"error": f"Compound '{ids[0]}' not found", "suggestions": [
                "Use search_compounds to find the correct ID"
            ]}
        return {"compound": result}
    results = biochem_service.get_compounds(ids)
    found_ids = {r["id"] for r in results}
    not_found = [cid for cid in ids if cid not in found_ids]
    response = {"compounds": results, "count": len(results)}
    if not_found:
        response["not_found"] = not_found
    return response


@mcp.tool()
def get_reaction(reaction_id: str) -> dict:
    """Get a ModelSEED reaction by its ID.

    Accepts a single ID (e.g. "rxn00148") or comma-separated IDs
    (e.g. "rxn00148,rxn00062").
    Returns reaction details: ID, name, equation, direction, pathways.
    """
    from modelseed_api.services import biochem_service

    ids = [rid.strip() for rid in reaction_id.split(",") if rid.strip()]
    if len(ids) == 1:
        result = biochem_service.get_reaction(ids[0])
        if result is None:
            return {"error": f"Reaction '{ids[0]}' not found", "suggestions": [
                "Use search_reactions to find the correct ID"
            ]}
        return {"reaction": result}
    results = biochem_service.get_reactions(ids)
    found_ids = {r["id"] for r in results}
    not_found = [rid for rid in ids if rid not in found_ids]
    response = {"reactions": results, "count": len(results)}
    if not_found:
        response["not_found"] = not_found
    return response
