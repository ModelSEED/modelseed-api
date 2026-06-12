"""Pydantic schemas for job management.

Matches the Task type from ProbModelSEED.spec.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


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

    @field_validator("genome_fasta")
    @classmethod
    def _validate_genome_fasta_content(cls, v):
        if v is None:
            return v
        has_seq = False
        in_record = False
        for line in v.splitlines():
            stripped = line.strip()
            if stripped.startswith(">"):
                in_record = True
            elif stripped and in_record:
                has_seq = True
                break
        if not has_seq:
            raise ValueError(
                "genome_fasta must contain at least one FASTA record "
                "(a >header line followed by sequence data); got no valid "
                "records. Pass actual FASTA content, not a file path or "
                "workspace reference."
            )
        return v

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


# ─────────────────────────────────────────────────────────────────────
# Bulk reconstruction (Phase 3)
# ─────────────────────────────────────────────────────────────────────


class OntologyTerm(BaseModel):
    """One ontology-term annotation with an evidence/probability score."""

    term: str = Field(min_length=1, description="The term ID, e.g. 'K00001' for KO.")
    score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Evidence/probability in [0.0, 1.0]; defaults to 1.0.",
    )


class GenomeAnnotationPayload(BaseModel):
    """One genome's annotations for a bulk-reconstruction batch.

    Annotations are a nested mapping `{ontology_type: [OntologyTerm, ...]}`.
    Recognized ontology types include SSO, EC, KO; others are accepted and
    routed through whatever translator the worker has wired up.

    A gene may carry multiple terms and multiple ontology types. Unmapped
    genes (whose terms don't resolve to any model reaction) are retained
    in the genes.csv output with a `disposition=unmapped` marker rather
    than dropped silently.
    """

    genome_id: str = Field(
        min_length=1,
        description="Stable identifier for this genome; keys all outputs.",
    )
    annotations: dict[str, dict[str, list[OntologyTerm]]] = Field(
        description=(
            "Nested mapping: gene_id -> ontology_type -> list of OntologyTerm. "
            "Empty annotations are accepted (the resulting model will be minimal)."
        ),
    )


# Hard cap on batch size. Chris confirmed 100 (2026-06-09 chat). Enforced
# via the Field max_length below; any batch over this returns 422 from
# Pydantic without the request body ever reaching the dispatcher.
_BULK_RECONSTRUCT_MAX = 100


class BulkReconstructionRequest(BaseModel):
    """Submit N genomes for template-based reconstruction in one call.

    Output (per the PRD): for each input genome, a COBRApy JSON model
    written to `output_path/model_<genome_id>.json`. Combined CSVs
    `reactions.csv` and `genes.csv` (carrying a `genome_id` column) are
    written once at `output_path/`. See docs/BULK_RECONSTRUCT.md.

    Defaults mirror what Chris asked for: gapfill OFF (caller opts in)
    so the default batch is pure reconstruction; FVA ON because the
    KBase reactions-table columns require it. Both can be flipped per
    call.
    """

    genomes: list[GenomeAnnotationPayload] = Field(
        min_length=1,
        max_length=_BULK_RECONSTRUCT_MAX,
        description=(
            "List of genomes to reconstruct. Cap of "
            f"{_BULK_RECONSTRUCT_MAX} per request, enforced server-side."
        ),
    )

    template_type: _TEMPLATE_TYPE = Field(
        default="auto",
        description="Reconstruction template; 'auto' invokes the classifier per genome.",
    )
    atp_safe: bool = Field(default=True, description="Run the ATP correction step.")

    gapfill: bool = Field(
        default=False,
        description=(
            "When true, run MSGapfill per genome after build. Adds 2-5s/genome. "
            "Caller must supply gapfill_media."
        ),
    )
    gapfill_media: Optional[str] = Field(
        default=None,
        description=(
            "Workspace media reference or built-in media name. Required when "
            "gapfill=true."
        ),
    )

    fva: bool = Field(
        default=True,
        description=(
            "When true, run FVA on rich and minimal media per genome to fill "
            "the rich_media_* and minimal_media_* columns in reactions.csv / "
            "genes.csv. Adds ~30s-2min per genome (model-size dependent). When "
            "false, those columns are emitted empty (not null)."
        ),
    )

    output_path: Optional[str] = Field(
        default=None,
        description=(
            "Workspace path for outputs. Defaults to "
            "'/<user>/modelseed/bulk_<job_id>/' (worker fills in)."
        ),
    )

    @model_validator(mode="after")
    def _gapfill_requires_media(self) -> "BulkReconstructionRequest":
        if self.gapfill and not self.gapfill_media:
            raise ValueError(
                "gapfill_media is required when gapfill=true "
                "(workspace path or built-in media name)"
            )
        return self
