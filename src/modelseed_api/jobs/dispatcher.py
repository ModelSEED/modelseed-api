"""Job dispatcher - dispatches long-running operations.

Supports two modes:
- Celery: Sends tasks to the shared bioseed Redis scheduler (production)
- Subprocess: Launches local Python scripts (local dev fallback)

Mode is controlled by settings.use_celery.
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from modelseed_api.config import settings
from modelseed_api.jobs.store import JobStore


class JobDispatcher:
    """Dispatches jobs to Celery tasks or external Python scripts."""

    # Maps app names to job script files (subprocess mode)
    SCRIPT_MAP = {
        "ModelReconstruction": "reconstruct.py",
        "GapfillModel": "gapfill.py",
        "FluxBalanceAnalysis": "run_fba.py",
        "MergeModels": "merge_models.py",
    }

    # Maps app names to Celery task names
    CELERY_TASK_MAP = {
        "ModelReconstruction": "modelseed.reconstruct",
        "GapfillModel": "modelseed.gapfill",
        "FluxBalanceAnalysis": "modelseed.fba",
    }

    def __init__(self, store: JobStore):
        self.store = store
        self.scripts_dir = Path(settings.job_scripts_dir)

    def dispatch(self, app: str, parameters: dict, user: str, token: str) -> str:
        """Create a job and dispatch it.

        Uses Celery if settings.use_celery is True, otherwise subprocess fallback.
        Returns the job ID.
        """
        if settings.use_celery:
            return self._dispatch_celery(app, parameters, user, token)
        return self._dispatch_subprocess(app, parameters, user, token)

    def _dispatch_celery(self, app: str, parameters: dict, user: str, token: str) -> str:
        """Dispatch via Celery to the bioseed Redis scheduler."""
        from modelseed_api.jobs.celery_app import app as celery_app

        task_name = self.CELERY_TASK_MAP.get(app)
        if not task_name:
            job_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H:%M:%S")
            self.store.create_job(job_id, app, parameters, user, now)
            self.store.fail_job(job_id, f"No Celery task for app: {app}")
            return job_id

        # Build task kwargs from parameters
        task_kwargs = {"token": token, **parameters}

        # Send to Celery
        result = celery_app.send_task(task_name, kwargs=task_kwargs)

        # Use the Celery task ID as our job ID
        job_id = result.id
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H:%M:%S")

        # Also create a local job record for status tracking
        self.store.create_job(
            job_id=job_id,
            app=app,
            parameters={"command": app, "arguments": parameters},
            user=user,
            submit_time=now,
        )

        return job_id

    def _dispatch_subprocess(self, app: str, parameters: dict, user: str, token: str) -> str:
        """Dispatch via subprocess (local dev fallback)."""
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H:%M:%S")

        # Create job record
        self.store.create_job(
            job_id=job_id,
            app=app,
            parameters={"command": app, "arguments": parameters},
            user=user,
            submit_time=now,
        )

        # Find the script
        script_name = self.SCRIPT_MAP.get(app)
        if not script_name:
            self.store.fail_job(job_id, f"Unknown app: {app}")
            return job_id

        script_path = self.scripts_dir / script_name
        if not script_path.exists():
            self.store.fail_job(job_id, f"Job script not found: {script_path}")
            return job_id

        # Dispatch as subprocess
        try:
            subprocess.Popen(
                [
                    sys.executable,
                    str(script_path),
                    "--job-id", job_id,
                    "--token", token,
                    "--params", json.dumps(parameters),
                    "--job-store-dir", settings.job_store_dir,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            self.store.fail_job(job_id, f"Failed to dispatch: {e}")

        return job_id
