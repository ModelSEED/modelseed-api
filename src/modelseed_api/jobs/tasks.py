"""Celery tasks for the modelseed worker.

Each task runs on the 'modelseed' queue in the shared bioseed Redis scheduler.
Tasks mirror the subprocess job scripts (src/job_scripts/) to ensure parity.
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

    # WORKAROUND: templates from local files lack .info attribute
    class _Info:
        def __init__(self, n):
            self.name = n
        def __str__(self):
            return self.name
    template.info = _Info(filename.replace(".json", ""))

    return template


def _init_kwargs(token: str) -> dict:
    """Common kwargs for KBUtilLib initialization."""
    # WORKAROUND: cobrakbase requires non-empty KB_AUTH_TOKEN
    os.environ.setdefault("KB_AUTH_TOKEN", "unused")
    return dict(
        config_file=False,
        token_file=None,
        kbase_token_file=None,
        token={"patric": token, "kbase": "unused"},
        modelseed_path=MODELSEED_DB_PATH,
        cb_annotation_ontology_api_path=CB_ANNO_ONT_PATH,
    )


def _fetch_model_obj(ws, model_ref: str, token: str) -> dict:
    """Fetch model JSON from workspace, handling Shock URLs."""
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
            return resp.json()
        return json.loads(raw_data)
    if isinstance(raw_data, dict):
        return raw_data
    return {}


def _load_media(ws, media_ref: str, token: str):
    """Load media from workspace and convert to MSMedia object."""
    from job_scripts.utils import fetch_workspace_object, workspace_media_to_msmedia
    media_obj = fetch_workspace_object(ws, media_ref, token)
    if media_obj:
        return workspace_media_to_msmedia(media_obj)
    return None


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

    Mirrors src/job_scripts/reconstruct.py for full parity.
    """
    from kbutillib import BVBRCUtils, MSReconstructionUtils
    # WORKAROUND: BVBRCUtils.save() needs KBase SDK NotebookUtils
    BVBRCUtils.save = lambda self, name, obj: None

    kwargs = _init_kwargs(token)

    # Step 1: Fetch genome from BV-BRC API
    self.update_state(state="PROGRESS", meta={"status": "Fetching genome..."})
    bvbrc = BVBRCUtils(**kwargs)
    kbase_genome = bvbrc.build_kbase_genome_from_api(genome_id)

    # Step 2: Convert to MSGenome
    self.update_state(state="PROGRESS", meta={"status": "Converting genome..."})
    recon = MSReconstructionUtils(**kwargs)
    genome = recon.get_msgenome_from_dict(kbase_genome)

    # Step 3: Load templates from local files
    self.update_state(state="PROGRESS", meta={"status": "Loading templates..."})
    core_template = _load_template("core")
    gs_template_obj = _load_template(template_type)

    # Step 4: Build model
    self.update_state(state="PROGRESS", meta={"status": "Building model..."})
    output, mdlutl = recon.build_metabolic_model(
        genome=genome,
        # WORKAROUND: classifier pickle files not available
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

    # Step 5: Gapfill if requested
    gapfill_count = 0
    if gapfill:
        self.update_state(state="PROGRESS", meta={"status": "Running gapfilling..."})
        from modelseedpy import MSGapfill

        # Load media from workspace if specified
        ms_media = None
        if media_ref:
            from modelseed_api.services.workspace_service import WorkspaceService
            ws = WorkspaceService(token)
            ms_media = _load_media(ws, media_ref, token)

        gapfiller = MSGapfill(
            mdlutl.model,
            default_target="bio1",
            default_gapfill_templates=[gs_template_obj],
        )
        solution = gapfiller.run_gapfilling(media=ms_media)
        if solution:
            gapfiller.integrate_gapfill_solution(solution)
            gapfill_count = 1

    # Compute model stats
    n_reactions = output.get("Reactions", len(mdlutl.model.reactions))
    n_genes = output.get("Model genes", len(mdlutl.model.genes))
    n_metabolites = len(mdlutl.model.metabolites)
    n_compartments = len(mdlutl.model.compartments)
    classification = output.get("Class", template_type)

    # Step 6: Save model to PATRIC workspace
    if output_path:
        self.update_state(state="PROGRESS", meta={"status": "Saving to workspace..."})
        from modelseed_api.services.workspace_service import WorkspaceService
        ws = WorkspaceService(token)

        if not hasattr(mdlutl.model, 'get_data'):
            from cobrakbase.core.kbasefba.fbamodel_from_cobra import CobraModelConverter
            mdlutl.model = CobraModelConverter(mdlutl.model).build()
        mdlutl.save_attributes()
        ws_data = mdlutl.model.get_data()

        # Persist gapfilling solution data to model object
        if gapfill_count > 0:
            mdlutl.create_kb_gapfilling_data(ws_data)

        model_data = json.dumps(ws_data)
        n_biomasses = len(ws_data.get("biomasses", []))

        folder_meta = {
            "id": genome_id,
            "name": genome_id,
            "source_id": genome_id,
            "source": "ModelSEED",
            "type": classification,
            "genome_ref": genome_id,
            "num_reactions": str(n_reactions),
            "num_compounds": str(n_metabolites),
            "num_genes": str(n_genes),
            "num_compartments": str(n_compartments),
            "num_biomasses": str(n_biomasses),
            "integrated_gapfills": str(gapfill_count),
            "unintegrated_gapfills": "0",
            "fba_count": "0",
        }

        ws.create({
            "objects": [
                [output_path, "modelfolder", folder_meta, ""],
                [f"{output_path}/model", "model", {}, model_data],
            ],
            "overwrite": 1,
        })

        try:
            ws.update_metadata({"objects": [[output_path, folder_meta]]})
        except Exception:
            pass

    return {
        "status": "success",
        "genome_id": genome_id,
        "reactions": n_reactions,
        "metabolites": n_metabolites,
        "genes": n_genes,
        "classification": classification,
        "core_gapfilling": output.get("Core GF", 0),
        "gapfilled": gapfill,
        "gapfill_solutions": gapfill_count,
        "atp_safe": atp_safe,
        "template_type": template_type,
        "reconstruction_output": output,
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

    Mirrors src/job_scripts/gapfill.py for full parity.
    """
    _init_kwargs(token)  # sets KB_AUTH_TOKEN

    self.update_state(state="PROGRESS", meta={"status": "Loading model..."})

    from modelseed_api.services.workspace_service import WorkspaceService
    ws = WorkspaceService(token)
    model_obj = _fetch_model_obj(ws, model_ref, token)

    # Load as FBAModel (preserves workspace format for save-back)
    self.update_state(state="PROGRESS", meta={"status": "Converting model..."})
    from cobrakbase.core.kbasefba.fbamodel_builder import FBAModelBuilder
    from modelseedpy.core.msmodelutl import MSModelUtil
    fba_model = FBAModelBuilder(model_obj).build()
    mdlutl = MSModelUtil.get(fba_model)

    # Load template
    self.update_state(state="PROGRESS", meta={"status": "Loading template..."})
    template = _load_template(template_type)

    # Load media if specified
    ms_media = None
    if media_ref:
        self.update_state(state="PROGRESS", meta={"status": "Loading media..."})
        ms_media = _load_media(ws, media_ref, token)

    # Run gapfilling
    self.update_state(state="PROGRESS", meta={"status": "Running gapfilling..."})
    from modelseedpy import MSGapfill
    gapfiller = MSGapfill(
        fba_model,
        default_target="bio1",
        default_gapfill_templates=[template],
    )
    solution = gapfiller.run_gapfilling(media=ms_media)

    solutions_count = 0
    added_reactions = []
    if solution:
        gapfiller.integrate_gapfill_solution(solution)
        solutions_count = 1
        for rxn_id in solution.get("new", {}):
            added_reactions.append(rxn_id)
        for rxn_id in solution.get("reversed", {}):
            added_reactions.append(rxn_id)

    # Save gapfilled model back to workspace
    if solutions_count > 0:
        self.update_state(state="PROGRESS", meta={"status": "Saving model..."})
        ws_data = fba_model.get_data()
        mdlutl.create_kb_gapfilling_data(ws_data)
        model_data = json.dumps(ws_data)

        ws.create({
            "objects": [[
                f"{model_ref}/model",
                "model",
                {},
                model_data,
            ]],
            "overwrite": 1,
        })

        n_gapfillings = len(ws_data.get("gapfillings", []))
        try:
            ws.update_metadata({
                "objects": [[model_ref, {
                    "num_reactions": str(len(fba_model.reactions)),
                    "num_compounds": str(len(fba_model.metabolites)),
                    "integrated_gapfills": str(n_gapfillings),
                }]],
            })
        except Exception:
            pass

    return {
        "status": "success",
        "model_ref": model_ref,
        "solutions_count": solutions_count,
        "added_reactions": len(added_reactions),
        "added_reaction_ids": added_reactions,
    }


@app.task(bind=True, name="modelseed.fba")
def run_fba(
    self,
    token: str,
    model_ref: str,
    media_ref: str | None = None,
):
    """Run flux balance analysis on a model.

    Mirrors src/job_scripts/run_fba.py for full parity.
    """
    self.update_state(state="PROGRESS", meta={"status": "Loading model..."})

    from modelseed_api.services.workspace_service import WorkspaceService
    from modelseed_api.services.export_service import workspace_model_to_cobra

    ws = WorkspaceService(token)
    model_obj = _fetch_model_obj(ws, model_ref, token)
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
