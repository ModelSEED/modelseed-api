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

    try:
        # Add project root to path for imports
        sys.path.insert(0, str(Path(__file__).parent.parent))

        # Fetch model from workspace
        from modelseed_api.services.workspace_service import WorkspaceService
        from modelseed_api.services.export_service import workspace_model_to_cobra

        ws = WorkspaceService(args.token)
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

        # Convert to cobra model
        cobra_model = workspace_model_to_cobra(model_obj)

        # Run FBA
        solution = cobra_model.optimize()

        # Collect results
        fluxes = {}
        for rxn in cobra_model.reactions:
            if abs(solution.fluxes[rxn.id]) > 1e-6:
                fluxes[rxn.id] = round(solution.fluxes[rxn.id], 6)

        result_data = {
            "objective_value": round(solution.objective_value, 6) if solution.objective_value else 0,
            "status": solution.status,
            "nonzero_fluxes": len(fluxes),
        }

        # Mark as completed with results
        update_job(job_file, {
            "status": "completed",
            "completed_time": now(),
            "result": result_data,
        })

        print(f"FBA completed: objective={result_data['objective_value']}, "
              f"status={result_data['status']}, fluxes={result_data['nonzero_fluxes']}")

    except Exception as e:
        update_job(job_file, {
            "status": "failed",
            "error": str(e),
            "completed_time": now(),
        })
        print(f"FBA failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
