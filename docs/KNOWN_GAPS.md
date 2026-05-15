# Known gaps

Features that should exist but currently don't, distinct from `WORKAROUNDS.md` (which catalogs ugly fixes for upstream bugs that *do* work).

A gap belongs here when:
- We know the feature is missing or broken
- We can't fix it right now for reasons outside the codebase (infrastructure, external dependency, vendor decision)
- It's worth tracking so we don't pretend it works

When a gap gets resolved, move it to a "Resolved" section at the bottom and link to the commit / PR that closed it.

---

## (none currently active)

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

**What unblocked it:** Bob added the missing MySQL `GRANT SELECT` on `fig_anno_v5` for the `modelseed` user; Dan repointed MSSS's database config from chestnut to a reachable host; Sam restarted the MSSS service. We confirmed `getRastGenomeData(genome="85962.43")` returns a real `RastGenome` with 1813 features and 1687 protein sequences. Vibhav's frontend already implemented the right fallback design (try our endpoint, fall back to MSSS direct), so this lights up for users automatically once deployed.

**Outstanding follow-ups (non-blocking):**

- ~~Native FIGV port (reading `/vol/rast-prod/jobs/` directly in Python) would let us retire MSSS entirely once branch is decommissioned.~~ **DONE 2026-05-15:** `RastFigvReader` reads `/vol/rast-prod/jobs/<job_id>/rp/<genome_id>/` directly. `/api/rast/genome` no longer touches MSSS. Differential test confirmed byte-equivalent output. The mount is read-only at five enforcement layers (NetApp export, host kernel, Docker `:ro`, application code with no write syscalls, NFS root_squash); empirically verified in a transient validation container.
- ~~MSSS still returns `DNAsequence: [None]` even with `getDNASequence=1`.~~ **Resolved as a side-effect of the FIGV port:** the reader parses the `contigs` FASTA on disk directly, so `DNAsequence` now contains real contig sequences.
- `/api/rast/jobs` still wraps MSSS `list_rast_jobs`. The filesystem alternative would require a background-built `job_id -> user` index (live walks across 13 NFS shards exceed 10 minutes; per Dan's "don't list the main directory" warning). Not blocking anything: list_rast_jobs is fast on MSSS's side and not on a hot path. Replace with an indexed reader if/when MSSS is actually decommissioned.

**History:** Full investigation trail in `.claude/plans/parallel-napping-rabbit.md` (Parts 1, 3, and 4) and project memories `project_msss_disposition.md` and `project_msss_retirement.md`.
