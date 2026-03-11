# ModelSEED API

Modern REST API backend for the [ModelSEED](https://modelseed.org) metabolic modeling platform. Replaces the legacy Perl-based ProbModelSEED JSON-RPC service with a Python FastAPI application.

## Architecture

```
New Frontend (Next.js) ──REST──> modelseed-api (FastAPI) ──JSON-RPC──> PATRIC Workspace
                       ──HTTP──> Solr (biochemistry, direct)
                       ──HTTP──> Shock (file uploads, direct)
```

**Key design decisions:**
- **Synchronous service only** - long-running operations (model reconstruction, gapfilling, FBA) are dispatched to external job scripts
- **Full workspace proxy** - frontend never talks to the Workspace service directly
- **Biochemistry queries** - handled by this API (replaces ms_fba support service for biochem)
- **RAST job listing** - stays on the separate `modelseed_support` service
- **Solr/reference data** - queried directly by the frontend, not proxied

## API Endpoints

### Models (`/api/models`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/models?path=` | List user's metabolic models |
| GET | `/api/models/data?ref=` | Get full model data |
| DELETE | `/api/models?ref=` | Delete a model |
| POST | `/api/models/copy` | Copy a model |
| GET | `/api/models/export?ref=&format=` | Export model (JSON, SBML) |
| GET | `/api/models/gapfills?ref=` | List gapfill solutions |
| POST | `/api/models/gapfills/manage` | Manage gapfill solutions |
| GET | `/api/models/fba?ref=` | List FBA studies |

### Jobs (`/api/jobs`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/jobs?ids=` | Poll job status |
| POST | `/api/jobs/reconstruct` | Dispatch model reconstruction |
| POST | `/api/jobs/gapfill` | Dispatch gapfilling |
| POST | `/api/jobs/fba` | Dispatch FBA |
| POST | `/api/jobs/manage` | Cancel/delete jobs |

### Workspace (`/api/workspace`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/workspace/ls` | List workspace contents |
| POST | `/api/workspace/get` | Get objects/metadata |
| POST | `/api/workspace/create` | Create objects |
| POST | `/api/workspace/copy` | Copy/move objects |
| POST | `/api/workspace/delete` | Delete objects |
| POST | `/api/workspace/metadata` | Update metadata |
| POST | `/api/workspace/download-url` | Get download URLs |
| POST | `/api/workspace/permissions` | List permissions |

### Media (`/api/media`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/media/public` | List public media |
| GET | `/api/media/mine` | List user's media |
| GET | `/api/media/export?ref=` | Export media |

### Biochemistry (`/api/biochem`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/biochem/full` | Get full biochemistry DB |
| GET | `/api/biochem/reactions?ids=` | Get reaction details |
| GET | `/api/biochem/compounds?ids=` | Get compound details |
| POST | `/api/biochem/adjust-reaction` | Adjust model reactions |

### System
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check |

## Authentication

The API accepts PATRIC or RAST authentication tokens in the `Authorization` header. Both token types are supported via the `nexus_emulation` OAuth1 service.

The API does not handle login - the frontend authenticates directly with RAST or PATRIC and passes the token to this API.

## Quick Start

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Copy and configure environment
cp .env.example .env

# Run the development server
uvicorn modelseed_api.main:app --reload --port 8000

# View API docs
open http://localhost:8000/docs
```

## Development

```bash
# Run tests
pytest

# Run with auto-reload
uvicorn modelseed_api.main:app --reload

# Lint
ruff check src/
```

## Project Structure

```
src/
  modelseed_api/
    main.py              # FastAPI app entry point
    config.py            # Configuration (pydantic-settings)
    auth/
      dependencies.py    # Token extraction and user context
    schemas/             # Pydantic request/response models
      models.py          # ModelStats, ModelData, etc.
      jobs.py            # Task
      workspace.py       # ObjectMeta, WS request types
    routes/              # API endpoint definitions
      models.py          # /api/models/*
      jobs.py            # /api/jobs/*
      workspace.py       # /api/workspace/*
      media.py           # /api/media/*
      biochem.py         # /api/biochem/*
    services/            # Business logic wrapping KBUtilLib
      workspace_service.py  # Workspace JSON-RPC proxy
      model_service.py      # Model CRUD + gapfill/FBA listing
    jobs/                # Job dispatch system
      dispatcher.py      # Subprocess-based job dispatch
      store.py           # File-based job status tracking
  job_scripts/           # External scripts for long-running tasks
    reconstruct.py
    gapfill.py
    run_fba.py
tests/
```

## Related Repositories

- [ProbModelSEED](https://github.com/ModelSEED/ProbModelSEED) - Legacy Perl backend (being replaced)
- [ModelSEED-UI](https://github.com/ModelSEED/ModelSEED-UI) - Current AngularJS frontend
- [KBUtilLib](https://github.com/cshenry/KBUtilLib) - Python utility library (service layer)
- [ModelSEEDpy](https://github.com/ModelSEED/ModelSEEDpy) - Core metabolic modeling library
- [Workspace](https://github.com/cshenry/Workspace) - PATRIC Workspace service
