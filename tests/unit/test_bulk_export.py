"""Unit tests for bulk_export CSV builders.

Uses a small fake model that mimics the cobra.Model surface we touch
(reactions, genes, gene_reaction_rule, build_reaction_string, bounds,
notes). Keeps the tests fast and free of solver/network dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pytest

from modelseed_api.services.bulk_export import (
    GENES_COLUMNS,
    REACTIONS_COLUMNS,
    _directionality,
    _fva_class,
    _most_constrained_class,
    _strip_compartment,
    build_genes_rows,
    build_reactions_rows,
    write_combined_csvs,
)


# ─────────────────────────────────────────────────────────────────────
# Pure helpers
# ─────────────────────────────────────────────────────────────────────


def test_strip_compartment_removes_c0_e0():
    assert _strip_compartment("rxn00001_c0") == "rxn00001"
    assert _strip_compartment("rxn00001_e0") == "rxn00001"


def test_strip_compartment_passthrough_when_no_suffix():
    assert _strip_compartment("rxn00001") == "rxn00001"
    assert _strip_compartment("EX_glc") == "EX_glc"


@pytest.mark.parametrize("lb,ub,expected", [
    (-10, 10, "reversible"),
    (0, 10, "forward"),
    (5, 10, "forward"),
    (-10, 0, "reverse"),
    (-10, -5, "reverse"),
    (0, 0, "blocked"),
])
def test_directionality_table(lb, ub, expected):
    assert _directionality(lb, ub) == expected


@pytest.mark.parametrize("mn,mx,expected", [
    (1.0, 5.0, "essential_forward"),
    (-5.0, -1.0, "essential_reverse"),
    (0.0, 0.0, "blocked"),
    (-5.0, 5.0, "reversible"),
    (0.0, 5.0, "forward_only"),
    (-5.0, 0.0, "reverse_only"),
])
def test_fva_class_table(mn, mx, expected):
    assert _fva_class(mn, mx) == expected


def test_most_constrained_class_picks_essential_over_variable():
    assert _most_constrained_class(["essential_forward", "reversible"]) == "essential"


def test_most_constrained_class_picks_variable_over_blocked():
    assert _most_constrained_class(["blocked", "reversible"]) == "variable"


def test_most_constrained_class_blocked_when_only_blocked():
    assert _most_constrained_class(["blocked", "blocked"]) == "blocked"


def test_most_constrained_class_empty_string_when_no_inputs():
    assert _most_constrained_class([]) == ""
    assert _most_constrained_class(["", ""]) == ""


# ─────────────────────────────────────────────────────────────────────
# Fake model fixture
# ─────────────────────────────────────────────────────────────────────


@dataclass
class _FakeReaction:
    id: str
    gene_reaction_rule: str = ""
    lower_bound: float = -1000.0
    upper_bound: float = 1000.0
    notes: dict = field(default_factory=dict)
    _eq_names: str = "A + B -> C"
    _eq_ids: str = "cpd1 + cpd2 -> cpd3"
    _genes: list = field(default_factory=list)

    def build_reaction_string(self, use_metabolite_names: bool = False) -> str:
        return self._eq_names if use_metabolite_names else self._eq_ids

    def genes(self):
        return self._genes


@dataclass
class _FakeGene:
    id: str
    reactions: list = field(default_factory=list)


@dataclass
class _FakeModel:
    reactions: list
    genes: list


def _toy_model() -> _FakeModel:
    """3 reactions, 2 genes. Gene1 -> rxn1 + rxn2. Gene2 -> rxn3."""
    g1 = _FakeGene("gene1")
    g2 = _FakeGene("gene2")

    rxn1 = _FakeReaction(
        id="rxn00001_c0",
        gene_reaction_rule="gene1",
        lower_bound=0.0,
        upper_bound=1000.0,
        _eq_names="ATP -> ADP",
        _eq_ids="cpd00002 -> cpd00008",
    )
    rxn2 = _FakeReaction(
        id="rxn00002_c0",
        gene_reaction_rule="gene1",
        lower_bound=-1000.0,
        upper_bound=1000.0,
        notes={"gapfilling_status": "core"},
    )
    rxn3 = _FakeReaction(
        id="EX_glc_e0",
        gene_reaction_rule="gene2",
        lower_bound=-10.0,
        upper_bound=0.0,
    )

    g1.reactions = [rxn1, rxn2]
    g2.reactions = [rxn3]
    return _FakeModel(reactions=[rxn1, rxn2, rxn3], genes=[g1, g2])


# ─────────────────────────────────────────────────────────────────────
# Row builders
# ─────────────────────────────────────────────────────────────────────


def test_build_reactions_rows_one_per_reaction():
    m = _toy_model()
    rows = build_reactions_rows(m, genome_id="G1")
    assert len(rows) == 3
    assert {r["reaction_id"] for r in rows} == {"rxn00001", "rxn00002", "EX_glc"}


def test_build_reactions_rows_columns_match_spec_in_order():
    m = _toy_model()
    rows = build_reactions_rows(m, genome_id="G1")
    for r in rows:
        assert tuple(r.keys()) == REACTIONS_COLUMNS


def test_build_reactions_rows_fva_off_leaves_columns_empty_string():
    """The plan calls for empty (not null) when FVA is off."""
    m = _toy_model()
    rows = build_reactions_rows(m, genome_id="G1")  # no fva args
    for r in rows:
        assert r["rich_media_flux"] == ""
        assert r["rich_media_class"] == ""
        assert r["minimal_media_flux"] == ""
        assert r["minimal_media_class"] == ""


def test_build_reactions_rows_fva_on_populates_flux_and_class():
    m = _toy_model()
    fva_rich = {"rxn00001": (5.0, "essential_forward")}
    fva_min = {"rxn00001": (0.0, "blocked")}
    rows = build_reactions_rows(m, "G1", fva_rich=fva_rich, fva_minimal=fva_min)
    r1 = next(r for r in rows if r["reaction_id"] == "rxn00001")
    assert r1["rich_media_flux"] == 5.0
    assert r1["rich_media_class"] == "essential_forward"
    assert r1["minimal_media_flux"] == 0.0
    assert r1["minimal_media_class"] == "blocked"
    # Reactions not in FVA dicts get empty columns
    r2 = next(r for r in rows if r["reaction_id"] == "rxn00002")
    assert r2["rich_media_flux"] == ""


def test_build_reactions_rows_gapfilling_status_from_notes():
    m = _toy_model()
    rows = build_reactions_rows(m, "G1")
    r2 = next(r for r in rows if r["reaction_id"] == "rxn00002")
    assert r2["gapfilling_status"] == "core"
    r1 = next(r for r in rows if r["reaction_id"] == "rxn00001")
    assert r1["gapfilling_status"] == "none"


def test_build_reactions_rows_directionality_derived_from_bounds():
    m = _toy_model()
    rows = build_reactions_rows(m, "G1")
    r1 = next(r for r in rows if r["reaction_id"] == "rxn00001")
    assert r1["directionality"] == "forward"
    r2 = next(r for r in rows if r["reaction_id"] == "rxn00002")
    assert r2["directionality"] == "reversible"


# ─────────────────────────────────────────────────────────────────────
# Genes builder
# ─────────────────────────────────────────────────────────────────────


def test_build_genes_rows_one_per_model_gene_plus_unmapped():
    m = _toy_model()
    rows = build_genes_rows(m, "G1", unmapped_gene_ids=["geneX", "geneY"])
    ids = [r["gene_id"] for r in rows]
    assert ids == ["gene1", "gene2", "geneX", "geneY"]


def test_build_genes_rows_columns_match_spec_in_order():
    m = _toy_model()
    rows = build_genes_rows(m, "G1")
    for r in rows:
        assert tuple(r.keys()) == GENES_COLUMNS


def test_build_genes_rows_reaction_field_is_semicolon_joined_unique_sorted():
    m = _toy_model()
    rows = build_genes_rows(m, "G1")
    g1 = next(r for r in rows if r["gene_id"] == "gene1")
    # gene1 participates in rxn00001 + rxn00002
    assert g1["reaction"] == "rxn00001;rxn00002"


def test_build_genes_rows_disposition_mapped_vs_unmapped():
    m = _toy_model()
    rows = build_genes_rows(m, "G1", unmapped_gene_ids=["unmapped1"])
    by_id = {r["gene_id"]: r for r in rows}
    assert by_id["gene1"]["disposition"] == "mapped"
    assert by_id["unmapped1"]["disposition"] == "unmapped"
    assert by_id["unmapped1"]["reaction"] == ""


def test_build_genes_rows_unmapped_skip_when_actually_mapped():
    """If a gene is in both model.genes AND unmapped_gene_ids (because the
    caller passed it conservatively), the model membership wins. We don't
    emit a duplicate unmapped row."""
    m = _toy_model()
    rows = build_genes_rows(m, "G1", unmapped_gene_ids=["gene1"])
    g1_rows = [r for r in rows if r["gene_id"] == "gene1"]
    assert len(g1_rows) == 1
    assert g1_rows[0]["disposition"] == "mapped"


def test_build_genes_rows_fva_aggregation_picks_max_flux_and_constrained_class():
    m = _toy_model()
    # gene1 hits rxn00001 (flux=5, essential_forward) and rxn00002 (flux=2, reversible)
    fva_rich = {
        "rxn00001": (5.0, "essential_forward"),
        "rxn00002": (2.0, "reversible"),
    }
    rows = build_genes_rows(m, "G1", fva_rich=fva_rich)
    g1 = next(r for r in rows if r["gene_id"] == "gene1")
    assert g1["rich_media_flux"] == 5.0
    assert g1["rich_media_class"] == "essential"  # essential wins over variable


# ─────────────────────────────────────────────────────────────────────
# write_combined_csvs round trip
# ─────────────────────────────────────────────────────────────────────


def test_write_combined_csvs_round_trip(tmp_path):
    import csv as _csv

    m = _toy_model()
    rxn_rows = build_reactions_rows(m, "G1")
    gene_rows = build_genes_rows(m, "G1", unmapped_gene_ids=["geneZ"])

    rxn_path, gene_path = write_combined_csvs(rxn_rows, gene_rows, tmp_path)

    assert rxn_path.exists() and gene_path.exists()
    assert rxn_path.name == "reactions.csv"
    assert gene_path.name == "genes.csv"

    # Headers in spec order
    with rxn_path.open() as f:
        header = next(_csv.reader(f))
    assert tuple(header) == REACTIONS_COLUMNS
    with gene_path.open() as f:
        header = next(_csv.reader(f))
    assert tuple(header) == GENES_COLUMNS

    # Body counts match what we passed in
    with rxn_path.open() as f:
        assert len(list(_csv.DictReader(f))) == 3
    with gene_path.open() as f:
        rows = list(_csv.DictReader(f))
        assert len(rows) == 3  # gene1 + gene2 + geneZ
        assert {r["disposition"] for r in rows} == {"mapped", "unmapped"}
