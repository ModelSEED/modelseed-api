"""Unit tests for model_service pure functions: _build_equation, _normalize_ref,
_safe_int, _extract_genome_id, _parse_gpr_to_proteins."""

import pytest

from modelseed_api.services.model_service import (
    ModelService,
    _build_equation,
    _normalize_ref,
    _safe_int,
)

pytestmark = pytest.mark.unit


# ── _build_equation ──────────────────────────────────────────────────


class TestBuildEquation:
    def test_simple_forward_reaction(self):
        reagents = [
            {"coefficient": -1, "modelcompound_ref": "~/modelcompounds/id/cpd00001_c0"},
            {"coefficient": 1, "modelcompound_ref": "~/modelcompounds/id/cpd00002_c0"},
        ]
        names = {"cpd00001_c0": "H2O", "cpd00002_c0": "Glucose"}
        eq = _build_equation(reagents, names, ">")
        assert eq == "H2O => Glucose"

    def test_coefficient_of_one_suppressed(self):
        reagents = [
            {"coefficient": -1, "modelcompound_ref": "~/id/cpd00001_c0"},
            {"coefficient": 1, "modelcompound_ref": "~/id/cpd00002_c0"},
        ]
        names = {"cpd00001_c0": "H2O", "cpd00002_c0": "ATP"}
        eq = _build_equation(reagents, names, ">")
        assert "(1)" not in eq
        assert eq == "H2O => ATP"

    def test_coefficient_greater_than_one_shown(self):
        reagents = [
            {"coefficient": -2, "modelcompound_ref": "~/id/cpd00001_c0"},
            {"coefficient": 1, "modelcompound_ref": "~/id/cpd00002_c0"},
        ]
        names = {"cpd00001_c0": "H2O", "cpd00002_c0": "ATP"}
        eq = _build_equation(reagents, names, ">")
        assert "(2) H2O" in eq

    def test_direction_reversible(self):
        reagents = [
            {"coefficient": -1, "modelcompound_ref": "~/id/cpd00001_c0"},
            {"coefficient": 1, "modelcompound_ref": "~/id/cpd00002_c0"},
        ]
        names = {"cpd00001_c0": "H2O", "cpd00002_c0": "ATP"}
        eq = _build_equation(reagents, names, "=")
        assert "<=>" in eq

    def test_direction_reverse(self):
        reagents = [
            {"coefficient": -1, "modelcompound_ref": "~/id/cpd00001_c0"},
            {"coefficient": 1, "modelcompound_ref": "~/id/cpd00002_c0"},
        ]
        names = {"cpd00001_c0": "H2O", "cpd00002_c0": "ATP"}
        eq = _build_equation(reagents, names, "<")
        assert "<=" in eq

    def test_direction_forward(self):
        reagents = [
            {"coefficient": -1, "modelcompound_ref": "~/id/cpd00001_c0"},
            {"coefficient": 1, "modelcompound_ref": "~/id/cpd00002_c0"},
        ]
        names = {"cpd00001_c0": "A", "cpd00002_c0": "B"}
        eq = _build_equation(reagents, names, ">")
        assert "=>" in eq
        assert "<=>" not in eq

    def test_multiple_reactants_and_products(self):
        reagents = [
            {"coefficient": -1, "modelcompound_ref": "~/id/cpd00002_c0"},
            {"coefficient": -1, "modelcompound_ref": "~/id/cpd00001_c0"},
            {"coefficient": 1, "modelcompound_ref": "~/id/cpd00008_c0"},
            {"coefficient": 1, "modelcompound_ref": "~/id/cpd00009_c0"},
        ]
        names = {
            "cpd00001_c0": "H2O",
            "cpd00002_c0": "ATP",
            "cpd00008_c0": "ADP",
            "cpd00009_c0": "Pi",
        }
        eq = _build_equation(reagents, names, ">")
        assert "+" in eq
        assert "=>" in eq
        # LHS should have ATP and H2O
        lhs, rhs = eq.split("=>")
        assert "ATP" in lhs
        assert "H2O" in lhs
        assert "ADP" in rhs
        assert "Pi" in rhs

    def test_empty_reagents(self):
        eq = _build_equation([], {}, "=")
        assert "<=>" in eq

    def test_unknown_compound_falls_back_to_raw_id(self):
        reagents = [
            {"coefficient": -1, "modelcompound_ref": "~/id/cpd99999_c0"},
            {"coefficient": 1, "modelcompound_ref": "~/id/cpd88888_c0"},
        ]
        eq = _build_equation(reagents, {}, ">")
        assert "cpd99999_c0" in eq
        assert "cpd88888_c0" in eq

    def test_unknown_direction_defaults_to_reversible(self):
        reagents = [
            {"coefficient": -1, "modelcompound_ref": "~/id/cpd00001_c0"},
            {"coefficient": 1, "modelcompound_ref": "~/id/cpd00002_c0"},
        ]
        eq = _build_equation(reagents, {}, "?")
        assert "<=>" in eq

    def test_fractional_coefficient(self):
        reagents = [
            {"coefficient": -0.5, "modelcompound_ref": "~/id/cpd00001_c0"},
            {"coefficient": 1.5, "modelcompound_ref": "~/id/cpd00002_c0"},
        ]
        names = {"cpd00001_c0": "H2O", "cpd00002_c0": "ATP"}
        eq = _build_equation(reagents, names, ">")
        assert "(0.5) H2O" in eq
        assert "(1.5) ATP" in eq

    def test_zero_coefficient_excluded(self):
        reagents = [
            {"coefficient": -1, "modelcompound_ref": "~/id/cpd00001_c0"},
            {"coefficient": 0, "modelcompound_ref": "~/id/cpd00002_c0"},
            {"coefficient": 1, "modelcompound_ref": "~/id/cpd00003_c0"},
        ]
        names = {"cpd00001_c0": "A", "cpd00002_c0": "B", "cpd00003_c0": "C"}
        eq = _build_equation(reagents, names, ">")
        assert "B" not in eq


# ── _normalize_ref ───────────────────────────────────────────────────


class TestNormalizeRef:
    def test_strips_trailing_model(self):
        assert _normalize_ref("/user/modelseed/Model/model") == "/user/modelseed/Model"

    def test_already_clean_ref_unchanged(self):
        assert _normalize_ref("/user/modelseed/Model") == "/user/modelseed/Model"

    def test_only_model_suffix(self):
        assert _normalize_ref("/model") == ""

    def test_model_not_at_end_left_alone(self):
        assert _normalize_ref("/model/something") == "/model/something"

    def test_empty_string(self):
        assert _normalize_ref("") == ""


# ── _safe_int ────────────────────────────────────────────────────────


class TestSafeInt:
    def test_valid_int(self):
        assert _safe_int(42) == 42

    def test_string_int(self):
        assert _safe_int("123") == 123

    def test_float_string_returns_default(self):
        assert _safe_int("3.14") == 0

    def test_none_returns_default(self):
        assert _safe_int(None) == 0

    def test_empty_string_returns_default(self):
        assert _safe_int("") == 0

    def test_negative_works(self):
        assert _safe_int(-5) == -5

    def test_custom_default(self):
        assert _safe_int(None, default=-1) == -1

    def test_float_value_truncates(self):
        assert _safe_int(3.9) == 3

    def test_bool_true_is_1(self):
        assert _safe_int(True) == 1

    def test_string_negative(self):
        assert _safe_int("-7") == -7

    def test_non_numeric_string(self):
        assert _safe_int("abc") == 0


# ── _extract_genome_id ──────────────────────────────────────────────


class TestExtractGenomeId:
    def test_plain_id(self):
        assert ModelService._extract_genome_id("83333.1") == "83333.1"

    def test_workspace_path(self):
        result = ModelService._extract_genome_id("/user/modelseed/83333.1/genome||")
        assert result == "83333.1"

    def test_no_match(self):
        assert ModelService._extract_genome_id("no_genome") is None

    def test_empty_string(self):
        assert ModelService._extract_genome_id("") is None

    def test_none(self):
        assert ModelService._extract_genome_id(None) is None

    def test_multiple_dots_extracts_first(self):
        result = ModelService._extract_genome_id("path/469009.4/something/123.5")
        assert result == "469009.4"

    def test_complex_workspace_path(self):
        result = ModelService._extract_genome_id(
            "/jplfaria@patricbrc.org/modelseed/.469009.4/469009.4"
        )
        assert result == "469009.4"


# ── _parse_gpr_to_proteins ──────────────────────────────────────────


class TestParseGprToProteins:
    def setup_method(self):
        """Create a minimal ModelService instance for testing the method."""
        # _parse_gpr_to_proteins doesn't use self.ws or self.token
        # but we need an instance to call the method
        self.svc = object.__new__(ModelService)

    def test_single_gene(self):
        result = self.svc._parse_gpr_to_proteins("gene1")
        assert len(result) == 1  # 1 protein
        subunits = result[0]["modelReactionProteinSubunits"]
        assert len(subunits) == 1  # 1 subunit
        assert subunits[0]["feature_refs"] == ["~/genome/features/id/gene1"]

    def test_or_creates_multiple_proteins(self):
        result = self.svc._parse_gpr_to_proteins("gene1 or gene2")
        assert len(result) == 2  # 2 proteins (alternatives)
        assert result[0]["modelReactionProteinSubunits"][0]["feature_refs"] == [
            "~/genome/features/id/gene1"
        ]
        assert result[1]["modelReactionProteinSubunits"][0]["feature_refs"] == [
            "~/genome/features/id/gene2"
        ]

    def test_and_creates_multiple_subunits(self):
        result = self.svc._parse_gpr_to_proteins("gene1 and gene2")
        assert len(result) == 1  # 1 protein complex
        subunits = result[0]["modelReactionProteinSubunits"]
        assert len(subunits) == 2  # 2 subunits
        assert subunits[0]["feature_refs"] == ["~/genome/features/id/gene1"]
        assert subunits[1]["feature_refs"] == ["~/genome/features/id/gene2"]

    def test_or_with_and_group(self):
        result = self.svc._parse_gpr_to_proteins("gene1 or (gene2 and gene3)")
        assert len(result) == 2  # 2 proteins
        # First protein: single gene
        assert len(result[0]["modelReactionProteinSubunits"]) == 1
        # Second protein: 2 subunits
        assert len(result[1]["modelReactionProteinSubunits"]) == 2

    def test_empty_string_returns_empty(self):
        assert self.svc._parse_gpr_to_proteins("") == []

    def test_none_returns_empty(self):
        assert self.svc._parse_gpr_to_proteins(None) == []

    def test_whitespace_only_returns_empty(self):
        assert self.svc._parse_gpr_to_proteins("   ") == []

    def test_feature_refs_format(self):
        result = self.svc._parse_gpr_to_proteins("fig|83333.1.peg.1")
        subunits = result[0]["modelReactionProteinSubunits"]
        assert subunits[0]["feature_refs"] == [
            "~/genome/features/id/fig|83333.1.peg.1"
        ]

    def test_subunit_fields_complete(self):
        result = self.svc._parse_gpr_to_proteins("gene1")
        subunit = result[0]["modelReactionProteinSubunits"][0]
        assert subunit["role"] == ""
        assert subunit["triggering"] == 1
        assert subunit["optionalSubunit"] == 0
        assert subunit["note"] == ""

    def test_protein_fields_complete(self):
        result = self.svc._parse_gpr_to_proteins("gene1")
        protein = result[0]
        assert protein["note"] == ""
        assert "modelReactionProteinSubunits" in protein
