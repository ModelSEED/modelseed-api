# Running modelseed-api standalone

This guide is for someone who wants to use modelseed-api **without** the production ANL setup (no PATRIC account, no chestnut MySQL, no NFS-mounted RAST jobs). The standalone image is self-contained: pull it, run it, hit `localhost:8000`.

## Quick start

```bash
docker run -p 8000:8000 ghcr.io/modelseed/modelseed-api:latest
```

That's it. The image:

- Bundles all dependencies (`ModelSEEDpy`, `KBUtilLib`, `cobrakbase`, etc.)
- Bundles the `ModelSEEDDatabase` (~600 MB of biochemistry data) and `ModelSEEDTemplates`
- Defaults to local-filesystem storage at `/data/modelseed` inside the container
- Listens on port 8000

Open `http://localhost:8000/demo/` in your browser, or hit the API directly:

```bash
curl http://localhost:8000/api/health
# {"status":"ok","version":"0.1.0"}

curl 'http://localhost:8000/api/biochem/search?query=glucose&type=compounds&limit=5'
# [{"id":"cpd00027","name":"D-Glucose",...}, ...]
```

## Persisting models across container restarts

By default, anything you build gets stored in `/data/modelseed` inside the container and disappears when the container is removed. Mount a host directory to persist:

```bash
mkdir -p ~/.modelseed
docker run -p 8000:8000 \
    -v ~/.modelseed:/data/modelseed \
    ghcr.io/modelseed/modelseed-api:latest
```

Now models, gapfill solutions, FBA results, and uploaded media live in `~/.modelseed/` on your host.

## What works without any extra config

| Endpoint | Works? | Notes |
|---|---|---|
| `/api/health` | yes | no deps |
| `/api/biochem/*` | yes | bundled biochemistry database |
| `/api/media/public` | yes | bundled public media formulations |
| `/api/models/*` | yes | local filesystem storage |
| `/api/jobs/reconstruct` (BV-BRC genome ID) | with PATRIC token | hits BV-BRC API; PATRIC token in `Authorization` header |
| `/api/jobs/reconstruct` (FASTA upload) | yes | anonymous RAST kmer annotation via the public SEED endpoint at `tutorial.theseed.org` |
| `/api/jobs/reconstruct` (RAST job id) | only on ANL setup | needs `/vol/rast-prod/jobs` filesystem mount |
| `/api/jobs/gapfill` | yes | pure local compute |
| `/api/jobs/fba` | yes | pure local compute |
| `/api/jobs/merge` | yes | pure local compute |
| `/api/workspace/*` | only with PATRIC | proxies the PATRIC Workspace Service |
| `/api/rast/jobs` | only on ANL setup | needs chestnut MySQL access |
| `/api/rast/genome` | only on ANL setup | needs `/vol/rast-prod/jobs` filesystem mount |

The ANL-only endpoints return `503 RAST integration not configured for this deployment` (or similar) when their env vars aren't set. They don't crash and don't break the rest of the API.

## Building a model from a protein FASTA (no auth needed)

The simplest end-to-end workflow that requires only an internet connection:

```bash
# 1. Get a protein FASTA file ready (your own, or download from NCBI/UniProt)

# 2. Submit it for reconstruction
curl -X POST http://localhost:8000/api/jobs/reconstruct \
    -H 'Content-Type: application/json' \
    -d @- <<EOF
{
  "genome": "MyOrganism",
  "genome_fasta": "$(cat my_proteins.fasta | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))')",
  "template_type": "auto",
  "atp_safe": true,
  "gapfill": false,
  "output_path": "/MyOrganism"
}
EOF
# Returns a job id like "a1b2c3d4-..."

# 3. Poll for completion (typically 30s-2min for a small genome)
JOB=<the id from step 2>
curl "http://localhost:8000/api/jobs?ids=$JOB"

# 4. Fetch the model when status=completed
curl "http://localhost:8000/api/models/data?ref=/MyOrganism"
```

Under the hood: the FASTA is sent to the public RAST kmer annotation service (`tutorial.theseed.org`, no auth needed), annotations come back in seconds, ModelSEEDpy builds the model using the gn/gp/ar templates, and the result lands at `/MyOrganism` in your local storage.

## Using the MCP server for AI assistant integration

The package also ships an MCP (Model Context Protocol) server for use with AI assistants like Claude Desktop or Claude Code. It runs locally only (no auth, no network) and exposes ModelSEED tools directly to the assistant.

Run the MCP server from inside the container:

```bash
docker exec -it <container-name> python -m modelseed_mcp
```

Or run it on the host directly after installing the package:

```bash
pip install git+https://github.com/ModelSEED/modelseed-api.git#egg=modelseed-api[mcp]
modelseed-mcp
```

Configure Claude Desktop (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "modelseed": {
      "command": "docker",
      "args": ["exec", "-i", "<your-container-name>", "python", "-m", "modelseed_mcp"]
    }
  }
}
```

The assistant gets 17 tools: search compounds/reactions, list/edit/copy/export models, list/get media, build/gapfill/FBA/merge models, check job status.

## Opting into the production-only endpoints

If you have a PATRIC account or are on ANL infrastructure, set the relevant env vars to unlock the gated endpoints:

```bash
docker run -p 8000:8000 \
    -e MODELSEED_STORAGE_BACKEND=workspace \
    -v ~/.modelseed:/data/modelseed \
    ghcr.io/modelseed/modelseed-api:latest
```

| Env var | Enables |
|---|---|
| `MODELSEED_STORAGE_BACKEND=workspace` | `/api/workspace/*` proxy + workspace-backed model storage (needs PATRIC token in Authorization header on each request) |
| `MODELSEED_RAST_DB_HOST=...` + `_USER` + `_PASSWORD` | `/api/rast/jobs` (queries RastProdJobCache MySQL directly) |
| `MODELSEED_RAST_JOBS_DIR=/vol/rast-prod/jobs` (with bind-mount `/vol:/vol:ro`) | `/api/rast/genome` (reads RAST annotation files directly) |

Most users don't need any of these. They exist for the modelseed.org production deployment and similar internal use.

## Versioning + updates

Images are published on every push to `main` and tagged on every git tag:

- `ghcr.io/modelseed/modelseed-api:latest` -- tip of main, may have unreleased changes
- `ghcr.io/modelseed/modelseed-api:v0.1.0` -- specific release; recommended for production-like use
- `ghcr.io/modelseed/modelseed-api:main-<sha>` -- specific commit on main

To upgrade: `docker pull ghcr.io/modelseed/modelseed-api:latest` then restart your container. Local-storage data in your bind-mount survives the upgrade.

## Image size + first-run behavior

The image is ~1.5-2 GB on disk because it bundles:

- Python 3.11 + system deps (glpk, etc.): ~200 MB
- ModelSEEDpy + KBUtilLib + cobra + cobrakbase + dependencies: ~500 MB
- ModelSEEDDatabase (biochemistry data, dev branch): ~600 MB
- ModelSEEDTemplates + cb_annotation_ontology_api: ~200 MB

First request after container start may take ~10s while the biochemistry database loads into memory; subsequent requests are sub-millisecond for biochem queries.

## Source code

This image is built from [ModelSEED/modelseed-api](https://github.com/ModelSEED/modelseed-api), specifically `Dockerfile.standalone`. The build clones sibling repos (`cshenry/ModelSEEDpy`, `cshenry/KBUtilLib`, `Fxe/cobrakbase`, `ModelSEED/ModelSEEDDatabase` `dev` branch, `ModelSEED/ModelSEEDTemplates`) at build time, so the image always reflects HEAD of those repos at the time the image was built. For reproducible builds against pinned commits, pin the `--branch <ref>` in `Dockerfile.standalone` to specific commit SHAs.
