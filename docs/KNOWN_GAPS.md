# Known gaps

Features that should exist but currently don't, distinct from `WORKAROUNDS.md` (which catalogs ugly fixes for upstream bugs that *do* work).

A gap belongs here when:
- We know the feature is missing or broken
- We can't fix it right now for reasons outside the codebase (infrastructure, external dependency, vendor decision)
- It's worth tracking so we don't pretend it works

When a gap gets resolved, move it to a "Resolved" section at the bottom and link to the commit / PR that closed it.

---

### Model merging not implemented

**What it is:** `POST /api/jobs/merge` and the `merge_models` MCP tool are
part of the public API surface (documented, in the OpenAPI spec) but always
return immediately with "not implemented" (`HTTPException(501)` for the
route, an `{"error": ..., "status": "not_implemented"}` dict for the MCP
tool). No job is dispatched.

**Why:** merging models into a community model needs
`MSCommunity`-based logic that hasn't been integrated yet.

**Tracking:** implement via ModelSEEDpy's `MSCommunity`, then restore the
route/tool to actually dispatch a job (see git history prior to this note
for the previous stub job-script scaffolding under `src/job_scripts/`).

---

### `/my-models` and `/my-jobs` UI tests failing daily on the deployed frontend

**What it is:** `tests/live/ui/test_job_polling.py::test_my_models_page_renders`
and `tests/live/ui/test_failed_job_error_display.py::test_failed_job_error_visible_in_ui`
have failed on every scheduled "Live E2E tests" CI run for at least the last
week straight, despite carrying a `flaky_external` retry marker (added
2026-07-29 assuming this was a transient production blip; it isn't -- the
retry fires and fails again, every day).

**Diagnosis so far (2026-09-23):** this is very likely a frontend issue
(separate `ModelSEED-UI` repo), not a modelseed-api backend bug:
- The API side works: `test_failed_job_error_visible_in_ui` successfully
  submits a job and polls it to `failed` status with the expected error
  string via direct API calls -- only the *UI* assertion (does the error
  text appear on the rendered page) fails.
- Reproducing the same `authenticated_page` localStorage-injection technique
  interactively (Playwright, non-headless, a fresh `https://modelseed.org`
  context) renders `/my-models` correctly, including the empty-state text.
  So the injection technique itself, and the page in general, do work.
- In CI, the failure output for `test_failed_job_error_visible_in_ui` shows
  the submitted job's ID string is **not present anywhere in the rendered
  `/my-jobs` page body at all** (not just missing the error detail) -- this
  points toward the page not rendering job-specific content at all in that
  run, e.g. a redirect back to the sign-in landing page (which still
  contains "ModelSEED" branding text, incidentally satisfying the `"model"
  in body` half of the `test_my_models_page_renders` check while failing
  the rest), rather than a partial-rendering bug.
- Backend auth (`get_current_user()`) does not itself validate token
  signatures/expiry -- it only extracts the `un=` field and passes the raw
  token through to the PATRIC Workspace Service. So if this is an auth
  issue, it's either the `MODELSEED_TEST_TOKEN` CI secret being rejected
  downstream, or the frontend's own session-validity check, not this repo's
  auth layer.
- The test's own screenshot-on-failure diagnostic was silently broken: it
  saved to a pytest `tmp_path`, which is never uploaded as a CI artifact,
  so nobody had actually seen what the CI browser rendered. **Fixed** in
  this pass: screenshots now save under `tests/live/reports/` (uploaded by
  `live-tests.yml`), and both `test_my_models_page_renders` /
  `test_my_jobs_page_renders` gained the same screenshot + current-URL
  capture on failure that `test_failed_job_error_visible_in_ui` had.

**Why not fixed outright:** root-causing this fully needs either a real
CI run with the new screenshot capture (to see the actual rendered page
and confirm/refute the redirect theory) or access to the frontend's own
logs/error tracking, neither of which is available from this repo.

**Tracking:** next scheduled CI failure will have a screenshot artifact
under `ui-report-<run_id>/tests/live/reports/`; check whether the page
URL redirected away from `/my-jobs` or `/my-models` at failure time. If it
did, escalate to whoever maintains the `ModelSEED-UI` frontend session
handling. If not (page stayed on the right URL but rendered nothing),
this may be a client-side data-fetching race specific to the CI
environment worth investigating further from that side.

---

## Resolved gaps

### Build from RAST job: `getRastGenomeData` not replaced (RESOLVED 2026-05-13)

**What it was:** When a user picked one of their existing RAST annotation jobs in the UI and clicked "Build Model," the backend had no way to fetch the annotated genome data and feed it to the reconstruction pipeline. Our `/api/jobs/reconstruct` accepted a BV-BRC genome ID or a raw protein FASTA, but neither corresponded to "use my existing RAST annotation by job ID."

**Resolution:** We now have:

- **`GET /api/rast/genome?genome_id=...&job_id=...`**: fetches an annotated genome via MSSS `getRastGenomeData` and returns it as a KBase Genome dict ready for the reconstruction pipeline (`src/modelseed_api/routes/rast.py`).
- **`RastService.get_genome()` + `translate_rast_to_kbase_genome()`**: the JSON-RPC client and pure-function translator that converts the MSSS `RastGenome` shape into the KBase Genome dict (`src/modelseed_api/services/rast_service.py`).
- **`rast_job_id` + `rast_genome_id` fields on `ReconstructionRequest`**: third input mode for `POST /api/jobs/reconstruct`, mutually exclusive with `genome_fasta`. `genome` becomes a display-only label in this mode.
- **Full pipeline branch in `tasks.py:reconstruct()` and `reconstruct.py:main()`**: when `rast_job_id` is set, fetch via MSSS, translate, then run the same downstream reconstruction as the BV-BRC path.
- **`MODELSEED_MSSS_URL` config setting**: endpoint URL for the MSSS service. Defaults to `https://modelseed.org/services/ms_fba`.
- **90 translator unit tests** against a saved real production response (`tests/unit/test_rast_translator.py`, fixture at `tests/live/fixtures/rast_genome_pylori.json`).
- **7 live functional tests** for the endpoint (`tests/live/functional/test_rast_genome.py`).
- **Slow biological tests** for the full reconstruct pipeline + BV-BRC parity comparison (`tests/live/biological/test_reconstruct_from_rast.py`, `tests/live/biological/test_rast_vs_bvbrc_parity.py`).

**What unblocked it:** a DBA added the missing MySQL `GRANT SELECT` on `fig_anno_v5` for the `modelseed` user; the MSSS maintainer repointed MSSS's database config from chestnut to a reachable host and restarted the service. We confirmed `getRastGenomeData(genome="85962.43")` returns a real `RastGenome` with 1813 features and 1687 protein sequences. The frontend already implemented the right fallback design (try our endpoint, fall back to MSSS direct), so this lights up for users automatically once deployed.

**Outstanding follow-ups (non-blocking):**

- ~~Native FIGV port (reading `/vol/rast-prod/jobs/` directly in Python) would let us retire MSSS entirely once branch is decommissioned.~~ **DONE 2026-05-15:** `RastFigvReader` reads `/vol/rast-prod/jobs/<job_id>/rp/<genome_id>/` directly. `/api/rast/genome` no longer touches MSSS. Differential test confirmed byte-equivalent output. The mount is read-only at five enforcement layers (NetApp export, host kernel, Docker `:ro`, application code with no write syscalls, NFS root_squash); empirically verified in a transient validation container.
- ~~MSSS still returns `DNAsequence: [None]` even with `getDNASequence=1`.~~ **Resolved as a side-effect of the FIGV port:** the reader parses the `contigs` FASTA on disk directly, so `DNAsequence` now contains real contig sequences.
- ~~`/api/rast/jobs` still wraps MSSS `list_rast_jobs`.~~ **DONE 2026-05-27:** opened the poplar to chestnut MySQL conduit; `/api/rast/jobs` now queries `RastProdJobCache.Job` + `WebAppBackend2.User` directly. Real-time, sub-millisecond, no MSSS. modelseed-api has zero MSSS dependency; `ms_fba` JSON-RPC service is decommissionable.
