# Repro: failed-job error message is not surfaced in the UI

**Status: confirmed via Playwright (2026-06-09)**. The backend records a
clear `error` string on every failed job; the production UI at
modelseed.org renders only a "Failed" badge with no way to see why.

This document is for: (a) handing to Vibhav so he can wire `job.error`
into the UI, and (b) the user's Chrome agent if anyone wants to re-verify
the bug manually without running Playwright.

## What the backend returns

`GET /api/jobs?ids=<failed_job_id>` (auth: PATRIC token), for a failed
reconstruct job, returns a record like:

```json
{
  "id": "ab39ad4f-70f7-420b-ac5a-63bc89c887bc",
  "app": "ModelReconstruction",
  "status": "failed",
  "progress": "Fetching genome...",
  "error": "ValueError: No genome found with ID 9999999.9",
  "parameters": { "command": "ModelReconstruction", "arguments": {...} }
}
```

The `error` field is populated by `celery_app.py:_bridge_failure` for
every task that raises an exception. Three common shapes seen on poplar:

| Exception type | Example `error` value | Cause |
|----------------|------------------------|-------|
| `GenomeNotFoundError` | `GenomeNotFoundError: Genome '1589.518' could not be fetched from BV-BRC. ...` | User typed a non-BV-BRC genome ID into the BV-BRC field |
| `ModelNotFoundError` | `ModelNotFoundError: No model found at '/user/modelseed/X/model'. ...` | User runs gapfill/FBA on a model path that doesn't exist (often because reconstruct failed) |
| `WorkspaceError` | `WorkspaceError: Token validation failed: Token expired` | User's PATRIC token expired mid-job |

In all three, the `error` string is human-readable and actionable.

## What the UI currently does

On https://modelseed.org/my-jobs (authenticated):
- Job Status header with 4 counters: Queued / In Progress / Completed / Failed.
- Table columns: Task, Parameters, Submitted, Started, Status (and a
  small action icon at the right).
- Status column for a failed job shows: a small red **Failed** badge.
- **Clicking the Failed badge does nothing visible** (no tooltip, no
  modal, no expanded row).
- **Clicking the row does nothing visible.**
- No per-job detail route exists (no `/my-jobs/{id}` or `/jobs/{id}`).
- The Parameters column is truncated; even the submitted parameters are
  not fully visible.

Net: a user whose job fails sees only "Failed" with no explanation.

## How to reproduce in any Chrome tab

1. Log in to https://modelseed.org with a PATRIC account that has
   submitted at least one job. Or, easier, go to https://bv-brc.org,
   sign in, open the browser console, run `copy(window.App.authorizationToken)`,
   paste into a curl command (below).
2. Submit a job that will fail in seconds (nonexistent BV-BRC genome).
   Run this in a terminal with your token in `$TOKEN`:

   ```bash
   curl -X POST -H "Authorization: $TOKEN" -H "Content-Type: application/json" \
     'https://modelseed.org/PMS/api/jobs/reconstruct' \
     -d '{"genome":"9999999.9","template_type":"gn","atp_safe":true,"gapfill":false}'
   ```

   Response is a UUID job_id.
3. Verify the API records the error:

   ```bash
   curl -H "Authorization: $TOKEN" \
     "https://modelseed.org/PMS/api/jobs?ids=<job_id>"
   ```

   The response should include `"error": "ValueError: No genome found with ID 9999999.9"`.
4. In Chrome, navigate to https://modelseed.org/my-jobs. Find the row
   with the matching job id (newest at top usually).
5. **Bug**: the row shows a red "Failed" badge but the error text from
   step 3 is nowhere on the page. Hovering, clicking the badge, and
   clicking the row all produce no visible affordance.

## What the fix needs to do

Option A (minimal): on the failed row, surface `job.error` either as a
tooltip on the Failed badge or as an expandable detail when the row is
clicked.

Option B (better): a per-job detail page or side panel showing
parameters, progress messages, and the full `error` string. This also
solves the "Parameters column is truncated" problem.

The backend contract is already in place. Recommend Option A as a
two-line fix that unblocks users immediately, with Option B as a
follow-up.

## Future-proofing the contract

To make it harder for the UI to silently drop error info, the backend
could move from a single `error` string to a structured object:

```json
"error": {
  "code": "GENOME_NOT_FOUND",
  "user_message": "We couldn't find genome '9999999.9' in BV-BRC.",
  "hint": "Check the ID, or use 'Reconstruct from RAST job' if this is a RAST job ID.",
  "field": "genome",
  "retryable": false
}
```

This would also stabilize a key the ops repo's failure-watcher uses to
allowlist user errors vs real bugs (so we don't open a GitHub issue
every time a user typos a genome ID).

Not making this change yet: it would break Vibhav's UI if he starts
consuming `error` as a string. Coordinate first.
