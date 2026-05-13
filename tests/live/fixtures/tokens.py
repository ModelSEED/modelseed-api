"""Token loading utilities. Currently a thin wrapper around env vars.

If you ever need to load tokens from a keychain helper or a vault, add it
here so the rest of the suite stays decoupled from the source.
"""

from __future__ import annotations

import os


def get_test_token() -> str | None:
    """Return the PATRIC test token from the env, or None if unset."""
    token = os.environ.get("MODELSEED_TEST_TOKEN", "").strip()
    return token or None


def get_test_rast_token() -> str | None:
    """Return the RAST test token from the env, or None if unset."""
    token = os.environ.get("MODELSEED_TEST_RAST_TOKEN", "").strip()
    return token or None
