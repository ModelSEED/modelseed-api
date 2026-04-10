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

    def test_empty_query(self, mock_svc):
        """Empty query string should still call the service."""
        mock_svc.search_compounds.return_value = MOCK_COMPOUNDS
        result = search_compounds("")
        assert result["query"] == ""
        mock_svc.search_compounds.assert_called_once_with("", limit=20)

    def test_special_characters_in_query(self, mock_svc):
        """Special chars (parens, brackets, plus) should be passed through."""
        mock_svc.search_compounds.return_value = []
        result = search_compounds("(+)-glucose")
        assert result["query"] == "(+)-glucose"
        mock_svc.search_compounds.assert_called_once_with("(+)-glucose", limit=20)

    def test_whitespace_query(self, mock_svc):
        """Whitespace-only query should be passed to service as-is."""
        mock_svc.search_compounds.return_value = []
        result = search_compounds("   ")
        assert result["query"] == "   "

    def test_limit_zero(self, mock_svc):
        """Limit of 0 should be passed through (min(0,200)=0)."""
        mock_svc.search_compounds.return_value = []
        search_compounds("x", limit=0)
        mock_svc.search_compounds.assert_called_once_with("x", limit=0)

    def test_limit_negative(self, mock_svc):
        """Negative limit should be passed through (min(-5,200)=-5)."""
        mock_svc.search_compounds.return_value = []
        search_compounds("x", limit=-5)
        mock_svc.search_compounds.assert_called_once_with("x", limit=-5)

    def test_limit_exactly_200(self, mock_svc):
        """Limit of exactly 200 should pass through unchanged."""
        mock_svc.search_compounds.return_value = []
        search_compounds("x", limit=200)
        mock_svc.search_compounds.assert_called_once_with("x", limit=200)


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

    def test_empty_query(self, mock_svc):
        mock_svc.search_reactions.return_value = []
        result = search_reactions("")
        assert result["query"] == ""
        assert result["count"] == 0

    def test_special_characters(self, mock_svc):
        mock_svc.search_reactions.return_value = []
        result = search_reactions("ATP + H2O => ADP")
        assert result["query"] == "ATP + H2O => ADP"


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

    def test_empty_string(self, mock_svc):
        """Empty string produces empty ID list, falls to multi-ID path."""
        mock_svc.get_compounds.return_value = []
        result = get_compound("")
        assert result["count"] == 0

    def test_only_commas(self, mock_svc):
        """Commas only → all elements stripped to empty → empty list."""
        mock_svc.get_compounds.return_value = []
        result = get_compound(",,,")
        assert result["count"] == 0

    def test_whitespace_around_ids(self, mock_svc):
        """Whitespace around IDs should be stripped."""
        mock_svc.get_compounds.return_value = MOCK_COMPOUNDS
        get_compound("  cpd00027 , cpd00027_e0  ")
        mock_svc.get_compounds.assert_called_once_with(["cpd00027", "cpd00027_e0"])

    def test_single_id_with_trailing_comma(self, mock_svc):
        """Trailing comma after single ID → multi-ID path with 1 ID."""
        mock_svc.get_compounds.return_value = MOCK_COMPOUNDS[:1]
        result = get_compound("cpd00027,")
        # After split and strip: ["cpd00027"], len==1 → single-ID path
        assert "compound" in result or "compounds" in result

    def test_not_found_key_absent_when_all_found(self, mock_svc):
        """When all IDs are found, 'not_found' key must not exist."""
        mock_svc.get_compounds.return_value = MOCK_COMPOUNDS
        result = get_compound("cpd00027,cpd00027_e0")
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

    def test_empty_string(self, mock_svc):
        """Empty string → empty list → multi-ID path returns 0."""
        mock_svc.get_reactions.return_value = []
        result = get_reaction("")
        assert result["count"] == 0

    def test_whitespace_stripped(self, mock_svc):
        """Whitespace around reaction IDs should be stripped."""
        mock_svc.get_reactions.return_value = MOCK_REACTIONS
        get_reaction("  rxn00148 , rxn00062  ")
        mock_svc.get_reactions.assert_called_once_with(["rxn00148", "rxn00062"])

    def test_suggestions_on_not_found(self, mock_svc):
        """Single not-found should include suggestions list."""
        mock_svc.get_reaction.return_value = None
        result = get_reaction("rxn99999")
        assert "suggestions" in result
        assert len(result["suggestions"]) > 0
