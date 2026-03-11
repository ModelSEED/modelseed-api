"""ModelSEED API - FastAPI application entry point."""

import logging
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from modelseed_api.config import settings
from modelseed_api.routes import biochem, jobs, media, models, workspace

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("modelseed_api")


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

# CORS
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


# Serve demo page at /demo
_static_dir = Path(__file__).parent / "static"
if _static_dir.is_dir():
    app.mount("/demo", StaticFiles(directory=str(_static_dir), html=True), name="demo")
