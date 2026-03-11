# ModelSEED API

Modern REST API backend for the [ModelSEED](https://modelseed.org) metabolic modeling platform. Replaces the legacy Perl-based ProbModelSEED JSON-RPC service with a Python FastAPI application.

## Quick Start (5 minutes)

### Prerequisites

- Python 3.11+
- A [BV-BRC](https://www.bv-brc.org) account (for PATRIC auth token)

### 1. Clone all required repos

```bash
mkdir modelseed && cd modelseed

# This API
git clone https://github.com/ModelSEED/modelseed-api.git

# Modeling engine (MUST use cshenry fork, main branch)
git clone -b main https://github.com/cshenry/ModelSEEDpy.git

# KBase utility library
git clone https://github.com/kbase/KBUtilLib.git

# Data repos
git clone -b dev https://github.com/ModelSEED/ModelSEEDDatabase.git
git clone https://github.com/ModelSEED/ModelSEEDTemplates.git
git clone https://github.com/kbaseapps/cb_annotation_ontology_api.git
```

### 2. Install Python packages

```bash
pip install -e ModelSEEDpy
pip install -e KBUtilLib
pip install -e "modelseed-api[modeling]"
```

### 3. Configure data paths

```bash
cd modelseed-api
cat > .env << EOF
MODELSEED_MODELSEED_DB_PATH=$(realpath ../ModelSEEDDatabase)
MODELSEED_TEMPLATES_PATH=$(realpath ../ModelSEEDTemplates/templates/v7.0)
MODELSEED_CB_ANNOTATION_ONTOLOGY_API_PATH=$(realpath ../cb_annotation_ontology_api)
EOF
```

### 4. Run the server

```bash
cd src && python -m uvicorn modelseed_api.main:app --host 0.0.0.0 --port 8000
```

### 5. Open in browser

| URL | What |
|---|---|
| http://localhost:8000/demo/ | Interactive demo page |
| http://localhost:8000/docs | Swagger API docs (try endpoints interactively) |
| http://localhost:8000/redoc | ReDoc API docs |
| http://localhost:8000/api/health | Health check |

### 6. Get a PATRIC token

1. Log in to https://www.bv-brc.org
2. Open browser console (F12)
3. Run: `copy(TOKEN)`
4. Paste into the demo page token field

## Demo Page Features

Once logged in with a PATRIC token, the demo page provides:

| Tab | What you can do |
|---|---|
| **My Models** | List models, click to view detail, export JSON/SBML/CobraPy |
| **Public Media** | Browse available media formulations |
| **Biochemistry** | Search compounds and reactions |
| **Jobs** | Monitor jobs, build models from BV-BRC genome IDs |
| **Workspace** | Browse PATRIC workspace paths |

On a model detail page:
- **Export** as JSON, SBML, or CobraPy JSON
- **Run FBA** with media selection
- **Run Gapfill** with media selection
- **Integrate/Unintegrate/Delete** gapfill solutions

### Try model reconstruction

1. Go to Jobs tab > **Build Model**
2. Enter a BV-BRC genome ID: `107806.10` (Buchnera, small/fast, ~15s)
3. Select template: Gram Negative
4. Watch the Jobs tab for completion

## API Endpoints

All endpoints require a PATRIC token in the `Authorization` header.

### Models (`/api/models`)
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/models` | List user's models |
| `GET` | `/api/models/data?ref=` | Full model detail (reactions, compounds, genes) |
| `GET` | `/api/models/export?ref=&format=` | Export (json, sbml, cobra-json) |
| `GET` | `/api/models/gapfills?ref=` | List gapfill solutions |
| `POST` | `/api/models/gapfills/manage` | Integrate/unintegrate/delete gapfills |
| `GET` | `/api/models/fba?ref=` | List FBA studies |
| `DELETE` | `/api/models?ref=` | Delete a model |

### Jobs (`/api/jobs`)
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/jobs` | Check job statuses (poll this) |
| `POST` | `/api/jobs/reconstruct` | Build model from BV-BRC genome ID |
| `POST` | `/api/jobs/gapfill` | Gapfill a model |
| `POST` | `/api/jobs/fba` | Run flux balance analysis |
| `POST` | `/api/jobs/manage` | Delete/rerun jobs |

### Biochemistry (`/api/biochem`)
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/biochem/compounds?query=` | Search compounds |
| `GET` | `/api/biochem/reactions?query=` | Search reactions |
| `GET` | `/api/biochem/compounds/{id}` | Get compound by ID |
| `GET` | `/api/biochem/reactions/{id}` | Get reaction by ID |

### Media & Workspace
| Method | Path | Description |
|---|---|---|
| `GET` | `/api/media/public` | List public media formulations |
| `POST` | `/api/workspace/{op}` | Proxy to PATRIC workspace (ls, get, create, delete, etc.) |

## Architecture

```
Browser (Demo page / Future Next.js frontend)
    |
    v
FastAPI REST API (this repo, port 8000)
    |
    +-- /api/workspace/*  --> PATRIC Workspace (p3.theseed.org)
    +-- /api/biochem/*    --> Local ModelSEEDDatabase JSON files
    +-- /api/jobs/*       --> Job dispatch (subprocess or Celery)
    |
Job Scripts (src/job_scripts/)
    |
    +-- reconstruct.py ----> BVBRCUtils (fetch genome) + MSReconstructionUtils (build model)
    +-- gapfill.py --------> MSGapfill + local templates
    +-- run_fba.py --------> cobra.Model.optimize()
```

**Key design decisions:**
- Synchronous API — long-running ops dispatched to external job scripts
- API proxies all workspace calls (shields frontend from future workspace changes)
- Templates loaded from local git repos (not KBase workspace)
- Runs without KBase connection (BV-BRC/PATRIC only)

## Required Repositories

| Repository | Branch | Why this branch |
|---|---|---|
| [cshenry/ModelSEEDpy](https://github.com/cshenry/ModelSEEDpy) | **main** | Has `ModelSEEDBiochem.get(path=)` and `MSFBA` module |
| [ModelSEED/ModelSEEDDatabase](https://github.com/ModelSEED/ModelSEEDDatabase) | **dev** | Current biochemistry data (master is stale, 2021) |
| [ModelSEED/ModelSEEDTemplates](https://github.com/ModelSEED/ModelSEEDTemplates) | **main** | v7.0 templates (Core, GramPos, GramNeg) |
| [kbase/KBUtilLib](https://github.com/kbase/KBUtilLib) | **main** | BVBRCUtils, MSReconstructionUtils |
| [kbaseapps/cb_annotation_ontology_api](https://github.com/kbaseapps/cb_annotation_ontology_api) | **main** | Ontology data for genome annotation |

See [DEPENDENCIES.md](DEPENDENCIES.md) for KBUtilLib initialization patterns and known workarounds.

## Configuration

All settings via environment variables with `MODELSEED_` prefix, or `.env` file:

| Variable | Default | Description |
|---|---|---|
| `MODELSEED_MODELSEED_DB_PATH` | (local path) | ModelSEEDDatabase repo path |
| `MODELSEED_TEMPLATES_PATH` | (local path) | ModelSEEDTemplates/templates/v7.0 path |
| `MODELSEED_CB_ANNOTATION_ONTOLOGY_API_PATH` | (local path) | cb_annotation_ontology_api path |
| `MODELSEED_USE_CELERY` | `false` | Use Celery+Redis for job dispatch |
| `MODELSEED_WORKSPACE_URL` | `https://p3.theseed.org/services/Workspace` | PATRIC workspace URL |

## Project Structure

```
src/
  modelseed_api/
    main.py              # FastAPI app + static file serving
    config.py            # Settings (pydantic-settings, env vars)
    auth/dependencies.py # Token extraction from headers
    routes/              # API endpoint definitions
    schemas/             # Pydantic request/response models
    services/            # Business logic (workspace proxy, model ops)
    jobs/                # Job dispatch (Celery + subprocess)
    static/index.html    # Demo page
  job_scripts/           # External scripts for long-running ops
    reconstruct.py       # BV-BRC genome -> metabolic model
    gapfill.py           # Model gapfilling
    run_fba.py           # Flux balance analysis
```

## License

MIT
