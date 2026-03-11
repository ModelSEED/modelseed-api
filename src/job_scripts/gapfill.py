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
        from modelseed_api.services.workspace_service import WorkspaceService
        from modelseed_api.services.export_service import workspace_model_to_cobra

        # Step 1: Fetch model from workspace
        update_job(job_file, {"progress": "Loading model..."})
        ws = WorkspaceService(args.token)
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

        # Step 2: Convert to cobra model
        update_job(job_file, {"progress": "Converting model..."})
        cobra_model = workspace_model_to_cobra(model_obj)

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
        ms_media = None
        if media_ref:
            update_job(job_file, {"progress": "Loading media..."})
            from job_scripts.utils import fetch_workspace_object, workspace_media_to_msmedia
            media_obj = fetch_workspace_object(ws, media_ref, args.token)
            if media_obj:
                ms_media = workspace_media_to_msmedia(media_obj)

        # Step 5: Run gapfilling
        update_job(job_file, {"progress": "Running gapfilling..."})
        from modelseedpy import MSGapfill

        gapfiller = MSGapfill(
            cobra_model,
            default_target="bio1",
            default_gapfill_templates=[template],
        )
        solutions = gapfiller.run_gapfilling(media=ms_media)

        # Collect gapfilling results
        solutions_count = len(solutions) if solutions else 0
        added_reactions = []
        if solutions:
            for sol in solutions:
                if hasattr(sol, "reactions"):
                    added_reactions.extend([r.id for r in sol.reactions])

        result_data = {
            "status": "success",
            "model_ref": model_ref,
            "solutions_count": solutions_count,
            "added_reactions": len(added_reactions),
        }

        # TODO: Save gapfilled model back to workspace

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
    main()
