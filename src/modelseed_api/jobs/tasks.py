"""Celery tasks for the modelseed worker.

Each task runs on the 'modelseed' queue in the shared bioseed Redis scheduler.
Tasks use KBUtilLib/ModelSEEDpy for computation and the PATRIC workspace for
data storage. Templates are loaded from local ModelSEEDTemplates files
(bypassing KBase workspace).
"""

from __future__ import annotations

import json
import logging
import os

from modelseed_api.jobs.celery_app import app

logger = logging.getLogger(__name__)

# Template paths (v7.0 from ModelSEEDTemplates repo)
TEMPLATES_DIR = os.getenv(
    "MODELSEED_TEMPLATES_PATH",
    "/Users/jplfaria/repos/ModelSEEDTemplates/templates/v7.0",
)
MODELSEED_DB_PATH = os.getenv(
    "MODELSEED_DB_PATH",
    "/Users/jplfaria/repos/ModelSEEDDatabase",
)

# Map template type to local file
TEMPLATE_FILES = {
    "core": "Core-V6.json",
    "gp": "GramPosModelTemplateV7.json",
    "gn": "GramNegModelTemplateV7.json",
    "grampos": "GramPosModelTemplateV7.json",
    "gramneg": "GramNegModelTemplateV7.json",
}


def _load_template(template_type: str):
    """Load a template from local JSON file using MSTemplateBuilder."""
    from modelseedpy import MSTemplateBuilder

    filename = TEMPLATE_FILES.get(template_type)
    if not filename:
        raise ValueError(f"Unknown template type: {template_type}")

    path = os.path.join(TEMPLATES_DIR, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Template file not found: {path}")

    with open(path) as f:
        template_data = json.load(f)

    return MSTemplateBuilder.from_dict(template_data).build()


def _get_workspace_client(token: str):
    """Get a PATRIC workspace client."""
    from kbutillib.patric_ws_utils import PatricWSClient

    return PatricWSClient(token=token)


@app.task(bind=True, name="modelseed.reconstruct")
def reconstruct(
    self,
    token: str,
    genome_ref: str,
    template_type: str = "auto",
    atp_safe: bool = True,
    gapfill: bool = False,
    media_ref: str | None = None,
    output_path: str | None = None,
):
    """Build a metabolic model from a genome.

    Args:
        token: PATRIC auth token
        genome_ref: Workspace reference to genome (e.g., /user/genomes/12345.6)
        template_type: Template type (auto, gp, gn) — 'auto' classifies the genome
        atp_safe: Apply ATP-safe constraints
        gapfill: Run gapfilling after reconstruction
        media_ref: Media workspace reference (for gapfilling)
        output_path: Workspace path for output model
    """
    self.update_state(state="PROGRESS", meta={"status": "Starting reconstruction..."})

    from kbutillib.ms_reconstruction_utils import MSReconstructionUtils

    # Initialize reconstruction utils with PATRIC token
    recon = MSReconstructionUtils(token={"patric": token})

    # Load templates from local files
    self.update_state(state="PROGRESS", meta={"status": "Loading templates..."})
    core_template = _load_template("core")
    gs_template_obj = None
    if template_type != "auto":
        gs_template_obj = _load_template(template_type)

    # Override the KBase template paths so get_template() isn't called
    recon.templates = {k: None for k in recon.templates}

    # Fetch genome from workspace
    self.update_state(state="PROGRESS", meta={"status": "Fetching genome..."})
    ws_client = _get_workspace_client(token)
    genome_data = ws_client.get_object(genome_ref)

    # Build MSGenome from workspace genome data
    from modelseedpy import MSGenome

    genome = MSGenome.from_dict(genome_data)

    # Load genome classifier
    from modelseedpy import MSGenomeClassifier

    classifier = MSGenomeClassifier(MODELSEED_DB_PATH)

    # Build model
    self.update_state(state="PROGRESS", meta={"status": "Building model..."})
    output, mdlutl = recon.build_metabolic_model(
        genome=genome,
        genome_classifier=classifier,
        core_template=core_template,
        gs_template_obj=gs_template_obj,
        gs_template=template_type,
        atp_safe=atp_safe,
    )

    if mdlutl is None:
        return {
            "status": "skipped",
            "comments": output.get("Comments", []),
        }

    # Optionally run gapfilling
    if gapfill:
        self.update_state(state="PROGRESS", meta={"status": "Running gapfilling..."})
        from modelseedpy import MSGapfill

        gapfiller = MSGapfill(mdlutl.model)
        gapfiller.run_gapfilling(media=media_ref)

    # Save model to workspace
    self.update_state(state="PROGRESS", meta={"status": "Saving model..."})
    if output_path:
        recon.save_model(mdlutl, workspace=output_path)

    return {
        "status": "success",
        "model_id": mdlutl.wsid,
        "reactions": output.get("Reactions", 0),
        "genes": output.get("Model genes", 0),
        "classification": output.get("Class", "unknown"),
        "core_gapfilling": output.get("Core GF", "NA"),
    }


@app.task(bind=True, name="modelseed.gapfill")
def gapfill(
    self,
    token: str,
    model_ref: str,
    media_ref: str | None = None,
    template_type: str = "gn",
):
    """Run gapfilling on a model.

    Args:
        token: PATRIC auth token
        model_ref: Workspace reference to model folder
        media_ref: Media workspace reference (None = complete media)
        template_type: Template type for gapfilling
    """
    self.update_state(state="PROGRESS", meta={"status": "Loading model..."})

    # Fetch model from workspace
    ws_client = _get_workspace_client(token)
    model_data = ws_client.get_object(f"{model_ref}/model")

    # Convert to cobra model
    from modelseed_api.services.export_service import workspace_model_to_cobra

    cobra_model = workspace_model_to_cobra(model_data)

    # Load template
    self.update_state(state="PROGRESS", meta={"status": "Running gapfilling..."})
    template = _load_template(template_type)

    from modelseedpy import MSGapfill

    gapfiller = MSGapfill(cobra_model, default_target="bio1", templates=[template])
    solutions = gapfiller.run_gapfilling(media=media_ref)

    # Save gapfilled model back to workspace
    self.update_state(state="PROGRESS", meta={"status": "Saving model..."})
    # TODO: Save updated model back to workspace

    return {
        "status": "success",
        "model_ref": model_ref,
        "solutions_count": len(solutions) if solutions else 0,
    }


@app.task(bind=True, name="modelseed.fba")
def run_fba(
    self,
    token: str,
    model_ref: str,
    media_ref: str | None = None,
):
    """Run flux balance analysis on a model.

    Args:
        token: PATRIC auth token
        model_ref: Workspace reference to model folder
        media_ref: Media workspace reference (None = complete media)
    """
    self.update_state(state="PROGRESS", meta={"status": "Loading model..."})

    # Fetch model from workspace
    ws_client = _get_workspace_client(token)
    model_data = ws_client.get_object(f"{model_ref}/model")

    # Convert to cobra model
    from modelseed_api.services.export_service import workspace_model_to_cobra

    cobra_model = workspace_model_to_cobra(model_data)

    # Run FBA
    self.update_state(state="PROGRESS", meta={"status": "Running FBA..."})
    solution = cobra_model.optimize()

    # Collect flux results
    fluxes = {}
    for rxn in cobra_model.reactions:
        if abs(solution.fluxes[rxn.id]) > 1e-6:
            fluxes[rxn.id] = round(solution.fluxes[rxn.id], 6)

    return {
        "status": "success",
        "model_ref": model_ref,
        "objective_value": round(solution.objective_value, 6) if solution.objective_value else 0,
        "status_fba": solution.status,
        "nonzero_fluxes": len(fluxes),
        "fluxes": fluxes,
    }
