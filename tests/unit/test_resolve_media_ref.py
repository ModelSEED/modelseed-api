"""Unit tests for _resolve_media_ref.

Locks in the rule that ANY spelling of "Complete media" (keyword, empty,
or the canonical /chenry/public path the frontend defaults to) collapses
to None, which downstream interprets as "all exchanges open, no media
load required".

Regression test for the bug that surfaced 2026-06-10 when 4 user jobs
in a row failed with "No media compounds found in
/chenry/public/modelsupport/media/Complete" - the frontend's default
path was being sent through to a workspace fetch instead of being
short-circuited as the keyword would be.
"""

from __future__ import annotations

import pytest

from modelseed_api.jobs.tasks import _resolve_media_ref


@pytest.mark.parametrize("media_ref", [
    "",
    None,
    "Complete",
    "complete",
    "COMPLETE",
])
def test_resolve_media_ref_returns_none_for_keyword_or_empty(media_ref):
    assert _resolve_media_ref(media_ref) is None


@pytest.mark.parametrize("media_ref", [
    "/chenry/public/modelsupport/media/Complete",
    "/chenry/public/modelsupport/media/complete",
    "/chenry/public/modelsupport/media/COMPLETE",
    "/chenry/public/modelsupport/media/Complete/",   # trailing slash
    "/some/user/path/Complete",                       # any path ending in Complete
])
def test_resolve_media_ref_returns_none_for_any_path_ending_in_complete(media_ref):
    """Even the full canonical PATRIC path collapses to None. Workspace
    has no parseable compound list for Complete; loading it fails."""
    assert _resolve_media_ref(media_ref) is None


def test_resolve_media_ref_passes_through_real_media_paths():
    """Non-Complete workspace paths are returned unchanged so _load_media
    can fetch them."""
    assert _resolve_media_ref("/chenry/public/modelsupport/media/NMS") == \
        "/chenry/public/modelsupport/media/NMS"
    assert _resolve_media_ref("/user@patricbrc.org/media/CustomGrowth") == \
        "/user@patricbrc.org/media/CustomGrowth"


def test_resolve_media_ref_bare_name_goes_to_public_folder():
    """Names without '/' resolve under the configured public media path.
    Verifies the fall-through still works."""
    result = _resolve_media_ref("NMS")
    assert result is not None
    assert result.endswith("/NMS")
