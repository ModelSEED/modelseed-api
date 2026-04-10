"""Route tests for /api/media endpoints."""

import pytest

pytestmark = pytest.mark.integration


class TestListPublicMedia:
    def test_returns_200(self, local_client):
        resp = local_client.get("/api/media/public")
        assert resp.status_code == 200

    def test_no_auth_required(self, local_client):
        # No auth headers, should still work
        resp = local_client.get("/api/media/public")
        assert resp.status_code == 200


class TestListMyMedia:
    def test_returns_200(self, local_client):
        resp = local_client.get("/api/media/mine")
        assert resp.status_code == 200

    def test_empty_for_new_user(self, local_client):
        resp = local_client.get("/api/media/mine")
        assert resp.status_code == 200
        data = resp.json()
        # Should return path→[] mapping
        assert isinstance(data, dict)


class TestExportMedia:
    def test_export_json_media(self, seeded_client, auth_headers):
        # First get a media ref from the public list
        listing = seeded_client.get("/api/media/public")
        data = listing.json()
        # Find the first media entry
        media_entries = []
        for path, entries in data.items():
            for e in entries:
                media_entries.append(e)
        assert len(media_entries) > 0, "No public media found"
        # path field ([2]) is the full workspace path to the object
        ref = media_entries[0][2]
        resp = seeded_client.get(f"/api/media/export?ref={ref}", headers=auth_headers)
        assert resp.status_code == 200
        media_data = resp.json()
        assert "compounds" in media_data or "mediacompounds" in media_data

    def test_nonexistent_returns_404(self, seeded_client, auth_headers):
        resp = seeded_client.get("/api/media/export?ref=/nonexistent/media", headers=auth_headers)
        assert resp.status_code == 404
