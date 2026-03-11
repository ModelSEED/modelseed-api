"""FBA job script.

Runs outside the API service process.
Uses KBUtilLib/ModelSEEDpy to run flux balance analysis.

Usage:
    python run_fba.py --job-id <id> --token <token> --params <json> --job-store-dir <dir>
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="FBA job")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--job-store-dir", required=True)
    args = parser.parse_args()

    store_dir = Path(args.job_store_dir)
    job_file = store_dir / f"{args.job_id}.json"

    if job_file.exists():
        job = json.loads(job_file.read_text())
        job["status"] = "in-progress"
        from datetime import datetime, timezone

        job["start_time"] = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H:%M:%S")
        job_file.write_text(json.dumps(job, indent=2))

    try:
        # TODO: Implement FBA using MSFBAUtils
        raise NotImplementedError("FBA not yet integrated with KBUtilLib")
    except Exception as e:
        if job_file.exists():
            job = json.loads(job_file.read_text())
            job["status"] = "failed"
            job["error"] = str(e)
            from datetime import datetime, timezone

            job["completed_time"] = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H:%M:%S")
            job_file.write_text(json.dumps(job, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
