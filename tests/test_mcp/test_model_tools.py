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

    @patch(PATCH_SVC)
    def test_empty_list(self, MockSvc):
        """No models should return count=0 and empty list."""
        MockSvc.return_value.list_models.return_value = []
        result = list_models()
        assert result["count"] == 0
        assert result["models"] == []


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

    @patch(PATCH_SVC)
    def test_file_not_found_error(self, MockSvc):
        """FileNotFoundError is also caught and returns error dict."""
        MockSvc.return_value.get_model.side_effect = FileNotFoundError("missing")
        result = get_model("/local/modelseed/nope")
        assert "error" in result
        assert "suggestions" in result

    @patch(PATCH_SVC)
    def test_trailing_slash_in_ref(self, MockSvc):
        """Trailing slash in model ref should be passed through."""
        MockSvc.return_value.get_model.return_value = MOCK_MODEL_DETAIL
        get_model("/local/modelseed/model1/")
        MockSvc.return_value.get_model.assert_called_once_with("/local/modelseed/model1/")

    @patch(PATCH_SVC)
    def test_suggestions_content(self, MockSvc):
        """Error response should include helpful suggestions."""
        MockSvc.return_value.get_model.side_effect = ValueError("not found")
        result = get_model("/local/modelseed/nope")
        assert any("list_models" in s for s in result["suggestions"])


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

    @patch(PATCH_SVC)
    def test_value_error(self, MockSvc):
        """ValueError is also caught by delete_model."""
        MockSvc.return_value.delete_model.side_effect = ValueError("bad ref")
        result = delete_model("")
        assert "error" in result


class TestCopyModel:
    @patch(PATCH_SVC)
    def test_success(self, MockSvc):
        MockSvc.return_value.copy_model.return_value = {"copied": "a -> b"}
        result = copy_model("/local/modelseed/a", "/local/modelseed/b")
        assert "copied" in result

    @patch(PATCH_SVC)
    def test_source_not_found(self, MockSvc):
        """FileNotFoundError when source does not exist."""
        MockSvc.return_value.copy_model.side_effect = FileNotFoundError("src missing")
        result = copy_model("/local/modelseed/nope", "/local/modelseed/b")
        assert "error" in result

    @patch(PATCH_SVC)
    def test_value_error(self, MockSvc):
        MockSvc.return_value.copy_model.side_effect = ValueError("bad ref")
        result = copy_model("", "")
        assert "error" in result


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

    @patch("modelseed_api.services.export_service.export_cobra_json")
    @patch(PATCH_SVC)
    def test_cobrapy_alias(self, MockSvc, mock_json):
        """'cobrapy' is an alias for cobra_json export."""
        MockSvc.return_value.get_model_raw.return_value = MOCK_RAW_MODEL
        mock_json.return_value = {"id": "model1", "reactions": []}
        result = export_model("/local/modelseed/model1", format="cobrapy")
        assert result["format"] == "cobra_json"

    @patch("modelseed_api.services.export_service.export_cobra_json")
    @patch(PATCH_SVC)
    def test_json_alias(self, MockSvc, mock_json):
        """'json' is an alias for cobra_json export."""
        MockSvc.return_value.get_model_raw.return_value = MOCK_RAW_MODEL
        mock_json.return_value = {"id": "model1", "reactions": []}
        result = export_model("/local/modelseed/model1", format="json")
        assert result["format"] == "cobra_json"

    @patch("modelseed_api.services.export_service.export_sbml")
    @patch(PATCH_SVC)
    def test_default_format_is_sbml(self, MockSvc, mock_sbml):
        """Default format (no format arg) should export as SBML."""
        MockSvc.return_value.get_model_raw.return_value = MOCK_RAW_MODEL
        mock_sbml.return_value = "<sbml/>"
        result = export_model("/local/modelseed/model1")
        assert result["format"] == "sbml"

    @patch("modelseed_api.services.export_service.export_sbml")
    @patch(PATCH_SVC)
    def test_unknown_format_falls_to_sbml(self, MockSvc, mock_sbml):
        """Unrecognized format string falls to SBML (else branch)."""
        MockSvc.return_value.get_model_raw.return_value = MOCK_RAW_MODEL
        mock_sbml.return_value = "<sbml/>"
        result = export_model("/local/modelseed/model1", format="csv")
        assert result["format"] == "sbml"

    @patch(PATCH_SVC)
    def test_model_not_found(self, MockSvc):
        MockSvc.return_value.get_model_raw.side_effect = ValueError("not found")
        result = export_model("/local/modelseed/nope")
        assert "error" in result

    @patch("modelseed_api.services.export_service.export_sbml")
    @patch(PATCH_SVC)
    def test_model_id_from_ref(self, MockSvc, mock_sbml):
        """Model ID should be extracted from the last path segment."""
        MockSvc.return_value.get_model_raw.return_value = MOCK_RAW_MODEL
        mock_sbml.return_value = "<sbml/>"
        export_model("/local/modelseed/MyModel")
        mock_sbml.assert_called_once_with(MOCK_RAW_MODEL, model_id="MyModel")

    @patch("modelseed_api.services.export_service.export_sbml")
    @patch(PATCH_SVC)
    def test_model_id_trailing_slash(self, MockSvc, mock_sbml):
        """Trailing slash should be stripped when extracting model_id."""
        MockSvc.return_value.get_model_raw.return_value = MOCK_RAW_MODEL
        mock_sbml.return_value = "<sbml/>"
        export_model("/local/modelseed/MyModel/")
        mock_sbml.assert_called_once_with(MOCK_RAW_MODEL, model_id="MyModel")


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

    @patch("modelseed_api.schemas.models.EditModelRequest")
    @patch(PATCH_SVC)
    def test_no_op_edit(self, MockSvc, MockEditReq):
        """Edit with all None parameters should produce no changes."""
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            "reactions_added": [],
            "reactions_removed": [],
            "reactions_modified": [],
            "compounds_added": [],
            "compounds_removed": [],
            "compounds_modified": [],
            "warnings": [],
        }
        MockSvc.return_value.edit_model.return_value = mock_response
        result = edit_model("/local/modelseed/model1")
        assert result["reactions_added"] == []
        assert result["reactions_removed"] == []

    @patch("modelseed_api.schemas.models.EditModelRequest")
    @patch(PATCH_SVC)
    def test_combined_operations(self, MockSvc, MockEditReq):
        """Add and remove reactions in the same edit call."""
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            "reactions_added": ["rxn00002_c0"],
            "reactions_removed": ["rxn00001_c0"],
            "warnings": [],
        }
        MockSvc.return_value.edit_model.return_value = mock_response
        result = edit_model(
            "/local/modelseed/model1",
            reactions_to_add=[{"reaction_id": "rxn00002", "compartment": "c0"}],
            reactions_to_remove=["rxn00001_c0"],
        )
        assert "rxn00002_c0" in result["reactions_added"]
        assert "rxn00001_c0" in result["reactions_removed"]

    @patch("modelseed_api.schemas.models.EditModelRequest")
    @patch(PATCH_SVC)
    def test_result_without_model_dump(self, MockSvc, MockEditReq):
        """If result is a plain dict (no model_dump), it should be returned as-is."""
        MockSvc.return_value.edit_model.return_value = {"reactions_added": ["rxn00001_c0"]}
        result = edit_model(
            "/local/modelseed/model1",
            reactions_to_add=[{"reaction_id": "rxn00001", "compartment": "c0"}],
        )
        assert result["reactions_added"] == ["rxn00001_c0"]
