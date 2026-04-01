# CLAUDE.md — Project conventions for AI assistants

## What this project is

FastAPI REST API backend for [ModelSEED](https://modelseed.org) metabolic modeling. Replaces the legacy Perl ProbModelSEED service. Provides model listing, reconstruction, gapfilling, FBA, biochemistry queries, and storage operations.

## Architecture

```
FastAPI (uvicorn)
├── routes/          → API endpoints (thin, delegate to services)
├── services/        → Business logic (ModelService, BiochemService)
│   ├── storage_factory.py  → Returns LocalStorageService or WorkspaceService
│   ├── workspace_service.py → PATRIC Workspace proxy
│   └── local_storage_service.py → Filesystem storage (drop-in replacement)
├── jobs/
│   ├── dispatcher.py → Dispatches to subprocess or Celery
│   ├── tasks.py     → Celery tasks (production)
│   └── store.py     → Job status tracking (JSON files)
└── job_scripts/     → Subprocess job scripts (local dev fallback)
```

## Key rules

- **Always use `get_storage_service(token)` from `storage_factory.py`** — never import WorkspaceService directly in production code
- **Always use `settings` from `config.py`** — never use raw `os.getenv()` for config; the `Settings` class uses `env_prefix="MODELSEED_"` so all env vars are prefixed
- **No hardcoded local paths** — use `settings.templates_path`, `settings.modelseed_db_path`, etc.
- **Metadata writes must use merge pattern** — PATRIC workspace `update_metadata` replaces the entire user_meta dict; use `_merge_ws_metadata()` or `_merge_metadata()` helpers

## Dependencies (specific forks required)

| Package | Source | Branch | Why |
|---------|--------|--------|-----|
| ModelSEEDpy | cshenry/ModelSEEDpy | main | Chris Henry's fork has MSFBA, MSBiochem.get(path=) |
| cobrakbase | Fxe/cobrakbase | master | pip version (0.3.0) is too old — lacks KBaseObjectFactory._build_object() |
| KBUtilLib | cshenry/KBUtilLib | main | BVBRCUtils, MSReconstructionUtils |

## Storage backends

Controlled by `MODELSEED_STORAGE_BACKEND`:
- `workspace` (default) — proxies to PATRIC Workspace Service, requires PATRIC auth token
- `local` — reads/writes JSON files to `MODELSEED_LOCAL_DATA_DIR`, no external dependencies except RAST for annotation

Both backends return identical 12-element metadata tuples. All service code works unchanged with either backend.

## Job dispatch

- `MODELSEED_USE_CELERY=false` (default) — spawns subprocess scripts from `src/job_scripts/`
- `MODELSEED_USE_CELERY=true` — sends tasks to Redis via Celery (production on poplar)

Job scripts and Celery tasks must be kept in sync — they implement the same logic.

## Testing

- Live integration tests: `tests/test_live_integration.py` (requires PATRIC token)
- The demo dashboard at `/demo/` exercises most endpoints manually

## Workarounds

See `docs/WORKAROUNDS.md` for all active workarounds with upstream status and code locations.

## Common patterns

### Loading templates
```python
from modelseed_api.jobs.tasks import _load_template
template = _load_template("gn")  # or "gp", "core"
```

### Initializing KBUtilLib
```python
from modelseed_api.jobs.tasks import _init_kwargs
kwargs = _init_kwargs(token)
bvbrc = BVBRCUtils(**kwargs)
```

### Preserving KBase data through cobra.io roundtrip
When converting models through `cobra.io` → `CobraModelConverter`, KBase-specific fields (gapfillings, fbaFormulations, gapfill_data) are lost. Always merge these from the original model_obj before saving. See the gapfill task for the pattern.
