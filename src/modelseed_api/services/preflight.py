"""Pre-flight validation helpers for job submission routes.

Each `validate_*` function does the minimum upstream work needed to
prove that a job submission has a reasonable chance of succeeding, and
raises :class:`StructuredValidationError` (with a 4xx status code and
the structured error body) when it doesn't. Route handlers run these
before calling :class:`JobDispatcher.dispatch`.

What this layer is and isn't:

  - IS: a fast best-effort gate. Catches the high-frequency mistakes
    (wrong genome ID, missing model, expired token) so the user gets a
    synchronous 4xx instead of a doomed async job that fails 30s later.
  - ISN'T: a guarantee that the job will succeed. Race conditions
    (model deleted between submit and run) and runtime-only failures
    (solver infeasibility, classifier surprises) still surface as
    failed jobs and rely on the in-job error path. That's intentional.

Each helper takes a few hundred milliseconds at most. The total
pre-flight cost for a typical reconstruct submit is ~1s; for gapfill or
FBA it's ~200ms. Acceptable on a job-submit code path that already
goes through an HTTP round-trip.
"""

from __future__ import annotations

import logging

from modelseed_api.schemas.errors import (
    StructuredValidationError,
    err_genome_not_found,
    err_media_not_found,
    err_model_not_found,
    err_output_path_not_owned,
    err_token_expired,
)

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Workspace-backed checks: model, media, token
# ─────────────────────────────────────────────────────────────────────


def validate_model_exists(model_ref: str, token: str) -> None:
    """Confirm `model_ref/model` exists in the user's workspace.

    Reuses the existing `_fetch_model_obj` translation path so that the
    structured error mirrors the in-job ModelNotFoundError verbatim
    (same `model_ref/model` path, same hint). The fetch is short-circuited
    by `objects: [...]` with only the path, never pulling the model body.
    """
    from modelseed_api.services.storage_factory import get_storage_service
    from modelseed_api.services.workspace_service import WorkspaceError

    ws = get_storage_service(token)
    try:
        result = ws.get({"objects": [f"{model_ref}/model"]})
    except WorkspaceError as exc:
        msg = str(exc)
        if "Object not found" in msg:
            raise StructuredValidationError(404, err_model_not_found(model_ref)) from exc
        if "Token" in msg and ("expired" in msg or "invalid" in msg.lower()):
            raise StructuredValidationError(401, err_token_expired()) from exc
        # Other workspace errors aren't user-actionable; let them through
        # so the existing exception path handles them. Don't dress them
        # up in a structured shell that pretends to be user-error.
        raise
    if not result:
        raise StructuredValidationError(404, err_model_not_found(model_ref))


def validate_media_exists(media_ref: str, token: str) -> None:
    """Confirm `media_ref` resolves in workspace.

    Treats both 'not found' and 'empty result' as MEDIA_NOT_FOUND. Media
    refs that look like built-in shortcuts (no leading '/') are passed
    through unchanged: the task layer resolves them via the local media
    library, not workspace.
    """
    if not media_ref.startswith("/"):
        # Built-in media name (e.g. 'Complete', 'NMS'). Not a workspace
        # path; can't validate against workspace. Trust and continue.
        return

    from modelseed_api.services.storage_factory import get_storage_service
    from modelseed_api.services.workspace_service import WorkspaceError

    ws = get_storage_service(token)
    try:
        result = ws.get({"objects": [media_ref]})
    except WorkspaceError as exc:
        msg = str(exc)
        if "Object not found" in msg:
            raise StructuredValidationError(404, err_media_not_found(media_ref)) from exc
        if "Token" in msg and ("expired" in msg or "invalid" in msg.lower()):
            raise StructuredValidationError(401, err_token_expired()) from exc
        raise
    if not result:
        raise StructuredValidationError(404, err_media_not_found(media_ref))


def validate_token(token: str) -> None:
    """Confirm the PATRIC token is currently valid.

    Cheapest workspace call that fails on bad/expired token: an `ls`
    on the user's home directory. We don't care about the contents,
    just that the auth round-trip succeeds.
    """
    if not token:
        raise StructuredValidationError(401, err_token_expired())

    from modelseed_api.services.storage_factory import get_storage_service
    from modelseed_api.services.workspace_service import WorkspaceError

    # Derive username from token to ls their home; falls back to a
    # generic call if we can't parse it.
    username = ""
    for part in token.split("|"):
        if part.startswith("un="):
            username = part[3:]
            break

    ws = get_storage_service(token)
    try:
        # Just a touch. Any successful round-trip is enough.
        ws.ls({"paths": [f"/{username}/"] if username else ["/"]})
    except WorkspaceError as exc:
        msg = str(exc)
        if "Token" in msg and ("expired" in msg or "invalid" in msg.lower()):
            raise StructuredValidationError(401, err_token_expired()) from exc
        # Any other workspace error isn't a token issue; let the route
        # surface it via the normal path.
        raise


# ─────────────────────────────────────────────────────────────────────
# BV-BRC-backed checks: genome
# ─────────────────────────────────────────────────────────────────────


def validate_output_path_under_user(output_path: str | None, username: str) -> None:
    """Reject requests whose `output_path` is not under the caller's namespace.

    Workspace `create` calls on paths the user does not own come back as
    `WorkspaceError("Insufficient permissions to create ...")` 30 seconds
    into a queued job, after the worker has fetched the genome and built
    the model. That's a poor user experience even when the failure is
    technically the caller's fault. Catching it at submit time turns a
    "queued -> in-progress -> failed badge with no detail" sequence into a
    synchronous 403 with a clear hint.

    Specifically catches the bug we see in the wild: the frontend strips
    the `@bvbrc` (or `@patricbrc.org`) suffix from the username when
    constructing the path, so a user with workspace
    `/jose@bvbrc/modelseed/` ends up submitting `/jose/modelseed/`, which
    they do not own. The hint in OUTPUT_PATH_NOT_OWNED calls out the
    suffix gotcha explicitly.

    Empty `output_path` passes through unchanged: the worker fills in a
    sensible default from the token's `un=` value, which always has the
    correct suffix.
    """
    if not output_path:
        return
    expected_prefix = f"/{username}/"
    if output_path == f"/{username}" or output_path.startswith(expected_prefix):
        return
    raise StructuredValidationError(
        403, err_output_path_not_owned(output_path, expected_prefix)
    )


def validate_genome_exists(genome_id: str, token: str) -> None:
    """Confirm `genome_id` resolves in BV-BRC.

    Calls BVBRCUtils.build_kbase_genome_from_api and translates the
    not-found shapes (ValueError, HTTPError 500/404) to GENOME_NOT_FOUND.
    Note this DOES download the genome (the cheapest existence check
    available in BVBRCUtils); cost is ~500ms-2s depending on genome
    size and BV-BRC load. We discard the result.

    The same translation pattern is reused from `tasks._fetch_bvbrc_genome`,
    intentionally not factored to avoid coupling preflight to job-script
    internals (their failure modes diverge over time).
    """
    # Strip any source-prefix the frontend may have added.
    cleaned = genome_id.split(":", 1)[1] if ":" in genome_id else genome_id

    try:
        from modelseed_api.jobs.tasks import _init_kwargs
        from kbutillib import BVBRCUtils
    except Exception as exc:
        # If we can't even import the helpers, don't fail the submission.
        # The job dispatch will hit the same import and surface a clearer
        # internal error there.
        log.warning("preflight: BV-BRC validator imports failed: %s", exc)
        return

    try:
        kwargs = _init_kwargs(token)
        bvbrc = BVBRCUtils(**kwargs)
        result = bvbrc.build_kbase_genome_from_api(cleaned)
    except Exception as exc:
        msg = str(exc)
        not_found_markers = (
            "HTTPError" in type(exc).__name__,
            "No genome found with ID" in msg,
            " 500 " in msg,
            " 404 " in msg,
            "Internal Server Error" in msg,
            "Not Found" in msg,
        )
        if any(not_found_markers):
            raise StructuredValidationError(404, err_genome_not_found(cleaned)) from exc
        # Other exceptions during the lookup (transient network, BVBRC
        # outage) aren't the user's fault. Don't 4xx them.
        log.warning("preflight: BV-BRC lookup raised unexpected error, skipping check: %s", exc)
        return

    if not result:
        raise StructuredValidationError(404, err_genome_not_found(cleaned))
