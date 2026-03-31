"""Gapfilling job script.

Runs outside the API service process.
Uses MSGapfill to gapfill a metabolic model fetched from the workspace.

Pipeline:
  1. Fetch model from workspace (handle Shock URLs)
  2. Convert to cobra model via workspace_model_to_cobra()
  3. Load template from local ModelSEEDTemplates repo
  4. Run MSGapfill
  5. Save gapfilled model back to workspace

Usage:
    python gapfill.py --job-id <id> --token <token> --params <json> --job-store-dir <dir>
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
    parser = argparse.ArgumentParser(description="Gapfilling job")
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
    model_ref = params.get("model", "")
    template_type = params.get("template_type", "gn")
    media_ref = params.get("media")

    try:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from modelseed_api.config import settings
        from modelseed_api.services.storage_factory import get_storage_service

        # WORKAROUND: cobrakbase.KBaseAPI() requires non-empty KB_AUTH_TOKEN
        os.environ.setdefault("KB_AUTH_TOKEN", "unused")

        # Step 1: Fetch model from storage
        update_job(job_file, {"progress": "Loading model..."})
        ws = get_storage_service(args.token)
        model_path = f"{model_ref}/model"
        result = ws.get({"objects": [model_path]})

        if not result or len(result) == 0:
            raise ValueError(f"Model not found: {model_ref}")

        raw_data = result[0][1] if len(result[0]) > 1 else "{}"
        if isinstance(raw_data, str):
            if raw_data.startswith("http") and "shock" in raw_data:
                import requests
                download_url = raw_data.rstrip("/") + "?download"
                resp = requests.get(
                    download_url,
                    headers={"Authorization": f"OAuth {args.token}"},
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

        # Step 2: Load model as FBAModel (preserves workspace format for save-back)
        update_job(job_file, {"progress": "Converting model..."})
        from cobrakbase.core.kbasefba.fbamodel_builder import FBAModelBuilder
        from modelseedpy.core.msmodelutl import MSModelUtil
        fba_model = FBAModelBuilder(model_obj).build()
        mdlutl = MSModelUtil.get(fba_model)

        # Step 3: Load template
        update_job(job_file, {"progress": "Loading template..."})
        from modelseedpy import MSTemplateBuilder

        template_files = {
            "gn": "GramNegModelTemplateV7.json",
            "gp": "GramPosModelTemplateV7.json",
            "gramneg": "GramNegModelTemplateV7.json",
            "grampos": "GramPosModelTemplateV7.json",
            "core": "Core-V6.json",
        }
        gs_filename = template_files.get(template_type, "GramNegModelTemplateV7.json")
        with open(f"{settings.templates_path}/{gs_filename}") as f:
            template = MSTemplateBuilder.from_dict(json.load(f)).build()

        # Step 4: Load media if specified
        # "Complete" means all exchanges open (no media restriction) —
        # pass None to MSGapfill. Only fetch from workspace if it's a real path.
        ms_media = None
        if media_ref and media_ref.lower() != "complete" and "/" in media_ref:
            update_job(job_file, {"progress": "Loading media..."})
            from kbutillib import PatricWSUtils
            ws_utils = PatricWSUtils(
                config_file=False,
                token_file=None,
                kbase_token_file=None,
                token={"patric": args.token, "kbase": "unused"},
                modelseed_path=settings.modelseed_db_path,
                cb_annotation_ontology_api_path=settings.cb_annotation_ontology_api_path,
            )
            # Retry media loading — KBUtilLib's workspace client has no retry
            import time
            for _attempt in range(3):
                try:
                    ms_media = ws_utils.get_media(media_ref, as_msmedia=True)
                    break
                except Exception as _e:
                    if _attempt < 2 and "500" in str(_e):
                        print(f"Media load failed (attempt {_attempt + 1}/3), retrying: {_e}")
                        time.sleep(2 * (_attempt + 1))
                    else:
                        raise

        # Step 5: Run gapfilling
        update_job(job_file, {"progress": "Running gapfilling..."})
        from modelseedpy import MSGapfill
        from modelseedpy.core.msmedia import MSMedia

        # WORKAROUND: MSGapfill.test_gapfill_database() crashes with
        # "'NoneType' object has no attribute 'id'" when media=None and
        # gapfilling fails to find a solution. Pass an empty MSMedia
        # object instead of None — this is semantically identical
        # (all exchanges open) but gives the error path a .id to reference.
        if ms_media is None:
            ms_media = MSMedia("Complete", "Complete")

        gapfiller = MSGapfill(
            fba_model,
            default_target="bio1",
            default_gapfill_templates=[template],
        )
        # run_gapfilling returns a single solution dict or None
        solution = gapfiller.run_gapfilling(media=ms_media)

        solutions_count = 0
        added_reactions = []
        if solution:
            # Integrate solution into model (adds reactions, sets bounds,
            # assigns genes) and populates mdlutl.integrated_gapfillings
            gapfiller.integrate_gapfill_solution(solution)
            solutions_count = 1
            # Collect added reaction IDs from the solution
            for rxn_id in solution.get("new", {}):
                added_reactions.append(rxn_id)
            for rxn_id in solution.get("reversed", {}):
                added_reactions.append(rxn_id)

        # Step 6: Save gapfilled model back to workspace
        if solutions_count > 0:
            update_job(job_file, {"progress": "Saving gapfilled model..."})
            ws_data = fba_model.get_data()

            # Persist gapfilling solution data to model object
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

            # Update folder metadata with counts from the model object
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
            print(f"Gapfilled model saved to workspace: {model_ref}")

        result_data = {
            "status": "success",
            "model_ref": model_ref,
            "solutions_count": solutions_count,
            "added_reactions": len(added_reactions),
            "added_reaction_ids": added_reactions,
        }

        update_job(job_file, {
            "status": "completed",
            "completed_time": now(),
            "result": result_data,
        })

        print(f"Gapfilling completed: {solutions_count} solutions, "
              f"{len(added_reactions)} reactions added")

    except Exception as e:
        update_job(job_file, {
            "status": "failed",
            "error": str(e),
            "completed_time": now(),
        })
        print(f"Gapfilling failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        pass
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            _args = dict(zip(sys.argv[1::2], sys.argv[2::2]))
            _jf = Path(_args.get("--job-store-dir", "/tmp/modelseed-jobs")) / f"{_args.get('--job-id', 'unknown')}.json"
            if _jf.exists():
                update_job(_jf, {"status": "failed", "error": str(e)})
        except Exception:
            pass
