"""Tests for MCP biochemistry tools."""

from unittest.mock import patch

import modelseed_mcp.tools.biochem as biochem_mod

# Access underlying functions from FunctionTool wrappers
search_compounds = biochem_mod.search_compounds.fn
search_reactions = biochem_mod.search_reactions.fn
get_compound = biochem_mod.get_compound.fn
get_reaction = biochem_mod.get_reaction.fn

MOCK_COMPOUNDS = [
    {"id": "cpd00027", "name": "D-Glucose", "formula": "C6H12O6", "charge": 0},
    {"id": "cpd00027_e0", "name": "D-Glucose_e0", "formula": "C6H12O6", "charge": 0},
]

MOCK_REACTIONS = [
    {"id": "rxn00148", "name": "Pyruvate kinase", "equation": "...", "direction": ">"},
]


@patch("modelseed_api.services.biochem_service")
class TestSearchCompounds:
    def test_basic_search(self, mock_svc):
        mock_svc.search_compounds.return_value = MOCK_COMPOUNDS
        result = search_compounds("glucose")
        assert result["count"] == 2
        assert result["query"] == "glucose"
        assert len(result["compounds"]) == 2
        mock_svc.search_compounds.assert_called_once_with("glucose", limit=20)

    def test_limit_capped_at_200(self, mock_svc):
        mock_svc.search_compounds.return_value = []
        search_compounds("x", limit=500)
        mock_svc.search_compounds.assert_called_once_with("x", limit=200)

    def test_empty_results(self, mock_svc):
        mock_svc.search_compounds.return_value = []
        result = search_compounds("nonexistent")
        assert result["count"] == 0
        assert result["compounds"] == []


@patch("modelseed_api.services.biochem_service")
class TestSearchReactions:
    def test_basic_search(self, mock_svc):
        mock_svc.search_reactions.return_value = MOCK_REACTIONS
        result = search_reactions("pyruvate kinase")
        assert result["count"] == 1
        assert result["reactions"][0]["id"] == "rxn00148"

    def test_limit_capped(self, mock_svc):
        mock_svc.search_reactions.return_value = []
        search_reactions("x", limit=999)
        mock_svc.search_reactions.assert_called_once_with("x", limit=200)


@patch("modelseed_api.services.biochem_service")
class TestGetCompound:
    def test_single_found(self, mock_svc):
        mock_svc.get_compound.return_value = MOCK_COMPOUNDS[0]
        result = get_compound("cpd00027")
        assert result["compound"]["id"] == "cpd00027"

    def test_single_not_found(self, mock_svc):
        mock_svc.get_compound.return_value = None
        result = get_compound("cpd99999")
        assert "error" in result
        assert "cpd99999" in result["error"]

    def test_multiple_ids(self, mock_svc):
        mock_svc.get_compounds.return_value = MOCK_COMPOUNDS[:1]
        result = get_compound("cpd00027, cpd99999")
        assert result["count"] == 1
        assert result["not_found"] == ["cpd99999"]

    def test_comma_separated_all_found(self, mock_svc):
        mock_svc.get_compounds.return_value = MOCK_COMPOUNDS
        result = get_compound("cpd00027,cpd00027_e0")
        assert result["count"] == 2
        assert "not_found" not in result


@patch("modelseed_api.services.biochem_service")
class TestGetReaction:
    def test_single_found(self, mock_svc):
        mock_svc.get_reaction.return_value = MOCK_REACTIONS[0]
        result = get_reaction("rxn00148")
        assert result["reaction"]["id"] == "rxn00148"

    def test_single_not_found(self, mock_svc):
        mock_svc.get_reaction.return_value = None
        result = get_reaction("rxn99999")
        assert "error" in result

    def test_multiple_ids(self, mock_svc):
        mock_svc.get_reactions.return_value = MOCK_REACTIONS
        result = get_reaction("rxn00148,rxn00062")
        assert result["count"] == 1
        assert result["not_found"] == ["rxn00062"]
