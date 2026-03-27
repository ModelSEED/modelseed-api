"""ModelSEED API - FastAPI application entry point."""

import logging
import time
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from modelseed_api.config import settings
from modelseed_api.routes import biochem, jobs, media, models, workspace

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("modelseed_api")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log one line per request: METHOD /path [user] -> status (duration)."""

    _skip_prefixes = ("/api/health", "/demo/", "/docs", "/openapi.json", "/redoc")

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in self._skip_prefixes):
            return await call_next(request)

        start = time.time()

        # Extract username from token (best-effort, never block the request)
        username = "anon"
        token = request.headers.get("Authorization") or request.headers.get("Authentication")
        if token:
            raw = token.removeprefix("Bearer ").strip('"').strip("'")
            for part in raw.split("|"):
                if part.startswith("un="):
                    username = part[3:]
                    break

        response = await call_next(request)
        duration_ms = int((time.time() - start) * 1000)
        msg = f"{request.method} {path} [{username}] -> {response.status_code} ({duration_ms}ms)"

        if response.status_code >= 400:
            logger.warning(msg)
        else:
            logger.info(msg)

        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    from modelseed_api.services.biochem_service import init_db

    init_db()
    yield


app = FastAPI(
    title="ModelSEED API",
    description=(
        "Modern REST API backend for the ModelSEED metabolic modeling platform. "
        "Replaces the legacy Perl-based ProbModelSEED JSON-RPC service."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# Middleware (order matters: outermost = first to run)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register route modules
app.include_router(models.router, prefix="/api/models", tags=["Models"])
app.include_router(workspace.router, prefix="/api/workspace", tags=["Workspace"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["Jobs"])
app.include_router(media.router, prefix="/api/media", tags=["Media"])
app.include_router(biochem.router, prefix="/api/biochem", tags=["Biochemistry"])


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Log unhandled exceptions with full traceback."""
    logger.error(f"Unhandled error on {request.method} {request.url}: {exc}")
    logger.error(traceback.format_exc())
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.get("/api/health", tags=["System"])
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "version": "0.1.0"}


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    schema["components"]["securitySchemes"] = {
        "PatricToken": {
            "type": "apiKey",
            "in": "header",
            "name": "Authorization",
            "description": (
                "PATRIC/BV-BRC authentication token. "
                "Get yours: log in to bv-brc.org, open browser console (F12), run copy(TOKEN)."
            ),
        }
    }
    schema["security"] = [{"PatricToken": []}]
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi


# Serve demo page at /demo
_static_dir = Path(__file__).parent / "static"
if _static_dir.is_dir():
    app.mount("/demo", StaticFiles(directory=str(_static_dir), html=True), name="demo")
