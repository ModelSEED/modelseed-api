"""Unit tests for _load_media and _apply_media.

Regression tests for the bug where _load_media raised ValueError for the
Empty media (zero compounds), and _apply_media left default exchange bounds
instead of closing all exchanges for an empty MSMedia.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from modelseed_api.jobs.tasks import _apply_media, _load_media


def _mock_storage(raw_data):
    """Return a mock storage service that serves raw_data for any path."""
    ws = MagicMock()
    ws.get.return_value = [[None, raw_data]]
    return ws


class TestLoadMediaEmpty:
    def test_empty_json_returns_zero_compound_msmedia(self):
        raw = json.dumps({"mediacompounds": []})
        with patch("modelseed_api.jobs.tasks.get_storage_service", return_value=_mock_storage(raw)):
            ms_media = _load_media("/chenry/public/modelsupport/media/Empty", "tok")
        assert ms_media is not None
        assert len(ms_media.mediacompounds) == 0

    def test_empty_dict_returns_zero_compound_msmedia(self):
        raw = {"mediacompounds": []}
        with patch("modelseed_api.jobs.tasks.get_storage_service", return_value=_mock_storage(raw)):
            ms_media = _load_media("/chenry/public/modelsupport/media/Empty", "tok")
        assert ms_media is not None
        assert len(ms_media.mediacompounds) == 0

    def test_nonempty_media_still_loads_compounds(self):
        raw = {"mediacompounds": [{"compound_ref": "~/compounds/cpd00001", "concentration": 0.001, "minFlux": -100, "maxFlux": 100}]}
        with patch("modelseed_api.jobs.tasks.get_storage_service", return_value=_mock_storage(raw)):
            ms_media = _load_media("/chenry/public/modelsupport/media/NMS", "tok")
        assert len(ms_media.mediacompounds) == 1


class TestApplyMediaEmpty:
    def _make_cobra_model(self, exchange_ids):
        model = MagicMock()
        reactions = [MagicMock(id=rid) for rid in exchange_ids]
        model.reactions = reactions
        model.medium = {"EX_cpd00001_e0": 100.0}
        return model

    def test_empty_media_closes_all_exchanges(self):
        from modelseedpy.core.msmedia import MSMedia
        ms_media = MSMedia("Empty", name="Empty")
        cobra_model = self._make_cobra_model(["EX_cpd00001_e0", "EX_cpd00002_e0"])

        _apply_media(cobra_model, ms_media)

        cobra_model.__setattr__
        assert cobra_model.medium == {}

    def test_media_with_matching_compounds_opens_exchanges(self):
        from modelseedpy.core.msmedia import MSMedia, MediaCompound
        ms_media = MSMedia("NMS", name="NMS")
        ms_media.mediacompounds.append(MediaCompound("cpd00001", 100.0, -100.0))

        cobra_model = self._make_cobra_model(["EX_cpd00001_e0", "EX_cpd00002_e0"])
        _apply_media(cobra_model, ms_media)

        assert cobra_model.medium == {"EX_cpd00001_e0": 100.0}

    def test_media_with_no_matching_reactions_leaves_default_bounds(self):
        """Compounds present but none match model reactions -- not an Empty case."""
        from modelseedpy.core.msmedia import MSMedia, MediaCompound
        ms_media = MSMedia("Weird", name="Weird")
        ms_media.mediacompounds.append(MediaCompound("cpd99999", 100.0, -100.0))

        original_medium = {"EX_cpd00001_e0": 100.0}
        cobra_model = self._make_cobra_model(["EX_cpd00001_e0"])
        cobra_model.medium = original_medium.copy()

        _apply_media(cobra_model, ms_media)

        assert cobra_model.medium == original_medium
