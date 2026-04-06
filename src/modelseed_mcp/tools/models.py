"""Model CRUD tools — list, get, delete, copy, export, edit.

All operations use local storage mode with a fixed local token.
"""

from modelseed_mcp.server import mcp

LOCAL_TOKEN = "local-mcp-token"
LOCAL_USER = "local"


def _get_model_service():
    from modelseed_api.services.model_service import ModelService

    return ModelService(LOCAL_TOKEN)


@mcp.tool()
def list_models() -> dict:
    """List all local ModelSEED models with summary stats.

    Returns models with ID, name, organism, reaction/gene/compound counts,
    gapfill status, and more.
    """
    svc = _get_model_service()
    models = svc.list_models(username=LOCAL_USER)
    return {"models": models, "count": len(models)}


@mcp.tool()
def get_model(model_ref: str) -> dict:
    """Get full details of a ModelSEED model.

    Args:
        model_ref: Model reference path (e.g. "/local/modelseed/MyModel")

    Returns reactions, compounds, genes, compartments, biomasses, and pathways.
    """
    svc = _get_model_service()
    try:
        return svc.get_model(model_ref)
    except (ValueError, FileNotFoundError) as e:
        return {
            "error": str(e),
            "suggestions": [
                "Use list_models to see available models",
                "Check that the model_ref path is correct",
            ],
        }


@mcp.tool()
def delete_model(model_ref: str) -> dict:
    """Delete a ModelSEED model.

    Args:
        model_ref: Model reference path (e.g. "/local/modelseed/MyModel")

    This permanently removes the model and all associated data.
    """
    svc = _get_model_service()
    try:
        svc.delete_model(model_ref)
        return {"deleted": model_ref}
    except (ValueError, FileNotFoundError) as e:
        return {"error": str(e)}


@mcp.tool()
def copy_model(source: str, destination: str) -> dict:
    """Deep-copy a ModelSEED model to a new location.

    Args:
        source: Source model reference path
        destination: Destination model reference path

    Creates a complete independent copy of the model.
    """
    svc = _get_model_service()
    try:
        return svc.copy_model(source, destination)
    except (ValueError, FileNotFoundError) as e:
        return {"error": str(e)}


@mcp.tool()
def export_model(model_ref: str, format: str = "sbml") -> dict:
    """Export a ModelSEED model to SBML or CobraPy JSON format.

    Args:
        model_ref: Model reference path
        format: Export format — "sbml" (default) or "cobra_json"/"cobrapy"

    Returns the exported model content as a string (SBML) or dict (JSON).
    """
    from modelseed_api.services.export_service import export_cobra_json, export_sbml

    svc = _get_model_service()
    try:
        model_obj = svc.get_model_raw(model_ref)
    except (ValueError, FileNotFoundError) as e:
        return {"error": str(e)}

    model_id = model_ref.rstrip("/").split("/")[-1]

    if format in ("cobra_json", "cobrapy", "json"):
        result = export_cobra_json(model_obj, model_id=model_id)
        return {"format": "cobra_json", "model": result}
    else:
        result = export_sbml(model_obj, model_id=model_id)
        return {"format": "sbml", "sbml": result}


@mcp.tool()
def edit_model(
    model_ref: str,
    reactions_to_add: list[dict] | None = None,
    reactions_to_remove: list[str] | None = None,
    reactions_to_modify: list[dict] | None = None,
    compounds_to_add: list[dict] | None = None,
    compounds_to_remove: list[str] | None = None,
    compounds_to_modify: list[dict] | None = None,
    biomass_changes: list[dict] | None = None,
    biomasses_to_add: list[dict] | None = None,
    biomasses_to_remove: list[str] | None = None,
) -> dict:
    """Edit a ModelSEED model — add, remove, or modify reactions, compounds, and biomasses.

    Args:
        model_ref: Model reference path
        reactions_to_add: List of reactions to add. Each dict: {reaction_id, compartment?, direction?, gpr?}
        reactions_to_remove: List of model reaction IDs to remove (e.g. ["rxn00001_c0"])
        reactions_to_modify: List of modifications. Each dict: {reaction_id, direction?, name?, gpr?}
        compounds_to_add: List of compounds. Each dict: {compound_id, compartment?, name?, formula?, charge?}
        compounds_to_remove: List of model compound IDs to remove
        compounds_to_modify: List of modifications. Each dict: {compound_id, name?, formula?, charge?}
        biomass_changes: Modify existing biomasses. Each dict: {biomass_id, name?, compound_changes?}
        biomasses_to_add: Add new biomasses. Each dict: {name?, compounds?}
        biomasses_to_remove: List of biomass IDs to remove

    Returns a summary of all changes made.
    """
    from modelseed_api.schemas.models import EditModelRequest

    svc = _get_model_service()

    edits = EditModelRequest(
        model=model_ref,
        reactions_to_add=reactions_to_add or [],
        reactions_to_remove=reactions_to_remove or [],
        reactions_to_modify=reactions_to_modify or [],
        compounds_to_add=compounds_to_add or [],
        compounds_to_remove=compounds_to_remove or [],
        compounds_to_modify=compounds_to_modify or [],
        biomass_changes=biomass_changes or [],
        biomasses_to_add=biomasses_to_add or [],
        biomasses_to_remove=biomasses_to_remove or [],
    )

    try:
        result = svc.edit_model(model_ref, edits)
        if hasattr(result, "model_dump"):
            return result.model_dump()
        return result
    except ValueError as e:
        return {"error": str(e)}
