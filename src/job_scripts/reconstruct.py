"""Model reconstruction job script.

Runs outside the API service process.
Uses KBUtilLib/ModelSEEDpy to build a metabolic model from a BV-BRC genome.

Pipeline:
  1. Fetch genome from BV-BRC API via BVBRCUtils
  2. Convert to MSGenome via KBaseObjectFactory
  3. Load templates from local ModelSEEDTemplates repo
  4. Build model via MSReconstructionUtils.build_metabolic_model()
  5. Save model to PATRIC workspace

Usage:
    python reconstruct.py --job-id <id> --token <token> --params <json> --job-store-dir <dir>
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def update_job(job_file, updates):
    """Update job JSON file with new fields."""
    if job_file.exists():
        job = json.loads(job_file.read_text())
        job.update(updates)
        job_file.write_text(json.dumps(job, indent=2))




def main():
    parser = argparse.ArgumentParser(description="Model reconstruction job")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--job-store-dir", required=True)
    args = parser.parse_args()

    store_dir = Path(args.job_store_dir)
    job_file = store_dir / f"{args.job_id}.json"
    now = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d-%H:%M:%S")

    update_job(job_file, {"status": "in-progress", "start_time": now()})

    params = json.loads(args.params)
    genome_id = params.get("genome", "")
    template_type = params.get("template_type", "gn")
    atp_safe = params.get("atp_safe", True)
    do_gapfill = params.get("gapfill", False)
    media_ref = params.get("media")
    output_path = params.get("output_path")

    try:
        # Add project root to path for imports
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from modelseed_api.config import settings

        # Set up environment for KBUtilLib
        # WORKAROUND 1/4: cobrakbase.KBaseAPI() requires non-empty KB_AUTH_TOKEN
        # even when we don't use KBase. Fix: add template_source=git to KBUtilLib.
        os.environ.setdefault("KB_AUTH_TOKEN", "unused")

        from kbutillib import BVBRCUtils, MSReconstructionUtils

        init_kwargs = dict(
            config_file=False,
            token_file=None,
            kbase_token_file=None,
            token={"patric": args.token, "kbase": "unused"},
            modelseed_path=settings.modelseed_db_path,
            cb_annotation_ontology_api_path=settings.cb_annotation_ontology_api_path,
        )

        # Step 1: Fetch genome from BV-BRC API
        update_job(job_file, {"status": "in-progress", "progress": "Fetching genome..."})
        bvbrc = BVBRCUtils(**init_kwargs)
        kbase_genome = bvbrc.build_kbase_genome_from_api(genome_id)

        # Extract organism/taxonomy info from genome before conversion
        organism_name = kbase_genome.get("scientific_name", "")
        taxonomy = kbase_genome.get("taxonomy", "")
        domain = kbase_genome.get("domain", "")

        # Step 2: Convert to MSGenome
        update_job(job_file, {"progress": "Converting genome..."})
        recon = MSReconstructionUtils(**init_kwargs)
        genome = recon.get_msgenome_from_dict(kbase_genome)

        # Step 3: Load templates from local files
        update_job(job_file, {"progress": "Loading templates..."})
        from modelseedpy import MSTemplateBuilder

        templates_dir = settings.templates_path
        with open(f"{templates_dir}/Core-V6.json") as f:
            core_template = MSTemplateBuilder.from_dict(json.load(f)).build()

        template_files = {
            "gn": "GramNegModelTemplateV7.json",
            "gp": "GramPosModelTemplateV7.json",
            "gramneg": "GramNegModelTemplateV7.json",
            "grampos": "GramPosModelTemplateV7.json",
        }
        gs_filename = template_files.get(template_type, "GramNegModelTemplateV7.json")
        with open(f"{templates_dir}/{gs_filename}") as f:
            gs_template = MSTemplateBuilder.from_dict(json.load(f)).build()

        # Step 4: Build model
        update_job(job_file, {"progress": "Building model..."})
        output, mdlutl = recon.build_metabolic_model(
            genome=genome,
            # WORKAROUND 4/4: MSGenomeClassifier needs pickle/features files
            # not available in KBUtilLib repo. Pass None + explicit template_type.
            # Fix: Chris to provide classifier data files or add them to KBUtilLib.
            genome_classifier=None,
            core_template=core_template,
            gs_template_obj=gs_template,
            gs_template=template_type,
            atp_safe=atp_safe,
        )

        if mdlutl is None:
            update_job(job_file, {
                "status": "completed",
                "completed_time": now(),
                "result": {
                    "status": "skipped",
                    "comments": output.get("Comments", []),
                },
            })
            print(f"Reconstruction skipped: {output.get('Comments')}")
            return

        # Step 5: Gapfill if requested
        gapfill_count = 0
        if do_gapfill:
            update_job(job_file, {"progress": "Loading media for gapfilling..."})

            # Load media from workspace and convert to MSMedia object
            ms_media = None
            if media_ref:
                from kbutillib import PatricWSUtils
                ws_utils = PatricWSUtils(**init_kwargs)
                ms_media = ws_utils.get_media(media_ref, as_msmedia=True)

            update_job(job_file, {"progress": "Running gapfilling..."})
            from modelseedpy import MSGapfill
            gapfiller = MSGapfill(
                mdlutl.model,
                default_target="bio1",
                default_gapfill_templates=[gs_template],
            )
            # run_gapfilling returns a single solution dict or None
            solution = gapfiller.run_gapfilling(media=ms_media)
            if solution:
                # Integrate solution into the model (adds reactions, sets bounds,
                # assigns genes) and populates mdlutl.integrated_gapfillings
                gapfiller.integrate_gapfill_solution(solution)
                gapfill_count = 1
            print(f"Gapfilling completed: {gapfill_count} solution(s)")

        # Compute model stats (use live model counts — may differ from
        # initial output if gapfilling added reactions)
        n_reactions = len(mdlutl.model.reactions)
        n_genes = len(mdlutl.model.genes)
        n_metabolites = len(mdlutl.model.metabolites)
        n_compartments = len(mdlutl.model.compartments)
        classification = output.get("Class", template_type)

        # Step 6: Save model to storage
        if output_path:
            update_job(job_file, {"progress": "Saving model..."})
            from modelseed_api.services.storage_factory import get_storage_service
            ws = get_storage_service(args.token)

            # Serialize to workspace format (modelreactions, modelcompounds, etc.)
            # mdlutl.model is an FBAModel (from cobrakbase) — get_data() returns
            # workspace-format dict with modelreactions, modelcompounds, etc.
            if not hasattr(mdlutl.model, 'get_data'):
                from cobrakbase.core.kbasefba.fbamodel_from_cobra import CobraModelConverter
                mdlutl.model = CobraModelConverter(mdlutl.model).build()
            mdlutl.save_attributes()
            ws_data = mdlutl.model.get_data()

            # Persist gapfilling solution data to model object so it's
            # available via list_gapfill_solutions() and the detail view
            if gapfill_count > 0:
                mdlutl.create_kb_gapfilling_data(ws_data)

            model_data = json.dumps(ws_data)

            n_biomasses = len(ws_data.get("biomasses", []))

            # Folder metadata so list_models picks it up
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

            # Create modelfolder + model data in one call
            ws.create({
                "objects": [
                    [output_path, "modelfolder", folder_meta, ""],
                    [f"{output_path}/model", "model", {}, model_data],
                ],
                "overwrite": 1,
            })

            # Explicitly set folder metadata (ws.create may not persist it)
            try:
                ws.update_metadata({"objects": [[output_path, folder_meta]]})
            except Exception:
                pass  # non-critical

            print(f"Model saved to workspace: {output_path}")

        result_data = {
            "status": "success",
            "genome_id": genome_id,
            "reactions": n_reactions,
            "metabolites": n_metabolites,
            "genes": n_genes,
            "classification": classification,
            "core_gapfilling": output.get("Core GF", 0),
            "gapfilled": do_gapfill,
            "gapfill_solutions": gapfill_count,
            "atp_safe": atp_safe,
            "template_type": template_type,
            "reconstruction_output": output,
        }

        update_job(job_file, {
            "status": "completed",
            "completed_time": now(),
            "result": result_data,
        })

        print(f"Reconstruction completed: {result_data['reactions']} reactions, "
              f"{result_data['genes']} genes, class={result_data['classification']}")

    except Exception as e:
        update_job(job_file, {
            "status": "failed",
            "error": str(e),
            "completed_time": now(),
        })
        print(f"Reconstruction failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    # Outer safety net: if main() raises before its own try/except
    # (e.g., arg parsing failure), still update the job file
    try:
        main()
    except SystemExit:
        pass  # main() calls sys.exit(1) on failure — already handled
    except Exception as e:
        # Last resort: try to update job file from sys.argv
        import traceback
        traceback.print_exc()
        try:
            _args = dict(zip(sys.argv[1::2], sys.argv[2::2]))
            _jf = Path(_args.get("--job-store-dir", "/tmp/modelseed-jobs")) / f"{_args.get('--job-id', 'unknown')}.json"
            if _jf.exists():
                update_job(_jf, {"status": "failed", "error": str(e)})
        except Exception:
            pass
