"""Model export service - SBML and CobraPy JSON export.

Converts workspace model objects to CobraPy Model objects,
then uses cobra.io for standard format export.
"""

from __future__ import annotations

import json
import logging
import tempfile
from typing import Any

import cobra
import cobra.io

logger = logging.getLogger(__name__)


def _model_obj_to_cobra(model_obj: dict, model_id: str = "model") -> cobra.Model:
    """Convert a workspace model dict to a cobra Model via FBAModelBuilder.

    Uses cobrakbase's FBAModelBuilder which correctly handles compartments,
    stoichiometry, GPR, exchange reactions, and biomass.
    """
    from cobrakbase.core.kbasefba.fbamodel_builder import FBAModelBuilder

    # FBAModelBuilder does hard key access on 'optionalSubunit'
    # which is @optional in the KBase spec — old models lack this field.
    for rxn in model_obj.get("modelreactions", []):
        for prot in rxn.get("modelReactionProteins", []):
            for sub in prot.get("modelReactionProteinSubunits", []):
                sub.setdefault("optionalSubunit", 0)

    model = FBAModelBuilder(model_obj).build()
    model.id = model_id
    return model


def get_cobra_model(model_ref: str, ws, model_obj: dict | None = None) -> cobra.Model:
    """Get a cobra Model, preferring the saved cobra_model sub-object.

    The cobra_model sub-object (saved during reconstruction/gapfilling)
    is lossless — it preserves exchange bounds, SK_/DM_ reactions, and
    gene associations.  Falls back to FBAModelBuilder if unavailable.

    Args:
        model_ref: Workspace path to the model folder
        ws: Storage service instance
        model_obj: Pre-fetched workspace model dict (optional, avoids re-fetch)
    """
    # Try saved cobra_model first (lossless)
    try:
        result = ws.get({"objects": [f"{model_ref}/cobra_model"]})
        if result and result[0]:
            raw = result[0][1] if len(result[0]) > 1 else None
            if raw and isinstance(raw, str) and not raw.startswith("http"):
                model = cobra.io.model_from_dict(json.loads(raw))
                model.id = model_ref.rstrip("/").split("/")[-1]
                logger.debug("Loaded cobra_model from workspace for %s", model_ref)
                return model
    except Exception:
        pass

    # Fallback: build from workspace model via FBAModelBuilder
    if model_obj is None:
        result = ws.get({"objects": [f"{model_ref}/model"]})
        if not result or not result[0]:
            raise ValueError(f"Model not found: {model_ref}")
        raw = result[0][1] if len(result[0]) > 1 else "{}"
        model_obj = json.loads(raw) if isinstance(raw, str) else raw

    model_id = model_ref.rstrip("/").split("/")[-1]
    model = _model_obj_to_cobra(model_obj, model_id)
    logger.debug("Built cobra model via FBAModelBuilder for %s", model_ref)
    return model


def export_sbml(model_obj: dict, model_id: str = "model") -> str:
    """Export model as SBML XML string."""
    cobra_model = _model_obj_to_cobra(model_obj, model_id)
    with tempfile.NamedTemporaryFile(suffix=".xml", mode="w", delete=True) as f:
        cobra.io.write_sbml_model(cobra_model, f.name)
        with open(f.name) as rf:
            return rf.read()


def export_cobra_json(model_obj: dict, model_id: str = "model") -> dict:
    """Export model as CobraPy JSON dict."""
    cobra_model = _model_obj_to_cobra(model_obj, model_id)
    return cobra.io.model_to_dict(cobra_model)
