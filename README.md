# ModelSEED API

Modern REST API backend for the [ModelSEED](https://modelseed.org) metabolic modeling platform. Replaces the legacy Perl-based ProbModelSEED JSON-RPC service with a Python FastAPI application.

The API handles model listing, reconstruction, gapfilling, FBA, biochemistry queries, and PATRIC workspace operations. Long-running jobs (model building, gapfilling, FBA) are dispatched to external scripts via subprocess or Celery.

A separate Next.js/TypeScript frontend will be built to replace the current ModelSEED website. This repo includes a lightweight demo dashboard at `/demo/` for development and testing.


## Quick Start

### 1. Clone required repositories

```bash
mkdir modelseed && cd modelseed

# This API
git clone https://github.com/ModelSEED/modelseed-api.git

# Modeling engine -- MUST use cshenry fork, main branch
git clone -b main https://github.com/cshenry/ModelSEEDpy.git

# KBase utility library
git clone https://github.com/cshenry/KBUtilLib.git

# KBase/cobra bridge -- MUST use Fxe fork, master branch (pip version is too old)
git clone https://github.com/Fxe/cobrakbase.git

# Data repos
git clone -b dev https://github.com/ModelSEED/ModelSEEDDatabase.git
git clone https://github.com/ModelSEED/ModelSEEDTemplates.git
git clone https://github.com/kbaseapps/cb_annotation_ontology_api.git
```

### 2a. Docker (recommended)

```bash
cd modelseed
docker compose -f modelseed-api/docker-compose.yml up --build
```

Open http://localhost:8000/demo/ -- all Python dependencies are installed inside the container.

### 2b. Manual setup

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

Run the server:

```bash
cd src && python -m uvicorn modelseed_api.main:app --host 0.0.0.0 --port 8000
```

### 3. Open in browser

| URL | Description |
|-----|-------------|
| http://localhost:8000/demo/ | Demo dashboard (development/testing) |
| http://localhost:8000/docs | Swagger API docs (interactive) |
| http://localhost:8000/redoc | ReDoc API docs |
| http://localhost:8000/api/health | Health check |

### Live deployment (poplar)

The API is deployed on poplar via Docker:

| URL | Description |
|-----|-------------|
| http://poplar.cels.anl.gov:8000/demo/ | Demo dashboard |
| http://poplar.cels.anl.gov:8000/docs | Swagger API docs |
| http://poplar.cels.anl.gov:8000/api/health | Health check |

Source and data repos are at `/scratch/jplfaria/repos/`. To redeploy after code changes:

```bash
cd /scratch/jplfaria/repos && docker compose -f modelseed-api/docker-compose.yml up --build -d
```

### 4. Get a PATRIC token

1. Log in to https://www.bv-brc.org
2. Open browser console (F12)
3. Run: `copy(TOKEN)`
4. Paste into the demo page token field


## API Endpoints

All endpoints require a PATRIC token in the `Authorization` header.

### Models (`/api/models`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/models` | List user's models |
| `GET` | `/api/models/data?ref=` | Full model detail (reactions, compounds, genes) |
| `GET` | `/api/models/export?ref=&format=` | Export as json, sbml, or cobra-json |
| `GET` | `/api/models/gapfills?ref=` | List gapfill solutions |
| `POST` | `/api/models/gapfills/manage` | Integrate, unintegrate, or delete gapfills |
| `GET` | `/api/models/fba?ref=` | List FBA studies |
| `DELETE` | `/api/models?ref=` | Delete a model |

### Jobs (`/api/jobs`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/jobs` | Check job statuses (poll this) |
| `POST` | `/api/jobs/reconstruct` | Build model from BV-BRC genome ID |
| `POST` | `/api/jobs/gapfill` | Gapfill a model |
| `POST` | `/api/jobs/fba` | Run flux balance analysis |
| `POST` | `/api/jobs/merge` | Merge multiple models |
| `POST` | `/api/jobs/manage` | Delete or rerun jobs |

### Biochemistry (`/api/biochem`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/biochem/compounds?query=` | Search compounds |
| `GET` | `/api/biochem/reactions?query=` | Search reactions |
| `GET` | `/api/biochem/compounds/{id}` | Get compound by ID |
| `GET` | `/api/biochem/reactions/{id}` | Get reaction by ID |
| `GET` | `/api/biochem/stats` | Database statistics |
| `GET` | `/api/biochem/search?query=&type=` | Unified search |

### Media and Workspace

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/media/public` | List public media formulations |
| `POST` | `/api/workspace/{op}` | Proxy to PATRIC workspace (ls, get, create, delete, etc.) |


## Architecture

```
Browser (Demo dashboard or future Next.js frontend)
    |
    v
FastAPI REST API (this repo, port 8000)
    |
    +-- /api/workspace/*  --> PATRIC Workspace (p3.theseed.org)
    +-- /api/biochem/*    --> Local ModelSEEDDatabase files
    +-- /api/jobs/*       --> Job dispatch (subprocess or Celery)
    |
Job Scripts (src/job_scripts/)
    |
    +-- reconstruct.py ----> BVBRCUtils (fetch genome) + MSReconstructionUtils (build model)
    +-- gapfill.py --------> FBAModelBuilder + MSGapfill + local templates
    +-- run_fba.py --------> cobra.Model.optimize()
```

Key design decisions:

- **Synchronous API** -- long-running operations are dispatched to external job scripts, not handled in-process
- **Workspace proxy** -- the API proxies all PATRIC workspace calls, shielding the frontend from future workspace changes
- **Local templates** -- model templates are loaded from git repos on disk, not from KBase workspace
- **No KBase dependency** -- runs entirely against BV-BRC/PATRIC APIs, no KBase connection needed


## Demo Dashboard (Development Only)

The demo dashboard at `/demo/` is a single-page HTML app for testing API functionality during development. It is not the production frontend.

The production frontend will be a separate Next.js/TypeScript application built by the frontend team. The API is designed to be consumed by any HTTP client.

Demo features:

| Tab | What it does |
|-----|--------------|
| My Models | List models, click to view detail, export, gapfill, run FBA |
| Build Model | Build a new model from a BV-BRC genome ID with optional gapfilling |
| Public Media | Browse available media formulations |
| Biochemistry | Search compounds and reactions in the ModelSEED database |
| Jobs | Monitor running, completed, and failed jobs |
| Workspace | Browse PATRIC workspace paths |


## Dependencies

### Required Repositories

| Repository | Branch | Purpose | Why this branch |
|------------|--------|---------|-----------------|
| [cshenry/ModelSEEDpy](https://github.com/cshenry/ModelSEEDpy) | **main** | Core modeling engine | Has `ModelSEEDBiochem.get(path=)` and MSFBA module; the main ModelSEED/ModelSEEDpy repo does not |
| [ModelSEED/ModelSEEDDatabase](https://github.com/ModelSEED/ModelSEEDDatabase) | **dev** | Biochemistry data (compounds, reactions, aliases) | `master` branch is stale (last updated 2021); `dev` has current data |
| [ModelSEED/ModelSEEDTemplates](https://github.com/ModelSEED/ModelSEEDTemplates) | **main** | Model templates v7.0 (Core, GramPos, GramNeg) | v7.0 templates are only on main |
| [cshenry/KBUtilLib](https://github.com/cshenry/KBUtilLib) | **main** | BVBRCUtils (genome fetch), MSReconstructionUtils (model build) | Main utility library for BV-BRC integration |
| [kbaseapps/cb_annotation_ontology_api](https://github.com/kbaseapps/cb_annotation_ontology_api) | **main** | Ontology data for genome annotation | Required by BVBRCUtils for annotation mapping |
| [Fxe/cobrakbase](https://github.com/Fxe/cobrakbase) | **master** | KBase object factory (genome dict to MSGenome), FBAModel builder | 0.4.0 (master) is required; 0.3.0 on pip lacks `KBaseObjectFactory._build_object()` |

### Python Packages

Core dependencies (see `pyproject.toml`):

- `fastapi` + `uvicorn` -- web framework and ASGI server
- `cobra` -- constraint-based modeling (FBA, SBML I/O)
- `modelseedpy` -- ModelSEED modeling engine (from cshenry fork)
- `kbutillib` -- KBase/BV-BRC utility library
- `cobrakbase` -- KBase/cobra bridge for genome and model objects
- `requests` -- HTTP client for workspace and BV-BRC API calls
- `pydantic-settings` -- configuration management
- `celery[redis]` -- job scheduling (production mode only)


## Workarounds for KBase-Independent Operation

KBUtilLib was designed for KBase notebook apps. Running it standalone requires these workarounds, applied in the job scripts. These should ideally be fixed upstream in KBUtilLib.

### 1. BVBRCUtils.save() no-op

`build_kbase_genome_from_api()` calls `self.save("test_genome", genome)` which requires KBase SDK NotebookUtils. Patched as a no-op:

```python
BVBRCUtils.save = lambda self, name, obj: None
```

### 2. Template .info attribute

`MSTemplateBuilder.from_dict().build()` does not set the `.info` attribute on the template object, but `build_metabolic_model()` references it. Patched with a mock class:

```python
class _Info:
    def __init__(self, name):
        self.name = name
    def __str__(self):
        return self.name

template.info = _Info("GramNegModelTemplateV7")
```

### 3. Genome classifier bypass

`MSGenomeClassifier` needs pickle files and feature data not included in the KBUtilLib repo. Bypassed by passing `classifier=None` and specifying template type explicitly:

```python
recon.build_metabolic_model(genome, classifier=None, gs_template='gn')
```

### 4. KB_AUTH_TOKEN environment variable

`cobrakbase.KBaseAPI()` requires a non-empty `KB_AUTH_TOKEN` environment variable even when not using KBase. Set to a dummy value:

```python
os.environ['KB_AUTH_TOKEN'] = 'unused'
```

### 5. Gapfill solution integration (ModelSEEDpy)

`MSGapfill.run_gapfilling()` returns a raw solution dict but does **not** automatically integrate it into the model. The job scripts must explicitly call `integrate_gapfill_solution()` to add reactions, then `MSModelUtil.create_kb_gapfilling_data(ws_data)` to persist solution metadata to the workspace-format model dict. Without these calls, models appear to have zero gapfillings even though gapfilling ran successfully.

```python
solution = gapfiller.run_gapfilling(media=ms_media)
if solution:
    gapfiller.integrate_gapfill_solution(solution)  # adds reactions to model
    # ... later, before saving:
    ws_data = model.get_data()
    mdlutl.create_kb_gapfilling_data(ws_data)  # writes gapfillings array
```

### 6. PATRIC workspace metadata persistence

`ws.create()` does not reliably persist user metadata passed in the create tuple. An explicit `ws.update_metadata()` call is needed after creating modelfolder objects:

```python
ws.create({"objects": [[path, "modelfolder", folder_meta, ""]], "overwrite": 1})
# Metadata may not persist from create — set explicitly:
ws.update_metadata({"objects": [[path, folder_meta]]})
```

### Planned upstream fixes

Chris Henry has agreed to add a `template_source="git"` configuration parameter to KBUtilLib that would load templates from local git repos, eliminating workarounds 2 and 4.


## KBUtilLib Initialization

Full initialization pattern for running KBUtilLib without KBase:

```python
import os
os.environ['KB_AUTH_TOKEN'] = 'unused'

from kbutillib import BVBRCUtils, MSReconstructionUtils

BVBRCUtils.save = lambda self, name, obj: None

kwargs = dict(
    config_file=False,
    token_file=None,
    kbase_token_file=None,
    token={'patric': '<user_patric_token>', 'kbase': 'unused'},
    modelseed_path='<path_to_ModelSEEDDatabase>',
    cb_annotation_ontology_api_path='<path_to_cb_annotation_ontology_api>',
)

bvbrc = BVBRCUtils(**kwargs)
recon = MSReconstructionUtils(**kwargs)
```


## Template Loading

Templates are loaded from local JSON files instead of KBase workspace:

```python
import json
from modelseedpy import MSTemplateBuilder

with open('ModelSEEDTemplates/templates/v7.0/GramNegModelTemplateV7.json') as f:
    template = MSTemplateBuilder.from_dict(json.load(f)).build()

# Add mock .info (see workaround #2 above)
template.info = _Info("GramNegModelTemplateV7")
```

Available templates (v7.0):

| File | Description |
|------|-------------|
| `Core-V6.json` | Core metabolism (~252 reactions) |
| `GramNegModelTemplateV7.json` | Gram-negative (~8584 reactions) |
| `GramPosModelTemplateV7.json` | Gram-positive (~8584 reactions) |


## Job Scheduling

Two modes controlled by the `MODELSEED_USE_CELERY` setting (default: `false`):

**Local (development):** Jobs run as subprocesses via `src/job_scripts/`. Job state is stored as JSON files in `/tmp/modelseed-jobs/`. No external infrastructure needed.

**Production (Celery+Redis):** Jobs are dispatched via Celery to a shared Redis broker. The Celery task implementations in `src/modelseed_api/jobs/tasks.py` mirror the subprocess job scripts for full parity.

| Setting | Value |
|---------|-------|
| Broker | `redis://bioseed_redis:6379/10` |
| Queue | `modelseed` |
| Time limit | 4 hours |
| Monitoring | `http://poplar.cels.anl.gov:5555/` (Flower) |

To enable Celery mode, set `MODELSEED_USE_CELERY=true` in `.env`. The Redis broker must be reachable. Start the worker:

```bash
cd src && celery -A modelseed_api.jobs.celery_app worker -Q modelseed --loglevel=info
```

### Celery readiness status

The Celery tasks (`tasks.py`) are at **full parity** with the subprocess job scripts:

- **reconstruct**: Fetches genome, builds model, gapfills (optional), saves to workspace with metadata
- **gapfill**: Loads model from workspace, runs MSGapfill, integrates solution, saves back with gapfill data
- **fba**: Loads model, runs cobra optimize, returns flux results

The dispatcher creates job records BEFORE sending to Celery to avoid race conditions with fast-completing tasks.


## Project Structure

```
src/
  modelseed_api/              # FastAPI application (the API)
    main.py                   # App initialization, static file serving
    config.py                 # Settings (pydantic-settings, env vars)
    auth/dependencies.py      # PATRIC/RAST token extraction
    routes/                   # API endpoint definitions
      models.py               #   /api/models/*
      jobs.py                 #   /api/jobs/*
      biochem.py              #   /api/biochem/*
      media.py                #   /api/media/*
      workspace.py            #   /api/workspace/*
    schemas/                  # Pydantic request/response models
    services/                 # Business logic
      workspace_service.py    #   PATRIC workspace proxy
      model_service.py        #   Model CRUD, gapfill management
      biochem_service.py      #   ModelSEEDDatabase queries
      export_service.py       #   SBML/CobraPy export
    jobs/                     # Job dispatch system
      dispatcher.py           #   Subprocess or Celery dispatch
      store.py                #   Job state (JSON files)
      celery_app.py           #   Celery configuration
      tasks.py                #   Celery task definitions
    static/index.html         # Demo dashboard (development only)
  job_scripts/                # External scripts for long-running ops
    reconstruct.py            # BV-BRC genome to metabolic model
    gapfill.py                # Model gapfilling via MSGapfill
    run_fba.py                # Flux balance analysis
    merge_models.py           # Model merging
    utils.py                  # Shared utilities (media parsing, etc.)
tests/
  test_live_integration.py    # Integration tests against live workspace
```


## Configuration

All settings are loaded from environment variables with the `MODELSEED_` prefix, or from a `.env` file. See `.env.example` for the full list.

| Variable | Default | Description |
|----------|---------|-------------|
| `MODELSEED_HOST` | `0.0.0.0` | Server bind address |
| `MODELSEED_PORT` | `8000` | Server port |
| `MODELSEED_DEBUG` | `false` | Enable debug mode |
| `MODELSEED_MODELSEED_DB_PATH` | (required) | Path to ModelSEEDDatabase repo |
| `MODELSEED_TEMPLATES_PATH` | (required) | Path to ModelSEEDTemplates/templates/v7.0 |
| `MODELSEED_CB_ANNOTATION_ONTOLOGY_API_PATH` | (required) | Path to cb_annotation_ontology_api repo |
| `MODELSEED_WORKSPACE_URL` | `https://p3.theseed.org/services/Workspace` | PATRIC workspace URL |
| `MODELSEED_USE_CELERY` | `false` | Use Celery+Redis for job dispatch |
| `MODELSEED_JOB_STORE_DIR` | `/tmp/modelseed-jobs` | Directory for job state files |


## Docker-Specific Challenges

Building the Docker image requires care because several dependencies are not available from pip in the correct versions. The Dockerfile handles these automatically, but they are documented here for troubleshooting.

| Challenge | Symptom | Solution in Dockerfile |
|-----------|---------|----------------------|
| cobrakbase 0.3.0 (pip) is too old | `'KBaseObjectFactory' object has no attribute '_build_object'` | Install from local clone of `Fxe/cobrakbase` master (0.4.0) |
| cobrakbase reads token from file, not env var | `missing token value or ~/.kbase/token file` | `RUN mkdir -p /root/.kbase && echo "unused" > /root/.kbase/token` |
| ModelSEEDpy must be cshenry fork | Missing `ModelSEEDBiochem.get(path=)`, wrong API signatures | Install from local clone of `cshenry/ModelSEEDpy` main |
| pip git installs need git binary | `pip install git+https://...` fails | `apt-get install git` (though we use local clones instead) |
| Install order matters | Import errors from circular or missing deps | Install order: cobrakbase → ModelSEEDpy → KBUtilLib |
| Docker layer caching hides changes | Old code persists despite rebuilds | `docker compose down && docker rmi <image> && docker compose build --no-cache` |

The build context is the **parent directory** containing all sibling repos (not the `modelseed-api/` directory itself). This is set via `context: ..` in `docker-compose.yml`.


## Remaining Work

### Phase 2 features

- Model editing endpoints (edit reactions, compounds)
- PlantSEED endpoints (pipeline, annotate, features, compare regions)
- Import KBase models
- Delete FBA studies
- Reconstruction details endpoint (`GET /api/models/reconstruction?ref=`)

### Production hardening

- CI/CD pipeline
- Integration tests against dev workspace
- Structured logging
- Celery+Redis deployment on poplar (tasks are ready, infrastructure needed)
- Health check enhancements
- Job store file locking for concurrent access

### Upstream improvements needed

| Repo | Issue | Workaround |
|------|-------|------------|
| KBUtilLib | No `template_source="git"` config | Mock `.info` attribute + dummy `KB_AUTH_TOKEN` (workarounds 2, 4) |
| KBUtilLib | `BVBRCUtils.save()` requires NotebookUtils | No-op monkey-patch (workaround 1) |
| KBUtilLib | `MSGenomeClassifier` needs pickle files not in repo | Pass `classifier=None` + explicit template type (workaround 3) |
| KBUtilLib | PR #24 pending: PATRIC media TSV parsing | Custom TSV parser in `job_scripts/utils.py` |
| ModelSEEDpy | `run_gapfilling()` doesn't auto-integrate | Explicit `integrate_gapfill_solution()` + `create_kb_gapfilling_data()` calls (workaround 5) |
| PATRIC WS | `ws.create()` doesn't persist metadata | Explicit `ws.update_metadata()` after create (workaround 6) |


## License

MIT
