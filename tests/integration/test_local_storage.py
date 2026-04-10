"""Integration tests for LocalStorageService — full CRUD lifecycle on real filesystem."""

import json

import pytest

from modelseed_api.services.local_storage_service import LocalStorageService
from modelseed_api.services.workspace_service import WorkspaceError

pytestmark = pytest.mark.integration


# ── ls ───────────────────────────────────────────────────────────────


class TestLs:
    def test_empty_dir(self, local_storage):
        result = local_storage.ls({"paths": ["/local/modelseed/"]})
        assert "/local/modelseed/" in result
        # May have seeded media, but /local/modelseed/ is empty
        entries = result["/local/modelseed/"]
        assert isinstance(entries, list)

    def test_with_files(self, populated_storage):
        result = populated_storage.ls({"paths": ["/local/modelseed/"]})
        entries = result["/local/modelseed/"]
        names = [e[0] for e in entries]
        assert "TestModel" in names

    def test_skips_dot_meta(self, populated_storage):
        result = populated_storage.ls({"paths": ["/local/modelseed/"]})
        entries = result["/local/modelseed/"]
        names = [e[0] for e in entries]
        assert ".meta" not in names

    def test_metadata_tuple_has_12_elements(self, populated_storage):
        result = populated_storage.ls({"paths": ["/local/modelseed/"]})
        entries = result["/local/modelseed/"]
        for entry in entries:
            assert len(entry) == 12, f"Metadata tuple has {len(entry)} elements, expected 12"

    def test_metadata_tuple_indices(self, populated_storage):
        result = populated_storage.ls({"paths": ["/local/modelseed/"]})
        entries = result["/local/modelseed/"]
        folder_entry = next(e for e in entries if e[0] == "TestModel")
        assert folder_entry[0] == "TestModel"  # name
        assert folder_entry[1] == "modelfolder"  # type
        assert "/TestModel" in folder_entry[2]  # path contains name
        assert folder_entry[5] == "local"  # owner
        assert isinstance(folder_entry[7], dict)  # user_meta is dict

    def test_nonexistent_dir_returns_empty(self, local_storage):
        result = local_storage.ls({"paths": ["/nonexistent/path/"]})
        assert result["/nonexistent/path/"] == []

    def test_ls_lists_children(self, populated_storage):
        result = populated_storage.ls({"paths": ["/local/modelseed/TestModel/"]})
        entries = result["/local/modelseed/TestModel/"]
        # Should have at least the model file
        assert len(entries) >= 1


# ── create ───────────────────────────────────────────────────────────


class TestCreate:
    def test_create_folder(self, local_storage, local_data_dir):
        result = local_storage.create({
            "objects": [["/local/modelseed/NewFolder", "folder", {"name": "NewFolder"}, None]],
        })
        assert len(result) == 1
        assert result[0][0] == "NewFolder"
        assert (local_data_dir / "local" / "modelseed" / "NewFolder").is_dir()

    def test_create_file(self, local_storage, local_data_dir):
        # First create parent folder
        local_storage.create({
            "objects": [["/local/modelseed/test_folder", "folder", {}, None]],
        })
        result = local_storage.create({
            "objects": [["/local/modelseed/test_folder/data", "model", {}, '{"key": "value"}']],
        })
        assert len(result) == 1
        # File should exist with .json extension
        fp = local_data_dir / "local" / "modelseed" / "test_folder" / "data.json"
        assert fp.exists()
        assert json.loads(fp.read_text()) == {"key": "value"}

    def test_create_with_metadata(self, local_storage):
        meta = {"id": "test", "num_reactions": "5"}
        local_storage.create({
            "objects": [["/local/modelseed/MetaFolder", "modelfolder", meta, None]],
        })
        result = local_storage.ls({"paths": ["/local/modelseed/"]})
        entries = result["/local/modelseed/"]
        folder = next(e for e in entries if e[0] == "MetaFolder")
        assert folder[7]["id"] == "test"
        assert folder[7]["num_reactions"] == "5"

    def test_create_overwrite_false_raises(self, populated_storage):
        with pytest.raises(WorkspaceError) as exc_info:
            populated_storage.create({
                "objects": [["/local/modelseed/TestModel/model", "model", {}, "{}"]],
                "overwrite": False,
            })
        assert exc_info.value.code == 409

    def test_create_overwrite_true_succeeds(self, populated_storage):
        populated_storage.create({
            "objects": [["/local/modelseed/TestModel/model", "model", {}, '{"new": true}']],
            "overwrite": True,
        })
        result = populated_storage.get({"objects": ["/local/modelseed/TestModel/model"]})
        data = json.loads(result[0][1])
        assert data["new"] is True

    def test_create_modelfolder_type(self, local_storage):
        local_storage.create({
            "objects": [["/local/modelseed/MyModel", "modelfolder", {"source": "test"}, None]],
        })
        result = local_storage.ls({"paths": ["/local/modelseed/"]})
        entries = result["/local/modelseed/"]
        folder = next(e for e in entries if e[0] == "MyModel")
        assert folder[1] == "modelfolder"


# ── get ──────────────────────────────────────────────────────────────


class TestGet:
    def test_get_file_data_matches(self, populated_storage, sample_model_json):
        result = populated_storage.get({"objects": ["/local/modelseed/TestModel/model"]})
        assert len(result) == 1
        data = json.loads(result[0][1])
        assert data["id"] == "test_model"

    def test_get_metadata_only(self, populated_storage):
        result = populated_storage.get({
            "objects": ["/local/modelseed/TestModel/model"],
            "metadata_only": 1,
        })
        assert len(result) == 1
        assert len(result[0]) == 1  # only metadata, no data

    def test_get_nonexistent_raises_404(self, local_storage):
        with pytest.raises(WorkspaceError) as exc_info:
            local_storage.get({"objects": ["/nonexistent/file"]})
        assert exc_info.value.code == 404

    def test_get_json_extension_fallback(self, populated_storage):
        """Path without .json should find the .json file."""
        result = populated_storage.get({"objects": ["/local/modelseed/TestModel/model"]})
        assert len(result) == 1
        assert result[0][1]  # has data


# ── copy ─────────────────────────────────────────────────────────────


class TestCopy:
    def test_copy_file(self, populated_storage):
        populated_storage.copy({
            "objects": [["/local/modelseed/TestModel/model", "/local/modelseed/TestModel/model_copy"]],
        })
        result = populated_storage.get({"objects": ["/local/modelseed/TestModel/model_copy"]})
        assert len(result) == 1

    def test_copy_dir_recursive(self, populated_storage):
        populated_storage.copy({
            "objects": [["/local/modelseed/TestModel", "/local/modelseed/CopiedModel"]],
            "recursive": True,
        })
        result = populated_storage.ls({"paths": ["/local/modelseed/CopiedModel/"]})
        entries = result["/local/modelseed/CopiedModel/"]
        assert len(entries) >= 1

    def test_copy_metadata_updated(self, populated_storage):
        populated_storage.copy({
            "objects": [["/local/modelseed/TestModel", "/local/modelseed/CopiedModel"]],
            "recursive": True,
        })
        result = populated_storage.ls({"paths": ["/local/modelseed/"]})
        entries = result["/local/modelseed/"]
        copied = next((e for e in entries if e[0] == "CopiedModel"), None)
        assert copied is not None
        assert copied[0] == "CopiedModel"  # name updated
        assert "CopiedModel" in copied[2]  # path updated

    def test_copy_nonexistent_raises(self, local_storage):
        with pytest.raises(WorkspaceError) as exc_info:
            local_storage.copy({
                "objects": [["/nonexistent", "/local/copy"]],
            })
        assert exc_info.value.code == 404


# ── delete ───────────────────────────────────────────────────────────


class TestDelete:
    def test_delete_file(self, populated_storage):
        # Create a separate file to delete
        populated_storage.create({
            "objects": [["/local/modelseed/TestModel/to_delete", "model", {}, "{}"]],
            "overwrite": True,
        })
        populated_storage.delete({"objects": ["/local/modelseed/TestModel/to_delete"]})
        with pytest.raises(WorkspaceError):
            populated_storage.get({"objects": ["/local/modelseed/TestModel/to_delete"]})

    def test_delete_dir(self, populated_storage, local_data_dir):
        populated_storage.delete({"objects": ["/local/modelseed/TestModel"]})
        assert not (local_data_dir / "local" / "modelseed" / "TestModel").exists()

    def test_delete_nonexistent_raises_404(self, local_storage):
        with pytest.raises(WorkspaceError) as exc_info:
            local_storage.delete({"objects": ["/nonexistent"]})
        assert exc_info.value.code == 404


# ── update_metadata ─────────────────────────────────────────────────


class TestUpdateMetadata:
    def test_merge_metadata(self, populated_storage):
        populated_storage.update_metadata({
            "objects": [["/local/modelseed/TestModel", {"new_key": "new_value"}]],
        })
        result = populated_storage.ls({"paths": ["/local/modelseed/"]})
        entries = result["/local/modelseed/"]
        folder = next(e for e in entries if e[0] == "TestModel")
        # Original metadata should still be there
        assert folder[7]["id"] == "TestModel"
        # New key added
        assert folder[7]["new_key"] == "new_value"

    def test_id_field_updated(self, populated_storage):
        populated_storage.update_metadata({
            "objects": [["/local/modelseed/TestModel", {"id": "NewId"}]],
        })
        result = populated_storage.ls({"paths": ["/local/modelseed/"]})
        entries = result["/local/modelseed/"]
        folder = next(e for e in entries if e[0] == "TestModel")
        assert folder[4] == "NewId"  # id field at index 4

    def test_update_nonexistent_raises(self, local_storage):
        with pytest.raises(WorkspaceError) as exc_info:
            local_storage.update_metadata({
                "objects": [["/nonexistent", {"key": "val"}]],
            })
        assert exc_info.value.code == 404


# ── download_url ─────────────────────────────────────────────────────


class TestGetDownloadUrl:
    def test_returns_file_url(self, populated_storage):
        result = populated_storage.get_download_url({
            "objects": ["/local/modelseed/TestModel/model"],
        })
        assert len(result) == 1
        assert result[0].startswith("file://")

    def test_nonexistent_raises(self, local_storage):
        with pytest.raises(WorkspaceError):
            local_storage.get_download_url({"objects": ["/nonexistent"]})


# ── permissions ──────────────────────────────────────────────────────


class TestListPermissions:
    def test_returns_owner_permission(self, local_storage):
        result = local_storage.list_permissions({"objects": ["/local/modelseed/"]})
        assert len(result) == 1
        perms = result[0]["/local/modelseed/"]
        assert perms == [["local", "o"]]
