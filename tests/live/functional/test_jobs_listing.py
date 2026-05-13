"""Functional layer: /api/jobs filter combinations.

F36–F40 from docs/E2E_TEST_PLAN.md. Read-only — does not submit any jobs.
"""

from __future__ import annotations

import httpx
import pytest

from tests.live.assertions.api import assert_status

pytestmark = pytest.mark.requires_token


def test_jobs_default_returns_dict(live_client: httpx.Client) -> None:
    """F36: GET /api/jobs with no filters returns a dict (possibly empty)."""
    r = live_client.get("/api/jobs")
    assert_status(r, 200)
    assert isinstance(r.json(), dict)


def test_jobs_filter_only_completed(live_client: httpx.Client) -> None:
    """F37: include_completed=true, others=false returns only completed jobs."""
    r = live_client.get(
        "/api/jobs",
        params={
            "include_completed": "true",
            "include_failed": "false",
            "include_running": "false",
            "include_queued": "false",
        },
    )
    assert_status(r, 200)
    jobs = r.json()
    for jid, record in jobs.items():
        status = record.get("status")
        assert status == "completed", (
            f"Job {jid} has status {status!r} but include_completed-only filter active"
        )


def test_jobs_filter_all_off_returns_empty(live_client: httpx.Client) -> None:
    """F39: All include flags false returns an empty dict."""
    r = live_client.get(
        "/api/jobs",
        params={
            "include_completed": "false",
            "include_failed": "false",
            "include_running": "false",
            "include_queued": "false",
        },
    )
    assert_status(r, 200)
    assert r.json() == {}


def test_jobs_filter_only_active(live_client: httpx.Client) -> None:
    """F38: include_running + include_queued only returns active jobs."""
    r = live_client.get(
        "/api/jobs",
        params={
            "include_completed": "false",
            "include_failed": "false",
            "include_running": "true",
            "include_queued": "true",
        },
    )
    assert_status(r, 200)
    for jid, record in r.json().items():
        assert record.get("status") in {"queued", "in-progress"}, (
            f"Job {jid} status {record.get('status')!r} doesn't match active filter"
        )
