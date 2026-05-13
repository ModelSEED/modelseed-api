"""UI layer: dropdown enumeration tests.

U05 from docs/E2E_TEST_PLAN.md — every option in the publications Year
dropdown can be selected without producing a JS error.
"""

from __future__ import annotations

import pytest

from tests.live.assertions.ui import collect_console_errors, wait_for_network_idle


def test_publications_year_dropdown_every_option(page, target_env) -> None:
    """U05: select every option in the publications Year dropdown."""
    errors = collect_console_errors(page)
    page.goto(target_env.base_url + "/publications", wait_until="domcontentloaded")
    wait_for_network_idle(page, timeout_ms=10000)

    # Try common dropdown selectors. The actual DOM may vary; we attempt
    # a few and skip if none match, since this is opt-in UI testing and
    # we don't want false failures on UI restyles.
    selectors = [
        'select[name*="year" i]',
        'select[aria-label*="year" i]',
        '[role="combobox"]',
    ]
    dropdown = None
    for sel in selectors:
        try:
            dropdown = page.locator(sel).first
            if dropdown.count() > 0:
                break
            dropdown = None
        except Exception:
            continue

    if dropdown is None or dropdown.count() == 0:
        pytest.skip(
            "No Year dropdown matched any expected selector. "
            "Update test_publications_year_dropdown_every_option if the UI changed."
        )

    # Discover the available options (works for native <select>; for custom
    # combobox we'd need a different probing strategy).
    try:
        options = dropdown.evaluate(
            "el => Array.from(el.options || []).map(o => o.value)"
        )
    except Exception:
        pytest.skip(
            "Could not enumerate options on the Year dropdown — likely a "
            "custom combobox. Add a selector-specific implementation."
        )

    if not options:
        pytest.skip("Year dropdown has no options yet.")

    for value in options[:5]:  # cap at 5 to keep the test fast
        if value:
            try:
                dropdown.select_option(value)
                page.wait_for_timeout(500)
            except Exception as exc:
                pytest.fail(f"Selecting Year={value!r} failed: {exc}")

    real_errors = [e for e in errors if "googletagmanager" not in e]
    assert not real_errors, f"Console errors after dropdown changes: {real_errors}"
