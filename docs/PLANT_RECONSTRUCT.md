# Plant reconstruction (PlantSEED)

`POST /api/jobs/reconstruct` with `template_type: "plant"` annotates a plant
proteome against curated PlantSEED orthogroups and builds a primary-metabolism
model from that annotation. It replaces the legacy ProbModelSEED
`annotate_plant_genome` path.

## Request

```json
{
  "genome": "Populus trichocarpa v4.1",
  "template_type": "plant",
  "genome_fasta": ">Potri.001G000100.1.p\nMKV...\n...",
  "query_species": "Ptrichocarpa_v4.1"
}
```

| Field | Required | Notes |
|---|---|---|
| `genome` | yes | Display name. Its sanitized form is the model ID and folder name. |
| `genome_fasta` | yes | Protein FASTA. The UI checks that it is protein before submitting. A `<species>\|\|` prefix on headers is accepted and replaced. |
| `query_species` | no | Label used to prefix gene IDs during annotation. Defaults to the sanitized `genome`. |
| `output_path` | no | Defaults to `/<user>/plantseed/<genome>`. |

Plant models are not gapfilled: `gapfill` and `media` are ignored for plant
requests. `rast_job_id` is rejected for plant requests and `query_species`
for microbial ones. The job is
dispatched as app `PlantReconstruction` (Celery task
`modelseed.plant_reconstruct`, subprocess script `plant_reconstruct.py`).

## Output

The model folder holds the same objects as a microbial reconstruction plus
the annotation:

| Object | Type | Content |
|---|---|---|
| `<output_path>` | `modelfolder` | Model stats; `source: PlantSEED`, `plantseed: "1"` |
| `<output_path>/genome` | `genome` | Annotated genes: `function` (PlantSEED roles with compartments), `protein_translation`, and an `annotation_summary` |
| `<output_path>/model` | `model` | KBase FBAModel from PlantSEED; `genome_ref` points at the genome above |
| `<output_path>/cobra_model` | `string` | cobra JSON with `bio1` as objective |

`GET /api/models` lists `/<user>/plantseed/` alongside `/<user>/modelseed/`.

Only genes that received a PlantSEED annotation are saved in `genome`;
`annotation_summary` records how many proteins were submitted, placed, and
annotated.

## How it runs

The worker calls two tools on the PlantSEED MCP server (`plantseed:dev`
image, `Scripts/PlantSEED_v3/Delivery` in ModelSEED/PlantSEED):

1. `annotate`: DIAMOND placement into curated orthogroups and PSI scoring.
   Measured at about 45 s for 500 proteins and 6:41 for the full 52,400-gene
   Poplar proteome.
2. `reconstruct`: builds the FBAModel from the annotated genome (seconds).

The tools exchange file paths, so the worker and the server need a shared
directory:

- The worker writes `<PLANTSEED_JOBS_DIR>/plant-<job_id>/query.faa`.
- The server must run with `PLANTSEED_OUTPUT_DIR` inside that directory, so
  its outputs are readable by the worker.
- If the directory is mounted at different paths in the two containers, set
  `MODELSEED_PLANTSEED_SERVER_JOBS_DIR` to the server's path.

Per-job files are deleted when the job ends, whether it succeeded or failed.

### Why a separate service, and why MCP

A separate service rather than importing PlantSEED into the worker: the
annotator needs `diamond` and `mafft` binaries and a 1.6 GB reference bundle
that is versioned with PlantSEED's curation, not with modelseed-api. Keeping
them in one PlantSEED-owned image means the worker image does not change when
the curation or bundle does, and the code path is the one PlantSEED tests.

MCP rather than a bespoke HTTP API: the PlantSEED image already serves MCP
(the same server is used by AI agents, and the CDM Task Service lane runs the
same image), so it is an existing, tested interface rather than a second one
to maintain. To this worker it is just JSON over HTTP POST with a bearer
token, through one small client (`services/plantseed_client.py`). If a plain
REST endpoint is added to the PlantSEED image later, only that client
changes.

## Configuration

| Variable | Purpose |
|---|---|
| `MODELSEED_PLANTSEED_URL` | e.g. `http://plantseed-mcp:8931/mcp`. Unset disables plant reconstruction: `POST /api/jobs/reconstruct` with `template_type: "plant"` returns 503 `PLANTSEED_UNAVAILABLE` and dispatches nothing. |
| `MODELSEED_PLANTSEED_TOKEN` | The service's `PLANTSEED_MCP_TOKEN`. |
| `MODELSEED_PLANTSEED_TIMEOUT` | Per-call timeout in seconds (default 3600). |
| `MODELSEED_PLANTSEED_JOBS_DIR` | Shared directory, worker's view. |
| `MODELSEED_PLANTSEED_SERVER_JOBS_DIR` | Shared directory, server's view (optional). |
| `MODELSEED_PLANTSEED_HOME_DIR` | Folder under `/<user>/` for plant models (default `plantseed`). |

The worker needs the `plantseed` extra (`pip install -e ".[plantseed]"`),
which the production `Dockerfile` installs.

## Deployment

The hosted deployment runs the service as `plantseed-mcp` in the same
compose project as the worker (ModelSEED/modelseed-api-ops
`docker-compose.api.yml`, runbook section "PlantSEED service"). The shape
of it:

- `plantseed-mcp` has no host port; the worker reaches it by service name on
  the compose network.
- Both containers mount the same named volume at `/output`. The server uses
  it as `PLANTSEED_OUTPUT_DIR`; the worker sets
  `MODELSEED_PLANTSEED_JOBS_DIR=/output`.
- The server runs as UID 10001, so the volume must be owned by 10001
  (writable by the server, and by the worker as root). The ops compose does
  this with a one-shot init container.
- The server's MCP transport only answers Host names it is told about:
  `PLANTSEED_MCP_ALLOWED_HOSTS=plantseed-mcp:*`. Otherwise a call by service
  name gets `HTTP 421`.

Standalone images leave `MODELSEED_PLANTSEED_URL` unset; plant requests then
return 503 and nothing else changes.
