"""Plant reconstruction job script (subprocess mode).

Used only when MODELSEED_USE_CELERY=false. Production runs go through the
Celery task `modelseed.plant_reconstruct`; both delegate to
`services.plant_reconstruction.run_plant_reconstruct` so they can't drift.

Usage:
    python plant_reconstruct.py --job-id <id> --token <token> \
        --params <json-or-@filename> --job-store-dir <dir>
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _update_job(job_file: Path, updates: dict) -> None:
    if job_file.exists():
        job = json.loads(job_file.read_text())
        job.update(updates)
        job_file.write_text(json.dumps(job, indent=2))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d-%H:%M:%S")


def main() -> int:
    parser = argparse.ArgumentParser(description="Plant reconstruction job")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--params", required=True,
                        help="JSON or @filename for large payloads")
    parser.add_argument("--job-store-dir", required=True)
    args = parser.parse_args()

    job_file = Path(args.job_store_dir) / f"{args.job_id}.json"
    _update_job(job_file, {"status": "in-progress", "start_time": _now()})

    if args.params.startswith("@"):
        params = json.loads(Path(args.params[1:]).read_text())
    else:
        params = json.loads(args.params)

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from modelseed_api.services.plant_reconstruction import run_plant_reconstruct

    try:
        result = run_plant_reconstruct(
            token=args.token,
            genome=params.get("genome", ""),
            genome_fasta=params.get("genome_fasta") or "",
            query_species=params.get("query_species"),
            output_path=params.get("output_path"),
            job_id=args.job_id,
            progress_cb=lambda msg: _update_job(job_file, {"progress": msg}),
        )
    except Exception as exc:
        logger.exception("plant_reconstruct failed: %s", exc)
        _update_job(job_file, {
            "status": "failed",
            "completed_time": _now(),
            "error": f"{type(exc).__name__}: {exc}",
        })
        return 1

    _update_job(job_file, {
        "status": "completed",
        "completed_time": _now(),
        "result": result,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
