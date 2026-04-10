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

    def test_has_file_field(self):
        """Each media entry should include the filename."""
        result = list_media()
        if result["count"] > 0:
            assert all("file" in m for m in result["media"])
            assert all(m["file"].endswith(".json") for m in result["media"])

    def test_count_matches_list_length(self):
        """Count should match the number of items in the list."""
        result = list_media()
        assert result["count"] == len(result["media"])

    def test_num_compounds_non_negative(self):
        """All media should have non-negative compound counts."""
        result = list_media()
        for m in result["media"]:
            assert m["num_compounds"] >= 0

    def test_error_result_has_empty_media_list(self):
        """When directory is missing, error result should still have media key."""
        with patch.object(media_mod, "_MEDIA_DIR", Path("/nonexistent")):
            result = list_media()
            assert result["media"] == []


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

    def test_empty_name(self):
        """Empty string should return not-found error."""
        result = get_media("")
        assert "error" in result

    def test_suggestions_on_not_found(self):
        """Not-found should include list_media suggestion."""
        result = get_media("NoSuchMedia")
        assert "suggestions" in result
        assert any("list_media" in s for s in result["suggestions"])

    def test_compounds_is_list(self):
        """Returned compounds should be a list."""
        listing = list_media()
        if listing["count"] > 0:
            name = listing["media"][0]["name"]
            result = get_media(name)
            assert isinstance(result["compounds"], list)

    def test_num_compounds_matches_list(self):
        """num_compounds should match len(compounds)."""
        listing = list_media()
        if listing["count"] > 0:
            name = listing["media"][0]["name"]
            result = get_media(name)
            assert result["num_compounds"] == len(result["compounds"])

    def test_lowercase_name(self):
        """Lowercase version of a media name should still be found."""
        listing = list_media()
        if listing["count"] > 0:
            name = listing["media"][0]["name"]
            result = get_media(name.lower())
            assert "compounds" in result

    def test_mixed_case_name(self):
        """Mixed case should work via case-insensitive fallback."""
        listing = list_media()
        if listing["count"] > 0:
            name = listing["media"][0]["name"]
            # Alternate case: first char upper, rest lower
            mixed = name[0].upper() + name[1:].lower() if len(name) > 1 else name
            result = get_media(mixed)
            assert "compounds" in result
