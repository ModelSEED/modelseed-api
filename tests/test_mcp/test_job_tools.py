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


class TestRunFBA:
    @patch(PATCH_STORE)
    @patch(PATCH_DISPATCHER)
    def test_dispatch(self, MockDispatcher, MockStore):
        MockDispatcher.return_value.dispatch.return_value = "fba-123"
        result = run_fba("/local/modelseed/model1", wait=False)
        assert result["job_id"] == "fba-123"


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


class TestResolveMedia:
    def test_already_path(self):
        assert jobs_mod._resolve_media("/some/path") == "/some/path"

    def test_name_to_path(self):
        result = jobs_mod._resolve_media("Complete")
        assert result.endswith("/Complete")
        assert result.startswith("/")
