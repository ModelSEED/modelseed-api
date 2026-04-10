"""Tests for MCP async job tools."""

from unittest.mock import patch

import modelseed_mcp.tools.jobs as jobs_mod

# Access underlying functions from FunctionTool wrappers
build_model = jobs_mod.build_model.fn
gapfill_model = jobs_mod.gapfill_model.fn
run_fba = jobs_mod.run_fba.fn
merge_models = jobs_mod.merge_models.fn
check_job = jobs_mod.check_job.fn

PATCH_DISPATCHER = "modelseed_api.jobs.dispatcher.JobDispatcher"
PATCH_STORE = "modelseed_api.jobs.store.JobStore"


class TestBuildModel:
    @patch(PATCH_STORE)
    @patch(PATCH_DISPATCHER)
    def test_dispatch_no_wait(self, MockDispatcher, MockStore):
        MockDispatcher.return_value.dispatch.return_value = "job-123"
        result = build_model("83333.1", wait=False)
        assert result["job_id"] == "job-123"
        assert result["status"] == "queued"
        MockDispatcher.return_value.dispatch.assert_called_once()
        args = MockDispatcher.return_value.dispatch.call_args
        assert args[0][0] == "ModelReconstruction"
        assert args[0][1]["genome"] == "83333.1"

    @patch(PATCH_STORE)
    @patch(PATCH_DISPATCHER)
    def test_dispatch_with_fasta(self, MockDispatcher, MockStore):
        MockDispatcher.return_value.dispatch.return_value = "job-456"
        build_model("custom", genome_fasta=">prot\nMKKK", wait=False)
        params = MockDispatcher.return_value.dispatch.call_args[0][1]
        assert params["genome_fasta"] == ">prot\nMKKK"

    @patch(PATCH_STORE)
    @patch(PATCH_DISPATCHER)
    def test_poll_completed(self, MockDispatcher, MockStore):
        MockDispatcher.return_value.dispatch.return_value = "job-789"
        MockStore.return_value.get_jobs.return_value = {
            "job-789": {
                "status": "completed",
                "result": {"status": "success", "reactions": 100},
            }
        }
        result = build_model("83333.1", wait=True, timeout=5)
        assert result["status"] == "completed"
        assert result["result"]["reactions"] == 100

    @patch(PATCH_STORE)
    @patch(PATCH_DISPATCHER)
    def test_poll_failed(self, MockDispatcher, MockStore):
        MockDispatcher.return_value.dispatch.return_value = "job-fail"
        MockStore.return_value.get_jobs.return_value = {
            "job-fail": {
                "status": "failed",
                "error": "genome not found",
            }
        }
        result = build_model("bad_id", wait=True, timeout=5)
        assert result["status"] == "failed"
        assert "genome not found" in result["error"]

    @patch(PATCH_STORE)
    @patch(PATCH_DISPATCHER)
    def test_default_output_path(self, MockDispatcher, MockStore):
        """Default output_path should be /local/modelseed/{genome}."""
        MockDispatcher.return_value.dispatch.return_value = "job-x"
        build_model("83333.1", wait=False)
        params = MockDispatcher.return_value.dispatch.call_args[0][1]
        assert params["output_path"] == "/local/modelseed/83333.1"

    @patch(PATCH_STORE)
    @patch(PATCH_DISPATCHER)
    def test_custom_output_path(self, MockDispatcher, MockStore):
        """Custom output_path should override default."""
        MockDispatcher.return_value.dispatch.return_value = "job-x"
        build_model("83333.1", output_path="/local/custom/model", wait=False)
        params = MockDispatcher.return_value.dispatch.call_args[0][1]
        assert params["output_path"] == "/local/custom/model"

    @patch(PATCH_STORE)
    @patch(PATCH_DISPATCHER)
    def test_gapfill_with_media(self, MockDispatcher, MockStore):
        """When gapfill=True and media provided, media should be resolved."""
        MockDispatcher.return_value.dispatch.return_value = "job-x"
        build_model("83333.1", gapfill=True, media="Complete", wait=False)
        params = MockDispatcher.return_value.dispatch.call_args[0][1]
        assert params["gapfill"] is True
        assert "Complete" in params["media"]

    @patch(PATCH_STORE)
    @patch(PATCH_DISPATCHER)
    def test_no_media_is_none(self, MockDispatcher, MockStore):
        """When media is not provided, params['media'] should be None."""
        MockDispatcher.return_value.dispatch.return_value = "job-x"
        build_model("83333.1", wait=False)
        params = MockDispatcher.return_value.dispatch.call_args[0][1]
        assert params["media"] is None

    @patch(PATCH_STORE)
    @patch(PATCH_DISPATCHER)
    def test_empty_fasta_not_added(self, MockDispatcher, MockStore):
        """Empty genome_fasta string should not be added to params."""
        MockDispatcher.return_value.dispatch.return_value = "job-x"
        build_model("custom", genome_fasta="", wait=False)
        params = MockDispatcher.return_value.dispatch.call_args[0][1]
        assert "genome_fasta" not in params

    @patch(PATCH_STORE)
    @patch(PATCH_DISPATCHER)
    def test_atp_safe_always_true(self, MockDispatcher, MockStore):
        """atp_safe should always be True in dispatched params."""
        MockDispatcher.return_value.dispatch.return_value = "job-x"
        build_model("83333.1", wait=False)
        params = MockDispatcher.return_value.dispatch.call_args[0][1]
        assert params["atp_safe"] is True

    @patch(PATCH_STORE)
    @patch(PATCH_DISPATCHER)
    def test_queued_message(self, MockDispatcher, MockStore):
        """Non-waiting dispatch should include a message about check_job."""
        MockDispatcher.return_value.dispatch.return_value = "job-x"
        result = build_model("83333.1", wait=False)
        assert "message" in result
        assert "check_job" in result["message"]


class TestGapfillModel:
    @patch(PATCH_STORE)
    @patch(PATCH_DISPATCHER)
    def test_dispatch(self, MockDispatcher, MockStore):
        MockDispatcher.return_value.dispatch.return_value = "gf-123"
        result = gapfill_model("/local/modelseed/model1", media="Complete", wait=False)
        assert result["job_id"] == "gf-123"
        params = MockDispatcher.return_value.dispatch.call_args[0][1]
        assert params["model"] == "/local/modelseed/model1"
        assert "Complete" in params["media"]

    @patch(PATCH_STORE)
    @patch(PATCH_DISPATCHER)
    def test_no_media(self, MockDispatcher, MockStore):
        """Gapfill with no media should set params['media'] to None."""
        MockDispatcher.return_value.dispatch.return_value = "gf-x"
        gapfill_model("/local/modelseed/model1", wait=False)
        params = MockDispatcher.return_value.dispatch.call_args[0][1]
        assert params["media"] is None

    @patch(PATCH_STORE)
    @patch(PATCH_DISPATCHER)
    def test_template_type_passed(self, MockDispatcher, MockStore):
        """template_type should be passed through to params."""
        MockDispatcher.return_value.dispatch.return_value = "gf-x"
        gapfill_model("/local/modelseed/model1", template_type="gp", wait=False)
        params = MockDispatcher.return_value.dispatch.call_args[0][1]
        assert params["template_type"] == "gp"

    @patch(PATCH_STORE)
    @patch(PATCH_DISPATCHER)
    def test_app_name_is_gapfill(self, MockDispatcher, MockStore):
        """App name should be GapfillModel."""
        MockDispatcher.return_value.dispatch.return_value = "gf-x"
        gapfill_model("/local/modelseed/model1", wait=False)
        assert MockDispatcher.return_value.dispatch.call_args[0][0] == "GapfillModel"


class TestRunFBA:
    @patch(PATCH_STORE)
    @patch(PATCH_DISPATCHER)
    def test_dispatch(self, MockDispatcher, MockStore):
        MockDispatcher.return_value.dispatch.return_value = "fba-123"
        result = run_fba("/local/modelseed/model1", wait=False)
        assert result["job_id"] == "fba-123"

    @patch(PATCH_STORE)
    @patch(PATCH_DISPATCHER)
    def test_app_name_is_fba(self, MockDispatcher, MockStore):
        """App name should be FluxBalanceAnalysis."""
        MockDispatcher.return_value.dispatch.return_value = "fba-x"
        run_fba("/local/modelseed/model1", wait=False)
        assert MockDispatcher.return_value.dispatch.call_args[0][0] == "FluxBalanceAnalysis"

    @patch(PATCH_STORE)
    @patch(PATCH_DISPATCHER)
    def test_media_resolved(self, MockDispatcher, MockStore):
        """Media name should be resolved to full path."""
        MockDispatcher.return_value.dispatch.return_value = "fba-x"
        run_fba("/local/modelseed/model1", media="Complete", wait=False)
        params = MockDispatcher.return_value.dispatch.call_args[0][1]
        assert params["media"].endswith("/Complete")
        assert params["media"].startswith("/")


class TestMergeModels:
    @patch(PATCH_STORE)
    @patch(PATCH_DISPATCHER)
    def test_dispatch(self, MockDispatcher, MockStore):
        MockDispatcher.return_value.dispatch.return_value = "merge-123"
        result = merge_models(
            [{"model_ref": "/local/modelseed/a", "abundance": 0.5},
             {"model_ref": "/local/modelseed/b", "abundance": 0.5}],
            output_file="merged",
            output_path="/local/modelseed/merged",
            wait=False,
        )
        assert result["job_id"] == "merge-123"

    @patch(PATCH_STORE)
    @patch(PATCH_DISPATCHER)
    def test_model_tuples_format(self, MockDispatcher, MockStore):
        """Models should be converted to tuples of (ref, abundance)."""
        MockDispatcher.return_value.dispatch.return_value = "merge-x"
        merge_models(
            [{"model_ref": "/local/a", "abundance": 0.7},
             {"model_ref": "/local/b", "abundance": 0.3}],
            output_file="out",
            output_path="/local/out",
            wait=False,
        )
        params = MockDispatcher.return_value.dispatch.call_args[0][1]
        assert params["models"] == [("/local/a", 0.7), ("/local/b", 0.3)]

    @patch(PATCH_STORE)
    @patch(PATCH_DISPATCHER)
    def test_app_name_is_merge(self, MockDispatcher, MockStore):
        """App name should be MergeModels."""
        MockDispatcher.return_value.dispatch.return_value = "merge-x"
        merge_models(
            [{"model_ref": "/local/a", "abundance": 1.0}],
            output_file="out",
            output_path="/local/out",
            wait=False,
        )
        assert MockDispatcher.return_value.dispatch.call_args[0][0] == "MergeModels"


class TestCheckJob:
    @patch(PATCH_STORE)
    def test_found(self, MockStore):
        MockStore.return_value.get_jobs.return_value = {
            "job-123": {
                "app": "ModelReconstruction",
                "status": "in-progress",
                "submit_time": "2026-04-06-12:00:00",
                "progress": "Building model...",
            }
        }
        result = check_job("job-123")
        assert result["status"] == "in-progress"
        assert result["app"] == "ModelReconstruction"

    @patch(PATCH_STORE)
    def test_not_found(self, MockStore):
        MockStore.return_value.get_jobs.return_value = {}
        result = check_job("nonexistent")
        assert "error" in result

    @patch(PATCH_STORE)
    def test_not_found_has_suggestions(self, MockStore):
        """Not-found should include helpful suggestions."""
        MockStore.return_value.get_jobs.return_value = {}
        result = check_job("nonexistent")
        assert "suggestions" in result
        assert len(result["suggestions"]) > 0

    @patch(PATCH_STORE)
    def test_empty_job_id(self, MockStore):
        """Empty string job_id should return error."""
        MockStore.return_value.get_jobs.return_value = {}
        result = check_job("")
        assert "error" in result

    @patch(PATCH_STORE)
    def test_all_fields_present(self, MockStore):
        """Found job should have all expected fields."""
        MockStore.return_value.get_jobs.return_value = {
            "job-full": {
                "app": "GapfillModel",
                "status": "completed",
                "submit_time": "2026-04-06-12:00:00",
                "start_time": "2026-04-06-12:00:01",
                "completed_time": "2026-04-06-12:01:00",
                "progress": "Done",
                "result": {"reactions_added": 5},
                "error": None,
            }
        }
        result = check_job("job-full")
        expected_keys = {"job_id", "app", "status", "submit_time", "start_time",
                         "completed_time", "progress", "result", "error"}
        assert set(result.keys()) == expected_keys
        assert result["job_id"] == "job-full"
        assert result["result"]["reactions_added"] == 5

    @patch(PATCH_STORE)
    def test_missing_optional_fields(self, MockStore):
        """Job with minimal fields should still return all keys with None defaults."""
        MockStore.return_value.get_jobs.return_value = {
            "job-min": {"status": "queued"}
        }
        result = check_job("job-min")
        assert result["status"] == "queued"
        assert result["app"] == "unknown"
        assert result["submit_time"] is None
        assert result["start_time"] is None


class TestResolveMedia:
    def test_already_path(self):
        assert jobs_mod._resolve_media("/some/path") == "/some/path"

    def test_name_to_path(self):
        result = jobs_mod._resolve_media("Complete")
        assert result.endswith("/Complete")
        assert result.startswith("/")

    def test_path_with_subdirs(self):
        """Path starting with / should be returned as-is, even with subdirs."""
        assert jobs_mod._resolve_media("/custom/media/path") == "/custom/media/path"

    def test_name_with_extension(self):
        """Media name with .json extension should still be appended to path."""
        result = jobs_mod._resolve_media("Complete.json")
        assert result.endswith("/Complete.json")

    def test_name_produces_valid_path(self):
        """Resolved name should start with the public media path prefix."""
        result = jobs_mod._resolve_media("ArgonneLBMedia")
        assert "/chenry/public/modelsupport/media/" in result
