# Known gaps

Features that should exist but currently don't, distinct from `WORKAROUNDS.md` (which catalogs ugly fixes for upstream bugs that *do* work).

A gap belongs here when:
- We know the feature is missing or broken
- We can't fix it right now for reasons outside the codebase (infrastructure, external dependency, vendor decision)
- It's worth tracking so we don't pretend it works

When a gap gets resolved, move it to a "Resolved" section at the bottom and link to the commit / PR that closed it.

---

## Build from RAST job — `getRastGenomeData` not replaced

**Applies to:** Production stack (live `modelseed.org`).

**What's missing:** When a user picks one of their existing RAST annotation jobs in the UI and clicks "Build Model," the backend has no way to fetch the annotated genome data and feed it to the reconstruction pipeline. Our `/api/jobs/reconstruct` accepts a BV-BRC genome ID or a raw protein FASTA, but neither corresponds to "use my existing RAST annotation by job ID."

**Why we can't fix it right now:**

- The legacy MSSeedSupportServer (MSSS) at `https://modelseed.org/services/ms_fba` (proxied to `branch.mcs.anl.gov:4043`) used to provide this via its `getRastGenomeData` method. We thought MSSS was fully retired when we replaced `list_rast_jobs` with `/api/rast/jobs` in March 2026; we missed this second method.
- MSSS is currently non-functional. Its `WebAppBackend2` MySQL connection on `chestnut.cels.anl.gov:3306` is firewalled. Sam Seaver verified port-blocked. Dan Klos confirmed that a new network conduit will be denied because branch is EOL and ANL cyber has tightened requirements.
- A native Python port would require filesystem access to `/vol/rast-prod/jobs/` from poplar. That directory lives on the EOL branch host and isn't reachable from poplar. Migrating it is a sysadmin project that hasn't been scoped.
- We searched the entire ecosystem (ModelSEEDpy, cobrakbase, KBUtilLib, kbaseapps/RAST_SDK, kbaseapps/GenomeFileUtil, ModelSEED/GenomeImporter, kbaseattic/genome_annotation) for a Python `RAST → KBase Genome` translator. None exists. RAST_SDK has the canonical Perl version (`AnnotationUtils.pm`) but it's tightly coupled to KBase workspace.

**Current user impact:** The "Build from RAST job" UI path on `modelseed.org` is non-functional. Users who need to build models from existing RAST annotations must download the FASTA and resubmit via `POST /api/jobs/reconstruct` with `genome_fasta=...`, which re-runs annotation from scratch.

**Implementation sketch (when unblocked):**

- `src/modelseed_api/routes/rast.py` — add `GET /api/rast/genome?job_id=...` endpoint
- `src/modelseed_api/services/rast_service.py` — add `get_genome()` method + `_parse_figv_directory()` helper
- `src/modelseed_api/schemas/jobs.py` — add `rast_job_id: Optional[str]` to `ReconstructionRequest` (mutually exclusive with `genome` / `genome_fasta`)
- `src/modelseed_api/jobs/tasks.py` and `src/job_scripts/reconstruct.py` — new branch when `rast_job_id` is set
- `src/modelseed_api/config.py` — `MODELSEED_RAST_JOBS_PATH` setting
- Use `BVBRCUtils.build_kbase_genome_from_api()` (KBUtilLib `bvbrc_utils.py:170`) as the reference target shape (19 fields)
- Use RAST_SDK's `AnnotationUtils.pm` as the reference algorithm (Perl, but readable as a spec)

Estimated effort: ~2 days from data-path-available to feature-shipped.

**What we need to unblock:**

1. From Bob (via Sam): does RAST have a new API for fetching job output? Or what's the migration plan for `/vol/rast-prod/jobs/` when branch is decommissioned?
2. From Dan / sysadmin: can `/vol/rast-prod/jobs/` be relocated or NFS-exported to a long-lived host poplar can reach?
3. From product side: if neither (1) nor (2) works, do we sunset "Build from RAST job" and direct users to FASTA upload as the only path?

**Tracking:** See the holding doc at `.claude/plans/parallel-napping-rabbit.md` (Part 1) and the project memory `project_msss_disposition.md` for the full investigation history.

---

## Resolved gaps

(none yet)
