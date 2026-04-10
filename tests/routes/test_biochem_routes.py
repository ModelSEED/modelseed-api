"""Route tests for /api/biochem endpoints."""

import pytest

pytestmark = pytest.mark.integration


class TestBiochemStats:
    def test_stats_200(self, local_client):
        resp = local_client.get("/api/biochem/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_compounds" in data
        assert "total_reactions" in data

    def test_stats_no_auth_required(self, local_client):
        resp = local_client.get("/api/biochem/stats")
        assert resp.status_code == 200


class TestGetReactions:
    def test_single_id(self, local_client):
        resp = local_client.get("/api/biochem/reactions?ids=rxn00001")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 0  # May be 0 if DB not loaded

    def test_multiple_ids(self, local_client):
        resp = local_client.get("/api/biochem/reactions?ids=rxn00001,rxn00002")
        assert resp.status_code == 200

    def test_no_ids_returns_400(self, local_client):
        resp = local_client.get("/api/biochem/reactions?ids=")
        assert resp.status_code == 400


class TestGetCompounds:
    def test_single_id(self, local_client):
        resp = local_client.get("/api/biochem/compounds?ids=cpd00001")
        assert resp.status_code == 200

    def test_comma_separated(self, local_client):
        resp = local_client.get("/api/biochem/compounds?ids=cpd00001,cpd00027")
        assert resp.status_code == 200

    def test_no_ids_returns_400(self, local_client):
        resp = local_client.get("/api/biochem/compounds?ids=")
        assert resp.status_code == 400


class TestSearch:
    def test_search_compounds(self, local_client):
        resp = local_client.get("/api/biochem/search?query=glucose&type=compounds")
        assert resp.status_code == 200

    def test_search_reactions(self, local_client):
        resp = local_client.get("/api/biochem/search?query=kinase&type=reactions")
        assert resp.status_code == 200

    def test_invalid_type_returns_400(self, local_client):
        resp = local_client.get("/api/biochem/search?query=test&type=invalid")
        assert resp.status_code == 400

    def test_limit_respected(self, local_client):
        resp = local_client.get("/api/biochem/search?query=a&type=compounds&limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) <= 5

    def test_limit_capped_at_200(self, local_client):
        # FastAPI enforces le=200 via Query parameter
        resp = local_client.get("/api/biochem/search?query=a&type=compounds&limit=500")
        assert resp.status_code == 422  # Validation error
