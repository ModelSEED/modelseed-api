"""Factory for creating the appropriate storage service based on config."""

from modelseed_api.config import settings


def get_storage_service(token: str):
    """Return a storage service instance based on the configured backend.

    When storage_backend == "local", returns a LocalStorageService that
    reads/writes JSON files to the local filesystem.
    Otherwise, returns a WorkspaceService that proxies to PATRIC Workspace.
    """
    if settings.storage_backend == "local":
        from modelseed_api.services.local_storage_service import LocalStorageService

        return LocalStorageService(token, settings.local_data_dir)

    from modelseed_api.services.workspace_service import WorkspaceService

    return WorkspaceService(token)
