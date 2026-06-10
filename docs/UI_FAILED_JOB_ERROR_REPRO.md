# Failed-job error display: UI integration guide

**Status as of 2026-06-10**: most user-input errors now return a 4xx
synchronously at submit time with a structured error body. The original
"job fails, UI hides the reason" problem (verified via Playwright on
2026-06-09) is partially resolved by routing those errors through HTTP
errors that the frontend already knows how to surface. The residual
in-job-failure path still needs the UI to render `job.error` for
errors that can only be detected after the worker picks up the job.

This document is for: (a) handing to Vibhav so he can wire both error
contracts into the UI, and (b) anyone re-verifying the behavior in a
browser without running Playwright.

## What changed in the API (2026-06-10, commit 413727a)

`POST /api/jobs/reconstruct`, `/gapfill`, `/fba`, `/merge` now run a
pre-flight validation pass before dispatching the Celery job. If a
catchable user-input issue is detected, the route returns a 4xx with
a structured body instead of a 200 + a queued job that fails later.

The structured error body:

```json
{
  "detail": {
    "code": "GENOME_NOT_FOUND",
    "message": "Genome '9999999.9' could not be fetched from BV-BRC.",
    "hint": "Check the genome ID is correct (BV-BRC format, e.g. '83332.12'). If you meant a RAST job id, use the RAST job submission flow instead.",
    "field": "genome",
    "retryable": false
  }
}
```

(FastAPI wraps the body in a `detail` key. The structured object lives
under `body.detail`.)

Fields:

| Field | Type | Meaning |
|-------|------|---------|
| `code` | string | Stable SCREAMING_SNAKE_CASE identifier. Key off this for icon/disposition/CTAs. Do not parse `message`. |
| `message` | string | Human-readable one-sentence description. Render verbatim. |
| `hint` | string \| null | What the user should do next. Render in lighter weight under `message`. |
| `field` | string \| null | Request body field name (e.g. "genome", "model", "media") for inline form highlighting. |
| `retryable` | bool | True for transient upstream issues; false when the user must change the input. |

Codes the API emits today (more may be added; treat `code` as an open
enum and fall back on `message` for unknown codes):

| `code` | HTTP | When |
|--------|------|------|
| `MISSING_REQUIRED_FIELD` | 422 | Required field absent or empty. `field` populated. |
| `INVALID_TEMPLATE_TYPE` | 422 | template_type not in the allowed set. `field=template_type`. |
| `GENOME_NOT_FOUND` | 404 | Genome ID doesn't resolve in BV-BRC. `field=genome`. |
| `MODEL_NOT_FOUND` | 404 | Model ref doesn't resolve in workspace. `field=model`. |
| `MEDIA_NOT_FOUND` | 404 | Media ref doesn't resolve in workspace. `field=media`. |
| `TOKEN_EXPIRED` | 401 | PATRIC token expired or invalid. Frontend should prompt re-login. |

The opt-out: `POST /api/jobs/reconstruct?skip_validation=true` skips
the pre-flight pass and goes straight to dispatch (for callers willing
to fire-and-forget). Default off.

## What still goes through the old `job.error` path

Pre-flight is best-effort. Some failures only happen mid-job:

- Solver-level issues (infeasible gapfill, unbounded growth)
- Classifier surprises ("Cyanobacteria not yet supported")
- Race conditions (model existed at submit, deleted before worker ran)
- Token expiry mid-job (was valid at submit, expired by step 5)
- Bugs and unexpected exceptions

For these, `GET /api/jobs?ids=<job_id>` returns a record with
`status: "failed"` and an `error` field holding a stringy message like:

```json
{
  "status": "failed",
  "progress": "Saving model...",
  "error": "WorkspaceError: Token validation failed: Token expired"
}
```

The UI needs to render this string somewhere too. We may upgrade
`job.error` to the same structured shape later, but not in this round.

## What the UI needs to do

Two paths to handle:

1. **Synchronous 4xx on job submit.** The fetch/axios call to
   `/api/jobs/<verb>` rejects with `response.status` in `{401, 404, 422}`
   and `response.body.detail` containing the structured error. Surface
   it inline: toast or inline form-field error using `message` and
   `hint`. Highlight the offending field via `field` if you wire that
   in. On `code === "TOKEN_EXPIRED"`, redirect to login.

2. **Async failure surfaced via `/my-jobs` polling.** When a row has
   `status: "failed"`, render `job.error` somewhere visible. Tooltip
   on the Failed badge is the minimal fix; a per-job detail
   page/side-panel showing parameters + progress + error is the
   better one.

The Playwright verification on 2026-06-09 found that the production
UI currently does neither - both paths are needed.

## Verification (do not need Playwright)

With a PATRIC token in `$TOKEN`:

```bash
# Pre-flight path: returns 404 with structured body in ~4 seconds.
curl -i -X POST \
  -H "Authorization: $TOKEN" \
  -H "Content-Type: application/json" \
  https://modelseed.org/PMS/api/jobs/reconstruct \
  -d '{"genome":"9999999.9","template_type":"gn","atp_safe":true,"gapfill":false}'
# Expected: HTTP 404 + JSON body { "detail": { "code": "GENOME_NOT_FOUND", ... } }

# Async path: with skip_validation, the bad input flows through to a real
# failed job. Poll /api/jobs to see the in-job error string.
JOB=$(curl -s -X POST \
  -H "Authorization: $TOKEN" \
  -H "Content-Type: application/json" \
  "https://modelseed.org/PMS/api/jobs/reconstruct?skip_validation=true" \
  -d '{"genome":"9999999.9","template_type":"gn","atp_safe":true,"gapfill":false}' \
  | tr -d '"')
sleep 3
curl -s -H "Authorization: $TOKEN" \
  "https://modelseed.org/PMS/api/jobs?ids=$JOB" | python3 -m json.tool
# Expected: failed status, error field with GenomeNotFoundError message
```

## Open items

- The frontend currently shows just a red "Failed" badge with no tooltip,
  modal, or expanded row. Both error paths above are dropped silently
  today (confirmed via Playwright 2026-06-09 + screenshot artifact in
  tests/live/ui/test_failed_job_error_display.py).
- Pre-flight wiring on `bulk_reconstruct` is part of Phase 3 work (not
  yet shipped).
- `job.error` may be upgraded to the same `{code, message, hint, field,
  retryable}` shape later. When that lands, the UI render path is the
  same for both sync and async errors.
