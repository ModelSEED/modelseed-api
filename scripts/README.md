# scripts/

Manual, standalone tools. Nothing here runs in CI; each script is invoked
by hand when needed.

- **`integration_test.py`**: comprehensive manual smoke test that validates
  every field the frontend reads from every endpoint, against a live
  deployment. Run with `python scripts/integration_test.py --token TOKEN
  --api-url <url>`. Complements, rather than duplicates, the automated
  `tests/live/` suite (see [`docs/E2E_TEST_PLAN.md`](../docs/E2E_TEST_PLAN.md)):
  this script checks frontend data-contract correctness field-by-field,
  the automated suite checks endpoint behavior and biological correctness.
