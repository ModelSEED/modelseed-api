"""Client for the PlantSEED MCP server (annotate + reconstruct tools).

The plantseed server's tools exchange file paths, not file contents: the
caller writes a query FASTA somewhere the server can read, and the server
writes its annotated genome / model JSON under its own output directory.
This client therefore owns the path translation between the worker's view
of the shared directory (`settings.plantseed_jobs_dir`) and the server's
(`settings.plantseed_server_jobs_dir`).

The `mcp` package is imported lazily so the API process and the
microbial worker paths never need it installed.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from modelseed_api.config import settings


class PlantSEEDServiceError(RuntimeError):
    """The PlantSEED service is unconfigured, unreachable, or returned an error."""


class PlantSEEDClient:
    def __init__(
        self,
        url: str,
        token: str = "",
        timeout: float = 3600,
        jobs_dir: str = "",
        server_jobs_dir: str = "",
    ):
        if not url:
            raise PlantSEEDServiceError(
                "PlantSEED service is not configured (MODELSEED_PLANTSEED_MCP_URL is unset)"
            )
        if not jobs_dir:
            raise PlantSEEDServiceError(
                "PlantSEED shared directory is not configured "
                "(MODELSEED_PLANTSEED_JOBS_DIR is unset)"
            )
        self.url = url
        self.token = token
        self.timeout = timeout
        self.jobs_dir = Path(jobs_dir)
        self.server_jobs_dir = server_jobs_dir or jobs_dir

    @classmethod
    def from_settings(cls) -> "PlantSEEDClient":
        return cls(
            url=settings.plantseed_mcp_url,
            token=settings.plantseed_mcp_token,
            timeout=settings.plantseed_mcp_timeout,
            jobs_dir=settings.plantseed_jobs_dir,
            server_jobs_dir=settings.plantseed_server_jobs_dir,
        )

    def to_server_path(self, local_path: Path | str) -> str:
        rel = Path(local_path).resolve().relative_to(self.jobs_dir.resolve())
        return str(Path(self.server_jobs_dir) / rel)

    def to_local_path(self, server_path: str) -> Path:
        try:
            rel = Path(server_path).relative_to(self.server_jobs_dir)
        except ValueError:
            raise PlantSEEDServiceError(
                f"PlantSEED wrote {server_path!r}, outside the shared directory "
                f"{self.server_jobs_dir!r}; the server's PLANTSEED_OUTPUT_DIR "
                "must lie inside it"
            ) from None
        return self.jobs_dir / rel

    def annotate(self, genome_path: Path | str, query_species: str) -> dict:
        return self.call_tool("annotate", {
            "genome": self.to_server_path(genome_path),
            "query_species": query_species,
        })

    def reconstruct(self, genome_server_path: str, model_id: str) -> dict:
        return self.call_tool("reconstruct", {
            "genome": genome_server_path,
            "model_id": model_id,
        })

    def call_tool(self, name: str, arguments: dict) -> dict:
        try:
            result = asyncio.run(self._call_tool(name, arguments))
        except PlantSEEDServiceError:
            raise
        except Exception as exc:
            raise PlantSEEDServiceError(
                f"PlantSEED {name} call to {self.url} failed: {type(exc).__name__}: {exc}"
            ) from exc
        return parse_tool_result(name, result)

    async def _call_tool(self, name: str, arguments: dict):
        import httpx2
        from mcp import Client
        from mcp.client.streamable_http import streamable_http_client

        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        async with httpx2.AsyncClient(headers=headers, timeout=self.timeout) as http:
            transport = streamable_http_client(self.url, http_client=http)
            async with Client(transport, read_timeout_seconds=self.timeout) as client:
                return await client.call_tool(
                    name, arguments, read_timeout_seconds=self.timeout
                )


def parse_tool_result(name: str, result) -> dict:
    """Turn a CallToolResult into the tool's JSON payload, raising on errors."""
    texts = [c.text for c in (result.content or []) if getattr(c, "type", "") == "text"]
    if result.is_error:
        raise PlantSEEDServiceError(f"PlantSEED {name} failed: {' '.join(texts) or 'error'}")

    payload = None
    if texts:
        try:
            payload = json.loads(texts[0])
        except json.JSONDecodeError:
            payload = None
    if payload is None and isinstance(result.structured_content, dict):
        payload = result.structured_content
        if set(payload) == {"result"} and isinstance(payload["result"], dict):
            payload = payload["result"]
    if not isinstance(payload, dict):
        raise PlantSEEDServiceError(f"PlantSEED {name} returned an unreadable result")
    if payload.get("error"):
        raise PlantSEEDServiceError(f"PlantSEED {name} failed: {payload['error']}")
    return payload
