"""Standalone builder for the RAST job index.

Walks the FIGV-format job dirs across all NFS shards on poplar and writes
a JSON index mapping `job_id -> {USER, PROJECT, GENOME, GENOME_ID, shard}`.
The index is consumed by `RastService.list_jobs` (via `RastFigvReader`) so
/api/rast/jobs serves user listings sub-millisecond.

Build cost: ~25-30 minutes wall-clock on poplar for ~1.6M dirs.
Index size: ~150-200 MB JSON.

Usage on the poplar host:

    # First-time build (or rebuild):
    python3 /scratch/modelseed/modelseed-api/scripts/build_rast_index.py \
        /vol/rast-prod/jobs \
        /scratch/modelseed/rast_index/rast_user_index.json

    # Suggested cron for nightly rebuilds at 3am (low NFS contention):
    0 3 * * *  cd /scratch/modelseed/modelseed-api && \
               python3 scripts/build_rast_index.py \
                   /vol/rast-prod/jobs \
                   /scratch/modelseed/rast_index/rast_user_index.json \
                   >> /var/log/modelseed-api/rast_index.log 2>&1

The script writes atomically (tmp file + rename), so concurrent readers
in the api/worker containers never observe a partial index.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

# Allow running directly without `pip install -e`. Adjust if your checkout
# of modelseed-api is at a different path.
_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir():
    sys.path.insert(0, str(_SRC))

from modelseed_api.services.rast_figv_reader import RastFigvReader  # noqa: E402


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} <jobs_dir> <output_index_path>", file=sys.stderr)
        return 2
    jobs_dir = sys.argv[1]
    out_path = Path(sys.argv[2])

    if not Path(jobs_dir).is_dir():
        print(f"error: jobs_dir does not exist: {jobs_dir}", file=sys.stderr)
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[{time.strftime('%H:%M:%S')}] Building index from {jobs_dir} to {out_path}")
    reader = RastFigvReader(jobs_dir)
    summary = reader.build_user_index(index_path=out_path)
    print(f"[{time.strftime('%H:%M:%S')}] Done: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
