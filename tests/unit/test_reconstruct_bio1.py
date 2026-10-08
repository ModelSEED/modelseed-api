"""Unit tests: reconstruct task returns failed dict when model has no bio1 reaction.

The root cause of issue #36 (modelseed-api-ops) was: tasks.py raised a RuntimeError for a user-input condition
(genome too small / wrong template), which triggered a Celery task-failure alert.
The fix changes that path to return {"status": "failed", ...} like other graceful-failure paths in the same function.
"""
from __future__ import annotations

import pytest

from unittest.mock import MagicMock, patch


def _make_mock_mdlutl(reaction_ids):
    """Return a minimal mock mdlutl with the given reaction ids."""
    mock_reactions = [MagicMock(id=rid) for rid in reaction_ids]
    mock_model = MagicMock()
    mock_model.reactions = mock_reactions
    mock_model.genes = []
    mock_model.metabolites = []
    mock_model.compartments = {}
    mock_model.get_data = MagicMock(return_value={"biomasses": []})
    mock_mdlutl = MagicMock()
    mock_mdlutl.model = mock_model
    return mock_mdlutl


class TestReconstructBio1Check:
    """Bio1 check in reconstruct should return a failed-status dict
    (not raise RuntimeError) when the reconstructed model has no bio1 bo1
    reaction -- this is a user-input condition, not a code bug."""

    def _run_reconstruct_to_bio1_check(self, mdlutl):
        """Common harness: patch all heavy deps and run reconstruct with output_path."""
        from modelseed_api.jobs.tasks import reconstruct

        mock_task = MagicMock()
        mock_task.update_state = MagicMock()

        mock_recon = MagicMock()
        mock_recon.get_msgenome_from_dict.return_value = MagicMock()
        mock_recon.build_metabolic_model.return_value = (
            {"Reactions": 0, "Model genes": 0, "Class": "Gram Negative"},
            mdlutl,
        )
        mock_bvbrc = MagicMock()
        mock_ws = MagicMock()

        with (patch("modelseed_api.jobs.tasks._init_kwargs", return_value={}),
             patch("modelseed_api.jobs.tasks._load_template", return_value=MagicMock()),
             patch("modelseed_api.jobs.tasks._classify_genome", return_value=("Gram Negative", "gn")),
             patch("modelseed_api.jobs.tasks._fetch_bvbrc_genome", return_value={"scientific_name": "E. coli", "taxonomy": "", "domain": ""}),
             patch("kbutillib.BVBRCUtils", return_value=mock_bvbrc),
             patch("kbutillib.MSReconstructionUtils", return_value=mock_recon),
             patch("modelseed_api.services.storage_factory.get_storage_service", return_value=mock_ws)):
            return reconstruct(
                mock_task,
                token="un=testuser|tokenid=tok123|expiry=9999999999|sig=test",
                genome="83332.12",
                template_type="ar",
                output_path="/testuser/modelseed/83332.12",
            )

    def test_missing_bio1_returns_failed_dict(self):
        """When reconstruction produces a model without a bio1 reaction,
        the task should return {'status': 'failed'} instead of raising.

        Regression test for modelseed-api-ops issue #36:
        no-bio1 used to raise RuntimeError, triggering a Celery
        task-failure alert for a user-input problem.
        """
        mdlutl = _make_mock_mdlutl([])  # no reactions at all -- no bio1
        result = self._run_reconstruct_to_bio1_check(mdlutl)
        assert result["status"] == "failed"
        assert "bio1" in result["error"]

    def test_missing_bio1_does_not_raise(self):
        """Ensure RuntimeError is not raised for the no-bio1 case."""
        mdlutl = _make_mock_mdlutl(["rxn001", "rxn002"])  # no bio1
        # Should return a dict, not raise
        result = self._run_reconstruct_to_bio1_check(mdlutl)
        assert isinstance(result, dict)
        assert result["status"] == "failed"
