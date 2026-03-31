"""FBA job script.

Runs outside the API service process.
Uses cobra to run flux balance analysis on a model fetched from the workspace.

Usage:
    python run_fba.py --job-id <id> --token <token> --params <json> --job-store-dir <dir>
"""

import argparse
import json
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
    parser = argparse.ArgumentParser(description="FBA job")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--job-store-dir", required=True)
    args = parser.parse_args()

    store_dir = Path(args.job_store_dir)
    job_file = store_dir / f"{args.job_id}.json"
    now = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d-%H:%M:%S")

    # Mark as in-progress
    update_job(job_file, {"status": "in-progress", "start_time": now()})

    params = json.loads(args.params)
    model_ref = params.get("model", "")
    media_ref = params.get("media")

    try:
        # Add project root to path for imports
        sys.path.insert(0, str(Path(__file__).parent.parent))

        # Fetch model from storage
        from modelseed_api.services.storage_factory import get_storage_service

        update_job(job_file, {"progress": "Loading model..."})
        ws = get_storage_service(args.token)

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
                    print(f"Loaded cobra_model from workspace")
        except Exception:
            pass  # cobra_model not available, fall back to workspace format

        if cobra_model is None:
            model_path = f"{model_ref}/model"
            result = ws.get({"objects": [model_path]})

            if not result or len(result) == 0:
                raise ValueError(f"Model not found: {model_ref}")

            # Parse model data (handle Shock URLs)
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

            # Use FBAModelBuilder (same as gapfill) for a working cobra model,
            # then save cobra_model for future FBA runs (lazy migration).
            import cobra.io
            from cobrakbase.core.kbasefba.fbamodel_builder import FBAModelBuilder

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
                print(f"Migrated: saved cobra_model to workspace")
            except Exception as _save_err:
                print(f"Warning: could not save cobra_model: {_save_err}")

            print(f"Loaded model via FBAModelBuilder (fallback)")

        # Run FBA
        update_job(job_file, {"progress": "Running FBA..."})
        solution = cobra_model.optimize()

        # Collect results
        fluxes = {}
        for rxn in cobra_model.reactions:
            if abs(solution.fluxes[rxn.id]) > 1e-6:
                fluxes[rxn.id] = round(solution.fluxes[rxn.id], 6)

        objective_value = round(solution.objective_value, 6) if solution.objective_value else 0

        # Determine next FBA ID (fba.0, fba.1, ...)
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
            "rundate": now(),
        }

        # Save FBA result object to workspace
        update_job(job_file, {"progress": "Saving FBA results..."})
        fba_result_obj = {
            "id": fba_id,
            "model_ref": model_ref,
            "media_ref": media_ref or "Complete",
            "objectiveValue": objective_value,
            "status": solution.status,
            "nonzero_fluxes": len(fluxes),
            "fluxes": fluxes,
            "rundate": now(),
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
        except Exception:
            pass

        result_data = {
            "status": "success",
            "model_ref": model_ref,
            "fba_id": fba_id,
            "objective_value": objective_value,
            "fba_status": solution.status,
            "nonzero_fluxes": len(fluxes),
        }

        # Mark as completed with results
        update_job(job_file, {
            "status": "completed",
            "completed_time": now(),
            "result": result_data,
        })

        print(f"FBA completed: {fba_id}, objective={objective_value}, "
              f"status={solution.status}, fluxes={len(fluxes)}")

    except Exception as e:
        update_job(job_file, {
            "status": "failed",
            "error": str(e),
            "completed_time": now(),
        })
        print(f"FBA failed: {e}", file=sys.stderr)
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
