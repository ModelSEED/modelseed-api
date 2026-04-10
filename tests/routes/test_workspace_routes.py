"""Route tests for /api/workspace proxy endpoints."""

import pytest

pytestmark = pytest.mark.integration


class TestWorkspaceLs:
    def test_ls_empty(self, local_client, auth_headers):
        resp = local_client.post("/api/workspace/ls", json={
            "paths": ["/local/modelseed/"],
        }, headers=auth_headers)
        assert resp.status_code == 200

    def test_ls_with_data(self, seeded_client, auth_headers):
        resp = seeded_client.post("/api/workspace/ls", json={
            "paths": ["/local/modelseed/"],
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "/local/modelseed/" in data


class TestWorkspaceGet:
    def test_get_metadata_only(self, seeded_client, auth_headers):
        resp = seeded_client.post("/api/workspace/get", json={
            "objects": ["/local/modelseed/TestModel/model"],
            "metadata_only": True,
        }, headers=auth_headers)
        assert resp.status_code == 200

    def test_get_with_data(self, seeded_client, auth_headers):
        resp = seeded_client.post("/api/workspace/get", json={
            "objects": ["/local/modelseed/TestModel/model"],
        }, headers=auth_headers)
        assert resp.status_code == 200


class TestWorkspaceCreate:
    def test_create_folder(self, local_client, auth_headers):
        resp = local_client.post("/api/workspace/create", json={
            "objects": [["/local/test_create", "folder", {}, None]],
        }, headers=auth_headers)
        assert resp.status_code == 200


class TestWorkspaceCopy:
    def test_copy(self, seeded_client, auth_headers):
        resp = seeded_client.post("/api/workspace/copy", json={
            "objects": [["/local/modelseed/TestModel", "/local/modelseed/TestCopy"]],
            "recursive": True,
        }, headers=auth_headers)
        assert resp.status_code == 200


class TestWorkspaceDelete:
    def test_delete(self, seeded_client, auth_headers):
        # Create something to delete
        seeded_client.post("/api/workspace/create", json={
            "objects": [["/local/to_delete", "folder", {}, None]],
        }, headers=auth_headers)
        resp = seeded_client.post("/api/workspace/delete", json={
            "objects": ["/local/to_delete"],
        }, headers=auth_headers)
        assert resp.status_code == 200


class TestWorkspaceMetadata:
    def test_update_metadata(self, seeded_client, auth_headers):
        resp = seeded_client.post("/api/workspace/metadata", json={
            "objects": [["/local/modelseed/TestModel", {"new_field": "value"}]],
        }, headers=auth_headers)
        assert resp.status_code == 200


class TestWorkspaceDownloadUrl:
    def test_download_url(self, seeded_client, auth_headers):
        resp = seeded_client.post("/api/workspace/download-url", json={
            "objects": ["/local/modelseed/TestModel/model"],
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0].startswith("file://")


class TestWorkspacePermissions:
    def test_permissions(self, seeded_client, auth_headers):
        resp = seeded_client.post("/api/workspace/permissions", json={
            "objects": ["/local/modelseed/TestModel"],
        }, headers=auth_headers)
        assert resp.status_code == 200
