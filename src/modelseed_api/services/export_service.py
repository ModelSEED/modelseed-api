"""Model export service - SBML and CobraPy JSON export.

Converts workspace model objects to CobraPy Model objects,
then uses cobra.io for standard format export.
"""

from __future__ import annotations

import io
import json
import tempfile
from typing import Any

import cobra


def workspace_model_to_cobra(model_obj: dict, model_id: str = "model") -> cobra.Model:
    """Convert a raw workspace model object to a CobraPy Model.

    Args:
        model_obj: Raw model dict from workspace (with modelreactions,
                   modelcompounds, modelcompartments, biomasses)
        model_id: ID for the cobra model
    """
    model = cobra.Model(model_id)

    # Add compartments
    for cpt in model_obj.get("modelcompartments", []):
        cpt_id = cpt.get("id", "")
        model.compartments[cpt_id] = cpt.get("label", cpt.get("name", cpt_id))

    # Add metabolites (compounds)
    metabolites = {}
    for cpd in model_obj.get("modelcompounds", []):
        cpd_id = cpd.get("id", "")
        # Parse compartment from ID (e.g., "cpd00001_c0" -> compartment "c0")
        parts = cpd_id.rsplit("_", 1)
        compartment = parts[1] if len(parts) > 1 else "c0"

        met = cobra.Metabolite(
            id=cpd_id,
            name=cpd.get("name", ""),
            formula=cpd.get("formula"),
            charge=cpd.get("charge", 0),
            compartment=compartment,
        )
        metabolites[cpd_id] = met
        model.add_metabolites([met])

    # Add reactions
    for rxn_data in model_obj.get("modelreactions", []):
        rxn_id = rxn_data.get("id", "")
        rxn = cobra.Reaction(
            id=rxn_id,
            name=rxn_data.get("name", ""),
        )

        # Set bounds from direction
        direction = rxn_data.get("direction", "=")
        if direction == ">":
            rxn.lower_bound = 0
            rxn.upper_bound = 1000
        elif direction == "<":
            rxn.lower_bound = -1000
            rxn.upper_bound = 0
        else:  # "=" or reversible
            rxn.lower_bound = -1000
            rxn.upper_bound = 1000

        # Add metabolites (stoichiometry)
        stoich = {}
        for reagent in rxn_data.get("modelReactionReagents", []):
            cpd_ref = reagent.get("modelcompound_ref", "")
            cpd_id = cpd_ref.split("/")[-1] if "/" in cpd_ref else cpd_ref
            coeff = reagent.get("coefficient", 0)
            if cpd_id in metabolites:
                stoich[metabolites[cpd_id]] = coeff

        if stoich:
            rxn.add_metabolites(stoich)

        # Set GPR from protein subunits
        gpr_parts = []
        for prot in rxn_data.get("modelReactionProteins", []):
            subunit_genes = []
            for subunit in prot.get("modelReactionProteinSubunits", []):
                for fref in subunit.get("feature_refs", []):
                    gene_id = fref.split("/")[-1] if "/" in fref else fref
                    if gene_id:
                        subunit_genes.append(gene_id)
            if subunit_genes:
                gpr_parts.append(" and ".join(subunit_genes))
        if gpr_parts:
            rxn.gene_reaction_rule = " or ".join(f"({g})" for g in gpr_parts) if len(gpr_parts) > 1 else gpr_parts[0]

        model.add_reactions([rxn])

    # Add biomass reactions
    for bio in model_obj.get("biomasses", []):
        bio_id = bio.get("id", "bio1")
        bio_rxn = cobra.Reaction(id=bio_id, name=bio.get("name", "Biomass"))
        bio_rxn.lower_bound = 0
        bio_rxn.upper_bound = 1000

        stoich = {}
        for bc in bio.get("biomasscompounds", []):
            cpd_ref = bc.get("modelcompound_ref", "")
            cpd_id = cpd_ref.split("/")[-1] if "/" in cpd_ref else cpd_ref
            coeff = bc.get("coefficient", 0)
            if cpd_id in metabolites:
                stoich[metabolites[cpd_id]] = coeff

        if stoich:
            bio_rxn.add_metabolites(stoich)
        model.add_reactions([bio_rxn])

    # Set objective to first biomass
    if model_obj.get("biomasses"):
        bio_id = model_obj["biomasses"][0].get("id", "bio1")
        if bio_id in model.reactions:
            model.objective = bio_id

    return model


def export_sbml(model_obj: dict, model_id: str = "model") -> str:
    """Export model as SBML XML string."""
    cobra_model = workspace_model_to_cobra(model_obj, model_id)
    with tempfile.NamedTemporaryFile(suffix=".xml", mode="w", delete=True) as f:
        cobra.io.write_sbml_model(cobra_model, f.name)
        with open(f.name) as rf:
            return rf.read()


def export_cobra_json(model_obj: dict, model_id: str = "model") -> dict:
    """Export model as CobraPy JSON dict."""
    cobra_model = workspace_model_to_cobra(model_obj, model_id)
    return cobra.io.model_to_dict(cobra_model)
