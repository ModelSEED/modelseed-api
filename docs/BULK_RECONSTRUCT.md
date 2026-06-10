# Bulk reconstruction endpoint

`POST /api/jobs/bulk_reconstruct` builds N metabolic models in one
call from probabilistic-annotation inputs. Per-genome COBRApy JSON
models plus combined `reactions.csv` and `genes.csv` are written to
the user's workspace. Implements Chris Henry's Phase 3 PRD.

## Request shape

```json
POST /api/jobs/bulk_reconstruct
Authorization: <PATRIC or RAST token>
Content-Type: application/json

{
  "genomes": [
    {
      "genome_id": "Ecoli_K12",
      "annotations": {
        "geneA": {
          "KO": [{"term": "K00001", "score": 0.9}],
          "EC": [{"term": "1.1.1.1", "score": 0.6}]
        },
        "geneB": {
          "SSO": [{"term": "SSO_alcohol_dehydrogenase", "score": 1.0}]
        }
      }
    }
  ],
  "template_type": "auto",
  "atp_safe": true,
  "gapfill": false,
  "gapfill_media": null,
  "fva": true,
  "output_path": null
}
```

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `genomes` | list | required | Max 100 per call (Pydantic enforced, 422 if over). |
| `genomes[].genome_id` | string | required | Stable id; keys per-genome outputs. |
| `genomes[].annotations` | `{gene_id: {ontology_type: [{term, score}]}}` | required | Score in [0.0, 1.0]. Ontology types: SSO, EC, KO; others accepted. |
| `template_type` | enum | `"auto"` | `auto` runs the classifier per genome. Other values: `core`, `gn`, `gp`, `grampos`, `gramneg`, `ar`, `archaea`. |
| `atp_safe` | bool | `true` | Run the ATP correction step. |
| `gapfill` | bool | `false` | Run MSGapfill per genome. Adds ~2-5s/genome. |
| `gapfill_media` | string \| null | none | Workspace path or built-in media name. Required when `gapfill=true`. |
| `fva` | bool | `true` | Run FVA on rich + minimal media to populate the flux/class columns. Adds ~30s-2min per genome. When false, columns are emitted empty. |
| `output_path` | string \| null | derived | Workspace directory. Defaults to `/<user>/modelseed/bulk_<job_id>/`. |

The route also accepts `?skip_validation=true` to bypass pre-flight
checks (gapfill_media existence). Default off.

## Response

Returns a single job id (string). Poll `/api/jobs?ids=<job_id>` for
status. The final `result` payload has shape:

```json
{
  "status": "success",      // or "partial" when any genome failed
  "total": 5,
  "succeeded": 4,
  "failed": 1,
  "output_path": "/jplfaria@patricbrc.org/modelseed/bulk_<job_id>",
  "reactions_rows": 4200,
  "genes_rows": 3100,
  "per_genome": {
    "Ecoli_K12": {
      "status": "success",
      "genome_id": "Ecoli_K12",
      "reactions": 845,
      "metabolites": 920,
      "genes": 420,
      "unmapped_genes": 12,
      "classification": "gn",
      "gapfilled": false,
      "gapfill_solutions": 0,
      "fva": true
    },
    "bogus_id": {
      "status": "failed",
      "genome_id": "bogus_id",
      "error": "ValueError: annotations is empty"
    }
  }
}
```

A single bad genome surfaces in `per_genome.<id>` with
`status: "failed"` plus an error string; the rest of the batch is
not affected.

## Outputs in the workspace

At `output_path` (default `/<user>/modelseed/bulk_<job_id>/`):

| Path | Type | Notes |
|------|------|-------|
| `model_<genome_id>.json` | string | COBRApy JSON model, one per successful genome. |
| `reactions.csv` | string | Combined, one row per (genome_id, reaction_id). |
| `genes.csv` | string | Combined, one row per (genome_id, gene_id). |

## CSV column specs

`reactions.csv` mirrors KBDatalakeApps' `genome_reaction` schema:

```
genome_id, reaction_id, genes, equation_names, equation_ids,
directionality, upper_bound, lower_bound, gapfilling_status,
rich_media_flux, rich_media_class, minimal_media_flux, minimal_media_class
```

- `genes` is `rxn.gene_reaction_rule` (e.g. `(b1234 or b5678)`).
- `directionality` is one of `reversible`, `forward`, `reverse`, `blocked`.
- `gapfilling_status` is one of `core`, `rich`, `minimal`, `none`.
- `rich_*` / `minimal_*` are populated only when `fva=true`; empty (not null) otherwise.

`genes.csv` mirrors KBDatalakeApps' gene table with one extra column:

```
genome_id, gene_id, reaction, rich_media_flux, rich_media_class,
minimal_media_flux, minimal_media_class, disposition
```

- `reaction` is `;`-delimited list of reaction ids the gene participates in (empty when unmapped).
- `disposition` is `mapped` or `unmapped`. The PRD requires unmapped genes to be retained with a clear marker; this column adds it explicitly.
- `rich_media_flux` is the max abs(flux) across the gene's reactions; class is the most-constrained (essential > variable > blocked).

## Expected timing

Wall clock per batch, FVA on:

| Genome count | template_type | Approx duration |
|--------------|---------------|-----------------|
| 1 | gn (skip classifier) | ~30s |
| 1 | auto | ~45s |
| 10 | auto | ~5-10 min |
| 100 | auto | ~50-100 min |

FVA dominates. Setting `fva=false` cuts batch wall-clock by 5-10x; the
flux/class columns are then emitted empty.

## Pre-flight checks

Same pattern as the single-genome endpoints (see
`docs/JOB_ERROR_UI_INTEGRATION.md`):

- Pydantic validates `genomes` list size (max 100), template_type enum,
  score range [0,1], and the `gapfill -> gapfill_media required`
  cross-field rule.
- Workspace validation runs on `gapfill_media` when set.
- Per-genome inputs are validated inside the worker loop (one bad
  genome doesn't 422 the whole batch; it surfaces in `per_genome`).

## End-to-end example (curl)

```bash
source ~/.modelseed_tokens.env
JOB=$(curl -sS -X POST \
  -H "Authorization: $MODELSEED_TEST_TOKEN" \
  -H "Content-Type: application/json" \
  http://poplar.cels.anl.gov:3004/api/jobs/bulk_reconstruct \
  -d @tests/fixtures/bulk_smoke_2genomes.json | tr -d '"')
echo "submitted: $JOB"

while true; do
  STATUS=$(curl -sS -H "Authorization: $MODELSEED_TEST_TOKEN" \
    "http://poplar.cels.anl.gov:3004/api/jobs?ids=$JOB" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['$JOB']['status'])")
  echo "$STATUS"
  case "$STATUS" in completed|failed) break ;; esac
  sleep 10
done
```

## Architectural notes

- One Celery task per batch (not per genome). Per-genome errors are
  isolated inside the loop; the batch wraps a single `result` for
  consumers to poll on.
- The actual workflow lives in `tasks._run_bulk_reconstruct`; the
  Celery task is a thin wrapper that adds progress callbacks. The
  subprocess script under `job_scripts/bulk_reconstruct.py` calls the
  same function so the two paths can't drift.
- Combined CSV writing happens at the end of the batch (one workspace
  write each for reactions.csv + genes.csv) instead of per-genome
  appends, to minimize workspace round-trips.
- Upstream prereqs that ship the build path: `cshenry/ModelSEEDpy#26`
  adds the `AnnotationOntology.from_prd_input` factory and fixes the
  latent `msbuilder.py:789` `anno_ont.get_feature` bug. The route works
  the moment that PR is merged + the poplar image rebuilt.

## Out of scope for v1

- Parallel per-genome execution within a single batch (currently
  sequential). Revisit if real workloads hit the wall.
- Streaming progress updates back to the caller mid-batch. v1 returns
  when the whole batch finishes; intermediate state is visible via
  `job.progress`.
- A tarball download endpoint. Workspace path is the contract.
- Structured per-genome error contract matching the pre-flight error
  shape. Today `per_genome.<id>.error` is a stringy message; consumers
  parse on prefix if they need to discriminate.
