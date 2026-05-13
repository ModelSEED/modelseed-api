"""Reference genomes used by the biological test layer.

Each entry is a known organism with a stable BV-BRC genome ID, used as
input to /api/jobs/reconstruct in the biological tests. Picked to cover
gram-negative, gram-positive, and archaeal classification paths.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReferenceGenome:
    """A reference genome for biological reconstruction tests."""

    genome_id: str  # BV-BRC genome ID
    short_name: str  # used in test IDs and workspace paths
    expected_template: str  # gn | gp | ar — for asserting auto-classification
    expected_min_reactions: int  # reasonable lower bound on draft model size
    notes: str = ""


# Known stable genomes. If BV-BRC removes or renames any of these,
# update the genome_id; do not add per-test genome lookups.
ECOLI_K12_MG1655 = ReferenceGenome(
    genome_id="511145.12",
    short_name="ecoli_k12",
    expected_template="gn",
    expected_min_reactions=1000,
    notes="E. coli K-12 MG1655 — canonical gram-negative test organism",
)

BSUBTILIS_168 = ReferenceGenome(
    genome_id="224308.1",
    short_name="bsubtilis_168",
    expected_template="gp",
    expected_min_reactions=900,
    notes="Bacillus subtilis 168 — canonical gram-positive test organism",
)

MJANNASCHII_DSM2661 = ReferenceGenome(
    genome_id="243232.1",
    short_name="mjannaschii",
    expected_template="ar",
    expected_min_reactions=500,
    notes="Methanocaldococcus jannaschii DSM 2661 — canonical archaeal test organism",
)


REFERENCE_GENOMES = [ECOLI_K12_MG1655, BSUBTILIS_168, MJANNASCHII_DSM2661]


# Pairwise reduction of (template_type, genome) — see docs/E2E_TEST_PLAN.md.
# Each tuple is (template_type, ReferenceGenome). Covers every enum value
# at least once and every genome at least once, with `auto` exercising the
# classifier against all three.
TEMPLATE_GENOME_PAIRS = [
    ("auto", ECOLI_K12_MG1655),
    ("auto", BSUBTILIS_168),
    ("auto", MJANNASCHII_DSM2661),
    ("gn", ECOLI_K12_MG1655),
    ("gp", BSUBTILIS_168),
    ("ar", MJANNASCHII_DSM2661),
    ("gramneg", ECOLI_K12_MG1655),
    ("grampos", BSUBTILIS_168),
    ("archaea", MJANNASCHII_DSM2661),
]
