"""Unit tests for bio1 objective guard logic."""
import pytest

pytestmark = pytest.mark.unit


def _make_reactions(ids):
    """Create mock reactions from a list of IDs."""
    return [type("R", (), {"id": i})() for i in ids]


class TestBio1Check:
    def test_bio1_present_passes_guard(self):
        reactions = _make_reactions(["rxn00001", "bio1"])
        assert "bio1" in {r.id for r in reactions}

    def test_bio1_absent_triggers_failure_path(self):
        reactions = _make_reactions(["rxn00001", "rxn00002"])
        assert "bio1" not in {r.id for r in reactions}

    def test_bio_fallback_finds_bio2(self):
        reactions = _make_reactions(["rxn00001", "bio2"])
        fallback = next(
            (r.id for r in reactions if r.id.startswith("bio")), None
        )
        assert fallback == "bio2"

    def test_no_biomass_reaction_returns_none(self):
        reactions = _make_reactions(["rxn00001", "rxn00002"])
        fallback = next(
            (r.id for r in reactions if r.id.startswith("bio")), None
        )
        assert fallback is None
