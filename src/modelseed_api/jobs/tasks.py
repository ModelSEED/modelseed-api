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


def _load_media(media_ref: str, token: str):
    """Load media from workspace and convert to MSMedia object.

    Retries up to 3 times on transient 500 errors since KBUtilLib's
    workspace client has no built-in retry logic.
    """
    import time
    from kbutillib import PatricWSUtils
    kwargs = _init_kwargs(token)
    ws_utils = PatricWSUtils(**kwargs)
    for attempt in range(3):
        try:
            return ws_utils.get_media(media_ref, as_msmedia=True)
        except Exception as e:
            if attempt < 2 and "500" in str(e):
                logger.warning("Media load failed (attempt %d/3), retrying: %s", attempt + 1, e)
                time.sleep(2 * (attempt + 1))
            else:
                raise


@app.task(bind=True, name="modelseed.reconstruct")
def reconstruct(
    self,
    token: str,
    genome: str = "",
    template_type: str = "gn",
    atp_safe: bool = True,
    gapfill: bool = False,
    media: str | None = None,
    output_path: str | None = None,
    # Legacy aliases
    genome_id: str = "",
    media_ref: str | None = None,
):
    """Build a metabolic model from a BV-BRC genome.

    Mirrors src/job_scripts/reconstruct.py for full parity.
    """
    # Resolve parameter aliases
    genome_id = genome or genome_id
    media_ref = media or media_ref
    if not genome_id:
        raise ValueError("genome (or genome_id) is required")
    # Strip source prefix if frontend sends "PATRIC:469009.4" or "RAST:12345"
    if ":" in genome_id:
        genome_id = genome_id.split(":", 1)[1]

    from kbutillib import BVBRCUtils, MSReconstructionUtils

    kwargs = _init_kwargs(token)

    # Step 1: Fetch genome from BV-BRC API
    self.update_state(state="PROGRESS", meta={"status": "Fetching genome..."})
    bvbrc = BVBRCUtils(**kwargs)
    kbase_genome = bvbrc.build_kbase_genome_from_api(genome_id)

    # Extract organism/taxonomy info from genome
    organism_name = kbase_genome.get("scientific_name", "")
    taxonomy = kbase_genome.get("taxonomy", "")
    domain = kbase_genome.get("domain", "")

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
        from modelseedpy.core.msmedia import MSMedia

        # Load media from workspace if specified
        # "Complete" means all exchanges open — skip workspace fetch
        ms_media = None
        if media_ref and media_ref.lower() != "complete" and "/" in media_ref:
            ms_media = _load_media(media_ref, token)

        # WORKAROUND: MSGapfill crashes on media=None in error path
        if ms_media is None:
            ms_media = MSMedia("Complete", "Complete")

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

    # Step 6: Save model to storage
    if output_path:
        self.update_state(state="PROGRESS", meta={"status": "Saving model..."})
        from modelseed_api.services.storage_factory import get_storage_service
        ws = get_storage_service(token)

        # Save cobra JSON BEFORE CobraModelConverter (which loses exchange
        # bounds and breaks FBA). cobra.io roundtrip is lossless.
        import cobra.io
        mdlutl.model.objective = "bio1"
        cobra_json = json.dumps(cobra.io.model_to_dict(mdlutl.model))

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
            "name": organism_name or genome_id,
            "source_id": genome_id,
            "source": "ModelSEED",
            "type": classification,
            "genome_ref": genome_id,
            "organism_name": organism_name,
            "taxonomy": taxonomy,
            "domain": domain,
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
                [f"{output_path}/cobra_model", "string", {}, cobra_json],
            ],
            "overwrite": 1,
        })

        try:
            ws.update_metadata({"objects": [[output_path, folder_meta]]})
            logger.info("Updated folder metadata for %s", output_path)
        except Exception as e:
            logger.warning("Failed to update folder metadata for %s: %s", output_path, e)

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
    model: str = "",
    media: str | None = None,
    template_type: str = "gn",
    # Legacy aliases (kept for in-flight tasks during deploy)
    model_ref: str = "",
    media_ref: str | None = None,
):
    """Run gapfilling on a model.

    Mirrors src/job_scripts/gapfill.py for full parity.
    """
    # Resolve parameter aliases (dispatcher sends 'model'/'media',
    # legacy callers may send 'model_ref'/'media_ref')
    model_ref = model or model_ref
    media_ref = media or media_ref
    if not model_ref:
        raise ValueError("model (or model_ref) is required")

    _init_kwargs(token)  # sets KB_AUTH_TOKEN

    self.update_state(state="PROGRESS", meta={"status": "Loading model..."})

    from modelseed_api.services.storage_factory import get_storage_service
    ws = get_storage_service(token)
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
    # "Complete" means all exchanges open (no media restriction) —
    # pass None to MSGapfill. Only fetch from workspace if it's a real path.
    ms_media = None
    if media_ref and media_ref.lower() != "complete" and "/" in media_ref:
        self.update_state(state="PROGRESS", meta={"status": "Loading media..."})
        ms_media = _load_media(media_ref, token)

    # Run gapfilling
    self.update_state(state="PROGRESS", meta={"status": "Running gapfilling..."})
    from modelseedpy import MSGapfill
    from modelseedpy.core.msmedia import MSMedia

    # WORKAROUND: MSGapfill.test_gapfill_database() crashes on media=None
    # when gapfilling fails. Pass empty MSMedia instead (semantically identical).
    if ms_media is None:
        ms_media = MSMedia("Complete", "Complete")

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

        # Save cobra JSON for FBA (workspace format loses exchange bounds)
        import cobra.io
        fba_model.objective = "bio1"
        cobra_json = json.dumps(cobra.io.model_to_dict(fba_model))

        model_data = json.dumps(ws_data)
        ws.create({
            "objects": [
                [f"{model_ref}/model", "model", {}, model_data],
                [f"{model_ref}/cobra_model", "string", {}, cobra_json],
            ],
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
            logger.info("Updated gapfill metadata for %s: %d gapfillings", model_ref, n_gapfillings)
        except Exception as e:
            logger.warning("Failed to update gapfill metadata for %s: %s", model_ref, e)

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
    model: str = "",
    media: str | None = None,
    # Legacy aliases
    model_ref: str = "",
    media_ref: str | None = None,
):
    """Run flux balance analysis on a model.

    Mirrors src/job_scripts/run_fba.py for full parity.
    """
    # Resolve parameter aliases
    model_ref = model or model_ref
    media_ref = media or media_ref
    if not model_ref:
        raise ValueError("model (or model_ref) is required")

    self.update_state(state="PROGRESS", meta={"status": "Loading model..."})

    from modelseed_api.services.storage_factory import get_storage_service

    ws = get_storage_service(token)

    # Prefer cobra_model (lossless cobra JSON) over workspace format.
    # CobraModelConverter.get_data() loses exchange bounds, making FBA
    # return 0 for all models. cobra.io roundtrip is lossless.
    cobra_model = None
    try:
        cobra_result = ws.get({"objects": [f"{model_ref}/cobra_model"]})
        if cobra_result and cobra_result[0]:
            raw = cobra_result[0][1] if len(cobra_result[0]) > 1 else None
            if raw and isinstance(raw, str) and not raw.startswith("http"):
                import cobra.io
                cobra_model = cobra.io.model_from_dict(json.loads(raw))
                cobra_model.objective = "bio1"
                logger.info("Loaded cobra_model from workspace for %s", model_ref)
    except Exception:
        pass  # cobra_model not available, fall back to workspace format

    if cobra_model is None:
        # Use FBAModelBuilder (same as gapfill) for a working cobra model,
        # then save cobra_model for future FBA runs (lazy migration).
        import cobra.io
        from cobrakbase.core.kbasefba.fbamodel_builder import FBAModelBuilder

        model_obj = _fetch_model_obj(ws, model_ref, token)
        cobra_model = FBAModelBuilder(model_obj).build()
        cobra_model.objective = "bio1"

        # Persist cobra_model so future FBA runs are fast + lossless
        try:
            cobra_json = json.dumps(cobra.io.model_to_dict(cobra_model))
            ws.create({
                "objects": [[
                    f"{model_ref}/cobra_model", "string", {}, cobra_json,
                ]],
                "overwrite": 1,
            })
            logger.info("Migrated: saved cobra_model for %s", model_ref)
        except Exception:
            logger.warning("Could not save cobra_model for %s", model_ref, exc_info=True)

        logger.info("Loaded model via FBAModelBuilder (fallback) for %s", model_ref)
    else:
        # Still need model_obj for saving FBA study back to model
        model_obj = _fetch_model_obj(ws, model_ref, token)

    # Run FBA
    self.update_state(state="PROGRESS", meta={"status": "Running FBA..."})
    solution = cobra_model.optimize()

    # Collect flux results
    fluxes = {}
    for rxn in cobra_model.reactions:
        if abs(solution.fluxes[rxn.id]) > 1e-6:
            fluxes[rxn.id] = round(solution.fluxes[rxn.id], 6)

    objective_value = round(solution.objective_value, 6) if solution.objective_value else 0

    # Determine next FBA ID (fba.0, fba.1, ...)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H:%M:%S")
    # Use whichever key the model already has (fbaFormulations for legacy models)
    fba_key = "fbaFormulations" if "fbaFormulations" in model_obj else "fba_studies"
    existing_studies = model_obj.get(fba_key, [])
    fba_idx = len(existing_studies)
    fba_id = f"fba.{fba_idx}"

    # Build FBA study record for the model object
    fba_record = {
        "id": fba_id,
        "ref": f"{model_ref}/{fba_id}",
        "media_ref": media_ref or "Complete",
        "objectiveValue": objective_value,
        "objective_function": "bio1",
        "rundate": now,
    }

    # Build KBase-compatible FBAReactionVariables / FBACompoundVariables
    # so Vibhav's frontend can parse flux data via parseReactionFluxes()
    fba_rxn_vars = []
    fba_cpd_vars = []
    for rxn in cobra_model.reactions:
        flux = solution.fluxes[rxn.id]
        fba_rxn_vars.append({
            "modelreaction_ref": f"~/modelreactions/id/{rxn.id}",
            "value": round(flux, 6),
            "lowerBound": rxn.lower_bound,
            "upperBound": rxn.upper_bound,
            "class": "Blocked" if abs(flux) < 1e-6 else ("Positive" if flux > 0 else "Negative"),
            "name": rxn.name or rxn.id,
        })
    for met in cobra_model.metabolites:
        if met.id.endswith("_e0"):
            exc_rxn_id = f"EX_{met.id}"
            if exc_rxn_id in solution.fluxes:
                flux = solution.fluxes[exc_rxn_id]
                fba_cpd_vars.append({
                    "modelcompound_ref": f"~/modelcompounds/id/{met.id}",
                    "value": round(flux, 6),
                    "lowerBound": -1000,
                    "upperBound": 1000,
                    "class": "Blocked" if abs(flux) < 1e-6 else ("Uptake" if flux < 0 else "Secretion"),
                    "name": met.name or met.id,
                })

    # Save FBA result object to workspace
    self.update_state(state="PROGRESS", meta={"status": "Saving FBA results..."})
    fba_result_obj = {
        "id": fba_id,
        "model_ref": model_ref,
        "media_ref": media_ref or "Complete",
        "objectiveValue": objective_value,
        "status": solution.status,
        "nonzero_fluxes": len(fluxes),
        "fluxes": fluxes,
        "FBAReactionVariables": fba_rxn_vars,
        "FBACompoundVariables": fba_cpd_vars,
        "rundate": now,
    }
    ws.create({
        "objects": [[
            f"{model_ref}/{fba_id}",
            "fba",
            {},
            json.dumps(fba_result_obj),
        ]],
        "overwrite": 1,
    })

    # Append FBA study to model and save back (use the same key the model uses)
    if fba_key not in model_obj:
        model_obj[fba_key] = []
    model_obj[fba_key].append(fba_record)
    ws.create({
        "objects": [[
            f"{model_ref}/model",
            "model",
            {},
            json.dumps(model_obj),
        ]],
        "overwrite": 1,
    })

    # Update folder metadata with FBA count
    try:
        ws.update_metadata({
            "objects": [[model_ref, {
                "fba_count": str(fba_idx + 1),
            }]],
        })
    except Exception as e:
        logger.warning("Failed to update fba_count metadata for %s: %s", model_ref, e)

    return {
        "status": "success",
        "model_ref": model_ref,
        "fba_id": fba_id,
        "objective_value": objective_value,
        "status_fba": solution.status,
        "nonzero_fluxes": len(fluxes),
    }
