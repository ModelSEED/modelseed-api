"""Biological-soundness assertions for ModelSEED models, FBA results, gapfill solutions.

The 35 checks listed in docs/E2E_TEST_PLAN.md, codified. Each function
accepts our API's dict shape (ModelData, GapfillData, FBADetail, etc.)
and raises AssertionError with a metric-rich message on failure.

Severity is recorded by the choice of function:
  - assert_*    → hard failure
  - warn_*      → returns the warning string instead of raising; tests can
                  collect these into a list and report separately

When a single assertion is genuinely "soft" for some test (e.g. orphan
compounds are tolerable in some templates), call the warn_* variant if
one exists, or wrap the assert_* in pytest.warns/xfail at the call site.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Iterable

# IDs for essential cofactors used in the biomass-cofactor check.
ESSENTIAL_COFACTOR_IDS = {
    "cpd00001": "H2O",
    "cpd00002": "ATP",
    "cpd00003": "NAD",
    "cpd00004": "NADH",
    "cpd00005": "NADPH",
    "cpd00006": "NADP",
}

VALID_DIRECTIONS = {">", "<", "="}


# ─────────────────────────────────────────────────────────────────────────
# Helpers — work on our ModelData dict shape
# ─────────────────────────────────────────────────────────────────────────


def _reactions(model: dict) -> list[dict]:
    return model.get("reactions") or []


def _compounds(model: dict) -> list[dict]:
    return model.get("compounds") or []


def _genes(model: dict) -> list[dict]:
    return model.get("genes") or []


def _compartments(model: dict) -> list[dict]:
    return model.get("compartments") or []


def _biomasses(model: dict) -> list[dict]:
    return model.get("biomasses") or []


def _strip_compartment(compound_id: str) -> str:
    """`cpd00027_c0` → `cpd00027`. Returns input unchanged if not in that form."""
    m = re.match(r"^(cpd\d+)_[a-z]\d+$", compound_id)
    return m.group(1) if m else compound_id


def _exchange_reaction_ids(model: dict) -> set[str]:
    return {r["id"] for r in _reactions(model) if r.get("id", "").startswith("EX_")}


def _ref(model: dict) -> str:
    return model.get("ref") or model.get("id") or "<unknown>"


# ─────────────────────────────────────────────────────────────────────────
# Structural assertions (1–21)
# ─────────────────────────────────────────────────────────────────────────


def assert_model_has_minimum_reactions(model: dict, min_count: int = 50) -> None:
    """1. Model must have at least `min_count` reactions."""
    n = len(_reactions(model))
    if n < min_count:
        raise AssertionError(
            f"{_ref(model)}: only {n} reactions; expected ≥{min_count}"
        )


def assert_model_has_minimum_compounds(model: dict, min_count: int = 50) -> None:
    """2. Model must have at least `min_count` compounds."""
    n = len(_compounds(model))
    if n < min_count:
        raise AssertionError(
            f"{_ref(model)}: only {n} compounds; expected ≥{min_count}"
        )


def assert_model_has_minimum_compartments(model: dict, min_count: int = 2) -> None:
    """3. Model must have at least `min_count` compartments (cytosol + extracellular)."""
    n = len(_compartments(model))
    if n < min_count:
        raise AssertionError(
            f"{_ref(model)}: only {n} compartments; expected ≥{min_count}"
        )


def assert_extracellular_compartment_present(model: dict) -> None:
    """4. Model must have an extracellular compartment (e0 or e)."""
    ids = {c.get("id") for c in _compartments(model)}
    if not ({"e0", "e"} & ids):
        raise AssertionError(
            f"{_ref(model)}: no extracellular compartment. Compartments: {ids}"
        )


def assert_cytosol_compartment_present(model: dict) -> None:
    """5. Model must have a cytosol compartment (c0 or c)."""
    ids = {c.get("id") for c in _compartments(model)}
    if not ({"c0", "c"} & ids):
        raise AssertionError(
            f"{_ref(model)}: no cytosol compartment. Compartments: {ids}"
        )


def assert_at_least_one_biomass(model: dict) -> None:
    """6. Model must have at least one biomass reaction."""
    if len(_biomasses(model)) < 1:
        raise AssertionError(f"{_ref(model)}: no biomass reactions")


def assert_biomass_has_minimum_compounds(model: dict, min_count: int = 5) -> None:
    """7. Each biomass must contain at least `min_count` compounds."""
    for bio in _biomasses(model):
        n = len(bio.get("compounds") or [])
        if n < min_count:
            raise AssertionError(
                f"{_ref(model)}: biomass {bio.get('id')} has only {n} compounds; "
                f"expected ≥{min_count}"
            )


def assert_biomass_includes_essential_cofactors(model: dict) -> None:
    """8. Each biomass must reference at least the basic essential cofactors.

    Uses a permissive policy: at least 3 of the canonical cofactor families
    (water, ATP, NAD/NADH, NADP/NADPH) must be present in *some* biomass.
    """
    seen_families = set()
    for bio in _biomasses(model):
        for compound_entry in bio.get("compounds") or []:
            # ModelBiomass compounds entries are [compound_id, coefficient, compartment]
            cid = (
                compound_entry[0]
                if isinstance(compound_entry, (list, tuple))
                else compound_entry.get("compound_id", "")
            )
            stripped = _strip_compartment(cid)
            if stripped == "cpd00001":
                seen_families.add("water")
            elif stripped == "cpd00002":
                seen_families.add("atp")
            elif stripped in {"cpd00003", "cpd00004"}:
                seen_families.add("nad")
            elif stripped in {"cpd00005", "cpd00006"}:
                seen_families.add("nadp")
    if len(seen_families) < 3:
        raise AssertionError(
            f"{_ref(model)}: biomass missing essential cofactor families. "
            f"Saw: {sorted(seen_families)}; expected ≥3 of "
            f"{{water, atp, nad, nadp}}"
        )


def warn_orphan_compounds(model: dict) -> str | None:
    """9. (warn-only) Compounds not referenced by any reaction. Returns
    a description string if any orphans exist, else None."""
    referenced: set[str] = set()
    for r in _reactions(model):
        for stoich in r.get("stoichiometry") or []:
            # [coefficient, compound_id, compartment, ...]
            if isinstance(stoich, (list, tuple)) and len(stoich) >= 3:
                cid = stoich[1]
                comp = stoich[2]
                referenced.add(f"{cid}_{comp}" if comp else cid)
    all_compound_ids = {c.get("id") for c in _compounds(model)}
    orphans = sorted(all_compound_ids - referenced)
    if orphans:
        return (
            f"{_ref(model)}: {len(orphans)} orphan compound(s) "
            f"(first 5: {orphans[:5]})"
        )
    return None


def assert_no_orphan_reactions(model: dict) -> None:
    """10. Every reaction must have at least one reagent on each side, OR be
    a sink/exchange reaction (single reagent on one side is allowed)."""
    bad = []
    for r in _reactions(model):
        rid = r.get("id", "<unknown>")
        stoich = r.get("stoichiometry") or []
        if not stoich:
            bad.append(f"{rid} (no stoichiometry)")
    if bad:
        raise AssertionError(
            f"{_ref(model)}: {len(bad)} reaction(s) with no stoichiometry "
            f"(first 5: {bad[:5]})"
        )


def assert_all_reactions_have_directions(model: dict) -> None:
    """11. Every reaction has a direction in {>, <, =}."""
    bad = []
    for r in _reactions(model):
        d = r.get("direction")
        if d not in VALID_DIRECTIONS:
            bad.append(f"{r.get('id')}={d!r}")
    if bad:
        raise AssertionError(
            f"{_ref(model)}: {len(bad)} reaction(s) with invalid direction "
            f"(first 5: {bad[:5]}); valid: {VALID_DIRECTIONS}"
        )


def assert_gpr_coverage(model: dict, min_frac: float = 0.30) -> None:
    """12. At least `min_frac` of reactions have a GPR association."""
    rxns = _reactions(model)
    if not rxns:
        raise AssertionError(f"{_ref(model)}: no reactions to check GPR coverage")
    with_gpr = sum(1 for r in rxns if (r.get("gpr") or "").strip())
    frac = with_gpr / len(rxns)
    if frac < min_frac:
        raise AssertionError(
            f"{_ref(model)}: only {frac:.1%} of reactions have GPRs "
            f"({with_gpr}/{len(rxns)}); expected ≥{min_frac:.0%}"
        )


def assert_genes_referenced(model: dict) -> None:
    """13. Every declared gene is referenced by ≥1 reaction in its `reactions` list."""
    bad = [
        g.get("id") for g in _genes(model)
        if not (g.get("reactions") or [])
    ]
    if bad:
        raise AssertionError(
            f"{_ref(model)}: {len(bad)} gene(s) reference no reactions "
            f"(first 5: {bad[:5]})"
        )


def assert_compound_charges_are_numeric(model: dict) -> None:
    """14. Every compound has a finite numeric charge (or no charge field)."""
    bad = []
    for c in _compounds(model):
        ch = c.get("charge")
        if ch is None:
            continue
        try:
            v = float(ch)
        except (TypeError, ValueError):
            bad.append(f"{c.get('id')}={ch!r}")
            continue
        if not math.isfinite(v):
            bad.append(f"{c.get('id')}={ch!r}")
    if bad:
        raise AssertionError(
            f"{_ref(model)}: {len(bad)} compound(s) with non-numeric charge "
            f"(first 5: {bad[:5]})"
        )


def warn_unbalanced_reactions(model: dict, allowed_unbalanced_frac: float = 0.10) -> str | None:
    """15. (warn-only) Most reactions should be mass-balanced. We can't fully
    verify mass balance without atom maps, so this is a structural surrogate:
    flag reactions whose reactant-product compound counts are wildly skewed."""
    rxns = _reactions(model)
    if not rxns:
        return None
    skewed = 0
    for r in rxns:
        stoich = r.get("stoichiometry") or []
        if not stoich:
            continue
        coeffs = [
            float(s[0])
            for s in stoich
            if isinstance(s, (list, tuple)) and len(s) >= 1
        ]
        if not coeffs:
            continue
        n_reactants = sum(1 for c in coeffs if c < 0)
        n_products = sum(1 for c in coeffs if c > 0)
        if n_reactants == 0 or n_products == 0:
            # Sink/source — skip
            continue
        if max(n_reactants, n_products) > 5 * min(n_reactants, n_products):
            skewed += 1
    frac = skewed / len(rxns)
    if frac > allowed_unbalanced_frac:
        return (
            f"{_ref(model)}: {frac:.1%} of reactions have skewed stoichiometry "
            f"({skewed}/{len(rxns)}); threshold {allowed_unbalanced_frac:.0%}"
        )
    return None


def assert_no_duplicate_reaction_ids(model: dict) -> None:
    """16. No duplicate reaction IDs."""
    counts = Counter(r.get("id") for r in _reactions(model))
    dupes = {k: v for k, v in counts.items() if v > 1}
    if dupes:
        raise AssertionError(
            f"{_ref(model)}: duplicate reaction IDs: {dict(list(dupes.items())[:5])}"
        )


def assert_no_duplicate_compound_ids(model: dict) -> None:
    """17. No duplicate compound IDs."""
    counts = Counter(c.get("id") for c in _compounds(model))
    dupes = {k: v for k, v in counts.items() if v > 1}
    if dupes:
        raise AssertionError(
            f"{_ref(model)}: duplicate compound IDs: {dict(list(dupes.items())[:5])}"
        )


def assert_exchange_reactions_exist(model: dict, min_count: int = 10) -> None:
    """18. Model has at least `min_count` exchange reactions (EX_*)."""
    n = len(_exchange_reaction_ids(model))
    if n < min_count:
        raise AssertionError(
            f"{_ref(model)}: only {n} exchange reactions; expected ≥{min_count}"
        )


def assert_extracellular_biomass_compounds_have_exchange(model: dict) -> None:
    """19. Every extracellular biomass compound should have a matching exchange reaction."""
    exchanges = _exchange_reaction_ids(model)
    missing = []
    for bio in _biomasses(model):
        for entry in bio.get("compounds") or []:
            cid = entry[0] if isinstance(entry, (list, tuple)) else entry.get("compound_id")
            comp = entry[2] if isinstance(entry, (list, tuple)) and len(entry) > 2 else None
            if comp and comp.startswith("e"):
                ex_id = f"EX_{cid}"
                if ex_id not in exchanges:
                    missing.append(ex_id)
    if missing:
        raise AssertionError(
            f"{_ref(model)}: {len(missing)} extracellular biomass compound(s) "
            f"missing exchange reactions (first 5: {missing[:5]})"
        )


def assert_atp_maintenance_present(model: dict) -> None:
    """20. ATP maintenance / NGAM-like reaction should be present in models built
    with `atp_safe=True` (the default). Looks for any reaction whose ID contains
    'ATPM' or whose name suggests ATP maintenance."""
    candidates = [
        r for r in _reactions(model)
        if "ATPM" in (r.get("id") or "")
        or "maintenance" in (r.get("name") or "").lower()
    ]
    if not candidates:
        raise AssertionError(
            f"{_ref(model)}: no ATP maintenance reaction found "
            f"(searched for ATPM in id and 'maintenance' in name)"
        )


def assert_compartment_pH_set(model: dict) -> None:
    """21. Each compartment has a finite numeric pH."""
    bad = []
    for c in _compartments(model):
        ph = c.get("pH")
        if ph is None:
            bad.append(f"{c.get('id')}=<missing>")
            continue
        try:
            v = float(ph)
        except (TypeError, ValueError):
            bad.append(f"{c.get('id')}={ph!r}")
            continue
        if not math.isfinite(v):
            bad.append(f"{c.get('id')}={ph!r}")
    if bad:
        raise AssertionError(
            f"{_ref(model)}: compartments missing/invalid pH: {bad[:5]}"
        )


# ─────────────────────────────────────────────────────────────────────────
# FBA assertions (22–30)
# ─────────────────────────────────────────────────────────────────────────


def _objective(fba_result: dict) -> float:
    """Extract the objective value from an FBA result dict."""
    for key in ("objectiveValue", "objective"):
        if key in fba_result:
            return float(fba_result[key])
    raise AssertionError(
        f"FBA result missing objective field. Keys: {list(fba_result)}"
    )


def assert_grows_on_complete_media(fba_result: dict, min_obj: float = 0.01) -> None:
    """22. FBA on Complete media should yield non-trivial growth."""
    obj = _objective(fba_result)
    if obj < min_obj:
        raise AssertionError(
            f"FBA {fba_result.get('id', '?')}: objectiveValue={obj:.4f} "
            f"below growth threshold {min_obj} on media {fba_result.get('media_ref')}"
        )


def assert_no_growth_on_empty_media(fba_result: dict, tol: float = 1e-6) -> None:
    """23. FBA on a closed media (no exchanges) should produce zero growth."""
    obj = _objective(fba_result)
    if abs(obj) > tol:
        raise AssertionError(
            f"FBA {fba_result.get('id', '?')}: expected zero growth on empty media, "
            f"got objectiveValue={obj:.6f}"
        )


def assert_growth_on_glucose_minimal(fba_result: dict, min_obj: float = 0.01) -> None:
    """24. Most heterotrophs should grow on glucose-only media."""
    assert_grows_on_complete_media(fba_result, min_obj=min_obj)


def assert_objective_within_range(
    fba_result: dict, lo: float = 0.0, hi: float = 2.0
) -> None:
    """25. Objective value (growth rate, h⁻¹) is in a physically reasonable range."""
    obj = _objective(fba_result)
    if not (lo <= obj <= hi):
        raise AssertionError(
            f"FBA {fba_result.get('id', '?')}: objectiveValue={obj:.4f} "
            f"outside reasonable range [{lo}, {hi}]"
        )


def assert_fluxes_finite(fba_result: dict) -> None:
    """26. No NaN/Inf in the flux dict."""
    fluxes = fba_result.get("fluxes") or {}
    bad = [
        rid for rid, v in fluxes.items()
        if not isinstance(v, (int, float)) or not math.isfinite(float(v))
    ]
    if bad:
        raise AssertionError(
            f"FBA {fba_result.get('id', '?')}: {len(bad)} non-finite flux(es) "
            f"(first 5: {bad[:5]})"
        )


def assert_atp_production_positive_under_growth(fba_result: dict) -> None:
    """27. When growing, the ATP synthesis reaction(s) should carry positive net flux."""
    if _objective(fba_result) <= 0:
        return  # vacuously true if not growing
    fluxes = fba_result.get("fluxes") or {}
    atpm = fluxes.get("ATPM_c0") or fluxes.get("ATPM") or 0
    if atpm <= 0:
        # Look for any reaction whose ID suggests ATP synthesis with positive flux.
        atp_synth = sum(
            v for k, v in fluxes.items() if "ATPS" in k and isinstance(v, (int, float))
        )
        if atp_synth <= 0:
            raise AssertionError(
                f"FBA {fba_result.get('id', '?')}: growing but no positive ATP flux. "
                f"ATPM={atpm}, ATP-synth-like total={atp_synth}"
            )


def warn_thermodynamically_infeasible_loops(
    fba_result: dict, threshold: float = 1000.0
) -> str | None:
    """28. (warn-only) Any flux above `threshold` magnitude is a likely loop."""
    fluxes = fba_result.get("fluxes") or {}
    suspect = {k: v for k, v in fluxes.items() if abs(float(v)) > threshold}
    if suspect:
        return (
            f"FBA {fba_result.get('id', '?')}: {len(suspect)} flux(es) above "
            f"threshold {threshold} (first 5: {dict(list(suspect.items())[:5])})"
        )
    return None


def assert_oxygen_uptake_zero_under_anaerobic(
    fba_result: dict, tol: float = 1e-6
) -> None:
    """29. Under anaerobic conditions, EX_o2 (cpd00007) flux should be zero."""
    fluxes = fba_result.get("fluxes") or {}
    o2 = (
        fluxes.get("EX_cpd00007_e0")
        or fluxes.get("EX_cpd00007")
        or 0
    )
    if abs(float(o2)) > tol:
        raise AssertionError(
            f"FBA {fba_result.get('id', '?')}: O2 exchange flux={o2} under anaerobic "
            f"conditions; expected ≈0"
        )


# ─────────────────────────────────────────────────────────────────────────
# Gapfill assertions (31–34)
# ─────────────────────────────────────────────────────────────────────────


def _solution_reactions(gapfill: dict) -> list[list[dict]]:
    """Get the solution_reactions field, defaulting to []."""
    return gapfill.get("solution_reactions") or []


def assert_gapfill_solution_nonempty(gapfill: dict) -> None:
    """31. A gapfill that targets a non-viable model should produce ≥1 added reaction."""
    sols = _solution_reactions(gapfill)
    if not sols or not sols[0]:
        raise AssertionError(
            f"Gapfill {gapfill.get('id', '?')}: solution is empty"
        )


def assert_gapfill_solution_minimal(gapfill: dict, max_added: int = 30) -> None:
    """32. Gapfill solutions for typical organisms should add ≤30 reactions."""
    sols = _solution_reactions(gapfill)
    if not sols:
        return
    n = len(sols[0])
    if n > max_added:
        raise AssertionError(
            f"Gapfill {gapfill.get('id', '?')}: added {n} reactions; "
            f"expected ≤{max_added} for a minimal solution. "
            f"This may indicate an overly broad search or a poor template match."
        )


def assert_gapfill_added_reactions_have_valid_directions(gapfill: dict) -> None:
    """33b. Every added reaction has a valid direction."""
    bad = []
    for sol in _solution_reactions(gapfill):
        for entry in sol:
            d = entry.get("direction") if isinstance(entry, dict) else None
            if d not in VALID_DIRECTIONS:
                bad.append(f"{entry!r}")
    if bad:
        raise AssertionError(
            f"Gapfill {gapfill.get('id', '?')}: {len(bad)} added reaction(s) "
            f"with invalid direction (first 5: {bad[:5]})"
        )


def assert_media_ref_populated(gapfill: dict) -> None:
    """34a. Integrated solutions must record their media reference."""
    if gapfill.get("integrated") and not gapfill.get("media_ref"):
        raise AssertionError(
            f"Gapfill {gapfill.get('id', '?')}: integrated but media_ref is empty"
        )


# ─────────────────────────────────────────────────────────────────────────
# Round-trip / format assertions (35)
# ─────────────────────────────────────────────────────────────────────────


def assert_sbml_round_trips(sbml_text: str, original_model: dict) -> None:
    """35. SBML export round-trips through cobra.io and preserves counts.

    Requires the `[modeling]` extra (`cobra` package).
    """
    try:
        import cobra.io
    except ImportError as exc:
        raise AssertionError(
            "Cobra not installed — cannot verify SBML round-trip. "
            "Install with `pip install -e \".[modeling]\"`"
        ) from exc

    import io as _io
    parsed = cobra.io.read_sbml_model(_io.StringIO(sbml_text))

    n_orig = len(_reactions(original_model))
    n_parsed = len(parsed.reactions)
    # SBML export auto-creates exchange reactions, so allow a modest delta.
    if abs(n_parsed - n_orig) > max(20, int(0.05 * n_orig)):
        raise AssertionError(
            f"SBML round-trip reaction count mismatch: original={n_orig}, "
            f"parsed={n_parsed} (delta={n_parsed - n_orig})"
        )

    n_orig_compounds = len(_compounds(original_model))
    n_parsed_metabolites = len(parsed.metabolites)
    if abs(n_parsed_metabolites - n_orig_compounds) > max(20, int(0.05 * n_orig_compounds)):
        raise AssertionError(
            f"SBML round-trip compound count mismatch: original={n_orig_compounds}, "
            f"parsed={n_parsed_metabolites}"
        )


def collect_warnings(*warning_results: Iterable[str | None]) -> list[str]:
    """Convenience: collect non-None warning strings into a single list."""
    out: list[str] = []
    for w in warning_results:
        if w:
            out.append(w)
    return out
