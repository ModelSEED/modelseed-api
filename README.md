# ModelSEED API

Modern REST API backend for the [ModelSEED](https://modelseed.org) metabolic modeling platform. Replaces the legacy Perl-based ProbModelSEED JSON-RPC service with a Python FastAPI application.

The API handles model listing, reconstruction, gapfilling, FBA, biochemistry queries, and PATRIC workspace operations. Long-running jobs (model building, gapfilling, FBA) run as Celery tasks in production or as subprocesses in local development.

The user-facing frontend is a separate Next.js/TypeScript application maintained by Vibhav, deployed at https://modelseed.org. This repo also includes a lightweight demo dashboard at `/demo/` for development and testing.


## Live API

The production API is served at **https://modelseed.org/PMS/**.

| URL | Description |
|-----|-------------|
| https://modelseed.org/PMS/docs | Swagger API docs (interactive) |
| https://modelseed.org/PMS/redoc | ReDoc API docs (readable) |
| https://modelseed.org/PMS/openapi.json | OpenAPI spec |
| https://modelseed.org/PMS/api/health | Health check |
| https://modelseed.org/PMS/demo/ | Demo dashboard |

For deployment, restart procedures, on-call runbook, and infrastructure details, see the private operations repo: [`ModelSEED/modelseed-api-ops`](https://github.com/ModelSEED/modelseed-api-ops). Access is invite-only: ask Chris Henry or Jose Faria.


## Run standalone (your own machine, no ANL setup)

The repo ships a self-contained Docker image on GitHub Container Registry. Bundles all dependencies + biochemistry data; no PATRIC account or RAST account needed for the local-mode workflow.

```bash
docker run -p 8000:8000 ghcr.io/modelseed/modelseed-api:latest
```

Then open `http://localhost:8000/demo/` or hit the API directly:

```bash
curl http://localhost:8000/api/health
curl 'http://localhost:8000/api/biochem/search?query=glucose&type=compounds&limit=5'
```

To persist models across container restarts, bind-mount a host directory:

```bash
docker run -p 8000:8000 \
    -v ~/.modelseed:/data/modelseed \
    ghcr.io/modelseed/modelseed-api:latest
```

The standalone image defaults to local-filesystem storage. Endpoints that need ANL infrastructure (`/api/workspace/*`, `/api/rast/*`) return a clean 503 unless their env vars are configured. See [`docs/STANDALONE.md`](docs/STANDALONE.md) for the full walkthrough including FASTA-to-model recipes and MCP server setup for Claude Desktop.


## API Endpoints

Most endpoints require a PATRIC token in the `Authorization` header (not needed in local mode). Biochemistry endpoints are always public.

### Health

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/api/health` | No | Returns `{"status":"ok","version":"0.1.0"}` |

### Models (`/api/models`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/models` | List user's models |
| `GET` | `/api/models/data?ref=` | Full model detail: reactions, compounds, genes, biomasses |
| `POST` | `/api/models/edit` | Atomic editing: add/remove/modify reactions, compounds, biomass |
| `POST` | `/api/models/copy` | Copy a model to a new workspace path |
| `DELETE` | `/api/models?ref=` | Delete a model |
| `GET` | `/api/models/export?ref=&format=` | Export as `json`, `sbml`, `cobra-json` |
| `GET` | `/api/models/gapfills?ref=` | List gapfill solutions |
| `POST` | `/api/models/gapfills/manage` | Integrate, unintegrate, or delete gapfill solutions |
| `GET` | `/api/models/fba?ref=` | List FBA studies for a model |
| `GET` | `/api/models/fba/data?ref=&fba_id=` | Get FBA result with reaction fluxes |
| `GET` | `/api/models/edits?ref=` | List edit history (stub: returns `[]`) |

### Jobs (`/api/jobs`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/jobs` | Check job statuses (supports `ids` filter and status filters) |
| `POST` | `/api/jobs/reconstruct` | Build a metabolic model from a BV-BRC genome ID |
| `POST` | `/api/jobs/gapfill` | Gapfill a model against a media condition |
| `POST` | `/api/jobs/fba` | Run flux balance analysis |
| `POST` | `/api/jobs/merge` | Merge multiple models |
| `POST` | `/api/jobs/manage` | Delete or rerun jobs |

### Biochemistry (`/api/biochem`, no auth)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/biochem/stats` | Compound and reaction counts |
| `GET` | `/api/biochem/reactions?ids=` | Get reactions by comma-separated IDs |
| `GET` | `/api/biochem/compounds?ids=` | Get compounds by comma-separated IDs |
| `GET` | `/api/biochem/search?query=&type=` | Search compounds or reactions (limit up to 200) |

### RAST (`/api/rast`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/rast/jobs` | List user's legacy RAST annotation jobs (RAST token required) |
| `GET` | `/api/rast/genome` | Fetch a RAST-annotated genome translated to KBase Genome shape |

### Media (`/api/media`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/media/public` | List public media formulations |
| `GET` | `/api/media/mine` | List user's custom media |
| `GET` | `/api/media/export?ref=` | Export a media condition |

### Workspace proxy (`/api/workspace`)

All workspace operations are POST-based proxies to the PATRIC Workspace service.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/workspace/ls` | List workspace contents |
| `POST` | `/api/workspace/get` | Get workspace objects (supports `metadata_only`) |
| `POST` | `/api/workspace/create` | Create workspace objects |
| `POST` | `/api/workspace/copy` | Copy or move workspace objects |
| `POST` | `/api/workspace/delete` | Delete workspace objects |
| `POST` | `/api/workspace/metadata` | Update workspace object metadata |
| `POST` | `/api/workspace/download-url` | Get download URLs |
| `POST` | `/api/workspace/permissions` | List permissions |


## MCP Server (AI assistant interface)

The MCP server exposes ModelSEED tools to AI assistants via the [Model Context Protocol](https://modelcontextprotocol.io). Runs in **local storage mode only** (no PATRIC account, no auth tokens, no network beyond BV-BRC genome fetching).

MCP tools call the same service layer as the REST API directly (no HTTP overhead, identical behavior).

### Run

```bash
python -m modelseed_mcp
# or, after pip install:
modelseed-mcp
```

### Claude Desktop / Claude Code config

```json
{
  "mcpServers": {
    "modelseed": {
      "command": "python",
      "args": ["-m", "modelseed_mcp"],
      "env": {
        "MODELSEED_MODELSEED_DB_PATH": "/path/to/ModelSEEDDatabase",
        "MODELSEED_TEMPLATES_PATH": "/path/to/ModelSEEDTemplates/templates/v7.0",
        "MODELSEED_CB_ANNOTATION_ONTOLOGY_API_PATH": "/path/to/cb_annotation_ontology_api"
      }
    }
  }
}
```

### MCP tools (17)

| Group | Tools |
|---|---|
| Biochemistry | `search_compounds`, `search_reactions`, `get_compound`, `get_reaction` |
| Models | `list_models`, `get_model`, `delete_model`, `copy_model`, `export_model`, `edit_model` |
| Media | `list_media`, `get_media` |
| Async jobs | `build_model`, `gapfill_model`, `run_fba`, `merge_models`, `check_job` |

Async tools dispatch jobs via subprocess and poll until completion. Set `wait=False` to get the job ID immediately and poll manually with `check_job`.


## Run it locally

### 1. Clone required repositories

The build context expects all sibling repos as siblings of `modelseed-api/`.

```bash
mkdir modelseed && cd modelseed
git clone https://github.com/ModelSEED/modelseed-api.git
git clone -b main https://github.com/cshenry/ModelSEEDpy.git
git clone https://github.com/cshenry/KBUtilLib.git
git clone https://github.com/Fxe/cobrakbase.git
git clone -b dev https://github.com/ModelSEED/ModelSEEDDatabase.git
git clone https://github.com/ModelSEED/ModelSEEDTemplates.git
git clone https://github.com/kbaseapps/cb_annotation_ontology_api.git
```

### 2a. Docker (recommended)

```bash
docker compose -f modelseed-api/docker-compose.yml up --build
```

### 2b. Manual

```bash
pip install -e cobrakbase
pip install -e ModelSEEDpy
pip install -e KBUtilLib
pip install -e "modelseed-api[modeling]"
```

Configure data paths:

```bash
cd modelseed-api
cat > .env << EOF
MODELSEED_MODELSEED_DB_PATH=$(realpath ../ModelSEEDDatabase)
MODELSEED_TEMPLATES_PATH=$(realpath ../ModelSEEDTemplates/templates/v7.0)
MODELSEED_CB_ANNOTATION_ONTOLOGY_API_PATH=$(realpath ../cb_annotation_ontology_api)
EOF
```

Start the server:

```bash
cd src && python -m uvicorn modelseed_api.main:app --host 0.0.0.0 --port 8000
```

### 2c. Local mode (no PATRIC account needed)

To run without PATRIC Workspace, use the local storage backend. Models are stored as JSON files on disk.

```bash
cat >> modelseed-api/.env << EOF
MODELSEED_STORAGE_BACKEND=local
MODELSEED_LOCAL_DATA_DIR=~/.modelseed/data
EOF
```

In local mode, no authentication is required. Public media formulations are bundled in `data/media/public/`.

### 3. Verify it's running

After starting the server (any of 2a / 2b / 2c), it listens on port 8000:

| URL | Description |
|-----|-------------|
| http://localhost:8000/api/health | Health check |
| http://localhost:8000/docs | Swagger API docs |
| http://localhost:8000/redoc | ReDoc API docs |
| http://localhost:8000/demo/ | Demo dashboard |

### 4. Get a PATRIC token (workspace mode only)

1. Log in to https://www.bv-brc.org
2. Open browser console (F12)
3. Run: `copy(TOKEN)`
4. Paste into the demo page token field, or set as the `Authorization` header in API calls.


## Architecture

This repo contains two interfaces to the same modeling engine:

```
                      Shared Service Layer
                      (biochem_service, ModelService, JobDispatcher,
                       export_service, JobStore, storage_factory)
                              |
            ----------------------------------
            |                                |
       REST API (HTTP)                  MCP Server
       modelseed_api                    modelseed_mcp
       FastAPI + uvicorn                FastMCP (stdio)
            |                                |
       Browser / Frontend              AI Assistants
       (PATRIC auth tokens)            (Claude, etc., local mode)
```

**REST API** (`modelseed_api`): HTTP endpoints for browsers and frontends. Supports both PATRIC Workspace and local storage. Requires auth tokens for workspace mode.

**MCP Server** (`modelseed_mcp`): MCP interface for AI assistants. Local storage mode only. No auth, no network dependencies. Calls the same service layer directly.

Key design decisions:

- **Synchronous API**: long-running operations are dispatched to external job scripts or Celery tasks
- **Pluggable storage**: a factory selects PATRIC Workspace (`storage_backend=workspace`) or local filesystem (`storage_backend=local`); both implement the same interface
- **Fully offline local mode**: with `storage_backend=local`, no PATRIC account or network access is needed; models are stored as JSON files on disk
- **Local templates**: model templates are loaded from git repos on disk, not from KBase workspace
- **No KBase dependency**: runs entirely against BV-BRC/PATRIC APIs

### REST API vs MCP

| | REST API | MCP Server |
|---|---|---|
| Client | Browsers, frontends, scripts | AI assistants |
| Transport | HTTP (port 8000) | stdio (Model Context Protocol) |
| Auth | PATRIC tokens (workspace mode) | None (local mode only) |
| Storage | Workspace or local | Local only |
| Install | `pip install -e ".[modeling]"` | `pip install -e ".[modeling,mcp]"` |


## Demo dashboard

The demo dashboard at `/demo/` is a single-page HTML app for testing API functionality during development. It is not the production frontend.

| Tab | What it does |
|-----|--------------|
| My Models | List models, view detail, export, gapfill, run FBA |
| Build Model | Build a new model from a BV-BRC genome ID with optional gapfilling |
| Public Media | Browse available media formulations |
| Biochemistry | Search compounds and reactions |
| Jobs | Monitor running, completed, and failed jobs |
| Workspace | Browse PATRIC workspace paths |


## Dependencies

### Required repositories

| Repository | Branch | Purpose |
|------------|--------|---------|
| [cshenry/ModelSEEDpy](https://github.com/cshenry/ModelSEEDpy) | `main` | Core modeling engine (cshenry fork has `ModelSEEDBiochem.get(path=)` and MSFBA) |
| [ModelSEED/ModelSEEDDatabase](https://github.com/ModelSEED/ModelSEEDDatabase) | `dev` | Biochemistry data (compounds, reactions, aliases) |
| [ModelSEED/ModelSEEDTemplates](https://github.com/ModelSEED/ModelSEEDTemplates) | `main` | Model templates v7.0 (Core, GramPos, GramNeg) |
| [cshenry/KBUtilLib](https://github.com/cshenry/KBUtilLib) | `main` | BVBRCUtils (genome fetch), MSReconstructionUtils (model build) |
| [kbaseapps/cb_annotation_ontology_api](https://github.com/kbaseapps/cb_annotation_ontology_api) | `main` | Ontology data for genome annotation |
| [Fxe/cobrakbase](https://github.com/Fxe/cobrakbase) | `master` | KBase object factory and FBAModel builder (0.4.0; pip 0.3.0 lacks `_build_object()`) |

### Python packages

Core dependencies (see `pyproject.toml`):

- `fastapi` + `uvicorn`: web framework and ASGI server
- `cobra`: constraint-based modeling (FBA, SBML I/O)
- `modelseedpy`: ModelSEED modeling engine (cshenry fork)
- `kbutillib`: KBase/BV-BRC utility library
- `cobrakbase`: KBase/cobra bridge
- `requests`: HTTP client for workspace and BV-BRC API calls
- `pydantic-settings`: configuration management
- `celery[redis]`: job scheduling (production mode only)
- `fastmcp`: MCP server framework (optional)


## Job scheduling

Two modes controlled by `MODELSEED_USE_CELERY` (default: `false`):

- **Local (development):** jobs run as subprocesses via `src/job_scripts/`. Job state is stored as JSON files in `/tmp/modelseed-jobs/`. No external infrastructure needed.
- **Production:** jobs are dispatched via Celery to a Redis broker. The Celery task implementations in `src/modelseed_api/jobs/tasks.py` mirror the subprocess job scripts for full parity.

| Setting | Value |
|---------|-------|
| Broker | configured via `MODELSEED_CELERY_BROKER_URL` (Redis) |
| Queue | `modelseed` |
| Time limit | 4 hours |

To enable Celery mode, set `MODELSEED_USE_CELERY=true` in `.env`. Start the worker:

```bash
cd src && celery -A modelseed_api.jobs.celery_app worker -Q modelseed --loglevel=info
```


## Configuration

All settings load from environment variables with the `MODELSEED_` prefix or from a `.env` file. See `.env.example` for the full list.

| Variable | Default | Description |
|----------|---------|-------------|
| `MODELSEED_HOST` | `0.0.0.0` | Server bind address |
| `MODELSEED_PORT` | `8000` | Server port |
| `MODELSEED_DEBUG` | `false` | Enable debug mode |
| `MODELSEED_CORS_ORIGINS` | `["*"]` | Allowed CORS origins (JSON list) |
| `MODELSEED_STORAGE_BACKEND` | `workspace` | `workspace` (PATRIC) or `local` (filesystem) |
| `MODELSEED_LOCAL_DATA_DIR` | `~/.modelseed/data` | Local storage directory (local mode) |
| `MODELSEED_MODELSEED_DB_PATH` | required | Path to ModelSEEDDatabase repo |
| `MODELSEED_TEMPLATES_PATH` | required | Path to ModelSEEDTemplates/templates/v7.0 |
| `MODELSEED_CB_ANNOTATION_ONTOLOGY_API_PATH` | required | Path to cb_annotation_ontology_api repo |
| `MODELSEED_WORKSPACE_URL` | `https://p3.theseed.org/services/Workspace` | PATRIC workspace URL |
| `MODELSEED_WORKSPACE_TIMEOUT` | `1800` | Workspace HTTP request timeout (seconds) |
| `MODELSEED_PUBLIC_MEDIA_PATH` | `/chenry/public/modelsupport/media` | Workspace path for public media |
| `MODELSEED_USE_CELERY` | `false` | Use Celery+Redis for job dispatch |
| `MODELSEED_CELERY_BROKER_URL` | `redis://localhost:6379/0` | Celery Redis broker URL |
| `MODELSEED_CELERY_RESULT_BACKEND` | `redis://localhost:6379/0` | Celery Redis result backend URL |
| `MODELSEED_JOB_STORE_DIR` | `/tmp/modelseed-jobs` | Directory for job state files |
| `MODELSEED_RAST_JOBS_DIR` | (empty) | Filesystem path to RAST job dirs (`/api/rast/genome`). Leave empty to disable. |
| `MODELSEED_RAST_DB_HOST` | (empty) | RAST job database host (`/api/rast/jobs`). Leave empty to disable. |
| `MODELSEED_RAST_DB_PORT` | `3306` | RAST job database port |
| `MODELSEED_RAST_DB_USER` | (empty) | RAST job database user |
| `MODELSEED_RAST_DB_PASSWORD` | (empty) | RAST job database password |
| `MODELSEED_RAST_DB_NAME` | `RastProdJobCache` | RAST job database name |


## Project structure

```
src/
  modelseed_api/              # FastAPI application (REST API)
    main.py                   # App initialization
    config.py                 # Settings (pydantic-settings)
    auth/dependencies.py      # PATRIC/RAST token extraction
    routes/                   # API endpoint definitions
    schemas/                  # Pydantic request/response models
    services/                 # Business logic (shared with MCP)
      storage_factory.py      #   WorkspaceService or LocalStorageService
      workspace_service.py    #   PATRIC workspace proxy
      local_storage_service.py#   Filesystem storage backend
      model_service.py        #   Model CRUD, gapfill management
      biochem_service.py      #   ModelSEEDDatabase queries
      export_service.py       #   SBML / CobraPy export
      rast_service.py         #   RAST endpoints (direct MySQL + filesystem)
    jobs/                     # Job dispatch (shared with MCP)
      dispatcher.py           #   Subprocess or Celery dispatch
      store.py                #   Job state (JSON files)
      celery_app.py
      tasks.py                #   Celery task definitions
    static/index.html         # Demo dashboard
  modelseed_mcp/              # MCP server (AI assistant interface)
    server.py                 # FastMCP instance + tool registration
    tools/                    # MCP tool definitions
  job_scripts/                # External scripts for long-running ops
    reconstruct.py
    gapfill.py
    run_fba.py
    merge_models.py
data/
  media/public/               # Bundled public media formulations
docs/
  WORKAROUNDS.md              # Active workarounds with upstream status
  KNOWN_GAPS.md               # Known gaps and follow-ups
  API_ONBOARDING.md           # Onboarding guide for frontend developers
  E2E_TEST_PLAN.md            # End-to-end test plan
tests/
  conftest.py
  test_live_integration.py    # Integration tests against live workspace
  test_auth.py                # Auth dependency unit tests
  test_mcp/                   # MCP tool unit tests
  live/                       # Layered live test suite (smoke / functional / biological / ui)
```


## Workarounds

A small number of upstream-fix-needed workarounds are tracked in [`docs/WORKAROUNDS.md`](docs/WORKAROUNDS.md) with current upstream status. Most prior workarounds have been merged upstream as of 2026-05.


## Contributing

Open issues and PRs at https://github.com/ModelSEED/modelseed-api/issues. For internal operational concerns (deployment, restarts, on-call), use the private [`modelseed-api-ops`](https://github.com/ModelSEED/modelseed-api-ops) repo instead.


## License

MIT
