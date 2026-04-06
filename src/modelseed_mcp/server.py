"""ModelSEED MCP server — FastMCP instance and tool registration."""

from fastmcp import FastMCP

mcp = FastMCP(
    "ModelSEED",
    instructions=(
        "ModelSEED metabolic modeling server. Provides tools for searching biochemistry "
        "databases (compounds, reactions), building genome-scale metabolic models, "
        "gapfilling, flux balance analysis, and model management. "
        "All models are stored locally as JSON files."
    ),
)

# Import tool modules to register their @mcp.tool() decorators
import modelseed_mcp.tools.biochem  # noqa: F401, E402
import modelseed_mcp.tools.jobs  # noqa: F401, E402
import modelseed_mcp.tools.media  # noqa: F401, E402
import modelseed_mcp.tools.models  # noqa: F401, E402


def main():
    """Entry point for `modelseed-mcp` console script."""
    import os

    os.environ.setdefault("MODELSEED_STORAGE_BACKEND", "local")

    from modelseed_api.services.biochem_service import init_db

    init_db()
    mcp.run()
