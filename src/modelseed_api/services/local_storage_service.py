"""Local filesystem storage backend.

Drop-in replacement for WorkspaceService that reads/writes JSON files
to a local directory instead of hitting the PATRIC Workspace service.
Returns the same 12-element metadata tuples so all callers work unchanged.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from modelseed_api.services.workspace_service import WorkspaceError

logger = logging.getLogger("modelseed_api.local_storage")

# Metadata tuple indices (matches PATRIC Workspace format)
_NAME = 0
_TYPE = 1
_PATH = 2
_CREATED = 3
_ID = 4
_OWNER = 5
_SIZE = 6
_USER_META = 7
_AUTO_META = 8
_USER_PERM = 9
_GLOBAL_PERM = 10
_SHOCK_URL = 11


class LocalStorageService:
    """Filesystem-backed storage with the same interface as WorkspaceService."""

    def __init__(self, token: str, data_dir: str):
        self.token = token
        self.data_dir = Path(os.path.expanduser(data_dir))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._seed_bundled_media()

    def _seed_bundled_media(self) -> None:
        """Copy bundled public media into local data dir if not already present."""
        from modelseed_api.config import settings

        target = self._ws_path_to_fs(settings.public_media_path)
        if target.exists():
            return  # already seeded

        # Find bundled media relative to repo root
        bundled = Path(__file__).resolve().parent.parent.parent.parent / "data" / "media" / "public"
        if not bundled.exists():
            logger.debug("No bundled media at %s — skipping seed", bundled)
            return

        target.mkdir(parents=True, exist_ok=True)
        count = 0
        for src in bundled.iterdir():
            if src.suffix == ".json":
                shutil.copy2(src, target / src.name)
                count += 1
        if count:
            logger.info("Seeded %d public media files into %s", count, target)

    # ── helpers ──────────────────────────────────────────────────────

    def _ws_path_to_fs(self, ws_path: str) -> Path:
        """Convert workspace path like '/user/modelseed/model1' to local fs path."""
        # Strip leading/trailing slashes, normalize
        clean = ws_path.strip("/")
        return self.data_dir / clean

    def _fs_to_ws_path(self, fs_path: Path) -> str:
        """Convert local fs path back to workspace-style path."""
        rel = fs_path.relative_to(self.data_dir)
        return "/" + str(rel) + ("/" if fs_path.is_dir() else "")

    def _meta_path(self, fs_path: Path) -> Path:
        """Return the metadata file path for a given object."""
        return fs_path.parent / ".meta" / (fs_path.name + ".json")

    def _read_meta(self, fs_path: Path) -> list:
        """Read metadata tuple for an object. Returns default if not found."""
        mp = self._meta_path(fs_path)
        if mp.exists():
            with open(mp) as f:
                return json.load(f)
        # Build default metadata from filesystem info
        return self._build_default_meta(fs_path)

    def _write_meta(self, fs_path: Path, meta: list) -> None:
        """Write metadata tuple for an object."""
        mp = self._meta_path(fs_path)
        mp.parent.mkdir(parents=True, exist_ok=True)
        with open(mp, "w") as f:
            json.dump(meta, f, indent=2)

    def _build_default_meta(self, fs_path: Path) -> list:
        """Build a 12-element metadata tuple from filesystem info."""
        name = fs_path.name
        if fs_path.is_dir():
            obj_type = "folder"
            size = 0
        else:
            # Strip .json extension for the name
            if name.endswith(".json"):
                name = name[:-5]
            obj_type = "unspecified"
            size = fs_path.stat().st_size if fs_path.exists() else 0

        ws_path = self._fs_to_ws_path(fs_path)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        mtime = ""
        if fs_path.exists():
            mtime = datetime.fromtimestamp(
                fs_path.stat().st_mtime, tz=timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%S")

        return [
            name,       # [0] name
            obj_type,   # [1] type
            ws_path,    # [2] path
            mtime or now,  # [3] creation_time
            name,       # [4] id
            "local",    # [5] owner
            size,       # [6] size
            {},         # [7] user_meta
            {},         # [8] auto_meta
            "o",        # [9] user_perm (owner)
            "n",        # [10] global_perm (none)
            "",         # [11] shockurl
        ]

    def _build_meta_for_create(
        self, ws_path: str, obj_type: str, user_meta: dict, data_size: int
    ) -> list:
        """Build metadata tuple for a newly created object."""
        name = ws_path.strip("/").split("/")[-1]
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        # Extract owner from path (first segment)
        parts = ws_path.strip("/").split("/")
        owner = parts[0] if parts else "local"

        return [
            name,       # [0] name
            obj_type,   # [1] type
            ws_path if ws_path.endswith("/") else ws_path + "/",  # [2] path
            now,        # [3] creation_time
            user_meta.get("id", name),  # [4] id
            owner,      # [5] owner
            data_size,  # [6] size
            user_meta,  # [7] user_meta
            {},         # [8] auto_meta
            "o",        # [9] user_perm
            "n",        # [10] global_perm
            "",         # [11] shockurl
        ]

    # ── public interface (matches WorkspaceService) ──────────────────

    def ls(self, params: dict) -> Any:
        """List directory contents.

        params: {"paths": ["/user/modelseed/"], ...}
        returns: {path: [meta_tuple, ...]}
        """
        paths = params.get("paths", [])
        result: dict[str, list] = {}

        for ws_path in paths:
            fs_path = self._ws_path_to_fs(ws_path)
            entries: list[list] = []

            if not fs_path.exists():
                result[ws_path] = []
                continue

            if fs_path.is_dir():
                for child in sorted(fs_path.iterdir()):
                    # Skip hidden metadata dirs
                    if child.name.startswith("."):
                        continue
                    meta = self._read_meta(child)
                    entries.append(meta)
            else:
                # Single file
                meta = self._read_meta(fs_path)
                entries.append(meta)

            result[ws_path] = entries

        return result

    def get(self, params: dict) -> Any:
        """Get objects (data + metadata).

        params: {"objects": ["/user/modelseed/model1/model"], "metadata_only": 1}
        returns: [[meta_tuple, data_string], ...]
        """
        objects = params.get("objects", [])
        metadata_only = params.get("metadata_only")
        results: list[list] = []

        for ws_ref in objects:
            fs_path = self._ws_path_to_fs(ws_ref)

            # Try with .json extension if path doesn't exist as-is
            if not fs_path.exists() and not fs_path.suffix:
                fs_path_json = fs_path.with_suffix(".json")
                if fs_path_json.exists():
                    fs_path = fs_path_json

            if not fs_path.exists() and not fs_path.is_dir():
                raise WorkspaceError(
                    f"Object not found: {ws_ref}", 404
                )

            meta = self._read_meta(fs_path)

            if metadata_only:
                results.append([meta])
            else:
                if fs_path.is_dir():
                    results.append([meta, "{}"])
                else:
                    data = fs_path.read_text()
                    results.append([meta, data])

        return results

    def create(self, params: dict) -> Any:
        """Create objects.

        params: {"objects": [[path, type, meta_dict, data_str], ...], "overwrite": 1}
        returns: list of metadata tuples
        """
        objects = params.get("objects", [])
        overwrite = params.get("overwrite", False)
        results: list[list] = []

        for obj_spec in objects:
            ws_path, obj_type, meta_dict, data_str = obj_spec
            fs_path = self._ws_path_to_fs(ws_path)

            if obj_type in ("folder", "modelfolder"):
                # Create directory
                fs_path.mkdir(parents=True, exist_ok=True)
                meta = self._build_meta_for_create(
                    ws_path, obj_type, meta_dict, 0
                )
                self._write_meta(fs_path, meta)
            else:
                # Create file
                if not fs_path.suffix:
                    fs_path = fs_path.with_suffix(".json")

                if fs_path.exists() and not overwrite:
                    raise WorkspaceError(
                        f"Object already exists: {ws_path}", 409
                    )

                fs_path.parent.mkdir(parents=True, exist_ok=True)
                data_str = data_str or ""
                fs_path.write_text(data_str)

                # Strip .json for the metadata path key
                meta_fs = fs_path.with_suffix("") if fs_path.suffix == ".json" else fs_path
                meta = self._build_meta_for_create(
                    ws_path, obj_type, meta_dict, len(data_str)
                )
                self._write_meta(meta_fs if meta_fs != fs_path else fs_path, meta)

            results.append(meta)

        return results

    def copy(self, params: dict) -> Any:
        """Copy objects.

        params: {"objects": [[src, dst], ...], "recursive": True}
        returns: list of metadata tuples for destinations
        """
        objects = params.get("objects", [])
        recursive = params.get("recursive", False)
        results: list[list] = []

        for src_path, dst_path in objects:
            src_fs = self._ws_path_to_fs(src_path)
            dst_fs = self._ws_path_to_fs(dst_path)

            if not src_fs.exists():
                # Try with .json
                src_json = src_fs.with_suffix(".json")
                if src_json.exists():
                    src_fs = src_json

            if not src_fs.exists():
                raise WorkspaceError(f"Source not found: {src_path}", 404)

            dst_fs.parent.mkdir(parents=True, exist_ok=True)

            if src_fs.is_dir():
                if recursive:
                    shutil.copytree(src_fs, dst_fs, dirs_exist_ok=True)
                else:
                    dst_fs.mkdir(parents=True, exist_ok=True)
            else:
                shutil.copy2(src_fs, dst_fs)

            # Copy the source's own metadata entry and update name/path
            src_meta_file = self._meta_path(src_fs)
            if src_meta_file.exists():
                dst_meta_file = self._meta_path(dst_fs)
                dst_meta_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_meta_file, dst_meta_file)
                # Update name and path to reflect destination
                meta = self._read_meta(dst_fs)
                dst_name = dst_fs.name
                meta[_NAME] = dst_name
                meta[_PATH] = self._fs_to_ws_path(dst_fs)
                meta[_ID] = dst_name
                if isinstance(meta[_USER_META], dict):
                    meta[_USER_META]["id"] = dst_name
                    if "name" in meta[_USER_META]:
                        meta[_USER_META]["name"] = dst_name
                self._write_meta(dst_fs, meta)

            meta = self._read_meta(dst_fs)
            results.append(meta)

        return results

    def delete(self, params: dict) -> Any:
        """Delete objects.

        params: {"objects": [path, ...], "deleteDirectories": True, "force": True}
        returns: list of deleted paths
        """
        objects = params.get("objects", [])
        results: list[str] = []

        for ws_path in objects:
            fs_path = self._ws_path_to_fs(ws_path)

            if not fs_path.exists():
                # Try with .json
                fs_json = fs_path.with_suffix(".json")
                if fs_json.exists():
                    fs_path = fs_json

            if not fs_path.exists():
                raise WorkspaceError(f"Object not found: {ws_path}", 404)

            # Remove metadata
            meta_file = self._meta_path(fs_path)
            if meta_file.exists():
                meta_file.unlink()

            if fs_path.is_dir():
                # Also remove the .meta directory inside
                meta_dir = fs_path / ".meta"
                if meta_dir.exists():
                    shutil.rmtree(meta_dir)
                shutil.rmtree(fs_path)
            else:
                fs_path.unlink()

            results.append(ws_path)

        return results

    def update_metadata(self, params: dict) -> Any:
        """Update object metadata.

        params: {"objects": [[path, meta_dict], ...]}
        returns: list of updated metadata tuples
        """
        objects = params.get("objects", [])
        results: list[list] = []

        for obj_spec in objects:
            ws_path, new_meta = obj_spec
            fs_path = self._ws_path_to_fs(ws_path)

            # Find the actual file/dir
            if not fs_path.exists():
                fs_json = fs_path.with_suffix(".json")
                if fs_json.exists():
                    fs_path = fs_json

            if not fs_path.exists():
                raise WorkspaceError(f"Object not found: {ws_path}", 404)

            meta = self._read_meta(fs_path)

            # Merge new metadata into user_meta (index 7)
            if not isinstance(meta[_USER_META], dict):
                meta[_USER_META] = {}
            meta[_USER_META].update(new_meta)

            # Also update id if provided
            if "id" in new_meta:
                meta[_ID] = new_meta["id"]

            self._write_meta(fs_path, meta)
            results.append(meta)

        return results

    def get_download_url(self, params: dict) -> Any:
        """Get download URLs — returns file:// paths for local storage."""
        objects = params.get("objects", [])
        results: list[str] = []

        for ws_path in objects:
            fs_path = self._ws_path_to_fs(ws_path)
            if not fs_path.exists():
                fs_json = fs_path.with_suffix(".json")
                if fs_json.exists():
                    fs_path = fs_json
            if fs_path.exists():
                results.append(f"file://{fs_path}")
            else:
                raise WorkspaceError(f"Object not found: {ws_path}", 404)

        return results

    def list_permissions(self, params: dict) -> Any:
        """List permissions — local storage always returns full owner access."""
        objects = params.get("objects", [])
        results: list[dict] = []

        for ws_path in objects:
            results.append({ws_path: [["local", "o"]]})

        return results
