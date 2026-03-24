"""Model merging job script.

Runs outside the API service process.
Uses ModelSEEDpy to merge multiple models into a community model.

Usage:
    python merge_models.py --job-id <id> --token <token> --params <json> --job-store-dir <dir>
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Model merging job")
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
        # TODO: Implement model merging using MSCommunity
        raise NotImplementedError("Model merging not yet integrated")
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
                job = json.loads(_jf.read_text())
                job["status"] = "failed"
                job["error"] = str(e)
                _jf.write_text(json.dumps(job, indent=2))
        except Exception:
            pass
