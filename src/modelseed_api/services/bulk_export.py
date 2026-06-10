"""CSV row builders and FVA helpers for the bulk-reconstruction endpoint.

Pure functions, no I/O beyond `write_combined_csvs` and `compute_fva_classes`
(the latter touches the solver, not the filesystem). The bulk_reconstruct
task imports these and feeds it model instances + FVA results; tests
exercise the row shapes against a small toy model fixture.

The CSV column specs mirror KBDatalakeApps' canonical `genome_reaction`
and `genome_gene_reaction_essentially_test` tables (see
`KBDatalakeApps/lib/KBDatalakeApps/KBDatalakeUtils.py:1074-1147`). One
deviation from the canonical: genes.csv carries an extra `disposition`
column with values `mapped|unmapped`. The PRD requires unmapped-gene
retention with a clear marker; this column makes that explicit instead
of leaving the consumer to infer from an empty `reaction` field.
"""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger(__name__)


REACTIONS_COLUMNS: tuple[str, ...] = (
    "genome_id",
    "reaction_id",
    "genes",
    "equation_names",
    "equation_ids",
    "directionality",
    "upper_bound",
    "lower_bound",
    "gapfilling_status",
    "rich_media_flux",
    "rich_media_class",
    "minimal_media_flux",
    "minimal_media_class",
)

GENES_COLUMNS: tuple[str, ...] = (
    "genome_id",
    "gene_id",
    "reaction",
    "rich_media_flux",
    "rich_media_class",
    "minimal_media_flux",
    "minimal_media_class",
    "disposition",
)

# Strip compartment suffix from reaction IDs to match KBDatalakeApps output
# (e.g. "rxn00001_c0" -> "rxn00001"). Same regex.
_COMPARTMENT_SUFFIX_RE = re.compile(r"_[a-z]\d+$")

# Class-priority used to collapse multiple FVA classes (per gene, across the
# reactions the gene participates in) down to one. Higher wins.
_CLASS_PRIORITY = {
    "essential_forward": 3,
    "essential_reverse": 3,
    "forward_only": 2,
    "reverse_only": 2,
    "reversible": 2,
    "blocked": 1,
    "": 0,
}
_FAMILY = {
    "essential_forward": "essential",
    "essential_reverse": "essential",
    "forward_only": "variable",
    "reverse_only": "variable",
    "reversible": "variable",
    "blocked": "blocked",
}


def _strip_compartment(rxn_id: str) -> str:
    return _COMPARTMENT_SUFFIX_RE.sub("", rxn_id)


def _directionality(lower_bound: float, upper_bound: float) -> str:
    """Map (lb, ub) to one of reversible|forward|reverse|blocked.

    Mirrors KBDatalakeUtils.py:1062-1072 exactly so consumers comparing
    outputs across the two sources see identical labels.
    """
    if lower_bound < 0 and upper_bound > 0:
        return "reversible"
    if lower_bound >= 0 and upper_bound > 0:
        return "forward"
    if lower_bound < 0 and upper_bound <= 0:
        return "reverse"
    return "blocked"


def _fva_class(minimum: float, maximum: float) -> str:
    """Classify a single reaction's FVA outcome on one medium.

    The string labels match KBDatalakeApps' (`essential_forward`,
    `essential_reverse`, `forward_only`, `reverse_only`, `reversible`,
    `blocked`) so the aggregation in `_most_constrained_class` works
    uniformly across both data sources.
    """
    if minimum > 0:
        return "essential_forward"
    if maximum < 0:
        return "essential_reverse"
    if minimum == 0 and maximum == 0:
        return "blocked"
    if minimum < 0 and maximum > 0:
        return "reversible"
    if minimum >= 0:
        return "forward_only"
    return "reverse_only"


def _most_constrained_class(classes: Iterable[str]) -> str:
    """Collapse a set of per-reaction FVA classes to one per-gene label.

    Returns one of `essential|variable|blocked|""` (the families used by
    KBDatalakeApps in the genes table). Empty string when no classes
    were supplied (the FVA-off path)."""
    best = ""
    best_priority = 0
    for c in classes:
        p = _CLASS_PRIORITY.get(c, 0)
        if p > best_priority:
            best_priority = p
            best = c
    return _FAMILY.get(best, "")


def compute_fva_classes(model, media_or_setup=None) -> dict[str, tuple[float, str]]:
    """Run FVA against `model` and return {reaction_id: (flux, class)}.

    Reaction IDs are stripped of compartment suffixes to match the
    other CSV builders. `flux` is the absolute value of the FVA maximum
    (i.e. the magnitude reachable in the forward direction), matching
    KBDatalakeApps' `pfba_fluxes` convention; we substitute the FVA
    max rather than running pFBA separately because the call is already
    in flight for the class computation.

    `media_or_setup` is currently unused beyond pass-through to the
    model's existing medium (the bulk_reconstruct task is responsible
    for configuring the model's medium before calling this). Kept in
    the signature so a future change to inject media-by-reference here
    doesn't require updating all call sites.
    """
    del media_or_setup  # placeholder for forward-compat (see docstring)
    from cobra.flux_analysis import flux_variability_analysis

    try:
        fva = flux_variability_analysis(model, fraction_of_optimum=0.0)
    except Exception as exc:
        log.warning("compute_fva_classes failed: %s", exc)
        return {}

    out: dict[str, tuple[float, str]] = {}
    for rxn_id, row in fva.iterrows():
        rid = _strip_compartment(rxn_id)
        mn = float(row["minimum"])
        mx = float(row["maximum"])
        klass = _fva_class(mn, mx)
        out[rid] = (abs(mx), klass)
    return out


def build_reactions_rows(
    model,
    genome_id: str,
    fva_rich: Optional[dict[str, tuple[float, str]]] = None,
    fva_minimal: Optional[dict[str, tuple[float, str]]] = None,
) -> list[dict]:
    """One row per reaction in `model.reactions`. Stable column order
    matches `REACTIONS_COLUMNS`."""
    fva_rich = fva_rich or {}
    fva_minimal = fva_minimal or {}
    rows = []
    for rxn in model.reactions:
        rid = _strip_compartment(rxn.id)
        try:
            eq_names = rxn.build_reaction_string(use_metabolite_names=True)
            eq_ids = rxn.build_reaction_string(use_metabolite_names=False)
        except Exception as exc:
            # build_reaction_string can fail on malformed reactions; emit
            # the row with empty equations rather than aborting the batch.
            log.warning("equation render failed for %s: %s", rxn.id, exc)
            eq_names = ""
            eq_ids = ""

        rf, rc = fva_rich.get(rid, ("", ""))
        mf, mc = fva_minimal.get(rid, ("", ""))

        rows.append({
            "genome_id": genome_id,
            "reaction_id": rid,
            "genes": getattr(rxn, "gene_reaction_rule", "") or "",
            "equation_names": eq_names,
            "equation_ids": eq_ids,
            "directionality": _directionality(rxn.lower_bound, rxn.upper_bound),
            "upper_bound": rxn.upper_bound,
            "lower_bound": rxn.lower_bound,
            "gapfilling_status": (rxn.notes or {}).get("gapfilling_status", "none"),
            "rich_media_flux": rf,
            "rich_media_class": rc,
            "minimal_media_flux": mf,
            "minimal_media_class": mc,
        })
    return rows


def build_genes_rows(
    model,
    genome_id: str,
    fva_rich: Optional[dict[str, tuple[float, str]]] = None,
    fva_minimal: Optional[dict[str, tuple[float, str]]] = None,
    unmapped_gene_ids: Optional[Iterable[str]] = None,
) -> list[dict]:
    """One row per gene. Genes in the model are `mapped` (linked to >=1
    reaction). Genes in `unmapped_gene_ids` (from the input PRD payload
    but not landed in the model) are emitted with `disposition=unmapped`
    and empty reaction/flux columns.

    Aggregation per gene: `reaction` is `;`-sorted-unique-joined list of
    rxn IDs the gene participates in. Fluxes are `max(abs(...))` over
    those reactions on each media. Class is the most-constrained.
    """
    fva_rich = fva_rich or {}
    fva_minimal = fva_minimal or {}
    unmapped_ids = list(unmapped_gene_ids or [])
    rows = []
    seen_gene_ids: set[str] = set()

    for gene in model.genes:
        seen_gene_ids.add(gene.id)
        rxn_ids: list[str] = []
        rich_fluxes: list[float] = []
        rich_classes: list[str] = []
        min_fluxes: list[float] = []
        min_classes: list[str] = []

        for rxn in gene.reactions:
            rid = _strip_compartment(rxn.id)
            rxn_ids.append(rid)
            rf, rc = fva_rich.get(rid, (0.0, ""))
            mf, mc = fva_minimal.get(rid, (0.0, ""))
            # fva_*.get returns (flux, class). Flux is already abs(max).
            if isinstance(rf, (int, float)):
                rich_fluxes.append(float(rf))
            if isinstance(mf, (int, float)):
                min_fluxes.append(float(mf))
            rich_classes.append(rc)
            min_classes.append(mc)

        rows.append({
            "genome_id": genome_id,
            "gene_id": gene.id,
            "reaction": ";".join(sorted(set(rxn_ids))),
            "rich_media_flux": max(rich_fluxes) if rich_fluxes else 0.0,
            "rich_media_class": _most_constrained_class(rich_classes),
            "minimal_media_flux": max(min_fluxes) if min_fluxes else 0.0,
            "minimal_media_class": _most_constrained_class(min_classes),
            "disposition": "mapped",
        })

    # Append unmapped genes (PRD input gave them but build pipeline didn't
    # land them on any reaction).
    for gid in unmapped_ids:
        if gid in seen_gene_ids:
            continue  # Already mapped; not actually unmapped.
        rows.append({
            "genome_id": genome_id,
            "gene_id": gid,
            "reaction": "",
            "rich_media_flux": 0.0,
            "rich_media_class": "",
            "minimal_media_flux": 0.0,
            "minimal_media_class": "",
            "disposition": "unmapped",
        })
    return rows


def write_combined_csvs(
    reactions_rows: list[dict],
    genes_rows: list[dict],
    output_dir: str | Path,
) -> tuple[Path, Path]:
    """Write reactions.csv and genes.csv to `output_dir`. Returns the
    two paths. Overwrites without warning (the bulk job's output dir
    is per-job, so collisions are intentional re-runs)."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    rxn_path = out / "reactions.csv"
    gene_path = out / "genes.csv"

    with rxn_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REACTIONS_COLUMNS)
        w.writeheader()
        w.writerows(reactions_rows)
    with gene_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=GENES_COLUMNS)
        w.writeheader()
        w.writerows(genes_rows)

    return rxn_path, gene_path
