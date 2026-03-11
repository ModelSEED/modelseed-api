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
CB_ANNO_ONT_PATH = os.getenv(
    "CB_ANNOTATION_ONTOLOGY_API_PATH",
    "/Users/jplfaria/repos/cb_annotation_ontology_api",
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

    template = MSTemplateBuilder.from_dict(template_data).build()

    # Add mock info attribute (templates loaded from files lack this)
    class _Info:
        def __init__(self, n):
            self.name = n
        def __str__(self):
            return self.name
    template.info = _Info(filename.replace(".json", ""))

    return template


def _init_kwargs(token: str) -> dict:
    """Common kwargs for KBUtilLib initialization."""
    os.environ.setdefault("KB_AUTH_TOKEN", "unused")
    return dict(
        config_file=False,
        token_file=None,
        kbase_token_file=None,
        token={"patric": token, "kbase": "unused"},
        modelseed_path=MODELSEED_DB_PATH,
        cb_annotation_ontology_api_path=CB_ANNO_ONT_PATH,
    )


@app.task(bind=True, name="modelseed.reconstruct")
def reconstruct(
    self,
    token: str,
    genome_id: str,
    template_type: str = "gn",
    atp_safe: bool = True,
    gapfill: bool = False,
    media_ref: str | None = None,
    output_path: str | None = None,
):
    """Build a metabolic model from a BV-BRC genome.

    Args:
        token: PATRIC auth token
        genome_id: BV-BRC genome ID (e.g., 83332.12)
        template_type: Template type (gp, gn)
        atp_safe: Apply ATP-safe constraints
        gapfill: Run gapfilling after reconstruction
        media_ref: Media workspace reference (for gapfilling)
        output_path: Workspace path for output model
    """
    from kbutillib import BVBRCUtils, MSReconstructionUtils
    BVBRCUtils.save = lambda self, name, obj: None

    kwargs = _init_kwargs(token)

    # Fetch genome from BV-BRC API
    self.update_state(state="PROGRESS", meta={"status": "Fetching genome from BV-BRC..."})
    bvbrc = BVBRCUtils(**kwargs)
    kbase_genome = bvbrc.build_kbase_genome_from_api(genome_id)

    # Convert to MSGenome
    self.update_state(state="PROGRESS", meta={"status": "Converting genome..."})
    recon = MSReconstructionUtils(**kwargs)
    genome = recon.get_msgenome_from_dict(kbase_genome)

    # Load templates from local files
    self.update_state(state="PROGRESS", meta={"status": "Loading templates..."})
    core_template = _load_template("core")
    gs_template_obj = _load_template(template_type)

    # Build model
    self.update_state(state="PROGRESS", meta={"status": "Building model..."})
    output, mdlutl = recon.build_metabolic_model(
        genome=genome,
        genome_classifier=None,
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
        template = _load_template(template_type)
        gapfiller = MSGapfill(mdlutl.model, default_target="bio1", templates=[template])
        gapfiller.run_gapfilling(media=media_ref)

    # Save model to workspace
    if output_path:
        self.update_state(state="PROGRESS", meta={"status": "Saving model..."})
        # TODO: Save model to PATRIC workspace

    return {
        "status": "success",
        "genome_id": genome_id,
        "reactions": output.get("Reactions", len(mdlutl.model.reactions)),
        "genes": output.get("Model genes", len(mdlutl.model.genes)),
        "classification": output.get("Class", template_type),
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
    from modelseed_api.services.workspace_service import WorkspaceService
    from modelseed_api.services.export_service import workspace_model_to_cobra

    ws = WorkspaceService(token)
    result = ws.get({"objects": [f"{model_ref}/model"]})
    if not result:
        raise ValueError(f"Model not found: {model_ref}")

    raw_data = result[0][1] if len(result[0]) > 1 else "{}"
    if isinstance(raw_data, str):
        if raw_data.startswith("http") and "shock" in raw_data:
            import requests
            resp = requests.get(
                raw_data.rstrip("/") + "?download",
                headers={"Authorization": f"OAuth {token}"},
                timeout=60,
            )
            resp.raise_for_status()
            model_obj = resp.json()
        else:
            model_obj = json.loads(raw_data)
    elif isinstance(raw_data, dict):
        model_obj = raw_data
    else:
        model_obj = {}

    cobra_model = workspace_model_to_cobra(model_obj)

    # Load template and run gapfilling
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

    from modelseed_api.services.workspace_service import WorkspaceService
    from modelseed_api.services.export_service import workspace_model_to_cobra

    ws = WorkspaceService(token)
    result = ws.get({"objects": [f"{model_ref}/model"]})
    if not result:
        raise ValueError(f"Model not found: {model_ref}")

    raw_data = result[0][1] if len(result[0]) > 1 else "{}"
    if isinstance(raw_data, str):
        if raw_data.startswith("http") and "shock" in raw_data:
            import requests
            resp = requests.get(
                raw_data.rstrip("/") + "?download",
                headers={"Authorization": f"OAuth {token}"},
                timeout=60,
            )
            resp.raise_for_status()
            model_obj = resp.json()
        else:
            model_obj = json.loads(raw_data)
    elif isinstance(raw_data, dict):
        model_obj = raw_data
    else:
        model_obj = {}

    cobra_model = workspace_model_to_cobra(model_obj)

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
