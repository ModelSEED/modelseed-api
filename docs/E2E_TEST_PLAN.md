# ModelSEED — Comprehensive E2E test plan

A repeatable, layered live test suite that runs against the deployed stack (https://modelseed.org and the API at `poplar.cels.anl.gov:3004` / `modelseed.org/PMS/`). Verifies both **functional correctness** (every endpoint, page, dropdown works) and **biological soundness** (built models grow, gapfill solutions are minimal, FBA fluxes are physically reasonable).

`/plant` is excluded from the suite because that section of the live site isn't functional yet.

The full design rationale is at `.claude/plans/parallel-napping-rabbit.md` (Part 2). This file is the operational reference — what to run, how to read results, how to add tests.

---

## Architecture

### Where tests live

```
tests/
  live/                         # all live tests
    __init__.py
    conftest.py                 # live_client, live_token, target_env, sandbox helpers
    assertions/
      __init__.py
      bio.py                    # ~35 biological soundness checks
      api.py                    # response-shape / pagination / status-code helpers
      ui.py                     # Playwright assertion helpers (UI layer only)
    smoke/                      # Layer 1 — runs in <5 min
      test_health.py
      test_pages_render.py
      test_public_endpoints.py
    functional/                 # Layer 2 — auth required, no jobs, ~5–15 min
      test_biochem_api.py
      test_models_read_api.py
      test_media_api.py
      test_workspace_api.py
      test_jobs_listing.py
      test_export_formats.py
      test_edit_model.py
      test_gapfill_manage.py
    biological/                 # Layer 3 — slow jobs + biology, ~30–90 min
      test_reconstruct_ecoli.py
      test_reconstruct_bsubtilis.py
      test_reconstruct_archaeon.py
      test_reconstruct_template_matrix.py
      test_gapfill_minimality.py
      test_fba_media_matrix.py
      test_round_trip_sbml.py
      test_merge_models.py
    ui/                         # Layer 4 — Playwright, opt-in, ~10–20 min
      test_dropdowns.py
      test_search.py
      test_job_polling.py
      test_pages_interactive.py
    load/                       # Layer 5 — opt-in, locust scenario
      locustfile.py
    fixtures/
      genomes.py                # 3 reference genomes (gn / gp / archaea)
      media.py                  # Complete, glucose-minimal, NMS, M9, custom
      tokens.py                 # MODELSEED_TEST_TOKEN loader
    reports/                    # gitignored — written by --html / --json
```

### Pytest markers

| Marker | Purpose |
|---|---|
| `live_smoke` | Sub-5-minute reads, no auth or read-only auth, no jobs |
| `live_functional` | Auth required, exercises every endpoint, no long jobs |
| `live_biological` | Submits real reconstruct/gapfill/FBA jobs and validates biology |
| `live_ui` | Playwright tests against deployed Next.js |
| `slow` | Test takes >60s alone |
| `flaky_external` | Retry-eligible; isolates PATRIC/BV-BRC/SOLR instability |
| `requires_token` | Skip-on-missing `MODELSEED_TEST_TOKEN` |
| `requires_modeling` | Needs `cobra`/`modelseedpy` (`[modeling]` extra) |

### Configuration — env vars

| Env var | Default | Purpose |
|---|---|---|
| `MODELSEED_TEST_ENV` | `production` | `production` \| `staging` \| `local` |
| `MODELSEED_TEST_BASE_URL` | derived | UI base, e.g. `https://modelseed.org` |
| `MODELSEED_TEST_API_URL` | derived | API base, e.g. `https://modelseed.org/PMS` |
| `MODELSEED_TEST_TOKEN` | unset | PATRIC token; `requires_token` tests skip if absent |
| `MODELSEED_TEST_RAST_TOKEN` | unset | RAST token (different namespace) |
| `MODELSEED_TEST_USERNAME` | derived | From token |
| `MODELSEED_TEST_WORKSPACE_ROOT` | `/{username}/modelseed/test_e2e/` | Sandbox path for cleanup |
| `MODELSEED_TEST_KEEP_ARTIFACTS` | `0` | If `1`, don't delete created models |
| `MODELSEED_TEST_PARALLEL` | `4` | xdist workers |
| `MODELSEED_TEST_JOB_TIMEOUT` | `1200` | Seconds before treating a job as hung |
| `MODELSEED_TEST_RETRY_EXTERNAL` | `2` | Retries for `flaky_external` tests |
| `MODELSEED_TEST_REPORT_DIR` | `tests/live/reports/` | Where reports land |
| `MODELSEED_TEST_UI_ENABLED` | `0` | `1` enables Playwright layer |
| `MODELSEED_TEST_UI_HEADLESS` | `1` | Run Playwright headless |

---

## Test layers

| Layer | Marker | Auth | Jobs? | Wall-clock | Trigger |
|---|---|---|---|---|---|
| 1 — Smoke | `live_smoke` | Optional | No | ≤5 min | Pre-merge to main; every deploy; on-demand |
| 2 — Functional | `live_functional` | Required | No | 5–15 min | Nightly; on-demand before release |
| 3 — Biological | `live_biological` | Required | Yes | 30–90 min | Weekly; on-demand before release; after solver/template change |
| 4 — UI | `live_ui` | Required (cookie injection) | No | 10–20 min | Nightly; on-demand for UI changes |
| 5 — Load | `live_load` | Required (separate user) | Mostly read | Variable | Manual / quarterly |

### Layer 1 — Smoke (11 tests)

"The deployment is up and the public surface works." Every public page returns 2xx. `/api/health` returns ok. Public biochem endpoints return correctly-shaped data for known compounds (glucose, water, H+) and known reactions. Public media list non-empty. RAST endpoint returns 503 when DB unconfigured (graceful degradation).

### Layer 2 — Functional (~48 tests)

"Every endpoint × every documented parameter returns the right shape and status." Every page that requires auth loads with the test token. Every endpoint hit at least once. Parameter enumeration: every enum value, every boolean filter combination class, every limit/format value. Edit-model: every operation type on a tiny seed model. Gapfill manage: every command (I, U, D) on pre-staged solutions. Workspace proxy: all 8 operations on the sandbox path.

### Layer 3 — Biological (~24 tests)

"Models the system builds are biologically sound." 3 representative reconstructs (gram-neg, gram-pos, archaeon). Cross-product of `template_type ∈ {auto, gn, gp, ar}` × representative genome (pairwise — see Coverage Matrix). Each built model passes the full assertion library. Gapfill on Complete media yields a viable model; gapfill on glucose-minimal yields a *minimal* set of additions (≤30 typical for E. coli). FBA: Complete media → objectiveValue > 0.01 h⁻¹; glucose-minimal → > 0; acetate-only → 0 (with infeasibility status) for E. coli K-12. SBML round-trip preserves objective. Merge produces a model with reaction count between max(individual) and sum(individual).

### Layer 4 — UI (~12 Playwright tests, opt-in)

"Things that only happen in the browser work." Search interactions on `/biochem/reactions` and `/biochem/compounds`. The `/publications` Year dropdown (every option fires a filter without JS error). The `/genomes` Export CSV button produces a non-empty CSV. `/my-models` table loads; click row → detail. `/my-jobs` shows queued job within 4 seconds (verifies polling loop). Public pages screenshot-tested.

### Layer 5 — Load (1 scenario, opt-in)

Locust: 50 simulated users, 70/20/10 mix of biochem reads / model reads / workspace ls. Pass: p95 < 2s on biochem reads, p95 < 8s on model reads, error rate < 1%.

---

## Coverage matrix

### API endpoints × parameters × layers

Layer codes: **S**=Smoke, **F**=Functional, **B**=Biological.

| Endpoint | Method | Parameter / value | Layer |
|---|---|---|---|
| `/api/health` | GET | — | S |
| `/api/biochem/stats` | GET | — | S |
| `/api/biochem/reactions` | GET | `ids=rxn00001` | S |
| `/api/biochem/reactions` | GET | `ids=rxn00001,…rxn00050` (50 IDs) | F |
| `/api/biochem/reactions` | GET | `ids=` (empty) → 400 | F |
| `/api/biochem/reactions` | GET | `ids=rxn99999999` (nonexistent) → empty list | F |
| `/api/biochem/compounds` | GET | `ids=cpd00001,cpd00067` | S |
| `/api/biochem/compounds` | GET | `ids=cpd00027` (glucose) | S |
| `/api/biochem/compounds` | GET | `ids=` (empty) → 400 | F |
| `/api/biochem/search` | GET | `type=compounds, query=glucose, limit=50` | S |
| `/api/biochem/search` | GET | `type=compounds, query=H2O, limit=1` | F |
| `/api/biochem/search` | GET | `type=compounds, limit=200` | F |
| `/api/biochem/search` | GET | `limit=201` → 422 | F |
| `/api/biochem/search` | GET | `type=reactions, query=ATPase, limit=50` | F |
| `/api/biochem/search` | GET | `type=reactions, query=cpd00001` | F |
| `/api/biochem/search` | GET | `type=metabolites` (invalid) → 400 | F |
| `/api/biochem/search` | GET | `query=` (empty) → 422 | F |
| `/api/models` | GET | (no path) | F |
| `/api/models` | GET | `path=/{user}/modelseed/test_e2e/` | F |
| `/api/models/data` | GET | `ref=<seeded>` | F |
| `/api/models/data` | GET | `ref=<missing>` → 404 | F |
| `/api/models` | DELETE | `ref=<seeded>` | F |
| `/api/models/copy` | POST | `{model, destination}` | F |
| `/api/models/copy` | POST | `{model, destname}` | F |
| `/api/models/copy` | POST | `{model, destination, copy_genome=True}` | F |
| `/api/models/export` | GET | `format=json` | F |
| `/api/models/export` | GET | `format=sbml` (round-trip via cobra) | B |
| `/api/models/export` | GET | `format=cobra-json` | F |
| `/api/models/export` | GET | `format=cobrapy` (alias) | F |
| `/api/models/export` | GET | `format=csv` → 400 | F |
| `/api/models/gapfills` | GET | `ref=<seeded>` (empty) | F |
| `/api/models/gapfills` | GET | `ref=<after build>` | B |
| `/api/models/gapfills/manage` | POST | `{commands: {gf.0: "I"}}` | B |
| `/api/models/gapfills/manage` | POST | `{commands: {gf.0: "U"}}` | B |
| `/api/models/gapfills/manage` | POST | `{commands: {gf.0: "D"}}` | B |
| `/api/models/gapfills/manage` | POST | `{commands: {gf.0: "X"}}` → 400 | F |
| `/api/models/fba` | GET | `ref=<seeded>` (empty list) | F |
| `/api/models/fba` | GET | `ref=<after FBA>` | B |
| `/api/models/fba/data` | GET | `ref=<model>, fba_id=fba.0` | B |
| `/api/models/fba/data` | GET | `fba_id=missing` → 404 | F |
| `/api/models/edits` | GET | `ref=<model>` | F |
| `/api/models/edit` | POST | `reactions_to_add` | F |
| `/api/models/edit` | POST | `reactions_to_remove` | F |
| `/api/models/edit` | POST | `reactions_to_modify` | F |
| `/api/models/edit` | POST | `compounds_to_add` | F |
| `/api/models/edit` | POST | `compounds_to_remove` | F |
| `/api/models/edit` | POST | `compounds_to_modify` | F |
| `/api/models/edit` | POST | `biomasses_to_add` | F |
| `/api/models/edit` | POST | `biomass_changes` | F |
| `/api/models/edit` | POST | `biomasses_to_remove` | F |
| `/api/models/edit` | POST | All 9 ops atomically | F |
| `/api/models/edit` | POST | Invalid biochem ID → warnings non-empty | F |
| `/api/jobs` | GET | (default) | F |
| `/api/jobs` | GET | filter equivalence classes (5 classes) | F |
| `/api/jobs` | GET | `ids=<id1>,<id2>` | F |
| `/api/jobs/reconstruct` | POST | pairwise matrix (9 jobs) | B |
| `/api/jobs/reconstruct` | POST | `gapfill=True, media=Complete` | B |
| `/api/jobs/reconstruct` | POST | `atp_safe=False` | B |
| `/api/jobs/reconstruct` | POST | `genome_fasta=<small FASTA>` | B |
| `/api/jobs/reconstruct` | POST | `genome=` (empty) → 422 | F |
| `/api/jobs/gapfill` | POST | `template_type=gn, media=Complete` | B |
| `/api/jobs/gapfill` | POST | `template_type=gp, media=GlucoseMin` | B |
| `/api/jobs/gapfill` | POST | `template_type=ar, media=NMS` | B |
| `/api/jobs/fba` | POST | `media=Complete` (3 models) | B |
| `/api/jobs/fba` | POST | `media=GlucoseMin` | B |
| `/api/jobs/fba` | POST | `media=AcetateOnly` (no growth for E. coli K-12) | B |
| `/api/jobs/merge` | POST | 2 models, 0.5/0.5 | B |
| `/api/jobs/manage` | POST | `action=d` on completed | F |
| `/api/jobs/manage` | POST | `action=r` (rerun) | F |
| `/api/media/public` | GET | (no auth) | S |
| `/api/media/public` | GET | (with auth) | F |
| `/api/media/mine` | GET | — | F |
| `/api/media/export` | GET | `ref=…/Complete` | F |
| `/api/media/export` | GET | `ref=…/Carbon-D-Glucose` | F |
| `/api/media/export` | GET | `ref=<missing>` → 404 | F |
| `/api/workspace/ls` | POST | `paths=[/{user}/]` | F |
| `/api/workspace/ls` | POST | `recursive=True` | F |
| `/api/workspace/ls` | POST | `excludeDirectories=True` | F |
| `/api/workspace/ls` | POST | `paths=[/nonexistent/]` → 403/404 | F |
| `/api/workspace/get` | POST | `metadata_only=True` | F |
| `/api/workspace/get` | POST | full | F |
| `/api/workspace/create` | POST | folder | F |
| `/api/workspace/create` | POST | file with `overwrite=True` | F |
| `/api/workspace/create` | POST | folder with `createUploadNodes=True` | F |
| `/api/workspace/copy` | POST | `move=False, recursive=False` | F |
| `/api/workspace/copy` | POST | `recursive=True` (model-aware path) | F |
| `/api/workspace/copy` | POST | `move=True` | F |
| `/api/workspace/delete` | POST | single object | F |
| `/api/workspace/delete` | POST | `deleteDirectories=True, force=True` (cleanup) | F |
| `/api/workspace/metadata` | POST | update one key | F |
| `/api/workspace/download-url` | POST | one object | F |
| `/api/workspace/permissions` | POST | one object | F |
| `/api/rast/jobs` | GET | (RAST token; expect 503 unless DB configured) | F |

### Pairwise reduction for `template_type` × genome

Full Cartesian = 7 × 3 = 21 reconstructs at ~8 min each = 2.8 hours. Pairwise:

| # | template_type | genome | rationale |
|---|---|---|---|
| 1 | `auto` | E. coli K-12 MG1655 (511145.12) | gn auto-detect |
| 2 | `auto` | B. subtilis 168 (224308.1) | gp auto-detect |
| 3 | `auto` | M. jannaschii DSM 2661 (243232.1) | archaea auto-detect |
| 4 | `gn` | E. coli K-12 MG1655 | explicit gn |
| 5 | `gp` | B. subtilis 168 | explicit gp |
| 6 | `ar` | M. jannaschii | explicit ar |
| 7 | `gramneg` (alias) | E. coli K-12 | alias coverage |
| 8 | `grampos` (alias) | B. subtilis | alias coverage |
| 9 | `archaea` (alias) | M. jannaschii | alias coverage |

9 jobs at ~8 min each = ~75 min serial → ~25 min wall-clock with `pytest-xdist -n 4`.

### `GET /api/jobs` filter combinations

5 equivalence classes (out of 16 possible boolean combinations):

| Class | `include_completed` | `include_failed` | `include_running` | `include_queued` | Expected |
|---|---|---|---|---|---|
| All on (default) | T | T | T | T | All jobs |
| All off | F | F | F | F | `{}` |
| Only completed | T | F | F | F | only `status=completed` |
| Only active | F | F | T | T | running + queued |
| Only failed | F | T | F | F | only failures |

---

## Reusable assertion library

`tests/live/assertions/bio.py` — 35 biological-soundness checks. Each takes a model dict (or `cobra.Model`) and raises `AssertionError` with a metric-rich message. Optional `severity="error"|"warning"` flag.

### Structural assertions (any model)

1. `assert_model_has_minimum_reactions(model, min=50)`
2. `assert_model_has_minimum_compounds(model, min=50)`
3. `assert_model_has_minimum_compartments(model, min=2)`
4. `assert_extracellular_compartment_present(model)`
5. `assert_cytosol_compartment_present(model)`
6. `assert_at_least_one_biomass(model)`
7. `assert_biomass_has_minimum_compounds(model, min=5)`
8. `assert_biomass_includes_essential_cofactors(model)` — ATP, NAD(P)(H), water (cpd00002, cpd00003/4, cpd00005/6, cpd00001)
9. `assert_no_orphan_compounds(model)` — every compound is in ≥1 reaction (warn-only)
10. `assert_no_orphan_reactions(model)` — every reaction has reagents on each side or is sink/exchange
11. `assert_all_reactions_have_directions(model)` — direction ∈ {>, <, =}
12. `assert_gpr_coverage(model, min_frac=0.30)` — ≥30% of reactions have a GPR
13. `assert_genes_referenced(model)` — each gene is referenced by ≥1 reaction
14. `assert_compound_charges_are_numeric(model)` — every compound's charge is a finite float
15. `assert_reactions_mass_balanced(model, tol=1e-6, allowed_unbalanced_frac=0.10)` — ≥90% mass-balanced
16. `assert_no_duplicate_reaction_ids(model)`
17. `assert_no_duplicate_compound_ids(model)`
18. `assert_exchange_reactions_exist(model, min=10)`
19. `assert_extracellular_biomass_compounds_have_exchange(model)`
20. `assert_atp_maintenance_present(model)` — ATPM-like reaction exists when `atp_safe=True`
21. `assert_compartment_pH_set(model)` — each compartment has finite pH

### Functional / FBA assertions

22. `assert_grows_on_complete_media(fba_result, min_obj=0.01)`
23. `assert_no_growth_on_empty_media(fba_result)`
24. `assert_growth_on_glucose_minimal(fba_result, min_obj=0.01)`
25. `assert_objective_within_range(fba_result, lo=0.0, hi=2.0)` — physically reasonable growth rate
26. `assert_fluxes_finite(fba_result)` — no NaN/Inf in flux dict
27. `assert_atp_production_positive_under_growth(fba_result)`
28. `assert_no_thermodynamically_infeasible_loops(fba_result, threshold=1000)`
29. `assert_oxygen_uptake_zero_under_anaerobic(fba_result)`
30. `assert_essential_genes_consistent(model_before, model_after_ko)`

### Gapfill assertions

31. `assert_gapfill_solution_nonempty(gapfill_result)`
32. `assert_gapfill_solution_minimal(gapfill_result, max_added=30)`
33. `assert_gapfill_makes_model_viable(model_after_integrate, fba_after)`
34. `assert_gapfill_added_reactions_exist_in_biochem(gapfill_result)`

### Round-trip / format

35. `assert_sbml_round_trips(sbml_str, original_model)` — `cobra.io.read_sbml_model()` succeeds; counts match within tolerance; FBA objective matches within 1e-6

---

## How to run

```bash
# One-time setup
pip install -e ".[dev,modeling]" pytest-html pytest-json-report \
            pytest-xdist pytest-timeout pytest-rerunfailures \
            pytest-playwright tenacity locust
playwright install --with-deps chromium     # only if running UI layer

# Set the token (never commit)
export MODELSEED_TEST_TOKEN="$(security find-generic-password -s patric_token -w)"
# or on CI: read from secrets.MODELSEED_TEST_TOKEN

# Pick env
export MODELSEED_TEST_ENV=production       # or staging

# Smoke (5 min)
pytest -m live_smoke

# Functional (15 min)
pytest -m "live_smoke or live_functional"

# Biological (60–90 min, parallel)
pytest -m live_biological -n 4

# Everything
pytest -m live --html=tests/live/reports/full.html --json-report
python scripts/format_live_report.py tests/live/reports/.report.json
```

## Token handling

| Where | How |
|---|---|
| Local dev | macOS Keychain (`security add-generic-password -s patric_token -a $USER -w`); shell rc reads it on demand. Never echo. |
| CI (GitHub Actions) | `secrets.MODELSEED_TEST_TOKEN`, scoped to live-test job only. Conftest log filters mask the token. |
| Shared dev box | dotenv at `~/.modelseed/test.env` with `chmod 600`; loaded by direnv. |
| Never | Commit, pass on CLI, print in failures. The conftest `pytest_runtest_logreport` hook string-replaces token with `***`. |

## Reading reports

`tests/live/reports/full.html` has every test row. The post-processor surfaces a 30-line summary in three sections:

- **Infrastructure failures** — errored before assert phase, or root cause was upstream 5xx
- **Functional failures** — assertion failures in S/F/U layers (typically engineering bugs)
- **Biological failures** — assertion failures in `assertions/bio.py` (the substantive ones for the modeling team)

## Adding a new test

1. Decide the layer. New endpoint? → Functional. New biology check? → add to `assertions/bio.py` and reference from a Biological test.
2. Place the file under `tests/live/<layer>/`.
3. Add markers: `@pytest.mark.live`, `@pytest.mark.live_functional`, `@pytest.mark.requires_token`, etc.
4. Use existing fixtures (`live_client`, `live_token`, `workspace_sandbox`); never read env vars directly.
5. If creating workspace artifacts, write them under `workspace_sandbox` so cleanup is automatic.
6. Update the Coverage Matrix section above if the test exercises a new endpoint or parameter.

## Handling flaky externals

| Symptom | Diagnosis | Action |
|---|---|---|
| Workspace returns 502 across all tests | PATRIC down | Health-check fixture marks suite `xfail`; rerun later |
| BV-BRC genome lookup intermittent | BV-BRC slow | `flaky_external` retries; if still failing, switch to `genome_fasta` variant |
| SOLR rate-limit on biochem search | Too many parallel workers | Reduce `-n` to 2 |
| Single test fails alone | Likely our bug | Reproduce locally with same token |
| Job dispatched but never completes | Bioseed scheduler stuck | `pytest-timeout` kills test at 1500s; mark job for cleanup |

A nightly CI job runs `live_smoke + live_functional` against production and posts the formatted report to the team chat. Biological runs weekly (Sunday night) so failures are visible Monday morning.
