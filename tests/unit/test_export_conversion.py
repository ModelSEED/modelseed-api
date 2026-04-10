"""Unit tests for export_service.workspace_model_to_cobra — validates cobra.Model fields."""

import pytest

pytestmark = pytest.mark.unit


# Skip all tests if cobra is not installed
cobra = pytest.importorskip("cobra")

from modelseed_api.services.export_service import workspace_model_to_cobra


class TestWorkspaceModelToCobra:
    def test_compartments_present(self, minimal_model_obj):
        model = workspace_model_to_cobra(minimal_model_obj)
        # cobra derives compartments from metabolites, so the keys come from metabolite.compartment
        assert "c0" in model.compartments
        assert "e0" in model.compartments

    def test_metabolite_fields(self, minimal_model_obj):
        model = workspace_model_to_cobra(minimal_model_obj)
        met = model.metabolites.get_by_id("cpd00001_c0")
        assert met.name == "H2O"
        assert met.formula == "H2O"
        assert met.charge == 0
        assert met.compartment == "c0"

    def test_metabolite_compartment_parsed_from_id(self, minimal_model_obj):
        model = workspace_model_to_cobra(minimal_model_obj)
        for met in model.metabolites:
            if "_" in met.id:
                expected_cpt = met.id.rsplit("_", 1)[1]
                assert met.compartment == expected_cpt

    def test_direction_forward_bounds(self, minimal_model_obj):
        model = workspace_model_to_cobra(minimal_model_obj)
        rxn = model.reactions.get_by_id("rxn00001_c0")
        assert rxn.lower_bound == 0
        assert rxn.upper_bound == 1000

    def test_direction_reversible_bounds(self, minimal_model_obj):
        model = workspace_model_to_cobra(minimal_model_obj)
        rxn = model.reactions.get_by_id("rxn00002_c0")
        assert rxn.lower_bound == -1000
        assert rxn.upper_bound == 1000

    def test_direction_reverse_bounds(self, minimal_model_obj):
        model = workspace_model_to_cobra(minimal_model_obj)
        rxn = model.reactions.get_by_id("rxn00003_c0")
        assert rxn.lower_bound == -1000
        assert rxn.upper_bound == 0

    def test_stoichiometric_coefficients_exact(self, minimal_model_obj):
        model = workspace_model_to_cobra(minimal_model_obj)
        rxn = model.reactions.get_by_id("rxn00001_c0")
        met_atp = model.metabolites.get_by_id("cpd00002_c0")
        met_adp = model.metabolites.get_by_id("cpd00008_c0")
        met_h2o = model.metabolites.get_by_id("cpd00001_c0")
        met_pi = model.metabolites.get_by_id("cpd00009_c0")
        assert rxn.metabolites[met_atp] == -1
        assert rxn.metabolites[met_h2o] == -1
        assert rxn.metabolites[met_adp] == 1
        assert rxn.metabolites[met_pi] == 1

    def test_gpr_string_built_correctly(self, minimal_model_obj):
        model = workspace_model_to_cobra(minimal_model_obj)
        # rxn00001_c0 has single gene
        rxn1 = model.reactions.get_by_id("rxn00001_c0")
        # Gene IDs with "|" get split by cobra's GPR parser ("|" → "or")
        # so we check the GPR is non-empty and contains the peg identifier
        assert rxn1.gene_reaction_rule != ""
        assert "83333.1.peg.1" in rxn1.gene_reaction_rule

    def test_gpr_and_subunits(self, minimal_model_obj):
        model = workspace_model_to_cobra(minimal_model_obj)
        # rxn00002_c0 has 2 subunits joined by "and"
        rxn2 = model.reactions.get_by_id("rxn00002_c0")
        assert "and" in rxn2.gene_reaction_rule
        assert "83333.1.peg.2" in rxn2.gene_reaction_rule
        assert "83333.1.peg.3" in rxn2.gene_reaction_rule

    def test_no_gpr_empty_rule(self, minimal_model_obj):
        model = workspace_model_to_cobra(minimal_model_obj)
        rxn3 = model.reactions.get_by_id("rxn00003_c0")
        assert rxn3.gene_reaction_rule == ""

    def test_biomass_reaction_created(self, minimal_model_obj):
        model = workspace_model_to_cobra(minimal_model_obj)
        bio = model.reactions.get_by_id("bio1")
        assert bio.lower_bound == 0
        assert bio.upper_bound == 1000
        assert bio.name == "Biomass"

    def test_biomass_stoichiometry(self, minimal_model_obj):
        model = workspace_model_to_cobra(minimal_model_obj)
        bio = model.reactions.get_by_id("bio1")
        met_atp = model.metabolites.get_by_id("cpd00002_c0")
        met_h2o = model.metabolites.get_by_id("cpd00001_c0")
        met_pi = model.metabolites.get_by_id("cpd00009_c0")
        assert bio.metabolites[met_atp] == -0.5
        assert bio.metabolites[met_h2o] == -10
        assert bio.metabolites[met_pi] == 1.0

    def test_objective_set_to_first_biomass(self, minimal_model_obj):
        model = workspace_model_to_cobra(minimal_model_obj)
        obj_rxn = list(model.objective.variables)
        # The objective should reference the biomass reaction
        assert any("bio1" in str(v) for v in obj_rxn)

    def test_exchange_reactions_for_e0(self, minimal_model_obj):
        model = workspace_model_to_cobra(minimal_model_obj)
        # cpd00027_e0 is in e0, should have an exchange reaction
        ex_rxns = [r for r in model.reactions if r.id.startswith("EX_")]
        assert len(ex_rxns) >= 1
        ex_ids = [r.id for r in ex_rxns]
        assert "EX_cpd00027_e0" in ex_ids

    def test_exchange_not_created_for_c0(self, minimal_model_obj):
        model = workspace_model_to_cobra(minimal_model_obj)
        ex_rxns = [r.id for r in model.reactions if r.id.startswith("EX_")]
        c0_exchanges = [eid for eid in ex_rxns if "_c0" in eid]
        assert len(c0_exchanges) == 0

    def test_exchange_reaction_bounds(self, minimal_model_obj):
        model = workspace_model_to_cobra(minimal_model_obj)
        ex = model.reactions.get_by_id("EX_cpd00027_e0")
        assert ex.lower_bound == -1000
        assert ex.upper_bound == 1000

    def test_empty_model(self):
        model = workspace_model_to_cobra({})
        assert isinstance(model, cobra.Model)
        assert len(model.reactions) == 0
        assert len(model.metabolites) == 0

    def test_model_id(self, minimal_model_obj):
        model = workspace_model_to_cobra(minimal_model_obj, model_id="my_model")
        assert model.id == "my_model"

    def test_default_model_id(self, minimal_model_obj):
        model = workspace_model_to_cobra(minimal_model_obj)
        assert model.id == "model"

    def test_reaction_count(self, minimal_model_obj):
        model = workspace_model_to_cobra(minimal_model_obj)
        # 3 model reactions + 1 biomass + 1 exchange = 5
        assert len(model.reactions) == 5

    def test_metabolite_count(self, minimal_model_obj):
        model = workspace_model_to_cobra(minimal_model_obj)
        assert len(model.metabolites) == 5
