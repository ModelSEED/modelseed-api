"""Celery application for the modelseed worker.

Connects to the shared bioseed Redis scheduler (same infrastructure as
bioseed_tools bakta worker). Each task runs on the 'modelseed' queue.

Usage (start worker on poplar):
    celery -A modelseed_api.jobs.celery_app worker --loglevel=info --queues=modelseed

Or use the worker() entry point:
    python -m modelseed_api.jobs.celery_app
"""

from __future__ import annotations

import os

from celery import Celery
from kombu import Exchange, Queue

QUEUE = "modelseed"

app = Celery(
    QUEUE,
    broker=os.getenv("CELERY_BROKER_URL", "redis://bioseed_redis:6379/10"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://bioseed_redis:6379/10"),
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
