"""Unit tests for _set_biomass_objective helper."""
import pytest

pytestmark = pytest.mark.unit


def _make_mock_model(reaction_ids):
    """Build a minimal mock cobra Model with the given reaction IDs."""
    import unittest.mock as mock

    reactions = []
    for rid in reaction_ids:
        r = mock.MagicMock()
        r.id = rid
        r.__str__ = lambda self: self.id
        reactions.append(r)

    model = mock.MagicMock()
    model.reactions = reactions
    model.objective = None
    return model


class TestSetBiomassObjective:
    def test_bio1_present_sets_bio1(self):
        from modelseed_api.jobs.tasks import _set_biomass_objective
        model = _make_mock_model(["rxn00001", "bio1", "rxn00002"])
        _set_biomass_objective(model)
        assert model.objective == "bio1"

    def test_no_bio1_falls_back_to_biomass_reaction(self):
        from modelseed_api.jobs.tasks import _set_biomass_objective
        model = _make_mock_model(["rxn00001", "bio2", "rxn00002"])
        _set_biomass_objective(model)
        assert model.objective == "bio2"

    def test_no_biomass_reaction_skips_silently(self):
        from modelseed_api.jobs.tasks import _set_biomass_objective
        model = _make_mock_model(["rxn00001", "rxn00002"])
        original = model.objective
        _set_biomass_objective(model)
        assert model.objective == original

    def test_empty_model_skips_silently(self):
        from modelseed_api.jobs.tasks import _set_biomass_objective
        model = _make_mock_model([])
        original = model.objective
        _set_biomass_objective(model)
        assert model.objective == original