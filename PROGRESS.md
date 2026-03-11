# ModelSEED API - Implementation Progress

## Phase 1: Core Synchronous Operations (MVP)

- [x] Project scaffolding (FastAPI, pyproject.toml, config, main.py)
- [x] Auth middleware (PATRIC/RAST token extraction)
- [x] Pydantic schemas (matching ProbModelSEED.spec)
- [x] Workspace proxy (all 8 operations)
- [x] `GET /api/models` - list_models
- [x] `GET /api/models/data` - get_model
- [x] `DELETE /api/models` - delete_model
- [x] `POST /api/models/copy` - copy_model
- [x] `GET /api/models/export` - export_model (JSON only, SBML/CobraPy TODO)
- [x] `GET /api/models/gapfills` - list_gapfill_solutions
- [ ] `POST /api/models/gapfills/manage` - integrate/unintegrate/delete (stub)
- [x] `GET /api/models/fba` - list_fba_studies
- [x] Media endpoints (list public, list user, export)
- [x] Job dispatch + status polling (subprocess-based)
- [ ] Biochem endpoints (stubs - need MSBiochemUtils integration)
- [ ] SBML/CobraPy export formats
- [ ] Tests

## Phase 2: Extended Features

- [ ] Model editing endpoints (edit_model, list_model_edits)
- [ ] PlantSEED endpoints (pipeline, annotate, features, compare_regions)
- [ ] MergeModels, ImportKBaseModel
- [ ] Copy genome
- [ ] Delete FBA studies

## Phase 3: Production Hardening & Containerization

- [ ] Dockerfile + docker-compose.yml
- [ ] Celery + Redis job queue
- [ ] Health check enhancements, structured logging
- [ ] CI/CD pipeline
- [ ] Integration tests against dev workspace
- [ ] Compatibility tests (match Perl backend responses)

## Notes

- Biochem endpoints are stubs - need to integrate MSBiochemUtils from KBUtilLib
- Gapfill management is a stub - needs model object read/modify/save logic
- Export only supports JSON format currently
- Job scripts (reconstruct.py, gapfill.py, etc.) are placeholders
- RAST job listing stays on modelseed_support (per Chris)
