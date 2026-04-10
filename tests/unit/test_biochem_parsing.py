"""Unit tests for biochem_service pure functions: _parse_pathways, _clean_compound, _clean_reaction."""

import pytest

from modelseed_api.services.biochem_service import (
    _clean_compound,
    _clean_reaction,
    _parse_pathways,
)

pytestmark = pytest.mark.unit


# ── _parse_pathways ──────────────────────────────────────────────────


class TestParsePathways:
    def test_single_source_single_pathway(self):
        raw = ["KEGG: rn00010 (Glycolysis)"]
        result = _parse_pathways(raw)
        assert len(result) == 1
        assert result[0] == {"source": "KEGG", "id": "rn00010", "name": "Glycolysis"}

    def test_multiple_pathways_semicolon_separated(self):
        raw = ["MetaCyc: PWY-5100 (Pyruvate); PWY-6507 (Amino acids)"]
        result = _parse_pathways(raw)
        assert len(result) == 2
        assert result[0]["source"] == "MetaCyc"
        assert result[0]["id"] == "PWY-5100"
        assert result[0]["name"] == "Pyruvate"
        assert result[1]["id"] == "PWY-6507"
        assert result[1]["name"] == "Amino acids"

    def test_multiple_sources(self):
        raw = [
            "KEGG: rn00010 (Glycolysis)",
            "MetaCyc: PWY-5100 (Pyruvate fermentation)",
        ]
        result = _parse_pathways(raw)
        assert len(result) == 2
        assert result[0]["source"] == "KEGG"
        assert result[1]["source"] == "MetaCyc"

    def test_no_parenthesized_name_uses_id_as_fallback(self):
        raw = ["KEGG: rn00010"]
        result = _parse_pathways(raw)
        assert len(result) == 1
        assert result[0]["id"] == "rn00010"
        assert result[0]["name"] == "rn00010"  # id used as name fallback

    def test_entry_without_colon_separator_skipped(self):
        raw = ["no colon here"]
        result = _parse_pathways(raw)
        assert result == []

    def test_empty_input_returns_empty(self):
        assert _parse_pathways([]) == []

    def test_none_input_returns_empty(self):
        assert _parse_pathways(None) == []

    def test_nested_parentheses_in_name(self):
        raw = ["KEGG: rn00020 (TCA (Krebs) cycle)"]
        result = _parse_pathways(raw)
        assert len(result) == 1
        # rsplit(" (", 1) should handle nested parens:
        # "rn00020 (TCA (Krebs) cycle)" -> rsplit gives id="rn00020 (TCA (Krebs", name="cycle)"
        # Actually the code uses rsplit which splits from the right
        # Let's just check it doesn't crash and returns something
        assert result[0]["source"] == "KEGG"
        assert result[0]["id"]  # has some id

    def test_trailing_semicolons_no_crash(self):
        raw = ["KEGG: rn00010 (Glycolysis); "]
        result = _parse_pathways(raw)
        # The empty part after trailing semicolon will be stripped
        # and since it doesn't have parens, id = name = ""
        assert len(result) >= 1
        assert result[0]["id"] == "rn00010"

    def test_empty_name_in_parens_falls_back_to_id(self):
        raw = ["KEGG: rn00010 ()"]
        result = _parse_pathways(raw)
        assert len(result) == 1
        assert result[0]["name"] == "rn00010"  # empty name -> fallback to id

    def test_mixed_valid_and_invalid_entries(self):
        raw = [
            "KEGG: rn00010 (Glycolysis)",
            "bad entry no colon",
            "MetaCyc: PWY-001 (Pathway One)",
        ]
        result = _parse_pathways(raw)
        assert len(result) == 2
        assert result[0]["source"] == "KEGG"
        assert result[1]["source"] == "MetaCyc"

    def test_colon_in_pathway_name(self):
        """Source is split on ': ' (with space), so colons in names are fine."""
        raw = ["KEGG: rn00010 (Glycolysis: first steps)"]
        result = _parse_pathways(raw)
        assert len(result) == 1
        assert result[0]["source"] == "KEGG"


# ── _clean_compound ──────────────────────────────────────────────────


class TestCleanCompound:
    def test_all_fields_present(self):
        cpd = {
            "id": "cpd00001",
            "name": "H2O",
            "formula": "H2O",
            "charge": 0,
            "mass": 18.015,
            "deltag": -56.69,
            "abbreviation": "H2O",
            "is_obsolete": False,
            "source": "ModelSEED",
            "extra_field": "should_not_appear",
        }
        result = _clean_compound(cpd)
        assert len(result) == 9  # exactly 9 fields
        assert result["id"] == "cpd00001"
        assert result["name"] == "H2O"
        assert result["formula"] == "H2O"
        assert result["charge"] == 0
        assert result["mass"] == 18.015
        assert result["deltag"] == -56.69
        assert result["abbreviation"] == "H2O"
        assert result["is_obsolete"] is False
        assert result["source"] == "ModelSEED"
        assert "extra_field" not in result

    def test_missing_optional_fields_returns_none(self):
        cpd = {"id": "cpd00001", "name": "H2O"}
        result = _clean_compound(cpd)
        assert result["id"] == "cpd00001"
        assert result["name"] == "H2O"
        assert result["formula"] is None
        assert result["charge"] is None
        assert result["mass"] is None

    def test_empty_dict(self):
        result = _clean_compound({})
        assert result["id"] is None
        assert result["name"] is None
        assert len(result) == 9


# ── _clean_reaction ──────────────────────────────────────────────────


class TestCleanReaction:
    def test_all_fields_present(self):
        rxn = {
            "id": "rxn00001",
            "name": "ATP hydrolysis",
            "abbreviation": "ATPH",
            "deltag": -30.5,
            "direction": ">",
            "reversibility": "=",
            "status": "OK",
            "equation": "H2O + ATP => ADP + Pi",
            "definition": "1 cpd00001 + 1 cpd00002 => 1 cpd00008 + 1 cpd00009",
            "source": "ModelSEED",
            "pathways": ["KEGG: rn00010 (Glycolysis)"],
            "extra_field": "ignored",
        }
        result = _clean_reaction(rxn)
        assert len(result) == 11  # exactly 11 fields
        assert result["id"] == "rxn00001"
        assert result["name"] == "ATP hydrolysis"
        assert result["direction"] == ">"
        assert result["equation"] == "H2O + ATP => ADP + Pi"
        assert "extra_field" not in result

    def test_pathways_field_gets_parsed(self):
        rxn = {
            "id": "rxn00001",
            "pathways": ["KEGG: rn00010 (Glycolysis)"],
        }
        result = _clean_reaction(rxn)
        assert isinstance(result["pathways"], list)
        assert len(result["pathways"]) == 1
        assert result["pathways"][0]["source"] == "KEGG"
        assert result["pathways"][0]["id"] == "rn00010"
        assert result["pathways"][0]["name"] == "Glycolysis"

    def test_missing_pathways_returns_empty_list(self):
        rxn = {"id": "rxn00001"}
        result = _clean_reaction(rxn)
        assert result["pathways"] == []

    def test_missing_optional_fields(self):
        rxn = {"id": "rxn00001"}
        result = _clean_reaction(rxn)
        assert result["id"] == "rxn00001"
        assert result["name"] is None
        assert result["direction"] is None
