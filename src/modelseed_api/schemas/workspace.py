"""Pydantic schemas for workspace operations.

ObjectMeta matches the 12-element tuple from the Workspace service.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class ObjectMeta(BaseModel):
    """Workspace object metadata.

    The workspace returns a 12-element tuple:
    [name, type, path, creation_time, id, owner, size, user_meta, auto_meta,
     user_perm, global_perm, shockurl]
    """

    name: str
    type: str
    path: str
    creation_time: str
    id: str
    owner: str
    size: int
    user_meta: dict[str, str]
    auto_meta: dict[str, str]
    user_perm: str
    global_perm: str
    shockurl: str


# Request schemas


class WSListRequest(BaseModel):
    """Request to list workspace contents."""

    paths: list[str]
    recursive: bool = False
    excludeDirectories: bool = False


class WSGetRequest(BaseModel):
    """Request to get workspace objects."""

    objects: list[str]
    metadata_only: bool = False


class WSCreateRequest(BaseModel):
    """Request to create workspace objects.

    Each object is [path, type, metadata, data].
    """

    objects: list[list[Any]]
    createUploadNodes: bool = False
    overwrite: bool = False


class WSCopyRequest(BaseModel):
    """Request to copy workspace objects.

    Each object pair is [source, destination].
    """

    objects: list[list[str]]
    move: bool = False
    recursive: bool = False
    overwrite: bool = False


class WSDeleteRequest(BaseModel):
    """Request to delete workspace objects."""

    objects: list[str]
    deleteDirectories: bool = False
    force: bool = False


class WSUpdateMetadataRequest(BaseModel):
    """Request to update workspace object metadata.

    Each entry is [path, metadata_dict].
    """

    objects: list[list[Any]]


class WSDownloadUrlRequest(BaseModel):
    """Request to get download URLs."""

    objects: list[str]


class WSPermissionsRequest(BaseModel):
    """Request to list permissions."""

    objects: list[str]
