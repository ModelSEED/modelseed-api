"""Pydantic schemas for job management.

Matches the Task type from ProbModelSEED.spec.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


# Valid template_type values. Mirrors TEMPLATE_FILES in jobs/tasks.py
# (must stay in sync). "auto" triggers the genome classifier instead of
# loading a specific template.
_TEMPLATE_TYPE = Literal[
    "auto",
    "core",
    "gn",
    "gp",
    "grampos",
    "gramneg",
    "ar",
    "archaea",
]
# The same set without "auto", for endpoints (gapfill, fba) that need a
# concrete template upfront.
_TEMPLATE_TYPE_CONCRETE = Literal[
    "core",
    "gn",
    "gp",
    "grampos",
    "gramneg",
    "ar",
    "archaea",
]


class Task(BaseModel):
    """A job/task in the system.

    Matches ProbModelSEED.spec Task type.
    """

    id: str
    app: str
    parameters: dict
    status: str  # queued, in-progress, completed, failed
    submit_time: Optional[str] = None
    start_time: Optional[str] = None
    completed_time: Optional[str] = None
    stdout_shock_node: Optional[str] = None
    stderr_shock_node: Optional[str] = None


class SubmitJobRequest(BaseModel):
    """Generic job submission request."""

    pass


class ReconstructionRequest(BaseModel):
    """Request to build a model from a genome.

    Three input modes (mutually exclusive, exactly one must be primary):
      - `genome`: BV-BRC genome ID (e.g. "83332.12"). Default path.
      - `genome_fasta`: FASTA content (DNA contigs or protein sequences;
        auto-detected). Skips BV-BRC lookup; routes through the RAST
        annotation service (with gene calling first for DNA). `genome` is
        treated as a display name.
      - `rast_job_id`: ID of an existing RAST annotation job. Skips both
        BV-BRC lookup and RAST submission; reads the already-annotated
        genome from the RAST jobs filesystem and feeds it directly into
        reconstruction.

    The `genome` field is required (BV-BRC ID or display name). When
    `genome_fasta` or `rast_job_id` is set, `genome` is just a label.
    """

    genome: str = Field(min_length=1)
    genome_fasta: Optional[str] = None
    rast_job_id: Optional[str] = Field(default=None, min_length=1)
    rast_genome_id: Optional[str] = Field(default=None, min_length=1)
    template_type: _TEMPLATE_TYPE = "auto"
    atp_safe: bool = True
    gapfill: bool = False
    media: Optional[str] = None
    output_path: Optional[str] = None

    @model_validator(mode="after")
    def _validate_input_modes(self) -> "ReconstructionRequest":
        """At most ONE of (genome_fasta, rast_job_id) may be set.

        `genome` is always required (used as label even when overridden by
        FASTA or RAST paths). The other two are mutually exclusive: combining
        them would mean ambiguous source-of-truth for the genome.
        """
        if self.genome_fasta is not None and self.rast_job_id is not None:
            raise ValueError(
                "genome_fasta and rast_job_id are mutually exclusive "
                "(provide at most one)"
            )
        # When rast_job_id is set, rast_genome_id is also required so we
        # know which RAST genome inside the job to fetch. (A single RAST
        # job can in principle annotate multiple genomes; we need both ids.)
        if self.rast_job_id is not None and not self.rast_genome_id:
            raise ValueError(
                "rast_genome_id is required when rast_job_id is set "
                "(the RAST genome ID inside the job, e.g. '85962.43')"
            )
        return self

class GapfillRequest(BaseModel):
    """Request to gapfill a model."""

    model: str = Field(min_length=1)  # workspace reference to model
    template_type: _TEMPLATE_TYPE_CONCRETE = "gn"
    media: Optional[str] = None  # media workspace reference


class FBARequest(BaseModel):
    """Request to run flux balance analysis."""

    model: str = Field(min_length=1)  # workspace reference to model
    media: Optional[str] = None  # media workspace reference


class MergeModelsRequest(BaseModel):
    """Request to merge multiple models."""

    models: list[tuple[str, float]] = Field(min_length=1)  # [(model_ref, abundance), ...]
    output_file: str = Field(min_length=1)
    output_path: str = Field(min_length=1)


class ManageJobsRequest(BaseModel):
    """Request to manage jobs."""

    jobs: list[str]  # job IDs
    action: str  # 'd' = delete, 'r' = rerun
    errors: Optional[dict[str, str]] = None
    reports: Optional[dict[str, str]] = None
