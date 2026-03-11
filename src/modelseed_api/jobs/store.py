"""Job store - tracks job status.

Phase 1: File-based storage (JSON files in a directory).
Phase 3: Will be replaced with Redis backend.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from modelseed_api.config import settings


class JobStore:
    """File-based job status store.

    Each job is stored as a JSON file: {job_store_dir}/{job_id}.json
    """

    def __init__(self):
        self.store_dir = Path(settings.job_store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)

    def _job_path(self, job_id: str) -> Path:
        return self.store_dir / f"{job_id}.json"

    def _read_job(self, job_id: str) -> Optional[dict]:
        path = self._job_path(job_id)
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def _write_job(self, job_id: str, data: dict):
        self._job_path(job_id).write_text(json.dumps(data, indent=2))

    def create_job(
        self,
        job_id: str,
        app: str,
        parameters: dict,
        user: str,
        submit_time: str,
    ):
        """Create a new job record."""
        self._write_job(
            job_id,
            {
                "id": job_id,
                "app": app,
                "parameters": parameters,
                "status": "queued",
                "submit_time": submit_time,
                "start_time": None,
                "completed_time": None,
                "stdout_shock_node": None,
                "stderr_shock_node": None,
                "user": user,
            },
        )

    def start_job(self, job_id: str):
        """Mark a job as in-progress."""
        job = self._read_job(job_id)
        if job:
            job["status"] = "in-progress"
            job["start_time"] = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H:%M:%S")
            self._write_job(job_id, job)

    def complete_job(self, job_id: str):
        """Mark a job as completed."""
        job = self._read_job(job_id)
        if job:
            job["status"] = "completed"
            job["completed_time"] = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H:%M:%S")
            self._write_job(job_id, job)

    def fail_job(self, job_id: str, error: str):
        """Mark a job as failed."""
        job = self._read_job(job_id)
        if job:
            job["status"] = "failed"
            job["completed_time"] = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H:%M:%S")
            job["error"] = error
            self._write_job(job_id, job)

    def delete_job(self, job_id: str, user: str):
        """Delete a job record."""
        job = self._read_job(job_id)
        if job and job.get("user") == user:
            self._job_path(job_id).unlink(missing_ok=True)

    def get_jobs(
        self, user: str, job_ids: Optional[list[str]] = None
    ) -> dict[str, dict]:
        """Get all jobs for a user, optionally filtered by IDs."""
        result = {}
        for path in self.store_dir.glob("*.json"):
            job = json.loads(path.read_text())
            if job.get("user") != user:
                continue
            if job_ids and job["id"] not in job_ids:
                continue
            result[job["id"]] = job
        return result
