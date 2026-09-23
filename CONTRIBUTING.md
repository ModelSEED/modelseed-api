# Contributing

## Getting set up

See the [README](README.md#run-standalone-your-own-machine-no-anl-setup) for
the standalone Docker image (fastest path to a working server) or
[Run it locally](README.md#run-it-locally) for building from source against
the dependency forks.

## Making changes

- Open an issue before a large change so the approach can be discussed first.
- Keep pull requests focused; unrelated cleanup belongs in its own PR.
- Match the existing style: `ruff check src/ tests/` must pass (see
  `[tool.ruff]` in `pyproject.toml` for the configured rules).
- Add or update tests for anything you change. `pytest` (bare, no flags)
  runs the hermetic suite (unit/routes/integration/e2e/mcp) and must pass;
  see [`docs/E2E_TEST_PLAN.md`](docs/E2E_TEST_PLAN.md) for the opt-in live
  suite against a deployed stack.
- If you touch a subprocess job script under `src/job_scripts/`, keep the
  corresponding Celery task in `src/modelseed_api/jobs/tasks.py` in sync --
  they implement the same logic for two different dispatch modes (see
  CLAUDE.md's "Job dispatch" section).

## Project conventions

Project-specific conventions (storage backend abstraction, settings usage,
dependency forks) are documented in [`CLAUDE.md`](CLAUDE.md). Active
workarounds for upstream issues are tracked in
[`docs/WORKAROUNDS.md`](docs/WORKAROUNDS.md); known missing features in
[`docs/KNOWN_GAPS.md`](docs/KNOWN_GAPS.md).

## Reporting issues

Open an issue at https://github.com/ModelSEED/modelseed-api/issues. For
questions about the ANL-hosted deployment specifically (not the code),
also open an issue -- deployment/on-call details are maintained separately
from this repository.
