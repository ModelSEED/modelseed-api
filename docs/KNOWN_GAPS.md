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

- MSSS still returns `DNAsequence: [None]` even with `getDNASequence=1`. Likely another DB grant FIGV needs for contig storage. Doesn't block reconstruction (we use protein sequences and feature metadata, not contig DNA, for ModelSEED templates). Worth a separate Slack to Sam/Bob.
- Native FIGV port (reading `/vol/rast-prod/jobs/` directly in Python) would let us retire MSSS entirely once branch is decommissioned. Currently blocked on poplar not being able to reach the RAST filesystem; not urgent.

**History:** Full investigation trail in the holding doc at `.claude/plans/parallel-napping-rabbit.md` (Parts 1 and 3) and the project memory `project_msss_disposition.md`.
