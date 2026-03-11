"""Model reconstruction job script.

This script runs outside the API service process.
It uses KBUtilLib/ModelSEEDpy to build a metabolic model from a genome.

Usage:
    python reconstruct.py --job-id <id> --token <token> --params <json> --job-store-dir <dir>
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Model reconstruction job")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--job-store-dir", required=True)
    args = parser.parse_args()

    store_dir = Path(args.job_store_dir)
    job_file = store_dir / f"{args.job_id}.json"

    # Mark as in-progress
    if job_file.exists():
        job = json.loads(job_file.read_text())
        job["status"] = "in-progress"
        from datetime import datetime, timezone

        job["start_time"] = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H:%M:%S")
        job_file.write_text(json.dumps(job, indent=2))

    params = json.loads(args.params)

    try:
        # TODO: Import and use MSReconstructionUtils here
        # from kbutillib.ms_reconstruction_utils import MSReconstructionUtils
        # recon = MSReconstructionUtils(token={"patric": args.token})
        # recon.build_metabolic_model(genome_ref=params["genome"])

        raise NotImplementedError(
            "Model reconstruction not yet integrated with KBUtilLib. "
            "This script needs MSReconstructionUtils to be connected."
        )

    except Exception as e:
        # Mark as failed
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
