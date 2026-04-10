"""Route tests for /api/jobs endpoints."""

import pytest

pytestmark = pytest.mark.integration


class TestCheckJobs:
    def test_no_jobs(self, local_client):
        resp = local_client.get("/api/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_filter_by_ids(self, local_client):
        resp = local_client.get("/api/jobs?ids=nonexistent-id")
        assert resp.status_code == 200
        assert resp.json() == {}


class TestReconstructJob:
    def test_dispatch_returns_job_id(self, local_client, auth_headers):
        resp = local_client.post("/api/jobs/reconstruct", json={
            "genome": "83333.1",
        }, headers=auth_headers)
        assert resp.status_code == 200
        job_id = resp.json()
        assert isinstance(job_id, str)
        assert len(job_id) > 0

    def test_with_genome_fasta(self, local_client, auth_headers):
        resp = local_client.post("/api/jobs/reconstruct", json={
            "genome": "custom",
            "genome_fasta": ">prot\nMKKK",
        }, headers=auth_headers)
        assert resp.status_code == 200


class TestGapfillJob:
    def test_dispatch(self, local_client, auth_headers):
        resp = local_client.post("/api/jobs/gapfill", json={
            "model": "/local/modelseed/TestModel",
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), str)


class TestFBAJob:
    def test_dispatch(self, local_client, auth_headers):
        resp = local_client.post("/api/jobs/fba", json={
            "model": "/local/modelseed/TestModel",
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), str)


class TestMergeJob:
    def test_dispatch(self, local_client, auth_headers):
        resp = local_client.post("/api/jobs/merge", json={
            "models": [
                ["/local/modelseed/a", 0.5],
                ["/local/modelseed/b", 0.5],
            ],
            "output_file": "merged",
            "output_path": "/local/modelseed/merged",
        }, headers=auth_headers)
        assert resp.status_code == 200


class TestManageJobs:
    def test_delete_action(self, local_client, auth_headers):
        # First create a job
        resp = local_client.post("/api/jobs/reconstruct", json={
            "genome": "83333.1",
        }, headers=auth_headers)
        job_id = resp.json()

        # Delete it
        resp = local_client.post("/api/jobs/manage", json={
            "jobs": [job_id],
            "action": "d",
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()[job_id]["status"] == "deleted"

    def test_rerun_not_implemented(self, local_client, auth_headers):
        resp = local_client.post("/api/jobs/manage", json={
            "jobs": ["some-id"],
            "action": "r",
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert "not yet implemented" in resp.json()["some-id"]["status"]
