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


def merge_ws_metadata(ws, obj_path, new_meta):
    """Merge new metadata into existing workspace metadata.

    PATRIC workspace update_metadata replaces the entire user_meta dict,
    so we must read existing metadata first, merge, then write back.
    ls on a folder lists its children, so we ls the parent and find our item.
    """
    existing = {}
    try:
        obj_path = obj_path.rstrip("/")
        parent = obj_path.rsplit("/", 1)[0] + "/"
        obj_name = obj_path.rsplit("/", 1)[1]
        result = ws.ls({"paths": [parent]})
        if result:
            for items in result.values():
                for item in items:
                    if item[0] == obj_name and len(item) > 7 and isinstance(item[7], dict):
                        existing = item[7]
                        break
                if existing:
                    break
    except Exception:
        pass
    merged = {**existing, **new_meta}
    ws.update_metadata({"objects": [[obj_path, merged]]})


def main():
    parser = argparse.ArgumentParser(description="FBA job")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--job-store-dir", required=True)
    args = parser.parse_args()

    store_dir = Path(args.job_store_dir)
    job_file = store_dir / f"{args.job_id}.json"
    now = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Mark as in-progress
    update_job(job_file, {"status": "in-progress", "start_time": now()})

    # Support @filename for large params
    if args.params.startswith("@"):
        params = json.loads(Path(args.params[1:]).read_text())
    else:
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

            # WORKAROUND: FBAModelBuilder does hard key access on 'optionalSubunit'
            # which is @optional in the KBase spec — old models lack this field.
            for _rxn in model_obj.get("modelreactions", []):
                for _prot in _rxn.get("modelReactionProteins", []):
                    for _sub in _prot.get("modelReactionProteinSubunits", []):
                        _sub.setdefault("optionalSubunit", 0)

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
        else:
            # Still need model_obj for saving FBA study back to model
            model_path = f"{model_ref}/model"
            result = ws.get({"objects": [model_path]})
            if not result or len(result) == 0:
                raise ValueError(f"Model not found: {model_ref}")
            raw_data = result[0][1] if len(result[0]) > 1 else "{}"
            if isinstance(raw_data, str):
                if raw_data.startswith("http") and "shock" in raw_data:
                    import requests as _req
                    resp = _req.get(
                        raw_data.rstrip("/") + "?download",
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
            print(f"Loaded model_obj for FBA study save-back")

        # Load and apply media constraints if specified
        def _resolve_media(ref):
            if not ref or ref.lower() == "complete":
                return None
            if "/" in ref:
                return ref
            from modelseed_api.config import settings
            return f"{settings.public_media_path}/{ref}"

        ws_media_path = _resolve_media(media_ref)
        if ws_media_path:
            update_job(job_file, {"progress": "Loading media..."})
            # Load media through our storage service (not PatricWSUtils)
            # to avoid issues with the old workspace API returning empty data
            media_result = ws.get({"objects": [ws_media_path]})
            if not media_result or not media_result[0]:
                raise ValueError(f"Media not found: {ws_media_path}")
            media_raw = media_result[0][1] if len(media_result[0]) > 1 else ""
            if isinstance(media_raw, str) and media_raw.startswith("http") and "shock" in media_raw:
                import requests as _req
                resp = _req.get(
                    media_raw.rstrip("/") + "?download",
                    headers={"Authorization": f"OAuth {args.token}"},
                    timeout=60,
                )
                resp.raise_for_status()
                media_raw = resp.text
            # Parse media (TSV or JSON)
            media_compounds = []
            if isinstance(media_raw, str):
                try:
                    media_obj = json.loads(media_raw)
                    if isinstance(media_obj, dict):
                        media_compounds = media_obj.get("mediacompounds", [])
                except (json.JSONDecodeError, TypeError):
                    # TSV format: id\tname\tconcentration\tminflux\tmaxflux
                    lines = media_raw.strip().split("\n")
                    for line in lines[1:]:
                        cols = line.split("\t")
                        if len(cols) >= 5:
                            media_compounds.append({
                                "id": cols[0],
                                "maxFlux": float(cols[4]) if cols[4] else 100,
                            })
            elif isinstance(media_raw, dict):
                media_compounds = media_raw.get("mediacompounds", [])

            if media_compounds:
                rxn_ids = {r.id for r in cobra_model.reactions}
                medium = {}
                for mc in media_compounds:
                    cpd_id = mc.get("id") or mc.get("compound_ref", "").split("/")[-1]
                    exc_rxn_id = f"EX_{cpd_id}_e0"
                    if exc_rxn_id in rxn_ids:
                        medium[exc_rxn_id] = mc.get("maxFlux", 100) or 1000.0
                if medium:
                    cobra_model.medium = medium
                    print(f"Applied media: {len(medium)} exchange reactions open")
                else:
                    print(f"Warning: media had no matching exchange reactions")
            else:
                print(f"Warning: could not parse media compounds from {ws_media_path}")

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
        update_job(job_file, {"progress": "Saving FBA results..."})
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
            merge_ws_metadata(ws, model_ref, {
                "fba_count": str(fba_idx + 1),
            })
            print(f"Updated FBA metadata: fba_count={fba_idx + 1}")
        except Exception as e:
            print(f"Warning: failed to update FBA metadata: {e}")

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
