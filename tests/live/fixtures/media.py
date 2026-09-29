"""Reference media references used by the biological test layer.

Each entry is a workspace path to a known public media. Used as input to
/api/jobs/gapfill and /api/jobs/fba in the biological tests.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReferenceMedia:
    """A reference media for biological FBA / gapfill tests."""

    ref: str  # workspace reference (or bare name like "Complete")
    short_name: str
    is_minimal: bool
    expected_carbon_sources: list[str]  # cpd IDs we expect uptake on
    notes: str = ""


COMPLETE = ReferenceMedia(
    ref="/chenry/public/modelsupport/media/Complete",
    short_name="complete",
    is_minimal=False,
    expected_carbon_sources=[],  # all exchanges open
    notes="All exchanges open — sanity check; every model should grow on this",
)

GLUCOSE_MINIMAL = ReferenceMedia(
    ref="/chenry/public/modelsupport/media/Carbon-D-Glucose",
    short_name="glucose_minimal",
    is_minimal=True,
    expected_carbon_sources=["cpd00027"],  # D-Glucose
    notes="Glucose-only carbon source on minimal salts",
)

EMPTY = ReferenceMedia(
    ref="/chenry/public/modelsupport/media/Empty",
    short_name="empty",
    is_minimal=True,
    expected_carbon_sources=[],
    notes="No nutrients; a model must not grow on this medium",
)


REFERENCE_MEDIA = [COMPLETE, GLUCOSE_MINIMAL, EMPTY]
