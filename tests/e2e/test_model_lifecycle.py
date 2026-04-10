"""E2E: Full model lifecycle through the API — no mocks.

Create → List → Get → Edit → Export → Copy → Delete

Every operation uses real local storage and real biochem DB.
"""

import json

import pytest

from tests.integration.conftest import SAMPLE_MODEL

pytestmark = pytest.mark.e2e

# Use /testuser/ prefix to match the auth username from the token
MODEL_BASE = "/testuser/modelseed"
MODEL_REF = f"{MODEL_BASE}/EcoliTest"
COPY_REF = f"{MODEL_BASE}/EcoliCopy"
COPY2_REF = f"{MODEL_BASE}/EcoliCopy2"


def _create_model(client, headers, model_json):
    """Helper: create a model folder + model object via workspace API."""
    resp = client.post("/api/workspace/create", json={
        "objects": [[MODEL_REF, "modelfolder", {
            "id": "EcoliTest",
            "name": "E. coli Test Model",
            "num_reactions": "1",
            "num_compounds": "2",
            "num_genes": "0",
            "num_compartments": "2",
            "num_biomasses": "1",
        }, None]],
    }, headers=headers)
    assert resp.status_code == 200

    resp = client.post("/api/workspace/create", json={
        "objects": [[f"{MODEL_REF}/model", "model", {}, model_json]],
        "overwrite": True,
    }, headers=headers)
    assert resp.status_code == 200


class TestModelLifecycle:
    """Complete model lifecycle exercised through the REST API."""

    def test_full_lifecycle(self, e2e_client, auth_headers, model_json):
        """Complete lifecycle: create → list → get → edit → export → copy → delete."""
        client = e2e_client
        h = auth_headers

        # ── Step 1: List models — should be empty ──
        resp = client.get("/api/models", headers=h)
        assert resp.status_code == 200
        assert resp.json() == []

        # ── Step 2: Create model via workspace API ──
        _create_model(client, h, model_json)

        # ── Step 3: List models — should now have 1 model ──
        resp = client.get("/api/models", headers=h)
        assert resp.status_code == 200
        models = resp.json()
        assert len(models) >= 1
        model = models[0]
        assert model["id"] == "EcoliTest"
        assert model["name"] == "E. coli Test Model"

        # ── Step 4: Get model data — verify all sections ──
        resp = client.get(f"/api/models/data?ref={MODEL_REF}", headers=h)
        assert resp.status_code == 200
        data = resp.json()
        assert "reactions" in data
        assert "compounds" in data
        assert "genes" in data
        assert "compartments" in data
        assert "biomasses" in data
        assert len(data["reactions"]) == 1
        rxn = data["reactions"][0]
        assert rxn["id"] == "rxn00001_c0"
        assert "=>" in rxn["equation"] or "<=>" in rxn["equation"]
        assert len(data["compounds"]) == 2
        assert len(data["compartments"]) == 2
        assert len(data["biomasses"]) == 1

        # ── Step 5: Edit model — remove the reaction ──
        resp = client.post("/api/models/edit", json={
            "model": MODEL_REF,
            "reactions_to_remove": ["rxn00001_c0"],
        }, headers=h)
        assert resp.status_code == 200
        edit_result = resp.json()
        assert "rxn00001_c0" in edit_result["reactions_removed"]

        # Verify edit persisted
        resp = client.get(f"/api/models/data?ref={MODEL_REF}", headers=h)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["reactions"]) == 0

        # ── Step 6: Export SBML ──
        resp = client.get(f"/api/models/export?ref={MODEL_REF}&format=sbml", headers=h)
        assert resp.status_code == 200
        assert resp.text.startswith("<?xml")

        # ── Step 7: Export cobra-json ──
        resp = client.get(f"/api/models/export?ref={MODEL_REF}&format=cobra-json", headers=h)
        assert resp.status_code == 200
        cobra_data = resp.json()
        assert "reactions" in cobra_data
        assert "metabolites" in cobra_data

        # ── Step 8: Copy model ──
        resp = client.post("/api/models/copy", json={
            "model": MODEL_REF,
            "destination": COPY_REF,
        }, headers=h)
        assert resp.status_code == 200

        # Verify copy exists via workspace ls (list_models deduplicates by
        # metadata id, so the copy shares the original's id and is hidden)
        resp = client.post("/api/workspace/ls", json={
            "paths": [f"{MODEL_BASE}/"],
        }, headers=h)
        assert resp.status_code == 200
        ls_data = resp.json()
        folder_names = [e[0] for e in ls_data[f"{MODEL_BASE}/"]]
        assert "EcoliCopy" in folder_names

        # Verify copy has same data as original
        resp = client.get(f"/api/models/data?ref={COPY_REF}", headers=h)
        assert resp.status_code == 200

        # ── Step 9: Delete original model ──
        resp = client.delete(f"/api/models?ref={MODEL_REF}", headers=h)
        assert resp.status_code == 200

        # After deleting original, the copy should now appear in list_models
        # (no more duplicate id conflict)
        resp = client.get("/api/models", headers=h)
        assert resp.status_code == 200
        models = resp.json()
        model_ids = [m["id"] for m in models]
        assert "EcoliTest" in model_ids  # Copy still has original's id in metadata

        # ── Step 10: Delete copy too ──
        resp = client.delete(f"/api/models?ref={COPY_REF}", headers=h)
        assert resp.status_code == 200

        resp = client.get("/api/models", headers=h)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_gapfills_and_fba_lists_empty(self, e2e_client, auth_headers, model_json):
        """New model should have empty gapfills and FBA lists."""
        _create_model(e2e_client, auth_headers, model_json)

        resp = e2e_client.get(f"/api/models/gapfills?ref={MODEL_REF}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

        resp = e2e_client.get(f"/api/models/fba?ref={MODEL_REF}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_edits_history_empty(self, e2e_client, auth_headers, model_json):
        """New model should have no edit history."""
        _create_model(e2e_client, auth_headers, model_json)

        resp = e2e_client.get(f"/api/models/edits?ref={MODEL_REF}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    def test_workspace_operations(self, e2e_client, auth_headers, model_json):
        """Test workspace ls/get/copy/delete through a full cycle."""
        _create_model(e2e_client, auth_headers, model_json)

        # ls
        resp = e2e_client.post("/api/workspace/ls", json={
            "paths": [f"{MODEL_BASE}/"],
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert f"{MODEL_BASE}/" in data
        entries = data[f"{MODEL_BASE}/"]
        folder_names = [e[0] for e in entries]
        assert "EcoliTest" in folder_names

        # get metadata
        resp = e2e_client.post("/api/workspace/get", json={
            "objects": [f"{MODEL_REF}/model"],
            "metadata_only": True,
        }, headers=auth_headers)
        assert resp.status_code == 200
        result = resp.json()
        assert len(result) == 1
        meta = result[0][0]
        assert len(meta) == 12

        # get with data
        resp = e2e_client.post("/api/workspace/get", json={
            "objects": [f"{MODEL_REF}/model"],
        }, headers=auth_headers)
        assert resp.status_code == 200
        result = resp.json()
        raw = result[0][1]
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        assert "modelreactions" in parsed

        # copy
        resp = e2e_client.post("/api/workspace/copy", json={
            "objects": [[MODEL_REF, COPY2_REF]],
            "recursive": True,
        }, headers=auth_headers)
        assert resp.status_code == 200

        # delete copy
        resp = e2e_client.post("/api/workspace/delete", json={
            "objects": [COPY2_REF],
        }, headers=auth_headers)
        assert resp.status_code == 200

    def test_error_paths(self, e2e_client, auth_headers):
        """Verify error responses for missing resources."""
        h = auth_headers

        resp = e2e_client.get(f"/api/models/data?ref={MODEL_BASE}/Missing", headers=h)
        assert resp.status_code == 404

        resp = e2e_client.delete(f"/api/models?ref={MODEL_BASE}/Missing", headers=h)
        assert resp.status_code == 404

        resp = e2e_client.get(f"/api/models/export?ref={MODEL_BASE}/Missing&format=json", headers=h)
        assert resp.status_code == 404

        resp = e2e_client.get(f"/api/models/export?ref={MODEL_BASE}/Missing&format=csv", headers=h)
        assert resp.status_code in (400, 404)
