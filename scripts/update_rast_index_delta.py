"""Incremental update for the RAST job index.

Cheap to run frequently (every 5 minutes via cron). Scans job IDs
sequentially upward from the highest known ID, picking up new entries
without re-walking the whole 1.6M-dir filesystem.

Usage on the poplar host:

    # Manual delta refresh:
    python3 /scratch/modelseed/modelseed-api/scripts/update_rast_index_delta.py \
        /vol/rast-prod/jobs \
        /scratch/modelseed/rast_index/rast_user_index.json

    # Suggested cron for 5-minute deltas:
    */5 * * * *  cd /scratch/modelseed/modelseed-api && \
                 python3 scripts/update_rast_index_delta.py \
                     /vol/rast-prod/jobs \
                     /scratch/modelseed/rast_index/rast_user_index.json \
                     >> /var/log/modelseed-api/rast_index_delta.log 2>&1

Cost per run: milliseconds when no new jobs exist; sub-second per new job.
Atomic write so concurrent readers in the api/worker containers never see
a partial index.

Requires the index file to already exist (run build_rast_index.py first
for the initial full build).
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

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
        print(f"usage: {sys.argv[0]} <jobs_dir> <index_path>", file=sys.stderr)
        return 2
    jobs_dir = sys.argv[1]
    index_path = Path(sys.argv[2])
    if not Path(jobs_dir).is_dir():
        print(f"error: jobs_dir does not exist: {jobs_dir}", file=sys.stderr)
        return 1
    if not index_path.is_file():
        print(
            f"error: index file does not exist: {index_path}\n"
            f"       Run build_rast_index.py first for the initial full build.",
            file=sys.stderr,
        )
        return 1

    print(f"[{time.strftime('%H:%M:%S')}] Delta-updating index at {index_path}")
    reader = RastFigvReader(jobs_dir)
    summary = reader.update_user_index_delta(index_path=index_path)
    print(f"[{time.strftime('%H:%M:%S')}] Done: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
