"""Structured error response contract.

A single response shape used by both:
  - Pre-flight validation in route handlers (returned as 4xx HTTP errors)
  - Failed-job records in /api/jobs (set into the job's `error` field)

Why structured: the frontend needs a stable key (`code`) to drive its
display logic (e.g. pick an icon, decide whether to suggest re-login on
TOKEN_EXPIRED, etc.) plus a clean message + hint to render to the user.
Stringly-typed `error: "GenomeNotFoundError: ..."` puts that parsing
burden on every consumer.

This module defines the shape. Route handlers raise
StructuredValidationError; FastAPI handles converting it to an HTTPException
with `detail` = the StructuredError dict.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class StructuredError(BaseModel):
    """Machine-readable user-facing error.

    All fields except code+message are optional so existing string-only
    errors can wrap into this shape without inventing data.
    """

    code: str = Field(
        description=(
            "Stable SCREAMING_SNAKE_CASE identifier. Frontends key off this. "
            "Do not change once published. Examples: GENOME_NOT_FOUND, "
            "MODEL_NOT_FOUND, MEDIA_NOT_FOUND, TOKEN_EXPIRED, "
            "INVALID_TEMPLATE_TYPE, MISSING_REQUIRED_FIELD."
        )
    )
    message: str = Field(
        description=(
            "Human-readable description of what went wrong. Surface verbatim "
            "to the end user. One sentence, no trailing period required."
        )
    )
    hint: Optional[str] = Field(
        default=None,
        description=(
            "What the user should do next. One sentence. Frontends typically "
            "render this beneath the message in a lighter weight."
        ),
    )
    field: Optional[str] = Field(
        default=None,
        description=(
            "Request body field name the error attaches to, if any. Lets the "
            "frontend highlight the offending input. e.g. 'genome', 'model'."
        ),
    )
    retryable: bool = Field(
        default=False,
        description=(
            "True when the same request could succeed later without user "
            "action (transient upstream issue). False when the user must "
            "change the request."
        ),
    )


class StructuredValidationError(Exception):
    """Carrier exception that route handlers raise during pre-flight.

    A small wrapper in routes/jobs.py catches this and converts to
    HTTPException(status_code=4xx, detail=err.error.model_dump()).
    Keeping it as an exception (not returning early) lets validation
    helpers compose naturally and lets pytest assert on the structured
    shape without route-level mocking.
    """

    def __init__(self, status_code: int, error: StructuredError) -> None:
        super().__init__(f"[{status_code}] {error.code}: {error.message}")
        self.status_code = status_code
        self.error = error


# Convenience constructors for the codes we expect to emit a lot.
# These keep the call sites tidy and the wording consistent across the
# pre-flight layer and the in-job failure path.


def err_missing_field(field: str) -> StructuredError:
    return StructuredError(
        code="MISSING_REQUIRED_FIELD",
        message=f"Required field '{field}' is missing or empty.",
        hint=f"Provide a value for '{field}' in the request body.",
        field=field,
    )


def err_invalid_template_type(value: str, allowed: tuple[str, ...]) -> StructuredError:
    return StructuredError(
        code="INVALID_TEMPLATE_TYPE",
        message=f"'{value}' is not a recognized template type.",
        hint=f"Use one of: {', '.join(allowed)}.",
        field="template_type",
    )


def err_genome_not_found(genome_id: str) -> StructuredError:
    return StructuredError(
        code="GENOME_NOT_FOUND",
        message=f"Genome '{genome_id}' could not be fetched from BV-BRC.",
        hint=(
            "Check the genome ID is correct (BV-BRC format, e.g. '83332.12'). "
            "If you meant a RAST job id, use the RAST job submission flow instead."
        ),
        field="genome",
    )


def err_model_not_found(model_ref: str) -> StructuredError:
    return StructuredError(
        code="MODEL_NOT_FOUND",
        message=f"No model found at '{model_ref}'.",
        hint=(
            "Check that the reconstruct job for this path completed "
            "successfully, or pass a different model ref."
        ),
        field="model",
    )


def err_media_not_found(media_ref: str) -> StructuredError:
    return StructuredError(
        code="MEDIA_NOT_FOUND",
        message=f"No media found at '{media_ref}'.",
        hint="Check the media path, or omit `media` to use the default complete media.",
        field="media",
    )


def err_token_expired() -> StructuredError:
    return StructuredError(
        code="TOKEN_EXPIRED",
        message="Your PATRIC token has expired or is invalid.",
        hint="Sign in again to refresh your token, then retry.",
        field=None,
    )


def err_rast_job_genome_id_required() -> StructuredError:
    return StructuredError(
        code="MISSING_REQUIRED_FIELD",
        message="rast_genome_id is required when rast_job_id is set.",
        hint=(
            "Provide the RAST genome ID inside the job (e.g. '85962.43') as "
            "rast_genome_id. A single RAST job can annotate multiple genomes."
        ),
        field="rast_genome_id",
    )
