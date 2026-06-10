# Job-error handling: integration guide for the frontend

A short handoff covering what the API does today for failed jobs, what
the UI needs to do to surface those failures to users, and how to
verify both ends are talking to each other.

If you're picking this up cold: the underlying issue is that users
whose jobs fail currently see a red "Failed" badge with no explanation.
The backend already produces actionable error messages; the gap is
on the rendering side. This doc explains both the new sync-4xx path
(landed 2026-06-10) and the pre-existing async `job.error` path that
still needs UI work.

## TL;DR

Two error paths. Both produce actionable messages. UI needs to render
both.

1. **Sync 4xx on submit** (new, live as of 2026-06-10). When a user
   submits a job whose input is obviously wrong (bad genome ID, missing
   model, expired token, etc.), the API now returns a 4xx with a
   structured `{code, message, hint, field, retryable}` body. The UI
   should surface this in its existing HTTP-error toast or as an inline
   form-field error.

2. **Async `job.error`** (pre-existing). For failures that only happen
   mid-job (solver infeasibility, classifier surprises, race conditions,
   mid-job token expiry), `GET /api/jobs?ids=<id>` returns
   `status: "failed"` with a stringy `error` field. Today the UI drops
   this on the floor. Tooltip on the Failed badge or a per-job detail
   panel both fix it.

## Path 1: sync 4xx on submit

Every job-submit route (`/api/jobs/reconstruct`, `/gapfill`, `/fba`,
`/merge`) now runs a pre-flight validation pass before dispatching
the Celery job. If the validation catches a user-input issue, the
route returns a 4xx with a structured body:

```http
POST https://modelseed.org/PMS/api/jobs/reconstruct
Content-Type: application/json
Authorization: <PATRIC token>

{"genome": "9999999.9", "template_type": "gn", "atp_safe": true, "gapfill": false}
```

```http
HTTP/1.1 404 Not Found
Content-Type: application/json

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

FastAPI wraps the body in a `detail` key, so the structured object
lives under `response.body.detail`.

### Fields

| Field | Type | Meaning |
|-------|------|---------|
| `code` | string | Stable SCREAMING_SNAKE_CASE identifier. Key off this for icon/disposition/CTAs. Do not parse `message`. Treat as an open enum: new codes may be added. |
| `message` | string | Human-readable one-sentence description. Surface verbatim. |
| `hint` | string \| null | What the user should do next. Render in lighter weight beneath `message`. |
| `field` | string \| null | Request body field name (e.g. `genome`, `model`, `media`) for inline form highlighting. |
| `retryable` | bool | True for transient upstream issues; false when the user must change the input. |

### Codes the API emits today

| `code` | HTTP | When | Suggested UI treatment |
|--------|------|------|------------------------|
| `MISSING_REQUIRED_FIELD` | 422 | Required field absent or empty. `field` populated. | Highlight `field`; show `message`. |
| `INVALID_TEMPLATE_TYPE` | 422 | template_type not in the allowed set. `field=template_type`. | Highlight template selector; show allowed values from `hint`. |
| `GENOME_NOT_FOUND` | 404 | Genome ID doesn't resolve in BV-BRC. `field=genome`. | Highlight genome input; offer "Use RAST flow instead" link if you have one. |
| `MODEL_NOT_FOUND` | 404 | Model ref doesn't resolve in workspace. `field=model`. | Highlight model picker. |
| `MEDIA_NOT_FOUND` | 404 | Media ref doesn't resolve in workspace. `field=media`. | Highlight media picker. |
| `TOKEN_EXPIRED` | 401 | PATRIC token expired or invalid. | Redirect to login. |

Anything you don't recognize: fall back on rendering `message` plus
`hint`. Don't fail loudly on unknown codes.

### Opt-out

`POST /api/jobs/<verb>?skip_validation=true` skips the pre-flight pass.
For cases where the caller knows the input is fine but pre-flight is
slow (e.g. BV-BRC being grumpy) and wants to fire-and-forget. Default
is off; you almost certainly don't need this.

## Path 2: async `job.error` from `/api/jobs`

Some failures can't be caught at submit. Examples:

- The gapfill solver finds no feasible solution.
- The genome classifier says "Cyanobacteria not supported".
- A workspace race: model existed when submit ran preflight, was
  deleted before the worker picked up the job.
- The PATRIC token was valid at submit but expired by the time the
  worker reached the workspace-save step.

For these, the job-status polling endpoint returns:

```http
GET https://modelseed.org/PMS/api/jobs?ids=<job_id>
Authorization: <token>
```

```json
{
  "<job_id>": {
    "id": "<job_id>",
    "app": "GapfillModel",
    "status": "failed",
    "progress": "Saving model...",
    "error": "WorkspaceError: Token validation failed: Token expired",
    "parameters": { "..." }
  }
}
```

The `error` field is a stringy message today (we may upgrade it to
the same structured shape in a later release). Render it on the row
as a tooltip on the Failed badge, an expanded sub-row, or a detail
side-panel. The full string is always safe to surface verbatim.

## What the UI needs to do, in priority order

1. **Handle the sync 4xx body.** In whatever code currently catches
   HTTP errors from `POST /api/jobs/*` calls, read
   `body.detail.message` and `body.detail.hint`, surface as your
   existing toast or inline form-field error. If `body.detail.field`
   is set, highlight that input. On `body.detail.code === "TOKEN_EXPIRED"`,
   redirect to login.

2. **Render `job.error` on the `/my-jobs` rows.** Minimum fix: hover
   tooltip on the red Failed badge that shows `job.error`. Better:
   click-to-expand or a side panel that also shows `parameters`,
   `progress`, and a deep link.

## Verification

Set a PATRIC token in `$TOKEN` (browser console at bv-brc.org:
`copy(window.App.authorizationToken)`).

```bash
# Sync 4xx path: returns 404 with structured body in ~4 seconds.
curl -i -X POST \
  -H "Authorization: $TOKEN" \
  -H "Content-Type: application/json" \
  https://modelseed.org/PMS/api/jobs/reconstruct \
  -d '{"genome":"9999999.9","template_type":"gn","atp_safe":true,"gapfill":false}'
# Expected: HTTP 404 + JSON body { "detail": { "code": "GENOME_NOT_FOUND", ... } }

# Async path: with skip_validation, the bad input flows to a real failed job.
JOB=$(curl -s -X POST \
  -H "Authorization: $TOKEN" \
  -H "Content-Type: application/json" \
  "https://modelseed.org/PMS/api/jobs/reconstruct?skip_validation=true" \
  -d '{"genome":"9999999.9","template_type":"gn","atp_safe":true,"gapfill":false}' \
  | tr -d '"')
sleep 3
curl -s -H "Authorization: $TOKEN" \
  "https://modelseed.org/PMS/api/jobs?ids=$JOB" | python3 -m json.tool
# Expected: failed status, error field populated with GenomeNotFoundError message.
```

## Recent real failures these changes target

Three jobs that died today on the live deploy, all caught at submit
by path 1 going forward and visible to users via path 2 in the meantime
once the UI renders `job.error`:

| Time UTC | Code | What the user did |
|----------|------|-------------------|
| 05:39 | `GENOME_NOT_FOUND` | Submitted a bad BV-BRC genome ID |
| 07:30 | `TOKEN_EXPIRED` | Token aged out during a workspace save |
| 10:09 | `MODEL_NOT_FOUND` | Ran gapfill on a model path that didn't exist |

All three would today produce a 4xx on submit (path 1). For the
token-expired case the user can also see the message via
`/api/jobs` polling once the UI renders `job.error` (path 2).

## Related

- `docs/UI_FAILED_JOB_ERROR_REPRO.md`: original verification doc with
  the Playwright repro (commit `8601800`).
- Backend commits: `413727a` adds pre-flight; `8601800` is this doc
  set; `a8e69ab` is the original Playwright test that surfaced the gap.
- Open question: when we upgrade `job.error` to the same structured
  shape, the UI render path is identical for both paths. No timeline
  yet; coordinate when the time comes.
