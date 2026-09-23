# Changelog

Format loosely follows [Keep a Changelog](https://keepachangelog.com/). Dates
are the day a change landed on `main`, not necessarily the day it was
deployed to production.

## [1.0.0] - 2026-09-23

First tagged release since the initial `v0.1.0`. Consolidates roughly five
months of feature work and a release-readiness cleanup pass ahead of citing
this repository (via a Zenodo-minted DOI) in the ModelSEED v2 manuscript.

### Added
- `POST /api/jobs/bulk_reconstruct`: build models for many genomes in a
  single job (see `docs/BULK_RECONSTRUCT.md`).
- MCP server (`modelseed-mcp`): 17 tools exposing model building, gapfilling,
  FBA, media, and biochemistry queries to AI assistants over the Model
  Context Protocol, local-storage mode only.
- Self-contained standalone Docker image (`Dockerfile.standalone`,
  published to `ghcr.io/modelseed/modelseed-api`): clones its own
  dependencies and bundles the biochemistry database, no PATRIC/RAST
  account or ANL infrastructure required.
- `POST /api/jobs/reconstruct` accepts DNA or protein FASTA directly
  (auto-detected; DNA is gene-called via prodigal + glimmer3 before RAST
  annotation), in addition to a BV-BRC genome ID or an existing RAST job ID.
- Pre-flight request validation: `reconstruct`/`gapfill`/`fba`/`merge` return
  a structured 4xx immediately for catchable input errors instead of
  dispatching a job that would fail once picked up.
- Automatic genome classification (`template_type="auto"`) for reconstruction.
- Layered live E2E test suite (`tests/live/`: smoke, functional, biological,
  UI) and the `live-tests.yml` GitHub Actions workflow that runs it on a
  schedule against the deployed stack.
- `CITATION.cff` for correct Zenodo/GitHub citation metadata.

### Changed
- `/api/rast/jobs` and `/api/rast/genome` now read directly from the
  chestnut MySQL job database and the on-disk FIGV filesystem
  respectively; the legacy MSSS JSON-RPC service is no longer in the loop
  (`ms_fba` is decommissionable). See `docs/KNOWN_GAPS.md`.
- Gapfilling now goes through KBUtilLib's `gapfill_metabolic_model()`
  (handles ATP tests, auto-sink demands, multi-gapfill, and growth
  verification) instead of calling `MSGapfill` directly.
- Celery worker wired to the shared bioseed Redis scheduler with
  `acks_late` + `reject_on_worker_lost` resilience settings.
- Dependency pinning: the `modeling` extra and `Dockerfile.standalone` now
  pin `kbutillib`, `modelseedpy`, and `cobrakbase` to exact commit SHAs
  (not moving branch names), so a rebuild of this release reproduces the
  same code even after upstream forks move on.
- `pytest` is hermetic by default (`-m 'not live'`); the live suite against
  a deployed stack is opt-in.

### Fixed
- Swagger UI / ReDoc rendering blank behind the `/PMS` reverse-proxy path
  prefix (missing `root_path` on the FastAPI app -- see `MODELSEED_ROOT_PATH`).
- Demo dashboard computing its API root from `window.location.origin` alone,
  which dropped the `/PMS` prefix and 502'd every API call from the page.
- numpy/scikit-learn ABI mismatch in Docker builds after editable installs.
- Celery import crash in subprocess (local dev) mode.
- Gapfill metadata: correct `gf.N` solution IDs, real media references.

### Removed
- `POST /api/jobs/merge`: now returns HTTP 501 immediately (MSCommunity-based
  merging was never integrated; the endpoint previously dispatched a job
  that always failed once picked up). Tracked in `docs/KNOWN_GAPS.md`.
- Dead FIGV-index-based RAST job listing (`RastFigvReader.list_jobs_for_user`,
  `build_user_index`, `update_user_index_delta`, `scripts/build_rast_index.py`,
  `MODELSEED_RAST_INDEX_PATH`), superseded by the direct-MySQL approach above
  and never actually wired into a route.
- Superseded one-off scripts (`scripts/compare_rast_vs_bvbrc.py`,
  `scripts/test_auto_classification.py`, `scripts/update_rast_index_delta.py`)
  and the legacy duplicate `tests/test_live_integration.py`, all confirmed
  fully covered by the newer `tests/live/` suite.

## [0.1.0] - 2026-04-06

Initial release.
