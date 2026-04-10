"""Integration tests for biochem_service with real ModelSEED database.

Skipped if MODELSEED_MODELSEED_DB_PATH is not set or DB files don't exist.
"""

import os

import pytest

from modelseed_api.services import biochem_service

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("MODELSEED_MODELSEED_DB_PATH"),
        reason="MODELSEED_MODELSEED_DB_PATH not set — skipping real DB tests",
    ),
]


@pytest.fixture(autouse=True, scope="module")
def ensure_db():
    """Initialize the biochem DB once for this module."""
    biochem_service._db = None  # reset
    biochem_service.init_db()


class TestInitDb:
    def test_loads_compounds(self):
        db = biochem_service._get_db()
        assert len(db["compounds"]) > 25_000

    def test_loads_reactions(self):
        db = biochem_service._get_db()
        assert len(db["reactions"]) > 30_000


class TestGetCompound:
    def test_h2o(self):
        cpd = biochem_service.get_compound("cpd00001")
        assert cpd is not None
        assert "H2O" in cpd["name"]

    def test_glucose_formula(self):
        cpd = biochem_service.get_compound("cpd00027")
        assert cpd is not None
        assert "C6H12O6" in cpd["formula"]

    def test_missing(self):
        assert biochem_service.get_compound("cpd99999999") is None


class TestSearchCompounds:
    def test_glucose(self):
        results = biochem_service.search_compounds("glucose")
        ids = [c["id"] for c in results]
        assert "cpd00027" in ids

    def test_case_insensitive(self):
        r1 = biochem_service.search_compounds("glucose")
        r2 = biochem_service.search_compounds("GLUCOSE")
        assert len(r1) == len(r2)

    def test_limit_respected(self):
        results = biochem_service.search_compounds("a", limit=5)
        assert len(results) <= 5


class TestGetCompoundsBatch:
    def test_found_returned(self):
        results = biochem_service.get_compounds(["cpd00001", "cpd00027"])
        assert len(results) == 2

    def test_missing_silently_dropped(self):
        results = biochem_service.get_compounds(["cpd00001", "cpd99999999"])
        assert len(results) == 1


class TestGetPathwayMap:
    def test_strips_compartment_suffix(self):
        # Use a reaction we know exists
        rxn = biochem_service.get_reaction("rxn00148")
        if rxn:
            result1 = biochem_service.get_pathway_map(["rxn00148_c0"])
            result2 = biochem_service.get_pathway_map(["rxn00148"])
            # Both should resolve to the same pathways (if any)
            if result1 or result2:
                pw1 = result1.get("rxn00148_c0", [])
                pw2 = result2.get("rxn00148", [])
                assert len(pw1) == len(pw2)


class TestGetStats:
    def test_returns_positive_counts(self):
        stats = biochem_service.get_stats()
        assert stats["total_compounds"] > 0
        assert stats["total_reactions"] > 0
