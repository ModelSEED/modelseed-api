"""Pydantic schemas for job management.

Matches the Task type from ProbModelSEED.spec.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


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
    """Request to build a model from a genome."""

    genome: str  # workspace reference to genome


class GapfillRequest(BaseModel):
    """Request to gapfill a model."""

    model: str  # workspace reference to model


class FBARequest(BaseModel):
    """Request to run flux balance analysis."""

    model: str  # workspace reference to model


class MergeModelsRequest(BaseModel):
    """Request to merge multiple models."""

    models: list[tuple[str, float]]  # [(model_ref, abundance), ...]
    output_file: str
    output_path: str


class ManageJobsRequest(BaseModel):
    """Request to manage jobs."""

    jobs: list[str]  # job IDs
    action: str  # 'd' = delete, 'r' = rerun
    errors: Optional[dict[str, str]] = None
    reports: Optional[dict[str, str]] = None
