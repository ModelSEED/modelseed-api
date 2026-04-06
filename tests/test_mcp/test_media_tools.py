"""Tests for MCP media tools."""

from pathlib import Path
from unittest.mock import patch

import modelseed_mcp.tools.media as media_mod

list_media = media_mod.list_media.fn
get_media = media_mod.get_media.fn

MOCK_MEDIA = {
    "name": "TestMedia",
    "mediacompounds": [
        {"id": "cpd00027", "name": "D-Glucose", "concentration": 0.001,
         "minflux": -100.0, "maxflux": 100.0},
        {"id": "cpd00001", "name": "H2O", "concentration": 0.001,
         "minflux": -100.0, "maxflux": 100.0},
    ],
}


class TestListMedia:
    def test_lists_real_media_dir(self):
        """The bundled data/media/public/ directory should have media files."""
        result = list_media()
        assert result["count"] > 0
        assert all("name" in m for m in result["media"])
        assert all("num_compounds" in m for m in result["media"])

    def test_missing_dir(self):
        with patch.object(media_mod, "_MEDIA_DIR", Path("/nonexistent")):
            result = list_media()
            assert "error" in result


class TestGetMedia:
    def test_get_existing_media(self):
        """Should find at least one real media file."""
        # First list to find a name
        listing = list_media()
        assert listing["count"] > 0
        name = listing["media"][0]["name"]

        result = get_media(name)
        assert "compounds" in result
        assert result["num_compounds"] > 0

    def test_case_insensitive(self):
        listing = list_media()
        if listing["count"] > 0:
            name = listing["media"][0]["name"]
            result = get_media(name.upper())
            assert "compounds" in result

    def test_not_found(self):
        result = get_media("NonexistentMedia12345")
        assert "error" in result
        assert "suggestions" in result

    def test_with_json_extension(self):
        listing = list_media()
        if listing["count"] > 0:
            filename = listing["media"][0]["file"]
            result = get_media(filename)
            assert "compounds" in result
