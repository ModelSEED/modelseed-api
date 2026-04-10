"""Route tests for /api/models endpoints."""

from unittest.mock import patch

import pytest

pytestmark = pytest.mark.integration


class TestListModels:
    @patch("modelseed_api.services.model_service.ModelService._lookup_genome_info", return_value=None)
    def test_empty_list(self, mock_lookup, local_client):
        resp = local_client.get("/api/models")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @patch("modelseed_api.services.model_service.ModelService._lookup_genome_info", return_value=None)
    def test_with_models(self, mock_lookup, seeded_client):
        resp = seeded_client.get("/api/models")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1

    @patch("modelseed_api.services.model_service.ModelService._lookup_genome_info", return_value=None)
    def test_custom_path(self, mock_lookup, seeded_client):
        resp = seeded_client.get("/api/models?path=/local/modelseed/")
        assert resp.status_code == 200


class TestGetModelData:
    @patch("modelseed_api.services.model_service.ModelService._lookup_genome_info", return_value=None)
    @patch("modelseed_api.services.biochem_service.get_pathway_map", return_value={})
    def test_existing_model(self, mock_pw, mock_lookup, seeded_client):
        resp = seeded_client.get("/api/models/data?ref=/local/modelseed/TestModel")
        assert resp.status_code == 200
        data = resp.json()
        assert "reactions" in data
        assert "compounds" in data
        assert "genes" in data
        assert "compartments" in data
        assert "biomasses" in data

    @patch("modelseed_api.services.biochem_service.get_pathway_map", return_value={})
    def test_nonexistent_returns_404(self, mock_pw, seeded_client):
        resp = seeded_client.get("/api/models/data?ref=/local/modelseed/Missing")
        assert resp.status_code == 404


class TestDeleteModel:
    def test_existing(self, seeded_client):
        resp = seeded_client.delete("/api/models?ref=/local/modelseed/TestModel")
        assert resp.status_code == 200

    def test_nonexistent(self, seeded_client):
        resp = seeded_client.delete("/api/models?ref=/local/modelseed/Missing")
        assert resp.status_code == 404


class TestCopyModel:
    @patch("modelseed_api.services.model_service.ModelService._lookup_genome_info", return_value=None)
    def test_copy_success(self, mock_lookup, seeded_client):
        resp = seeded_client.post("/api/models/copy", json={
            "model": "/local/modelseed/TestModel",
            "destination": "/local/modelseed/CopyModel",
        })
        assert resp.status_code == 200


class TestExportModel:
    @patch("modelseed_api.services.model_service.ModelService._lookup_genome_info", return_value=None)
    @patch("modelseed_api.services.biochem_service.get_pathway_map", return_value={})
    def test_json_format(self, mock_pw, mock_lookup, seeded_client):
        resp = seeded_client.get("/api/models/export?ref=/local/modelseed/TestModel&format=json")
        assert resp.status_code == 200
        assert "reactions" in resp.json()

    def test_sbml_format(self, seeded_client):
        resp = seeded_client.get("/api/models/export?ref=/local/modelseed/TestModel&format=sbml")
        assert resp.status_code == 200
        assert resp.text.startswith("<?xml")

    def test_cobra_json_format(self, seeded_client):
        resp = seeded_client.get("/api/models/export?ref=/local/modelseed/TestModel&format=cobra-json")
        assert resp.status_code == 200
        data = resp.json()
        assert "reactions" in data

    def test_unsupported_format_400(self, seeded_client):
        resp = seeded_client.get("/api/models/export?ref=/local/modelseed/TestModel&format=csv")
        assert resp.status_code == 400

    @patch("modelseed_api.services.biochem_service.get_pathway_map", return_value={})
    def test_nonexistent_404(self, mock_pw, seeded_client):
        resp = seeded_client.get("/api/models/export?ref=/local/modelseed/Missing&format=json")
        assert resp.status_code == 404


class TestGapfills:
    @patch("modelseed_api.services.biochem_service.get_pathway_map", return_value={})
    def test_list_gapfills(self, mock_pw, seeded_client):
        resp = seeded_client.get("/api/models/gapfills?ref=/local/modelseed/TestModel")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    @patch("modelseed_api.services.biochem_service.get_pathway_map", return_value={})
    def test_empty_model_gapfills(self, mock_pw, seeded_client):
        resp = seeded_client.get("/api/models/gapfills?ref=/local/modelseed/TestModel")
        assert resp.status_code == 200
        assert resp.json() == []


class TestFBA:
    @patch("modelseed_api.services.biochem_service.get_pathway_map", return_value={})
    def test_list_fba(self, mock_pw, seeded_client):
        resp = seeded_client.get("/api/models/fba?ref=/local/modelseed/TestModel")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestEditModel:
    @patch("modelseed_api.services.biochem_service.get_pathway_map", return_value={})
    def test_empty_edit(self, mock_pw, seeded_client):
        resp = seeded_client.post("/api/models/edit", json={
            "model": "/local/modelseed/TestModel",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["reactions_added"] == []
        assert data["reactions_removed"] == []
        assert data["reactions_modified"] == []

    @patch("modelseed_api.services.biochem_service.get_pathway_map", return_value={})
    def test_remove_reaction(self, mock_pw, seeded_client):
        resp = seeded_client.post("/api/models/edit", json={
            "model": "/local/modelseed/TestModel",
            "reactions_to_remove": ["rxn00001_c0"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "rxn00001_c0" in data["reactions_removed"]


class TestEditsHistory:
    def test_returns_empty(self, seeded_client):
        resp = seeded_client.get("/api/models/edits?ref=/local/modelseed/TestModel")
        assert resp.status_code == 200
        assert resp.json() == []
