# Active Workarounds

This document catalogs workarounds applied in the modelseed-api codebase. Each exists because of a limitation or bug in an upstream dependency. They are all safe to remove if the upstream issue is resolved.

## A. KB_AUTH_TOKEN dummy value

**Applies to:** Both local and workspace modes

**Root cause:** `cobrakbase.KBaseAPI()` requires a non-empty `KB_AUTH_TOKEN` environment variable and a file at `~/.kbase/token`, even when not connecting to KBase. This is triggered during model conversion (CobraModelConverter, FBAModelBuilder) which imports cobrakbase internals.

**Workaround:** Set `os.environ.setdefault("KB_AUTH_TOKEN", "unused")` before any cobrakbase import. In Docker, also create `~/.kbase/token` with dummy content.

**Locations:**
- `src/modelseed_api/jobs/tasks.py` — `_init_kwargs()` function
- `src/job_scripts/reconstruct.py`, `gapfill.py` — top of `main()`
- `Dockerfile` — `ENV KB_AUTH_TOKEN=unused` + file creation

**Upstream:** cobrakbase (Fxe/cobrakbase). Would need KBaseAPI to not require a token when not connecting to KBase.

---

## B. Genome classifier bypass

**Applies to:** Both local and workspace modes

**Root cause:** `MSGenomeClassifier` (used by KBUtilLib's `MSReconstructionUtils.build_metabolic_model()`) requires pickle files that are not distributed with the KBUtilLib package. Without them, genome classification (gram-positive vs gram-negative) fails.

**Workaround:** Pass `genome_classifier=None` and explicitly specify the template type (e.g., `template_type="gn"` for gram-negative). The user selects the template type in the UI.

**Locations:**
- `src/modelseed_api/jobs/tasks.py` — `reconstruct()` task, `genome_classifier=None` argument
- `src/job_scripts/reconstruct.py` — same pattern

**Upstream:** KBUtilLib (cshenry/KBUtilLib). Classifier pickle files need to be distributed with the package, or classification needs an alternative implementation.

---

## C. MSGapfill media=None crash guard

**Applies to:** Both local and workspace modes

**Root cause:** `MSGapfill.run_gapfilling()` and `MSGapfill.test_gapfill_database()` crash with `NoneType` errors when `media=None` and gapfilling fails to find a solution. The internal error handling path tries to access attributes on the media object without a null check.

**Workaround:** Substitute an empty `MSMedia("Complete", "Complete")` when media is None. This is semantically identical (all exchanges open = complete media).

**Locations:**
- `src/modelseed_api/jobs/tasks.py` — `reconstruct()` and `gapfill()` tasks
- `src/job_scripts/reconstruct.py`, `gapfill.py` — same pattern

**Upstream:** ModelSEEDpy (cshenry/ModelSEEDpy). `run_gapfilling()` should handle `media=None` gracefully.

---

## D. Explicit gapfill integration and persistence

**Applies to:** Both local and workspace modes

**Root cause:** `MSGapfill.run_gapfilling()` returns a raw solution dict but does NOT auto-integrate it into the model or persist it to the model object. Three separate calls are needed:
1. `gapfiller.integrate_gapfill_solution(solution)` — adds reactions to model
2. `mdlutl.create_kb_gapfilling_data(ws_data)` — writes gapfilling entries to model object
3. Manual save of the model data back to storage

**Workaround:** Explicitly call all three steps after `run_gapfilling()`.

**Locations:**
- `src/modelseed_api/jobs/tasks.py` — `reconstruct()` and `gapfill()` tasks
- `src/job_scripts/reconstruct.py`, `gapfill.py` — same pattern

**Upstream:** This may be intentional design in ModelSEEDpy (separation of concerns). Not necessarily a bug.

---

## E. PATRIC workspace metadata merge

**Applies to:** Workspace mode only (harmless in local mode)

**Root cause:** PATRIC workspace `update_metadata()` REPLACES the entire `user_meta` dict rather than merging new keys into existing metadata. Additionally, `ws.create()` does not reliably persist user metadata set at creation time. And `ws.ls()` on a folder path lists its children, not the folder itself — so reading a folder's own metadata requires listing the parent and finding the folder by name.

**Workaround:** A `_merge_ws_metadata()` helper that:
1. Lists the parent directory to find the target item
2. Reads existing `user_meta` (index 7 in the metadata tuple)
3. Merges new keys into existing metadata
4. Calls `update_metadata()` with the merged dict

After every `ws.create()` that sets metadata, an explicit `_merge_ws_metadata()` call is also made to ensure persistence.

**Locations:**
- `src/modelseed_api/jobs/tasks.py` — `_merge_ws_metadata()` function
- `src/job_scripts/reconstruct.py`, `gapfill.py`, `run_fba.py` — `merge_ws_metadata()` function
- `src/modelseed_api/services/model_service.py` — `_merge_metadata()` method

**Note:** `LocalStorageService.update_metadata()` does a proper merge internally, so the pre-read step is redundant but harmless in local mode.

**Upstream:** PATRIC Workspace Service. The `update_metadata` RPC should merge rather than replace, or at minimum the spec should document the replace behavior.

---

## F. optionalSubunit patch for FBAModelBuilder

**Applies to:** Both local and workspace modes (for older models)

**Root cause:** `cobrakbase.FBAModelBuilder` accesses `'optionalSubunit'` with a hard key lookup (not `.get()`) on `modelReactionProteinSubunits`. This field is `@optional` in the KBase type spec, so older models created before this field was added don't include it, causing `KeyError`.

**Workaround:** Patch model data in-place before passing to FBAModelBuilder:
```python
for rxn in model_obj.get("modelreactions", []):
    for prot in rxn.get("modelReactionProteins", []):
        for sub in prot.get("modelReactionProteinSubunits", []):
            sub.setdefault("optionalSubunit", 0)
```

New models created by our system always include this field.

**Locations:**
- `src/modelseed_api/jobs/tasks.py` — `_patch_model_for_builder()` function
- `src/job_scripts/gapfill.py`, `run_fba.py` — inline patching loops
- `src/modelseed_api/services/model_service.py` — sets field when creating reactions via edit API

**Upstream:** cobrakbase (Fxe/cobrakbase). `FBAModelBuilder` should use `.get("optionalSubunit", 0)` instead of hard key access.

---

## Resolved Workarounds

These workarounds were previously needed but have been fixed upstream:

1. **BVBRCUtils.save monkey-patch** — Fixed by KBUtilLib PR #25 (merged)
2. **Mock `_Info` class on templates** — Fixed by KBUtilLib PR #25 (merged)
3. **TSV media parsing** — Fixed by KBUtilLib PR #24 (merged), `get_media()` now handles both TSV and JSON formats
