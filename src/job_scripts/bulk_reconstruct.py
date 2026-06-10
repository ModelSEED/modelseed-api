"""Bulk reconstruction job script (subprocess mode).

Used only when MODELSEED_USE_CELERY=false. Production runs on poplar
go through the Celery task `modelseed.bulk_reconstruct` directly; this
script exists so the local-dev subprocess path stays consistent with
the rest of the job_scripts directory.

Delegates the actual workflow to `tasks._run_bulk_reconstruct` so the
two paths can't drift apart.

Usage:
    python bulk_reconstruct.py --job-id <id> --token <token> \
        --params <json-or-@filename> --job-store-dir <dir>
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def _update_job(job_file: Path, updates: dict) -> None:
    if job_file.exists():
        job = json.loads(job_file.read_text())
        job.update(updates)
        job_file.write_text(json.dumps(job, indent=2))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d-%H:%M:%S")


def main() -> int:
    parser = argparse.ArgumentParser(description="Bulk reconstruction job")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--params", required=True,
                        help="JSON or @filename for large payloads")
    parser.add_argument("--job-store-dir", required=True)
    args = parser.parse_args()

    store_dir = Path(args.job_store_dir)
    job_file = store_dir / f"{args.job_id}.json"
    _update_job(job_file, {"status": "in-progress", "start_time": _now()})

    if args.params.startswith("@"):
        params = json.loads(Path(args.params[1:]).read_text())
    else:
        params = json.loads(args.params)

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from modelseed_api.jobs.tasks import _run_bulk_reconstruct

    def _progress(msg: str) -> None:
        _update_job(job_file, {"progress": msg})

    try:
        result = _run_bulk_reconstruct(
            token=args.token,
            genomes=params.get("genomes") or [],
            template_type=params.get("template_type", "auto"),
            atp_safe=params.get("atp_safe", True),
            gapfill=params.get("gapfill", False),
            gapfill_media=params.get("gapfill_media"),
            fva=params.get("fva", True),
            output_path=params.get("output_path"),
            job_id=args.job_id,
            progress_cb=_progress,
        )
    except Exception as exc:
        logger.exception("bulk_reconstruct subprocess crashed: %s", exc)
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
