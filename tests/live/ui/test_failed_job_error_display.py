"""UI: verify the frontend renders the `error` field when a job fails.

The backend writes a user-facing string into the job record's `error`
field (see celery_app.py:_bridge_failure). This test:

  1. Submits a deliberately-bad reconstruct job via API (nonexistent
     genome ID 9999999.9 -> reconstruct fails in seconds).
  2. Logs into modelseed.org with the test token via localStorage.
  3. Opens /my-jobs and waits for the job to appear in failed state.
  4. Asserts that text from the backend's `error` field is visible to
     the user (the unique substring "9999999.9" must appear on screen).

If the assertion fails, a screenshot is dropped under tests/live/reports/
so we have concrete evidence of what the UI shows instead.
"""

from __future__ import annotations

import time

import httpx
import pytest

pytestmark = pytest.mark.requires_token

# Bad genome ID. BVBRCUtils raises ValueError("No genome found with ID ...")
# which the API records into job.error verbatim. The substring "9999999.9"
# is what we expect to see on screen.
_BAD_GENOME = "9999999.9"


def _submit_bad_genome(api_url: str, token: str) -> str:
    # Bypass the pre-flight check (which would otherwise return a synchronous
    # 404 for this bad genome ID). This test is verifying the UI behavior on
    # ASYNC job failure - i.e. job dispatches, runs, fails, UI renders the
    # error. The sync-4xx path is covered separately by route-level tests.
    with httpx.Client(base_url=api_url, headers={"Authorization": token}, timeout=30.0) as c:
        r = c.post(
            "/api/jobs/reconstruct",
            params={"skip_validation": "true"},
            json={
                "genome": _BAD_GENOME,
                "template_type": "gn",
                "atp_safe": True,
                "gapfill": False,
            },
        )
        r.raise_for_status()
        return r.text.strip().strip('"')


def _wait_for_failure(api_url: str, token: str, job_id: str, timeout_s: int = 30) -> dict:
    """Poll until the job is in failed state, then return its record."""
    deadline = time.time() + timeout_s
    last = {}
    with httpx.Client(base_url=api_url, headers={"Authorization": token}, timeout=30.0) as c:
        while time.time() < deadline:
            r = c.get("/api/jobs", params={"ids": job_id})
            r.raise_for_status()
            last = r.json().get(job_id, {})
            if last.get("status") == "failed":
                return last
            time.sleep(1)
    raise AssertionError(
        f"Job {job_id} did not reach failed state within {timeout_s}s. Last: {last}"
    )


@pytest.mark.flaky_external
def test_failed_job_error_visible_in_ui(
    authenticated_page,
    target_env,
    live_token,
    tmp_path,
) -> None:
    """Submit a bad-genome job, then assert /my-jobs shows the error text.

    Pass criterion: the substring "9999999.9" (uniquely identifying our
    failed job's error) is visible in the rendered DOM. If we instead see
    only a generic "Failed" badge with no detail, this test fails and
    leaves a screenshot for triage.
    """
    job_id = _submit_bad_genome(target_env.api_url, live_token)
    job_record = _wait_for_failure(target_env.api_url, live_token, job_id)

    # Sanity: the backend really did record the error string we expect.
    assert "9999999.9" in (job_record.get("error") or ""), (
        f"Backend didn't record expected error for {job_id}: {job_record!r}"
    )

    page = authenticated_page
    page.goto(target_env.base_url + "/my-jobs", wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass

    # The job row may need to be opened/expanded to reveal error text.
    # First check if the error is visible without interaction; if not,
    # try clicking the row to expand it.
    body_text = page.text_content("body") or ""
    if "9999999.9" not in body_text:
        # Try clicking each row that contains our job id, in case error
        # is hidden behind a click-to-expand interaction.
        rows = page.locator(f"text={job_id[:8]}").all()
        for row in rows:
            try:
                row.click(timeout=2000)
            except Exception:
                pass
        try:
            page.wait_for_timeout(1500)
        except Exception:
            pass
        body_text = page.text_content("body") or ""

    if "9999999.9" not in body_text:
        # Capture concrete evidence of what the UI does show.
        shot = tmp_path / "my_jobs_failed_job.png"
        page.screenshot(path=str(shot), full_page=True)
        # Also dump the body text excerpt around the job id so we can see
        # the badge label the UI uses instead.
        excerpt = ""
        idx = body_text.find(job_id[:8])
        if idx >= 0:
            excerpt = body_text[max(0, idx - 100) : idx + 400]
        raise AssertionError(
            f"/my-jobs did not display the error text '9999999.9' for failed "
            f"job {job_id}. Screenshot at {shot}. "
            f"Body excerpt around the job id:\n{excerpt!r}"
        )
