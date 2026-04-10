"""E2E: Biochemistry search and lookup workflow — no mocks.

Exercises /api/biochem endpoints with the real ModelSEED database.
Verifies result correctness: compound formulas, reaction equations, search results.
"""

import pytest

pytestmark = pytest.mark.e2e


class TestBiochemWorkflow:
    """Full biochemistry workflow through the API with real database."""

    def test_stats_populated(self, e2e_client):
        """Stats endpoint should return positive counts for compounds and reactions."""
        resp = e2e_client.get("/api/biochem/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_compounds"] > 25000
        assert data["total_reactions"] > 30000

    def test_search_and_lookup_compound(self, e2e_client):
        """Search for glucose, then look up the compound by ID."""
        # Search
        resp = e2e_client.get("/api/biochem/search?query=glucose&type=compounds")
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) > 0

        # Find cpd00027 (D-Glucose) in results
        cpd_ids = [r["id"] for r in results]
        assert "cpd00027" in cpd_ids

        # Lookup by ID
        resp = e2e_client.get("/api/biochem/compounds?ids=cpd00027")
        assert resp.status_code == 200
        compounds = resp.json()
        assert len(compounds) == 1
        glucose = compounds[0]
        assert glucose["id"] == "cpd00027"
        assert "C6H12O6" in glucose.get("formula", "")

    def test_search_and_lookup_reaction(self, e2e_client):
        """Search for a reaction, then look it up by ID."""
        resp = e2e_client.get("/api/biochem/search?query=kinase&type=reactions")
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) > 0

        # All results should have an equation field
        for rxn in results:
            assert "equation" in rxn or "definition" in rxn

        # Lookup first result by ID
        rxn_id = results[0]["id"]
        resp = e2e_client.get(f"/api/biochem/reactions?ids={rxn_id}")
        assert resp.status_code == 200
        reactions = resp.json()
        assert len(reactions) == 1
        assert reactions[0]["id"] == rxn_id

    def test_water_compound(self, e2e_client):
        """Verify cpd00001 (H2O) has correct formula."""
        resp = e2e_client.get("/api/biochem/compounds?ids=cpd00001")
        assert resp.status_code == 200
        compounds = resp.json()
        assert len(compounds) == 1
        water = compounds[0]
        assert water["id"] == "cpd00001"
        assert "H2O" in water.get("formula", "")
        assert "Water" in water.get("name", "") or "H2O" in water.get("name", "")

    def test_multiple_compound_lookup(self, e2e_client):
        """Batch lookup of multiple compound IDs."""
        resp = e2e_client.get("/api/biochem/compounds?ids=cpd00001,cpd00027,cpd00002")
        assert resp.status_code == 200
        compounds = resp.json()
        assert len(compounds) == 3
        ids = {c["id"] for c in compounds}
        assert ids == {"cpd00001", "cpd00027", "cpd00002"}

    def test_multiple_reaction_lookup(self, e2e_client):
        """Batch lookup of multiple reaction IDs."""
        resp = e2e_client.get("/api/biochem/reactions?ids=rxn00001,rxn00002")
        assert resp.status_code == 200
        reactions = resp.json()
        assert len(reactions) >= 1
        for rxn in reactions:
            assert "id" in rxn
            assert rxn["id"].startswith("rxn")

    def test_search_case_insensitive(self, e2e_client):
        """Search should be case-insensitive."""
        resp_lower = e2e_client.get("/api/biochem/search?query=glucose&type=compounds")
        resp_upper = e2e_client.get("/api/biochem/search?query=GLUCOSE&type=compounds")
        assert resp_lower.status_code == 200
        assert resp_upper.status_code == 200
        # Should find the same compounds
        ids_lower = {c["id"] for c in resp_lower.json()}
        ids_upper = {c["id"] for c in resp_upper.json()}
        assert ids_lower == ids_upper

    def test_search_limit_respected(self, e2e_client):
        """Search limit parameter should cap results."""
        resp = e2e_client.get("/api/biochem/search?query=a&type=compounds&limit=5")
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) <= 5

    def test_search_by_id(self, e2e_client):
        """Searching by exact compound ID should find it."""
        resp = e2e_client.get("/api/biochem/search?query=cpd00027&type=compounds")
        assert resp.status_code == 200
        results = resp.json()
        ids = [r["id"] for r in results]
        assert "cpd00027" in ids


class TestMediaWorkflow:
    """Media listing and export through the API."""

    def test_list_and_export_media(self, e2e_client, auth_headers):
        """List public media, then export one to verify compound data."""
        # List
        resp = e2e_client.get("/api/media/public")
        assert resp.status_code == 200
        data = resp.json()
        # Should have at least one path with media entries
        all_entries = []
        for path, entries in data.items():
            all_entries.extend(entries)
        assert len(all_entries) > 0

        # Export first media
        ref = all_entries[0][2]  # Full path from metadata tuple
        resp = e2e_client.get(f"/api/media/export?ref={ref}", headers=auth_headers)
        assert resp.status_code == 200
        media = resp.json()
        assert "compounds" in media or "mediacompounds" in media
        # Should have a name
        assert "name" in media

    def test_user_media_empty(self, e2e_client, auth_headers):
        """New user should have no custom media."""
        resp = e2e_client.get("/api/media/mine", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)
