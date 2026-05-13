"""Generic API response assertions and HTTP helpers shared across layers.

Keep these focused on shape/status/structure — anything biology-specific
goes in `bio.py`.
"""

from __future__ import annotations

import time
from typing import Any, Iterable

import httpx

# Statuses returned by /api/jobs Task records.
JOB_STATUSES_DONE = {"completed", "failed"}
JOB_STATUSES_ACTIVE = {"queued", "in-progress"}
JOB_STATUSES_ALL = JOB_STATUSES_DONE | JOB_STATUSES_ACTIVE


def assert_status(response: httpx.Response, expected: int | Iterable[int]) -> None:
    """Assert the response status code matches `expected` (int or iterable of ints).

    Includes the response body in the failure message because a 200/4xx/5xx
    mismatch usually points at a payload issue we want to read.
    """
    expected_set = {expected} if isinstance(expected, int) else set(expected)
    if response.status_code in expected_set:
        return
    body_preview = response.text[:500]
    raise AssertionError(
        f"Expected status {expected_set}, got {response.status_code} for "
        f"{response.request.method} {response.request.url}\n"
        f"Body (first 500 chars): {body_preview}"
    )


def assert_json_keys(payload: Any, required: Iterable[str], context: str = "") -> None:
    """Assert that every key in `required` is present in the JSON payload."""
    if not isinstance(payload, dict):
        raise AssertionError(
            f"{context}: expected JSON object, got {type(payload).__name__}: {payload!r}"
        )
    missing = [k for k in required if k not in payload]
    if missing:
        raise AssertionError(
            f"{context}: missing required keys {missing}. Got keys: {list(payload)}"
        )


def assert_list_of_dicts_with_keys(
    payload: Any, required: Iterable[str], context: str = "", min_len: int = 0
) -> None:
    """Assert payload is a list of dicts each containing the required keys."""
    if not isinstance(payload, list):
        raise AssertionError(
            f"{context}: expected list, got {type(payload).__name__}: {payload!r}"
        )
    if len(payload) < min_len:
        raise AssertionError(
            f"{context}: expected at least {min_len} entries, got {len(payload)}"
        )
    for i, item in enumerate(payload):
        try:
            assert_json_keys(item, required, context=f"{context}[{i}]")
        except AssertionError:
            raise


def poll_job_until_done(
    client: httpx.Client,
    job_id: str,
    *,
    timeout_s: int = 1200,
    poll_interval_s: float = 5.0,
) -> dict:
    """Poll /api/jobs?ids=<job_id> until the job is in a terminal state.

    Returns the job record (a dict). Raises TimeoutError if the job is
    still running after `timeout_s`.
    """
    deadline = time.monotonic() + timeout_s
    last_status = None
    while time.monotonic() < deadline:
        r = client.get("/api/jobs", params={"ids": job_id})
        assert_status(r, 200)
        jobs = r.json()
        if job_id not in jobs:
            # Hasn't shown up yet; the dispatcher may not have written the
            # initial record. Wait and retry.
            time.sleep(poll_interval_s)
            continue
        record = jobs[job_id]
        status = record.get("status")
        if status != last_status:
            last_status = status
        if status in JOB_STATUSES_DONE:
            return record
        time.sleep(poll_interval_s)
    raise TimeoutError(
        f"Job {job_id} did not finish within {timeout_s}s "
        f"(last seen status: {last_status})"
    )


def assert_job_succeeded(record: dict) -> None:
    """Assert a polled job record represents a successful completion."""
    if record.get("status") != "completed":
        raise AssertionError(
            f"Job {record.get('id')} did not complete successfully. "
            f"Status: {record.get('status')}, error: {record.get('error', '<none>')}"
        )
