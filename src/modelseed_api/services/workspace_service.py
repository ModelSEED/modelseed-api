"""Workspace service - proxies all operations to the PATRIC Workspace.

Wraps PatricWSClient from KBUtilLib to provide workspace operations.
All workspace calls from the frontend go through this service, shielding
us from eventual workspace replacement.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests

from modelseed_api.config import settings

logger = logging.getLogger("modelseed_api.workspace")


class WorkspaceService:
    """Proxy for the PATRIC Workspace JSON-RPC service.

    This is a lightweight wrapper that forwards calls to the workspace service.
    We implement the JSON-RPC client directly here to avoid requiring KBUtilLib
    as a hard dependency for the core API - KBUtilLib is only needed for job scripts.
    """

    def __init__(self, token: str):
        self.token = token
        self.url = settings.workspace_url
        self.timeout = settings.workspace_timeout

    # Retry transient errors (500, 502, 503, 504, connection failures)
    _RETRYABLE_CODES = {500, 502, 503, 504}
    _MAX_RETRIES = 3
    _RETRY_DELAYS = (1, 3, 5)  # seconds between retries

    def _call(self, method: str, params: dict) -> Any:
        """Make a JSON-RPC 1.1 call to the workspace service with retry."""
        logger.debug("Workspace.%s %s", method, _summarize_params(params))
        payload = {
            "version": "1.1",
            "method": f"Workspace.{method}",
            "params": [params],
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": self.token,
        }

        last_exc: Exception | None = None
        for attempt in range(self._MAX_RETRIES):
            try:
                response = requests.post(
                    self.url, json=payload, headers=headers, timeout=self.timeout,
                )
            except requests.RequestException as e:
                last_exc = WorkspaceError(f"Cannot reach workspace service: {e}")
                logger.warning("Workspace.%s connection failed (attempt %d/%d): %s",
                               method, attempt + 1, self._MAX_RETRIES, e)
                if attempt < self._MAX_RETRIES - 1:
                    time.sleep(self._RETRY_DELAYS[attempt])
                continue

            # Try to parse JSON body regardless of HTTP status — workspace often
            # returns JSON-RPC error objects inside non-200 responses
            try:
                result = response.json()
            except ValueError:
                if not response.ok:
                    if response.status_code in self._RETRYABLE_CODES and attempt < self._MAX_RETRIES - 1:
                        logger.warning("Workspace.%s HTTP %d (attempt %d/%d), retrying...",
                                       method, response.status_code, attempt + 1, self._MAX_RETRIES)
                        time.sleep(self._RETRY_DELAYS[attempt])
                        continue
                    logger.error("Workspace.%s HTTP %d (non-JSON): %s", method, response.status_code, response.text[:200])
                    raise WorkspaceError(
                        f"Workspace HTTP {response.status_code}: {response.text[:500]}",
                        response.status_code,
                    )
                return None

            if "error" in result:
                error = result["error"]
                error_code = error.get("code", -1)
                # Retry on server-side 500 errors (not auth/not-found errors)
                if response.status_code in self._RETRYABLE_CODES and attempt < self._MAX_RETRIES - 1:
                    logger.warning("Workspace.%s error [%s] (attempt %d/%d), retrying: %s",
                                   method, error_code, attempt + 1, self._MAX_RETRIES, error.get("message", "?"))
                    time.sleep(self._RETRY_DELAYS[attempt])
                    continue
                logger.error("Workspace.%s error [%s]: %s", method, error_code, error.get("message", "?"))
                raise WorkspaceError(
                    error.get("message", "Unknown workspace error"),
                    error_code,
                )

            if not response.ok:
                if response.status_code in self._RETRYABLE_CODES and attempt < self._MAX_RETRIES - 1:
                    logger.warning("Workspace.%s HTTP %d (attempt %d/%d), retrying...",
                                   method, response.status_code, attempt + 1, self._MAX_RETRIES)
                    time.sleep(self._RETRY_DELAYS[attempt])
                    continue
                logger.error("Workspace.%s HTTP %d", method, response.status_code)
                raise WorkspaceError(
                    f"Workspace HTTP {response.status_code}",
                    response.status_code,
                )

            return result.get("result", [None])[0]

        # All retries exhausted
        if last_exc:
            logger.error("Workspace.%s failed after %d attempts", method, self._MAX_RETRIES)
            raise last_exc
        raise WorkspaceError(f"Workspace.{method} failed after {self._MAX_RETRIES} attempts")

    def ls(self, params: dict) -> Any:
        """List workspace contents."""
        return self._call("ls", params)

    def get(self, params: dict) -> Any:
        """Get workspace objects."""
        return self._call("get", params)

    def create(self, params: dict) -> Any:
        """Create workspace objects."""
        return self._call("create", params)

    def copy(self, params: dict) -> Any:
        """Copy/move workspace objects."""
        return self._call("copy", params)

    def delete(self, params: dict) -> Any:
        """Delete workspace objects."""
        return self._call("delete", params)

    def update_metadata(self, params: dict) -> Any:
        """Update workspace object metadata."""
        return self._call("update_metadata", params)

    def get_download_url(self, params: dict) -> Any:
        """Get download URLs for workspace objects."""
        return self._call("get_download_url", params)

    def list_permissions(self, params: dict) -> Any:
        """List permissions on workspace objects."""
        return self._call("list_permissions", params)


def _summarize_params(params: dict) -> str:
    """Summarize params for debug logging (paths/objects only, skip large data)."""
    parts = []
    for key in ("paths", "objects"):
        if key in params:
            val = params[key]
            if isinstance(val, list):
                # Show first few paths/object refs
                items = [v[0] if isinstance(v, list) else str(v) for v in val[:3]]
                parts.append(f"{key}={items}")
    return " ".join(parts) if parts else str({k: v for k, v in params.items() if k != "data"})[:200]


class WorkspaceError(Exception):
    """Error from workspace service."""

    def __init__(self, message: str, code: int = -1):
        self.message = message
        self.code = code
        super().__init__(message)
