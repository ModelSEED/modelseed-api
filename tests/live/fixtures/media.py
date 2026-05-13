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

ACETATE_ONLY = ReferenceMedia(
    ref="/chenry/public/modelsupport/media/Carbon-Acetate",
    short_name="acetate_only",
    is_minimal=True,
    expected_carbon_sources=["cpd00029"],  # Acetate
    notes="Acetate-only — for testing carbon-source-specific growth predictions",
)


REFERENCE_MEDIA = [COMPLETE, GLUCOSE_MINIMAL, ACETATE_ONLY]
