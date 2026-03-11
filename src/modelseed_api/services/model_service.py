"""Model service - handles model CRUD, gapfill listing, FBA listing.

All operations are synchronous. Long-running operations (model building,
gapfilling, FBA) are dispatched to external job scripts via the job system.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import requests

from modelseed_api.schemas.models import (
    FBAData,
    GapfillData,
    ModelData,
    ModelStats,
)
from modelseed_api.services.workspace_service import WorkspaceService


class ModelService:
    """Service for model-related workspace operations.

    Wraps workspace calls to provide model-specific CRUD and query operations.
    This replicates the synchronous parts of ProbModelSEEDHelper.pm.
    """

    def __init__(self, token: str):
        self.ws = WorkspaceService(token)
        self.token = token

    def list_models(self, path: Optional[str] = None, username: str = "") -> list[dict]:
        """List all models for a user.

        Replicates ProbModelSEED.list_models.
        Default path: /{username}/modelseed/
        Returns ModelStats-shaped dicts from workspace modelfolder metadata.
        """
        if not path:
            path = f"/{username}/modelseed/"

        result = self.ws.ls({"paths": [path]})

        models = []
        if result and path in result:
            for obj_meta in result[path]:
                # obj_meta is workspace tuple:
                # [name, type, path, creation_time, id, owner, size, user_meta, auto_meta, ...]
                if len(obj_meta) < 8:
                    continue

                user_meta = obj_meta[7] if isinstance(obj_meta[7], dict) else {}

                # Models appear as folders or model objects with model metadata.
                # A model folder has num_reactions in user_meta; a bare "model" type
                # object may also appear at the top level.
                obj_type = obj_meta[1]
                is_model = (
                    obj_type in ("modelfolder", "model")
                    or (obj_type == "folder" and "num_reactions" in user_meta)
                )
                if not is_model:
                    continue
                models.append(
                    {
                        "id": user_meta.get("id", obj_meta[0]),
                        "ref": obj_meta[2] + obj_meta[0],
                        "name": user_meta.get("name", obj_meta[0]),
                        "source": user_meta.get("source"),
                        "source_id": user_meta.get("source_id"),
                        "type": user_meta.get("type"),
                        "genome_ref": user_meta.get("genome_ref"),
                        "template_ref": user_meta.get("template_ref"),
                        "rundate": user_meta.get("rundate", obj_meta[3]),
                        "fba_count": int(user_meta.get("fba_count", 0)),
                        "integrated_gapfills": int(user_meta.get("integrated_gapfills", 0)),
                        "unintegrated_gapfills": int(
                            user_meta.get("unintegrated_gapfills", 0)
                        ),
                        "gene_associated_reactions": int(
                            user_meta.get("gene_associated_reactions", 0)
                        ),
                        "gapfilled_reactions": int(
                            user_meta.get("gapfilled_reactions", 0)
                        ),
                        "num_genes": int(user_meta.get("num_genes", 0)),
                        "num_compounds": int(user_meta.get("num_compounds", 0)),
                        "num_reactions": int(user_meta.get("num_reactions", 0)),
                        "num_biomasses": int(user_meta.get("num_biomasses", 0)),
                        "num_biomass_compounds": int(
                            user_meta.get("num_biomass_compounds", 0)
                        ),
                        "num_compartments": int(user_meta.get("num_compartments", 0)),
                        "status": user_meta.get("status"),
                        "expression_data": user_meta.get("expression_data", []),
                    }
                )

        return models

    def _parse_ws_data(self, result: list) -> dict:
        """Parse workspace get result, fetching from Shock if needed.

        The workspace returns [[meta_tuple, data], ...]. data is either:
        - Inline JSON string (small objects)
        - A Shock URL (large objects stored in file storage)
        """
        if not result or len(result) == 0:
            return {}

        raw_data = result[0][1] if len(result[0]) > 1 else "{}"

        if isinstance(raw_data, dict):
            return raw_data

        if isinstance(raw_data, str):
            # Check if it's a Shock URL rather than inline JSON
            if raw_data.startswith("http") and "shock" in raw_data:
                return self._fetch_from_shock(raw_data)
            return json.loads(raw_data)

        return {}

    def _fetch_from_shock(self, shock_url: str) -> dict:
        """Download object data from Shock file storage."""
        # Shock download URL: {node_url}?download
        download_url = shock_url.rstrip("/") + "?download"
        resp = requests.get(
            download_url,
            headers={"Authorization": f"OAuth {self.token}"},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()

    def get_model_raw(self, model_ref: str) -> dict:
        """Get the raw workspace model object (for export/conversion)."""
        model_path = f"{model_ref}/model"
        result = self.ws.get({"objects": [model_path]})
        if not result or len(result) == 0:
            raise ValueError(f"Model not found: {model_ref}")
        return self._parse_ws_data(result)

    def get_model(self, model_ref: str) -> dict:
        """Get full model data (reactions, compounds, genes, compartments, biomasses).

        Replicates ProbModelSEED.get_model.
        Retrieves the model object from {model_ref}/model in the workspace.
        """
        model_obj = self.get_model_raw(model_ref)
        return self._format_model_data(model_ref, model_obj)

    def _format_model_data(self, ref: str, model_obj: dict) -> dict:
        """Format raw model object into ModelData shape."""
        reactions = []
        for rxn in model_obj.get("modelreactions", []):
            reagents = rxn.get("modelReactionReagents", [])
            stoich = []
            for r in reagents:
                stoich.append(
                    [
                        r.get("coefficient", 0),
                        r.get("modelcompound_ref", "").split("/")[-1],
                        r.get("compartment", ""),
                        r.get("compartmentIndex", 0),
                        r.get("name", ""),
                    ]
                )
            # Extract gene IDs from nested protein/subunit/feature_refs structure
            rxn_genes = []
            for prot in rxn.get("modelReactionProteins", []):
                for subunit in prot.get("modelReactionProteinSubunits", []):
                    for fref in subunit.get("feature_refs", []):
                        # feature_ref looks like ".../genome||/features/id/fig|..."
                        gene_id = fref.split("/")[-1] if "/" in fref else fref
                        if gene_id:
                            rxn_genes.append(gene_id)

            reactions.append(
                {
                    "id": rxn.get("id", ""),
                    "name": rxn.get("name", ""),
                    "stoichiometry": stoich,
                    "direction": rxn.get("direction", "="),
                    "gpr": rxn.get("gpr", ""),
                    "genes": rxn_genes,
                }
            )

        compounds = []
        for cpd in model_obj.get("modelcompounds", []):
            compounds.append(
                {
                    "id": cpd.get("id", ""),
                    "name": cpd.get("name", ""),
                    "formula": cpd.get("formula"),
                    "charge": cpd.get("charge"),
                }
            )

        genes = []
        # Build gene-to-reaction map from nested protein/subunit/feature structure
        gene_rxns: dict[str, list[str]] = {}
        for rxn in model_obj.get("modelreactions", []):
            for prot in rxn.get("modelReactionProteins", []):
                for subunit in prot.get("modelReactionProteinSubunits", []):
                    for fref in subunit.get("feature_refs", []):
                        gene_id = fref.split("/")[-1] if "/" in fref else fref
                        if gene_id:
                            gene_rxns.setdefault(gene_id, []).append(rxn.get("id", ""))
        for gene_id, rxn_ids in gene_rxns.items():
            genes.append({"id": gene_id, "reactions": rxn_ids})

        compartments = []
        for cpt in model_obj.get("modelcompartments", []):
            compartments.append(
                {
                    "id": cpt.get("id", ""),
                    "name": cpt.get("label", cpt.get("name", "")),
                    "pH": cpt.get("pH"),
                    "potential": cpt.get("potential"),
                }
            )

        biomasses = []
        for bio in model_obj.get("biomasses", []):
            bio_cpds = []
            for bc in bio.get("biomasscompounds", []):
                bio_cpds.append(
                    [
                        bc.get("modelcompound_ref", "").split("/")[-1],
                        bc.get("coefficient", 0),
                        bc.get("compartment", ""),
                    ]
                )
            biomasses.append(
                {
                    "id": bio.get("id", ""),
                    "compounds": bio_cpds,
                }
            )

        return {
            "ref": ref,
            "reactions": reactions,
            "compounds": compounds,
            "genes": genes,
            "compartments": compartments,
            "biomasses": biomasses,
        }

    def delete_model(self, model_ref: str) -> Any:
        """Delete a model folder from the workspace."""
        return self.ws.delete(
            {"objects": [model_ref], "deleteDirectories": True, "force": True}
        )

    def copy_model(self, source: str, destination: str, **kwargs) -> Any:
        """Copy a model to a new location."""
        return self.ws.copy(
            {"objects": [[source, destination]], "recursive": True}
        )

    def list_gapfill_solutions(self, model_ref: str) -> list[dict]:
        """List gapfilling solutions for a model.

        Gapfill data is stored as metadata on the model folder or
        within the model object itself.
        """
        model_path = f"{model_ref}/model"
        result = self.ws.get({"objects": [model_path]})

        model_obj = self._parse_ws_data(result)

        gapfillings = []
        for gf in model_obj.get("gapfillings", []):
            solutions = []
            for sol in gf.get("gapfillingSolutions", gf.get("solutions", [])):
                sol_rxns = []
                for rxn in sol.get("gapfillingSolutionReactions", sol.get("reactions", [])):
                    sol_rxns.append(
                        {
                            "reaction": rxn.get("reaction_ref", rxn.get("reaction", "")),
                            "direction": rxn.get("direction", "="),
                            "compartment": rxn.get("compartment_ref", rxn.get("compartment", "")),
                        }
                    )
                solutions.append(sol_rxns)

            gapfillings.append(
                {
                    "rundate": gf.get("rundate", ""),
                    "id": gf.get("id", ""),
                    "ref": gf.get("ref", f"{model_ref}/gapfill.{gf.get('id', '')}"),
                    "media_ref": gf.get("media_ref", ""),
                    "integrated": gf.get("integrated", False),
                    "integrated_solution": gf.get("integrated_solution", 0),
                    "solution_reactions": solutions,
                }
            )

        return gapfillings

    def manage_gapfill_solutions(
        self, model_ref: str, commands: dict[str, str], selected_solutions: dict | None = None
    ) -> dict:
        """Manage gapfilling solutions (integrate/unintegrate/delete).

        This is a synchronous operation that modifies the model in the workspace.
        """
        # TODO: Implement gapfill management by modifying the model object
        # This requires reading the model, modifying gapfill state, and saving back
        raise NotImplementedError("Gapfill management not yet implemented")

    def list_fba_studies(self, model_ref: str) -> list[dict]:
        """List FBA studies associated with a model."""
        model_path = f"{model_ref}/model"
        result = self.ws.get({"objects": [model_path]})

        model_obj = self._parse_ws_data(result)

        fbas = []
        for fba in model_obj.get("fbaFormulations", model_obj.get("fba_studies", [])):
            fbas.append(
                {
                    "rundate": fba.get("rundate", ""),
                    "id": fba.get("id", ""),
                    "ref": fba.get("ref", f"{model_ref}/fba.{fba.get('id', '')}"),
                    "objective": fba.get("objectiveValue", fba.get("objective", 0.0)),
                    "media_ref": fba.get("media_ref", ""),
                    "objective_function": fba.get("objectiveFunction", fba.get("objective_function", "")),
                }
            )

        return fbas
