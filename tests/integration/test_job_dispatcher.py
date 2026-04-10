"""Integration tests for JobDispatcher — subprocess dispatch with mocked Popen."""

import os
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def dispatcher(job_store_dir):
    """Create a JobDispatcher backed by a real JobStore in a temp dir."""
    from modelseed_api.jobs.dispatcher import JobDispatcher
    from modelseed_api.jobs.store import JobStore

    store = JobStore()
    return JobDispatcher(store), store


class TestDispatchSubprocess:
    @patch("modelseed_api.jobs.dispatcher.subprocess.Popen")
    def test_known_app_returns_job_id(self, mock_popen, dispatcher):
        disp, store = dispatcher
        # Ensure script exists
        script_path = disp.scripts_dir / "reconstruct.py"
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.touch()
        try:
            job_id = disp.dispatch("ModelReconstruction", {"genome": "83333.1"}, "user1", "token")
            assert job_id  # non-empty string
            mock_popen.assert_called_once()
        finally:
            script_path.unlink(missing_ok=True)

    @patch("modelseed_api.jobs.dispatcher.subprocess.Popen")
    def test_job_record_created(self, mock_popen, dispatcher):
        disp, store = dispatcher
        script_path = disp.scripts_dir / "reconstruct.py"
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.touch()
        try:
            job_id = disp.dispatch("ModelReconstruction", {"genome": "83333.1"}, "user1", "token")
            jobs = store.get_jobs("user1")
            assert job_id in jobs
            assert jobs[job_id]["app"] == "ModelReconstruction"
        finally:
            script_path.unlink(missing_ok=True)

    def test_unknown_app_fails_immediately(self, dispatcher):
        disp, store = dispatcher
        job_id = disp.dispatch("UnknownApp", {}, "user1", "token")
        jobs = store.get_jobs("user1")
        assert jobs[job_id]["status"] == "failed"
        assert "Unknown app" in jobs[job_id]["error"]

    def test_missing_script_fails(self, dispatcher):
        disp, store = dispatcher
        job_id = disp.dispatch("ModelReconstruction", {}, "user1", "token")
        jobs = store.get_jobs("user1")
        assert jobs[job_id]["status"] == "failed"
        assert "not found" in jobs[job_id]["error"]

    @patch("modelseed_api.jobs.dispatcher.subprocess.Popen")
    def test_large_params_written_to_file(self, mock_popen, dispatcher):
        disp, store = dispatcher
        script_path = disp.scripts_dir / "reconstruct.py"
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.touch()
        try:
            large_params = {"genome_fasta": "A" * 200_000}
            job_id = disp.dispatch("ModelReconstruction", large_params, "user1", "token")
            # Check that Popen was called with @-prefixed params arg
            call_args = mock_popen.call_args[0][0]
            params_arg = call_args[call_args.index("--params") + 1]
            assert params_arg.startswith("@")
        finally:
            script_path.unlink(missing_ok=True)

    @patch("modelseed_api.jobs.dispatcher.subprocess.Popen")
    def test_job_created_before_dispatch(self, mock_popen, dispatcher):
        """Race condition fix: job record must exist before subprocess starts."""
        disp, store = dispatcher
        script_path = disp.scripts_dir / "reconstruct.py"
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.touch()

        created_before_popen = []

        def check_job_exists(*args, **kwargs):
            jobs = store.get_jobs("user1")
            created_before_popen.append(len(jobs) > 0)
            return MagicMock()

        mock_popen.side_effect = check_job_exists
        try:
            disp.dispatch("ModelReconstruction", {}, "user1", "token")
            assert created_before_popen[0] is True
        finally:
            script_path.unlink(missing_ok=True)
