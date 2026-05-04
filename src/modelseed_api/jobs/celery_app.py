"""Celery application for the modelseed worker.

Connects to the shared bioseed Redis scheduler (same infrastructure as
bioseed_tools bakta worker). Each task runs on the 'modelseed' queue.

Usage (start worker on poplar):
    celery -A modelseed_api.jobs.celery_app worker --loglevel=info --queues=modelseed

Or use the worker() entry point:
    python -m modelseed_api.jobs.celery_app
"""

from __future__ import annotations

from celery import Celery
from kombu import Exchange, Queue

from modelseed_api.config import settings

QUEUE = "modelseed"

from celery import Task  # noqa: E402
from modelseed_api.jobs.store import JobStore  # noqa: E402

# Module-level JobStore — both the worker (in its own container) and
# the API (when imported in-process for testing) write to the same
# directory configured by MODELSEED_JOB_STORE_DIR.
_job_store = JobStore()


class JobStoreTask(Task):
    """Base task that mirrors ``update_state`` progress to JobStore.

    The API serves status from JSON files in ``MODELSEED_JOB_STORE_DIR``;
    this lets the existing ``self.update_state(meta={"status": "..."})``
    calls in tasks reach the frontend without changing task code.
    """

    def update_state(self, task_id=None, state=None, meta=None, **kw):
        super().update_state(task_id=task_id, state=state, meta=meta, **kw)
        if meta and isinstance(meta, dict):
            tid = task_id or self.request.id
            msg = meta.get("status") or meta.get("progress")
            if tid and msg:
                try:
                    _job_store.set_progress(tid, msg)
                except Exception:
                    pass


app = Celery(
    QUEUE,
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    task_cls=JobStoreTask,
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600 * 4,  # 4 hours max
    worker_prefetch_multiplier=1,
    task_default_queue=QUEUE,
    task_default_exchange=QUEUE,
    task_default_routing_key=QUEUE,
    task_queues=(Queue(QUEUE, Exchange(QUEUE), routing_key=QUEUE),),
    task_routes={f"{QUEUE}.*": {"queue": QUEUE, "routing_key": QUEUE}},
)


# Import tasks to register them with the app
from modelseed_api.jobs import tasks  # noqa: E402, F401

# ── Bridge Celery lifecycle to the file-based JobStore ──────────
# The API status endpoint reads from JobStore JSON files, not from
# Celery's result backend.  These signals keep both in sync so the
# worker (running in its own container) updates the same JSON files
# the API serves to the frontend.
from celery.signals import (  # noqa: E402
    task_prerun,
    task_postrun,
    task_failure,
)


@task_prerun.connect
def _bridge_prerun(task_id=None, task=None, **_):  # pragma: no cover - runs in worker
    if task_id:
        _job_store.start_job(task_id)


@task_postrun.connect
def _bridge_postrun(task_id=None, retval=None, state=None, **_):  # pragma: no cover
    if not task_id:
        return
    if state == "SUCCESS":
        _job_store.complete_job(task_id)
        if retval is not None:
            _job_store.set_result(task_id, retval)


@task_failure.connect
def _bridge_failure(task_id=None, exception=None, **_):  # pragma: no cover
    if task_id and exception is not None:
        _job_store.fail_job(task_id, f"{type(exception).__name__}: {exception}")


def main():
    """Start the Celery worker."""
    print("Starting ModelSEED Celery Worker...")
    print(f"Broker: {app.conf.broker_url}")
    print(f"Backend: {app.conf.result_backend}")

    app.worker_main(
        [
            "worker",
            "--loglevel=info",
            "--concurrency=2",
            f"--queues={QUEUE}",
            f"--hostname={QUEUE}@%h",
        ]
    )


if __name__ == "__main__":
    main()
