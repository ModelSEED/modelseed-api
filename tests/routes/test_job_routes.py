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
    # These tests exercise dispatch behavior, not preflight. Preflight gets
    # its own coverage in tests/unit/test_preflight.py + tests/live/. Pass
    # skip_validation=true to keep the focus on the dispatcher.
    def test_dispatch_returns_job_id(self, local_client, auth_headers):
        resp = local_client.post(
            "/api/jobs/reconstruct?skip_validation=true",
            json={"genome": "83333.1"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        job_id = resp.json()
        assert isinstance(job_id, str)
        assert len(job_id) > 0

    def test_with_protein_fasta(self, local_client, auth_headers):
        # FASTA path doesn't trigger genome preflight, but skip_validation
        # is still safe to pass (no-op).
        resp = local_client.post(
            "/api/jobs/reconstruct?skip_validation=true",
            json={"genome": "custom", "genome_fasta": ">prot\nMKKK"},
            headers=auth_headers,
        )
        assert resp.status_code == 200

    def test_with_dna_fasta(self, local_client, auth_headers):
        # DNA input is now first-class: schema accepts it, the task layer
        # routes it through the contig (gene calling + annotation) pipeline.
        resp = local_client.post(
            "/api/jobs/reconstruct?skip_validation=true",
            json={
                "genome": "custom",
                "genome_fasta": ">contig1\nGATATGGGACGTAGCTGCTAGCATCGATCGATCGTAGCTAG",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200

    def test_gzipped_fasta_rejected_before_dispatch(self, local_client, auth_headers):
        # A browser reading a .gz upload as text: gzip magic + U+FFFD noise.
        garbled = "\x1f\ufffd\x08\x08\ufffdFQXK01.1.fsa_nt\x00\ufffd>\ufffd\n\ufffd"
        resp = local_client.post(
            "/api/jobs/reconstruct?skip_validation=true",
            json={"genome": "custom", "genome_fasta": garbled},
            headers=auth_headers,
        )
        assert resp.status_code == 422
        assert "gzip-compressed" in resp.text


class TestPlantReconstructJob:
    PROTEINS = ">Potri.001G000100.1.p\nMKVLAAGLLSTPQ\n>Potri.001G000200.1.p\nMSDEEKLR\n"

    @pytest.fixture
    def dispatched(self, monkeypatch):
        from modelseed_api.config import settings
        from modelseed_api.routes import jobs as job_routes

        monkeypatch.setattr(settings, "plantseed_url", "http://plantseed-mcp:8931/mcp")
        calls = []

        def fake_dispatch(app, parameters, user, token):
            calls.append({"app": app, "parameters": parameters, "user": user})
            return "plant-job-id"

        monkeypatch.setattr(job_routes._dispatcher, "dispatch", fake_dispatch)
        return calls

    def _post(self, client, headers, **body):
        payload = {"genome": "Ptrichocarpa", "template_type": "plant",
                   "genome_fasta": self.PROTEINS, **body}
        return client.post("/api/jobs/reconstruct", json=payload, headers=headers)

    def test_dispatches_plant_app(self, local_client, auth_headers, dispatched):
        resp = self._post(local_client, auth_headers, query_species="Ptrichocarpa_v4.1")
        assert resp.status_code == 200
        assert resp.json() == "plant-job-id"
        (call,) = dispatched
        assert call["app"] == "PlantReconstruction"
        assert call["parameters"] == {
            "genome": "Ptrichocarpa",
            "genome_fasta": self.PROTEINS,
            "query_species": "Ptrichocarpa_v4.1",
            "output_path": None,
        }

    def test_microbial_requests_still_use_model_reconstruction(
        self, local_client, auth_headers, dispatched
    ):
        resp = local_client.post(
            "/api/jobs/reconstruct?skip_validation=true",
            json={"genome": "custom", "genome_fasta": ">p\nMKKK"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert dispatched[0]["app"] == "ModelReconstruction"

    @pytest.mark.parametrize("body,message", [
        ({"genome_fasta": None}, "requires genome_fasta"),
        ({"rast_job_id": "1", "rast_genome_id": "2.1"}, "mutually exclusive"),
        ({"query_species": "bad species!"}, "query_species"),
    ])
    def test_invalid_plant_requests_rejected(
        self, local_client, auth_headers, dispatched, body, message
    ):
        resp = self._post(local_client, auth_headers, **body)
        assert resp.status_code == 422
        assert message in resp.text
        assert dispatched == []

    def test_gapfill_and_media_ignored(self, local_client, auth_headers, dispatched):
        resp = self._post(local_client, auth_headers, gapfill=True, media="Complete")
        assert resp.status_code == 200
        (call,) = dispatched
        assert call["app"] == "PlantReconstruction"
        assert "gapfill" not in call["parameters"]
        assert "media" not in call["parameters"]

    def test_query_species_rejected_for_microbial(self, local_client, auth_headers, dispatched):
        resp = local_client.post(
            "/api/jobs/reconstruct?skip_validation=true",
            json={"genome": "custom", "genome_fasta": ">p\nMKKK", "query_species": "Sp"},
            headers=auth_headers,
        )
        assert resp.status_code == 422
        assert "only to template_type='plant'" in resp.text

    def test_output_path_preflight_applies(self, local_client, auth_headers, dispatched):
        resp = self._post(local_client, auth_headers, output_path="/someoneelse/plantseed/x")
        assert resp.status_code == 403
        assert dispatched == []

    def test_unconfigured_service_returns_503_without_dispatch(
        self, local_client, auth_headers, dispatched, monkeypatch
    ):
        from modelseed_api.config import settings

        monkeypatch.setattr(settings, "plantseed_url", "")
        resp = self._post(local_client, auth_headers)
        assert resp.status_code == 503
        assert resp.json()["detail"]["code"] == "PLANTSEED_UNAVAILABLE"
        assert dispatched == []

    def test_unconfigured_service_does_not_affect_microbial(
        self, local_client, auth_headers, dispatched, monkeypatch
    ):
        from modelseed_api.config import settings

        monkeypatch.setattr(settings, "plantseed_url", "")
        resp = local_client.post(
            "/api/jobs/reconstruct?skip_validation=true",
            json={"genome": "custom", "genome_fasta": ">p\nMKKK"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert dispatched[0]["app"] == "ModelReconstruction"

    def test_dispatcher_maps_plant_app(self):
        from modelseed_api.jobs.dispatcher import JobDispatcher

        assert JobDispatcher.CELERY_TASK_MAP["PlantReconstruction"] == "modelseed.plant_reconstruct"
        assert JobDispatcher.SCRIPT_MAP["PlantReconstruction"] == "plant_reconstruct.py"


class TestGapfillJob:
    def test_dispatch(self, local_client, auth_headers):
        resp = local_client.post(
            "/api/jobs/gapfill?skip_validation=true",
            json={"model": "/local/modelseed/TestModel"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), str)


class TestFBAJob:
    def test_dispatch(self, local_client, auth_headers):
        resp = local_client.post(
            "/api/jobs/fba?skip_validation=true",
            json={"model": "/local/modelseed/TestModel"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), str)


class TestMergeJob:
    def test_not_implemented(self, local_client, auth_headers):
        """Merge is not yet implemented; the route returns 501 immediately (no job dispatched)."""
        resp = local_client.post(
            "/api/jobs/merge?skip_validation=true",
            json={
                "models": [
                    ["/local/modelseed/a", 0.5],
                    ["/local/modelseed/b", 0.5],
                ],
                "output_file": "merged",
                "output_path": "/local/modelseed/merged",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 501


class TestManageJobs:
    def test_delete_action(self, local_client, auth_headers):
        # First create a job (skip_validation to avoid preflight)
        resp = local_client.post(
            "/api/jobs/reconstruct?skip_validation=true",
            json={"genome": "83333.1"},
            headers=auth_headers,
        )
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
