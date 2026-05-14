"""UI layer: authenticated pages — my-models, my-jobs, polling loop.

U07 + U08 from docs/E2E_TEST_PLAN.md. These require the auth token to be
injected into browser storage; the `authenticated_page` fixture does that
(or skips with a clear message if we don't yet know the storage key).
"""

from __future__ import annotations

import pytest

from tests.live.assertions.ui import (
    collect_console_errors,
    filter_noise,
    wait_for_network_idle,
)

pytestmark = pytest.mark.requires_token


def test_my_models_page_renders(authenticated_page, target_env) -> None:
    """U07: /my-models loads with auth and shows either models or an empty state."""
    errors = collect_console_errors(authenticated_page)
    authenticated_page.goto(target_env.base_url + "/my-models", wait_until="domcontentloaded")
    wait_for_network_idle(authenticated_page)

    body = (authenticated_page.text_content("body") or "").lower()
    # Either the user has models (table renders rows) or empty state ("no models").
    has_content = (
        "model" in body and ("rxn" in body or "reaction" in body or "no models" in body)
    )
    assert has_content, "My Models page didn't render expected table or empty state"

    real_errors = filter_noise(errors)
    assert not real_errors, f"Console errors on /my-models: {real_errors}"


def test_my_jobs_page_renders(authenticated_page, target_env) -> None:
    """U08 (partial): /my-jobs loads with auth and shows the jobs table or empty state.

    The full job-polling assertion (jobs appearing within 4 seconds of submission)
    is deferred — it requires submitting a job from inside the test, which is
    expensive. The structural check here verifies the page at least renders.
    """
    errors = collect_console_errors(authenticated_page)
    authenticated_page.goto(target_env.base_url + "/my-jobs", wait_until="domcontentloaded")
    wait_for_network_idle(authenticated_page)

    body = (authenticated_page.text_content("body") or "").lower()
    has_content = "job" in body
    assert has_content, "My Jobs page didn't render expected content"

    real_errors = filter_noise(errors)
    assert not real_errors, f"Console errors on /my-jobs: {real_errors}"
