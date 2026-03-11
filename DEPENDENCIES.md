# ModelSEED API - Dependency Documentation

## Required Repositories

All repos must be cloned locally. The API expects them at paths configured in
`src/modelseed_api/config.py` (overridable via `MODELSEED_*` env vars).

| Repository | Branch | Purpose | Config Key |
|---|---|---|---|
| [cshenry/ModelSEEDpy](https://github.com/cshenry/ModelSEEDpy) | **main** | Core modeling engine (cobra model building, gapfilling, FBA, biochem DB) | `pip install -e .` |
| [kbase/KBUtilLib](https://github.com/kbase/KBUtilLib) | **main** | BVBRCUtils (genome fetch), MSReconstructionUtils (model build), template loading | `pip install -e .` |
| [ModelSEED/ModelSEEDDatabase](https://github.com/ModelSEED/ModelSEEDDatabase) | **dev** | Biochemistry database (compounds, reactions, aliases) | `modelseed_db_path` |
| [ModelSEED/ModelSEEDTemplates](https://github.com/ModelSEED/ModelSEEDTemplates) | **main** | Model templates v7.0 (Core, GramPos, GramNeg) | `templates_path` |
| [kbaseapps/cb_annotation_ontology_api](https://github.com/kbaseapps/cb_annotation_ontology_api) | **main** | Ontology data for genome annotation (FilteredReactions.csv) | `cb_annotation_ontology_api_path` |
| [kbase/cobrakbase](https://github.com/kbase/cobrakbase) | (pip dep) | KBase object factory (genome dict to MSGenome conversion) | installed via pip |

### Critical: ModelSEEDpy Version

**Must use `cshenry/ModelSEEDpy` main branch**, NOT `ModelSEED/ModelSEEDpy` or `Fxe/ModelSEEDpy`.

Chris Henry's fork provides:
- `ModelSEEDBiochem.get(path=...)` for loading biochem from local files
- `modelseedpy.core.msfba.MSFBA` module required by KBUtilLib

Install:
```bash
cd /path/to/ModelSEEDpy
git remote add cshenry https://github.com/cshenry/ModelSEEDpy.git
git fetch cshenry
git checkout cshenry/main -- .
pip install -e .
```

### ModelSEEDDatabase Branch

**Must use `dev` branch** (confirmed by Chris Henry, 2026-03-10).
The `master` branch is from 2021 and is stale.

```bash
cd /path/to/ModelSEEDDatabase
git checkout dev
```

## Python Package Dependencies

Core packages (see `pyproject.toml` for full list):
- `fastapi` + `uvicorn` - Web framework
- `cobra` - Constraint-based modeling (FBA, model I/O)
- `modelseedpy` - ModelSEED modeling engine (from cshenry fork)
- `kbutillib` - KBase utility library
- `cobrakbase` - KBase/cobra bridge
- `celery[redis]` - Job scheduling (production mode)
- `requests` - HTTP client for workspace/BV-BRC API calls
- `pydantic-settings` - Configuration management

## KBUtilLib Initialization (KBase-Independent)

KBUtilLib was designed for KBase apps but can run standalone with these settings:

```python
import os
os.environ['KB_AUTH_TOKEN'] = 'unused'  # cobrakbase requires non-empty value

from kbutillib import BVBRCUtils, MSReconstructionUtils

# No-op the debug save method (requires KBase SDK NotebookUtils)
BVBRCUtils.save = lambda self, name, obj: None

kwargs = dict(
    config_file=False,           # Don't look for KBase config file
    token_file=None,             # Don't look for token file
    kbase_token_file=None,       # Don't look for KBase token file
    token={
        'patric': '<user_token>',
        'kbase': 'unused',      # KBase token not needed for BV-BRC operations
    },
    modelseed_path='<path_to_ModelSEEDDatabase>',
    cb_annotation_ontology_api_path='<path_to_cb_annotation_ontology_api>',
)

bvbrc = BVBRCUtils(**kwargs)
recon = MSReconstructionUtils(**kwargs)
```

## Template Loading (Local Files)

Templates are loaded from local JSON files instead of KBase workspace:

```python
from modelseedpy import MSTemplateBuilder
import json

with open('ModelSEEDTemplates/templates/v7.0/Core-V6.json') as f:
    core_template = MSTemplateBuilder.from_dict(json.load(f)).build()

# Templates loaded from files lack .info attribute - add mock
class _Info:
    def __init__(self, name):
        self.name = name
    def __str__(self):
        return self.name
core_template.info = _Info("Core-V6")
```

Available templates (v7.0):
- `Core-V6.json` - Core metabolism (252 reactions)
- `GramNegModelTemplateV7.json` - Gram-negative (8584 reactions)
- `GramPosModelTemplateV7.json` - Gram-positive (8584 reactions)

## Reconstruction Pipeline

Full E2E flow (tested with Buchnera aphidicola 107806.10, ~14 seconds):

1. `BVBRCUtils.build_kbase_genome_from_api(genome_id)` - Fetch genome from BV-BRC REST API
2. `recon.get_msgenome_from_dict(kbase_genome)` - Convert via cobrakbase KBaseObjectFactory
3. Load templates from local JSON files
4. `recon.build_metabolic_model(genome, classifier=None, ...)` - Build cobra model
5. Result: 462 reactions, 336 genes, FBA objective = 2.875

## Known Workarounds

These are minor patches needed for KBase-independent operation.
All can be fixed upstream in KBUtilLib (discussed with Chris Henry):

1. **`BVBRCUtils.save()` no-op**: `build_kbase_genome_from_api()` calls `self.save("test_genome", genome)` which requires KBase SDK. Patched as no-op lambda.

2. **Template `.info` attribute**: `MSTemplateBuilder.from_dict().build()` doesn't set `.info`, but `build_metabolic_model()` references it. Patched with mock `_Info` class.

3. **Genome classifier bypass**: `MSGenomeClassifier` needs pickle/features files not in the KBUtilLib repo. Bypassed by passing `classifier=None` and specifying `gs_template='gn'` or `'gp'` explicitly.

4. **KBase auth token**: `cobrakbase.KBaseAPI()` requires non-empty `KB_AUTH_TOKEN`. Set to `'unused'` since we don't use KBase workspace.

## Planned Upstream Fixes (KBUtilLib)

Chris Henry has agreed to:
- Add `template_source="git"` config parameter to load templates from local git repo
- This would eliminate workarounds #2 and #4 above

## Job Scheduling

Two modes controlled by `MODELSEED_USE_CELERY` (default: `False`):

- **Local (dev)**: subprocess dispatch, job state in `/tmp/modelseed-jobs/`
- **Production**: Celery + Redis on `redis://bioseed_redis:6379/10`, queue name `modelseed`, monitor at `http://poplar.cels.anl.gov:5555/`
