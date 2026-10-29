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

## Configuration

| Variable | Purpose |
|---|---|
| `MODELSEED_PLANTSEED_MCP_URL` | e.g. `http://plantseed-mcp:8931/mcp`. Unset makes plant jobs fail with a clear error. |
| `MODELSEED_PLANTSEED_MCP_TOKEN` | The server's `PLANTSEED_MCP_TOKEN`. |
| `MODELSEED_PLANTSEED_MCP_TIMEOUT` | Per-call timeout in seconds (default 3600). |
| `MODELSEED_PLANTSEED_JOBS_DIR` | Shared directory, worker's view. |
| `MODELSEED_PLANTSEED_SERVER_JOBS_DIR` | Shared directory, server's view (optional). |
| `MODELSEED_PLANTSEED_HOME_DIR` | Folder under `/<user>/` for plant models (default `plantseed`). |

The worker needs the `plantseed` extra (`pip install -e ".[plantseed]"`),
which the production `Dockerfile` installs.

Example server alongside the worker, sharing a named volume:

```bash
docker run -d --name plantseed-mcp --network bioseed_network \
  --read-only --tmpfs /tmp:rw,size=512m,mode=1777 \
  -e PLANTSEED_MCP_TOKEN="$TOKEN" \
  -e PLANTSEED_ANNOT_BUNDLE_DIR=/bundle \
  -e PLANTSEED_OUTPUT_DIR=/shared/out \
  -v /path/to/plantseed-refbuild-bundle:/bundle:ro \
  -v plantseed-shared:/shared \
  plantseed:dev
```

The worker then mounts `plantseed-shared:/shared` and sets
`MODELSEED_PLANTSEED_JOBS_DIR=/shared`. The server runs as UID 10001 and
the worker as root, so the server's output is readable by the worker and the
worker's query files (0644 in a 0755 directory) are readable by the server.
The shared directory itself must be writable by both.
