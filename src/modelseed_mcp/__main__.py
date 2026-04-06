"""Allow running as `python -m modelseed_mcp`."""

import os

os.environ.setdefault("MODELSEED_STORAGE_BACKEND", "local")

from modelseed_api.services.biochem_service import init_db

init_db()

from modelseed_mcp.server import mcp  # noqa: E402

mcp.run()
