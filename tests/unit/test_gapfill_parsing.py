"""Unit tests for gapfill solution parsing — all 4 storage formats must produce consistent output."""

import json
from unittest.mock import MagicMock

import pytest

from modelseed_api.services.model_service import ModelService

pytestmark = pytest.mark.unit


def _make_svc_with_model(model_obj):
    """Create a ModelService whose workspace returns model_obj for get()."""
    svc = object.__new__(ModelService)
    svc.token = "test"
    svc.ws = MagicMock()
    svc.ws.get.return_value = [[[], json.dumps(model_obj)]]
    return svc


class TestGapfillParsingLegacy:
    """Legacy KBase gapfillingSolutions array format."""

    def test_parse_legacy_solutions(self, gapfill_model_legacy):
        svc = _make_svc_with_model(gapfill_model_legacy)
        gf_list = svc.list_gapfill_solutions("/test/model")
        assert len(gf_list) == 1
        gf = gf_list[0]
        assert gf["id"] == "gf.0"
        assert gf["integrated"] is True
        assert len(gf["solution_reactions"]) >= 1
        # First solution should have 2 reactions
        sol_rxns = gf["solution_reactions"][0]
        assert len(sol_rxns) == 2

    def test_legacy_reaction_ids_have_compartment(self, gapfill_model_legacy):
        svc = _make_svc_with_model(gapfill_model_legacy)
        gf_list = svc.list_gapfill_solutions("/test/model")
        sol_rxns = gf_list[0]["solution_reactions"][0]
        rxn_ids = [r["reaction"] for r in sol_rxns]
        assert "rxn00062_c0" in rxn_ids
        assert "rxn00100_c0" in rxn_ids

    def test_legacy_directions(self, gapfill_model_legacy):
        svc = _make_svc_with_model(gapfill_model_legacy)
        gf_list = svc.list_gapfill_solutions("/test/model")
        sol_rxns = gf_list[0]["solution_reactions"][0]
        rxn_map = {r["reaction"]: r["direction"] for r in sol_rxns}
        assert rxn_map["rxn00062_c0"] == ">"
        assert rxn_map["rxn00100_c0"] == "="


class TestGapfillParsingMSPyString:
    """ModelSEEDpy string format: gapfill_data = {'gf.0': 'added:>'}."""

    def test_parse_mspy_string(self, gapfill_model_mspy_string):
        svc = _make_svc_with_model(gapfill_model_mspy_string)
        gf_list = svc.list_gapfill_solutions("/test/model")
        assert len(gf_list) == 1
        gf = gf_list[0]
        assert len(gf["solution_reactions"]) >= 1
        sol_rxns = gf["solution_reactions"][0]
        assert len(sol_rxns) == 2

    def test_mspy_string_directions(self, gapfill_model_mspy_string):
        svc = _make_svc_with_model(gapfill_model_mspy_string)
        gf_list = svc.list_gapfill_solutions("/test/model")
        sol_rxns = gf_list[0]["solution_reactions"][0]
        rxn_map = {r["reaction"]: r["direction"] for r in sol_rxns}
        assert rxn_map["rxn00062_c0"] == ">"
        assert rxn_map["rxn00100_c0"] == "="


class TestGapfillParsingMSPyDict:
    """ModelSEEDpy dict format: gapfill_data = {'gf.0': {'0': ['>', 1, []]}}."""

    def test_parse_mspy_dict(self, gapfill_model_mspy_dict):
        svc = _make_svc_with_model(gapfill_model_mspy_dict)
        gf_list = svc.list_gapfill_solutions("/test/model")
        assert len(gf_list) == 1
        gf = gf_list[0]
        assert len(gf["solution_reactions"]) >= 1
        sol_rxns = gf["solution_reactions"][0]
        assert len(sol_rxns) == 2

    def test_mspy_dict_directions(self, gapfill_model_mspy_dict):
        svc = _make_svc_with_model(gapfill_model_mspy_dict)
        gf_list = svc.list_gapfill_solutions("/test/model")
        sol_rxns = gf_list[0]["solution_reactions"][0]
        rxn_map = {r["reaction"]: r["direction"] for r in sol_rxns}
        assert rxn_map["rxn00062_c0"] == ">"
        assert rxn_map["rxn00100_c0"] == "="


class TestGapfillParsingSolutionData:
    """Stringified solutiondata JSON format."""

    def test_parse_solutiondata(self, gapfill_model_solutiondata):
        svc = _make_svc_with_model(gapfill_model_solutiondata)
        gf_list = svc.list_gapfill_solutions("/test/model")
        assert len(gf_list) == 1
        gf = gf_list[0]
        assert len(gf["solution_reactions"]) >= 1
        sol_rxns = gf["solution_reactions"][0]
        assert len(sol_rxns) == 2

    def test_solutiondata_directions(self, gapfill_model_solutiondata):
        svc = _make_svc_with_model(gapfill_model_solutiondata)
        gf_list = svc.list_gapfill_solutions("/test/model")
        sol_rxns = gf_list[0]["solution_reactions"][0]
        rxn_map = {r["reaction"]: r["direction"] for r in sol_rxns}
        assert rxn_map.get("rxn00062_c0", rxn_map.get("rxn00062")) == ">"
        assert rxn_map.get("rxn00100_c0", rxn_map.get("rxn00100")) == "="


class TestGapfillConsistency:
    """All 4 formats for the same reactions must produce consistent output."""

    def _extract_rxn_set(self, gf_list):
        """Extract set of (reaction, direction) tuples from parsed gapfill output."""
        if not gf_list or not gf_list[0]["solution_reactions"]:
            return set()
        sol = gf_list[0]["solution_reactions"][0]
        return {(r["reaction"], r["direction"]) for r in sol}

    def test_all_formats_have_same_reactions(
        self,
        gapfill_model_legacy,
        gapfill_model_mspy_string,
        gapfill_model_mspy_dict,
        gapfill_model_solutiondata,
    ):
        """Key test: all 4 formats must produce the same reactions with same directions."""
        legacy = self._extract_rxn_set(
            _make_svc_with_model(gapfill_model_legacy).list_gapfill_solutions("/m")
        )
        mspy_str = self._extract_rxn_set(
            _make_svc_with_model(gapfill_model_mspy_string).list_gapfill_solutions("/m")
        )
        mspy_dict = self._extract_rxn_set(
            _make_svc_with_model(gapfill_model_mspy_dict).list_gapfill_solutions("/m")
        )
        soldata = self._extract_rxn_set(
            _make_svc_with_model(gapfill_model_solutiondata).list_gapfill_solutions("/m")
        )

        # All should have 2 reactions
        assert len(legacy) == 2
        assert len(mspy_str) == 2
        assert len(mspy_dict) == 2
        assert len(soldata) == 2

        # Directions must match across formats
        # The reaction IDs may differ slightly (with/without compartment suffix)
        # so compare direction sets for each base reaction
        def _dir_map(rxn_set):
            return {rxn.replace("_c0", ""): d for rxn, d in rxn_set}

        legacy_dirs = _dir_map(legacy)
        mspy_str_dirs = _dir_map(mspy_str)
        mspy_dict_dirs = _dir_map(mspy_dict)
        soldata_dirs = _dir_map(soldata)

        assert legacy_dirs == mspy_str_dirs
        assert legacy_dirs == mspy_dict_dirs
        assert legacy_dirs == soldata_dirs

    def test_all_formats_have_gf_metadata(
        self,
        gapfill_model_legacy,
        gapfill_model_mspy_string,
        gapfill_model_mspy_dict,
        gapfill_model_solutiondata,
    ):
        """All formats should preserve gapfill metadata (id, rundate, media_ref)."""
        for model_obj in [
            gapfill_model_legacy,
            gapfill_model_mspy_string,
            gapfill_model_mspy_dict,
            gapfill_model_solutiondata,
        ]:
            svc = _make_svc_with_model(model_obj)
            gf_list = svc.list_gapfill_solutions("/m")
            assert gf_list[0]["id"] == "gf.0"
            assert gf_list[0]["rundate"] == "2026-01-01"
            assert "Complete" in gf_list[0]["media_ref"]


class TestGapfillEdgeCases:
    def test_empty_gapfillings(self):
        model = {"modelreactions": [], "gapfillings": []}
        svc = _make_svc_with_model(model)
        assert svc.list_gapfill_solutions("/m") == []

    def test_gapfill_no_solutions(self):
        model = {
            "modelreactions": [],
            "gapfillings": [
                {
                    "id": "gf.0",
                    "rundate": "",
                    "media_ref": "",
                    "integrated": False,
                    "integrated_solution": 0,
                    "fba_ref": "",
                }
            ],
        }
        svc = _make_svc_with_model(model)
        result = svc.list_gapfill_solutions("/m")
        assert len(result) == 1
        assert result[0]["solution_reactions"] == []

    def test_compartment_suffix_from_reaction_id(self, gapfill_model_mspy_string):
        svc = _make_svc_with_model(gapfill_model_mspy_string)
        gf_list = svc.list_gapfill_solutions("/m")
        sol_rxns = gf_list[0]["solution_reactions"][0]
        for r in sol_rxns:
            assert r["compartment"] == "c0"
