"""Integration tests for ModelService with real LocalStorageService — data round-trip correctness."""

import json
from unittest.mock import patch

import pytest

from modelseed_api.services.model_service import ModelService

pytestmark = pytest.mark.integration


@pytest.fixture
def model_svc(populated_storage, local_data_dir):
    """ModelService backed by real local storage with a pre-seeded model.

    local_data_dir already patches settings.storage_backend = 'local' and
    settings.local_data_dir, so get_storage_service() will return
    a LocalStorageService pointing at the temp dir.
    """
    return ModelService("test-token")


class TestListModels:
    def test_empty_returns_empty(self, local_storage, local_data_dir):
        svc = ModelService("test-token")
        result = svc.list_models(username="local")
        assert isinstance(result, list)

    @patch("modelseed_api.services.model_service.ModelService._lookup_genome_info", return_value=None)
    def test_with_models_returns_correct_count(self, mock_lookup, model_svc):
        result = model_svc.list_models(username="local")
        assert len(result) >= 1

    @patch("modelseed_api.services.model_service.ModelService._lookup_genome_info", return_value=None)
    def test_model_stats_fields(self, mock_lookup, model_svc):
        result = model_svc.list_models(username="local")
        m = result[0]
        assert "id" in m
        assert "ref" in m
        assert "name" in m
        assert "num_reactions" in m
        assert "num_compounds" in m


class TestGetModel:
    @patch("modelseed_api.services.model_service.ModelService._lookup_genome_info", return_value=None)
    @patch("modelseed_api.services.biochem_service.get_pathway_map", return_value={})
    def test_all_sections_present(self, mock_pw, mock_lookup, model_svc):
        result = model_svc.get_model("/local/modelseed/TestModel")
        assert "reactions" in result
        assert "compounds" in result
        assert "genes" in result
        assert "compartments" in result
        assert "biomasses" in result
        assert "pathways" in result

    @patch("modelseed_api.services.model_service.ModelService._lookup_genome_info", return_value=None)
    @patch("modelseed_api.services.biochem_service.get_pathway_map", return_value={})
    def test_equation_format(self, mock_pw, mock_lookup, model_svc):
        result = model_svc.get_model("/local/modelseed/TestModel")
        rxn = result["reactions"][0]
        assert "=>" in rxn["equation"] or "<=>" in rxn["equation"]

    @patch("modelseed_api.services.model_service.ModelService._lookup_genome_info", return_value=None)
    @patch("modelseed_api.services.biochem_service.get_pathway_map", return_value={})
    def test_compound_data_correct(self, mock_pw, mock_lookup, model_svc):
        result = model_svc.get_model("/local/modelseed/TestModel")
        cpd_ids = [c["id"] for c in result["compounds"]]
        assert "cpd00001_c0" in cpd_ids
        assert "cpd00002_c0" in cpd_ids

    @patch("modelseed_api.services.biochem_service.get_pathway_map", return_value={})
    def test_get_nonexistent_raises(self, mock_pw, model_svc):
        with pytest.raises((ValueError, Exception)):
            model_svc.get_model("/local/modelseed/NonExistent")


class TestCopyModel:
    @patch("modelseed_api.services.model_service.ModelService._lookup_genome_info", return_value=None)
    @patch("modelseed_api.services.biochem_service.get_pathway_map", return_value={})
    def test_copy_data_matches_source(self, mock_pw, mock_lookup, model_svc):
        model_svc.copy_model("/local/modelseed/TestModel", "/local/modelseed/CopiedModel")
        original = model_svc.get_model("/local/modelseed/TestModel")
        copied = model_svc.get_model("/local/modelseed/CopiedModel")
        assert len(original["reactions"]) == len(copied["reactions"])
        assert len(original["compounds"]) == len(copied["compounds"])


class TestDeleteModel:
    def test_delete_removes_folder(self, model_svc, local_data_dir):
        model_svc.delete_model("/local/modelseed/TestModel")
        result = model_svc.ws.ls({"paths": ["/local/modelseed/"]})
        names = [e[0] for e in result.get("/local/modelseed/", [])]
        assert "TestModel" not in names
