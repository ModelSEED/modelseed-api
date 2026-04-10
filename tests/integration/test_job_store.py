"""Integration tests for JobStore — job lifecycle with real JSON files."""

import json
import os

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def job_store(job_store_dir):
    """Create a JobStore backed by the temp dir."""
    from modelseed_api.jobs.store import JobStore

    return JobStore()


class TestJobLifecycle:
    def test_create_and_read(self, job_store):
        job_store.create_job(
            job_id="j-001",
            app="ModelReconstruction",
            parameters={"genome": "83333.1"},
            user="testuser",
            submit_time="2026-04-06-12:00:00",
        )
        jobs = job_store.get_jobs("testuser")
        assert "j-001" in jobs
        job = jobs["j-001"]
        assert job["id"] == "j-001"
        assert job["app"] == "ModelReconstruction"
        assert job["status"] == "queued"
        assert job["user"] == "testuser"
        assert job["submit_time"] == "2026-04-06-12:00:00"
        assert job["start_time"] is None
        assert job["completed_time"] is None

    def test_start_job(self, job_store):
        job_store.create_job("j-002", "GapfillModel", {}, "user1", "2026-04-06-12:00:00")
        job_store.start_job("j-002")
        jobs = job_store.get_jobs("user1")
        assert jobs["j-002"]["status"] == "in-progress"
        assert jobs["j-002"]["start_time"] is not None

    def test_complete_job(self, job_store):
        job_store.create_job("j-003", "FluxBalanceAnalysis", {}, "user1", "2026-04-06-12:00:00")
        job_store.start_job("j-003")
        job_store.complete_job("j-003")
        jobs = job_store.get_jobs("user1")
        assert jobs["j-003"]["status"] == "completed"
        assert jobs["j-003"]["completed_time"] is not None

    def test_fail_job(self, job_store):
        job_store.create_job("j-004", "ModelReconstruction", {}, "user1", "2026-04-06-12:00:00")
        job_store.fail_job("j-004", "genome not found")
        jobs = job_store.get_jobs("user1")
        assert jobs["j-004"]["status"] == "failed"
        assert jobs["j-004"]["error"] == "genome not found"
        assert jobs["j-004"]["completed_time"] is not None

    def test_delete_by_owner(self, job_store, job_store_dir):
        job_store.create_job("j-005", "ModelReconstruction", {}, "owner1", "2026-04-06-12:00:00")
        job_store.delete_job("j-005", "owner1")
        assert not (job_store_dir / "j-005.json").exists()

    def test_delete_wrong_user(self, job_store, job_store_dir):
        job_store.create_job("j-006", "ModelReconstruction", {}, "owner1", "2026-04-06-12:00:00")
        job_store.delete_job("j-006", "wrong_user")
        # File should still exist
        assert (job_store_dir / "j-006.json").exists()


class TestGetJobs:
    def test_filter_by_user(self, job_store):
        job_store.create_job("j-u1", "App", {}, "user1", "2026-04-06-12:00:00")
        job_store.create_job("j-u2", "App", {}, "user2", "2026-04-06-12:00:00")
        jobs = job_store.get_jobs("user1")
        assert "j-u1" in jobs
        assert "j-u2" not in jobs

    def test_filter_by_ids(self, job_store):
        job_store.create_job("j-a", "App", {}, "user1", "2026-04-06-12:00:00")
        job_store.create_job("j-b", "App", {}, "user1", "2026-04-06-12:00:00")
        job_store.create_job("j-c", "App", {}, "user1", "2026-04-06-12:00:00")
        jobs = job_store.get_jobs("user1", job_ids=["j-a", "j-c"])
        assert "j-a" in jobs
        assert "j-c" in jobs
        assert "j-b" not in jobs

    def test_no_jobs_returns_empty(self, job_store):
        assert job_store.get_jobs("no_such_user") == {}


class TestJobJsonSchema:
    def test_json_file_matches_schema(self, job_store, job_store_dir):
        job_store.create_job("j-schema", "ModelReconstruction", {"g": "1"}, "u", "2026-01-01")
        data = json.loads((job_store_dir / "j-schema.json").read_text())
        required_keys = {"id", "app", "parameters", "status", "submit_time",
                         "start_time", "completed_time", "user"}
        assert required_keys.issubset(data.keys())
