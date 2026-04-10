"""Unit tests for ModelService._format_model_data — validates formatted output shape and content."""

import json
from unittest.mock import MagicMock, patch

import pytest

from modelseed_api.services.model_service import ModelService

pytestmark = pytest.mark.unit


def _make_svc():
    """Create a ModelService without real workspace."""
    svc = object.__new__(ModelService)
    svc.token = "test"
    svc.ws = MagicMock()
    return svc


class TestFormatModelData:
    @patch("modelseed_api.services.biochem_service.get_pathway_map", return_value={})
    def test_all_sections_present(self, mock_pw, minimal_model_obj):
        svc = _make_svc()
        result = svc._format_model_data("/test/model", minimal_model_obj)
        assert "ref" in result
        assert "reactions" in result
        assert "compounds" in result
        assert "genes" in result
        assert "compartments" in result
        assert "biomasses" in result
        assert "pathways" in result

    @patch("modelseed_api.services.biochem_service.get_pathway_map", return_value={})
    def test_ref_preserved(self, mock_pw, minimal_model_obj):
        svc = _make_svc()
        result = svc._format_model_data("/test/model", minimal_model_obj)
        assert result["ref"] == "/test/model"

    @patch("modelseed_api.services.biochem_service.get_pathway_map", return_value={})
    def test_reaction_count(self, mock_pw, minimal_model_obj):
        svc = _make_svc()
        result = svc._format_model_data("/test/model", minimal_model_obj)
        assert len(result["reactions"]) == 3

    @patch("modelseed_api.services.biochem_service.get_pathway_map", return_value={})
    def test_reaction_fields(self, mock_pw, minimal_model_obj):
        svc = _make_svc()
        result = svc._format_model_data("/test/model", minimal_model_obj)
        rxn = result["reactions"][0]
        assert "id" in rxn
        assert "name" in rxn
        assert "stoichiometry" in rxn
        assert "direction" in rxn
        assert "equation" in rxn
        assert "gpr" in rxn
        assert "genes" in rxn
        assert "pathways" in rxn

    @patch("modelseed_api.services.biochem_service.get_pathway_map", return_value={})
    def test_equation_format(self, mock_pw, minimal_model_obj):
        svc = _make_svc()
        result = svc._format_model_data("/test/model", minimal_model_obj)
        # rxn00001_c0: direction ">", ATP + H2O => ADP + Pi
        rxn = next(r for r in result["reactions"] if r["id"] == "rxn00001_c0")
        assert "=>" in rxn["equation"]
        assert "ATP" in rxn["equation"]
        assert "ADP" in rxn["equation"]

    @patch("modelseed_api.services.biochem_service.get_pathway_map", return_value={})
    def test_gpr_string(self, mock_pw, minimal_model_obj):
        svc = _make_svc()
        result = svc._format_model_data("/test/model", minimal_model_obj)
        # rxn00001_c0 has single gene
        rxn1 = next(r for r in result["reactions"] if r["id"] == "rxn00001_c0")
        assert "fig|83333.1.peg.1" in rxn1["gpr"]

    @patch("modelseed_api.services.biochem_service.get_pathway_map", return_value={})
    def test_gpr_and_subunits_joined(self, mock_pw, minimal_model_obj):
        svc = _make_svc()
        result = svc._format_model_data("/test/model", minimal_model_obj)
        # rxn00002_c0 has 2 subunits joined by "and"
        rxn2 = next(r for r in result["reactions"] if r["id"] == "rxn00002_c0")
        assert "and" in rxn2["gpr"]

    @patch("modelseed_api.services.biochem_service.get_pathway_map", return_value={})
    def test_compound_count(self, mock_pw, minimal_model_obj):
        svc = _make_svc()
        result = svc._format_model_data("/test/model", minimal_model_obj)
        assert len(result["compounds"]) == 5

    @patch("modelseed_api.services.biochem_service.get_pathway_map", return_value={})
    def test_compound_fields(self, mock_pw, minimal_model_obj):
        svc = _make_svc()
        result = svc._format_model_data("/test/model", minimal_model_obj)
        cpd = result["compounds"][0]
        assert "id" in cpd
        assert "name" in cpd
        assert "formula" in cpd
        assert "charge" in cpd

    @patch("modelseed_api.services.biochem_service.get_pathway_map", return_value={})
    def test_gene_reaction_map_consistent(self, mock_pw, minimal_model_obj):
        """Verify gene→reaction and reaction→gene maps are bidirectionally consistent."""
        svc = _make_svc()
        result = svc._format_model_data("/test/model", minimal_model_obj)

        # Gene→reaction: each gene lists reactions it appears in
        for gene in result["genes"]:
            for rxn_id in gene["reactions"]:
                rxn = next(r for r in result["reactions"] if r["id"] == rxn_id)
                assert gene["id"] in rxn["genes"], (
                    f"Gene {gene['id']} claims rxn {rxn_id} but rxn doesn't list the gene"
                )

        # Reaction→gene: each reaction's gene list should be in genes
        gene_ids = {g["id"] for g in result["genes"]}
        for rxn in result["reactions"]:
            for gene_id in rxn["genes"]:
                assert gene_id in gene_ids, (
                    f"Reaction {rxn['id']} references gene {gene_id} but it's not in genes list"
                )

    @patch("modelseed_api.services.biochem_service.get_pathway_map", return_value={})
    def test_compartment_count(self, mock_pw, minimal_model_obj):
        svc = _make_svc()
        result = svc._format_model_data("/test/model", minimal_model_obj)
        assert len(result["compartments"]) == 2

    @patch("modelseed_api.services.biochem_service.get_pathway_map", return_value={})
    def test_compartment_fields(self, mock_pw, minimal_model_obj):
        svc = _make_svc()
        result = svc._format_model_data("/test/model", minimal_model_obj)
        cpt = result["compartments"][0]
        assert "id" in cpt
        assert "name" in cpt
        assert "pH" in cpt
        assert "potential" in cpt

    @patch("modelseed_api.services.biochem_service.get_pathway_map", return_value={})
    def test_biomass_count(self, mock_pw, minimal_model_obj):
        svc = _make_svc()
        result = svc._format_model_data("/test/model", minimal_model_obj)
        assert len(result["biomasses"]) == 1

    @patch("modelseed_api.services.biochem_service.get_pathway_map", return_value={})
    def test_biomass_compound_names_resolved(self, mock_pw, minimal_model_obj):
        svc = _make_svc()
        result = svc._format_model_data("/test/model", minimal_model_obj)
        bio = result["biomasses"][0]
        # Each compound entry: [cpd_id, coefficient, compartment, name]
        for bc in bio["compounds"]:
            assert len(bc) == 4
            cpd_id, coeff, cpt, name = bc
            # Name should be resolved from the name map
            assert name != ""
            if cpd_id == "cpd00002_c0":
                assert name == "ATP"
            elif cpd_id == "cpd00001_c0":
                assert name == "H2O"

    @patch(
        "modelseed_api.services.biochem_service.get_pathway_map",
        return_value={
            "rxn00001": [
                {"source": "KEGG", "id": "rn00010", "name": "Glycolysis"}
            ],
            "rxn00002": [
                {"source": "KEGG", "id": "rn00010", "name": "Glycolysis"},
                {"source": "MetaCyc", "id": "PWY-001", "name": "Pathway One"},
            ],
        },
    )
    def test_pathway_grouping(self, mock_pw, minimal_model_obj):
        svc = _make_svc()
        result = svc._format_model_data("/test/model", minimal_model_obj)
        assert len(result["pathways"]) >= 1
        # KEGG:rn00010 should group rxn00001 and rxn00002
        kegg_pw = next(
            (p for p in result["pathways"] if p["id"] == "rn00010"), None
        )
        assert kegg_pw is not None
        assert "rxn00001_c0" in kegg_pw["reactions"]
        assert "rxn00002_c0" in kegg_pw["reactions"]

    @patch("modelseed_api.services.biochem_service.get_pathway_map", return_value={})
    def test_empty_model(self, mock_pw):
        svc = _make_svc()
        result = svc._format_model_data("/test/model", {})
        assert result["reactions"] == []
        assert result["compounds"] == []
        assert result["genes"] == []
        assert result["compartments"] == []
        assert result["biomasses"] == []
        assert result["pathways"] == []

    @patch("modelseed_api.services.biochem_service.get_pathway_map", return_value={})
    def test_gene_count(self, mock_pw, minimal_model_obj):
        svc = _make_svc()
        result = svc._format_model_data("/test/model", minimal_model_obj)
        # 3 unique genes: peg.1, peg.2, peg.3
        assert len(result["genes"]) == 3

    @patch("modelseed_api.services.biochem_service.get_pathway_map", return_value={})
    def test_stoichiometry_format(self, mock_pw, minimal_model_obj):
        svc = _make_svc()
        result = svc._format_model_data("/test/model", minimal_model_obj)
        rxn = result["reactions"][0]
        for s in rxn["stoichiometry"]:
            assert len(s) == 5  # [coeff, cpd_id, compartment, compartment_idx, name]
