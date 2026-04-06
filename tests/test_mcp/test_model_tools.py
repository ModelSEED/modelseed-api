"""Tests for MCP model CRUD tools."""

from unittest.mock import MagicMock, patch

import modelseed_mcp.tools.models as models_mod

# Access underlying functions from FunctionTool wrappers
list_models = models_mod.list_models.fn
get_model = models_mod.get_model.fn
delete_model = models_mod.delete_model.fn
copy_model = models_mod.copy_model.fn
export_model = models_mod.export_model.fn
edit_model = models_mod.edit_model.fn

MOCK_MODEL_LIST = [
    {"id": "model1", "name": "E. coli", "num_reactions": 100, "num_genes": 50},
    {"id": "model2", "name": "B. subtilis", "num_reactions": 80, "num_genes": 40},
]

MOCK_MODEL_DETAIL = {
    "ref": "/local/modelseed/model1",
    "reactions": [{"id": "rxn00001_c0", "name": "Test rxn"}],
    "compounds": [{"id": "cpd00001_c0", "name": "H2O"}],
    "genes": [],
    "compartments": [],
    "biomasses": [],
    "pathways": [],
}

MOCK_RAW_MODEL = {
    "id": "model1",
    "modelreactions": [],
    "modelcompounds": [],
    "modelcompartments": [],
    "biomasses": [],
}

# Patch at the source so the lazy import inside _get_model_service picks it up
PATCH_SVC = "modelseed_api.services.model_service.ModelService"


class TestListModels:
    @patch(PATCH_SVC)
    def test_returns_models(self, MockSvc):
        MockSvc.return_value.list_models.return_value = MOCK_MODEL_LIST
        result = list_models()
        assert result["count"] == 2
        assert len(result["models"]) == 2
        MockSvc.return_value.list_models.assert_called_once_with(username="local")


class TestGetModel:
    @patch(PATCH_SVC)
    def test_found(self, MockSvc):
        MockSvc.return_value.get_model.return_value = MOCK_MODEL_DETAIL
        result = get_model("/local/modelseed/model1")
        assert result["ref"] == "/local/modelseed/model1"

    @patch(PATCH_SVC)
    def test_not_found(self, MockSvc):
        MockSvc.return_value.get_model.side_effect = ValueError("not found")
        result = get_model("/local/modelseed/nope")
        assert "error" in result
        assert "suggestions" in result


class TestDeleteModel:
    @patch(PATCH_SVC)
    def test_success(self, MockSvc):
        MockSvc.return_value.delete_model.return_value = None
        result = delete_model("/local/modelseed/model1")
        assert result["deleted"] == "/local/modelseed/model1"

    @patch(PATCH_SVC)
    def test_not_found(self, MockSvc):
        MockSvc.return_value.delete_model.side_effect = FileNotFoundError("nope")
        result = delete_model("/local/modelseed/nope")
        assert "error" in result


class TestCopyModel:
    @patch(PATCH_SVC)
    def test_success(self, MockSvc):
        MockSvc.return_value.copy_model.return_value = {"copied": "a -> b"}
        result = copy_model("/local/modelseed/a", "/local/modelseed/b")
        assert "copied" in result


class TestExportModel:
    @patch("modelseed_api.services.export_service.export_sbml")
    @patch(PATCH_SVC)
    def test_sbml_export(self, MockSvc, mock_sbml):
        MockSvc.return_value.get_model_raw.return_value = MOCK_RAW_MODEL
        mock_sbml.return_value = "<sbml>...</sbml>"
        result = export_model("/local/modelseed/model1", format="sbml")
        assert result["format"] == "sbml"
        assert "<sbml>" in result["sbml"]

    @patch("modelseed_api.services.export_service.export_cobra_json")
    @patch(PATCH_SVC)
    def test_json_export(self, MockSvc, mock_json):
        MockSvc.return_value.get_model_raw.return_value = MOCK_RAW_MODEL
        mock_json.return_value = {"id": "model1", "reactions": []}
        result = export_model("/local/modelseed/model1", format="cobra_json")
        assert result["format"] == "cobra_json"
        assert result["model"]["id"] == "model1"

    @patch(PATCH_SVC)
    def test_model_not_found(self, MockSvc):
        MockSvc.return_value.get_model_raw.side_effect = ValueError("not found")
        result = export_model("/local/modelseed/nope")
        assert "error" in result


class TestEditModel:
    @patch("modelseed_api.schemas.models.EditModelRequest")
    @patch(PATCH_SVC)
    def test_add_reaction(self, MockSvc, MockEditReq):
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            "reactions_added": ["rxn00001_c0"],
            "warnings": [],
        }
        MockSvc.return_value.edit_model.return_value = mock_response
        result = edit_model(
            "/local/modelseed/model1",
            reactions_to_add=[{"reaction_id": "rxn00001", "compartment": "c0"}],
        )
        assert result["reactions_added"] == ["rxn00001_c0"]

    @patch("modelseed_api.schemas.models.EditModelRequest")
    @patch(PATCH_SVC)
    def test_validation_error(self, MockSvc, MockEditReq):
        MockSvc.return_value.edit_model.side_effect = ValueError("bad edit")
        result = edit_model(
            "/local/modelseed/model1",
            reactions_to_remove=["nonexistent_c0"],
        )
        assert "error" in result
