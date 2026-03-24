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


def _safe_int(val, default=0):
    """Safely convert a value to int, returning default on failure."""
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


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
                # Also include plain folders — they may contain model data
                # saved without explicit modelfolder metadata.
                obj_type = obj_meta[1]
                is_model = (
                    obj_type in ("modelfolder", "model")
                    or (obj_type == "folder" and "num_reactions" in user_meta)
                    or obj_type == "folder"  # include all folders under modelseed/
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
                        "fba_count": _safe_int(user_meta.get("fba_count", 0)),
                        "integrated_gapfills": _safe_int(user_meta.get("integrated_gapfills", 0)),
                        "unintegrated_gapfills": _safe_int(
                            user_meta.get("unintegrated_gapfills", 0)
                        ),
                        "gene_associated_reactions": _safe_int(
                            user_meta.get("gene_associated_reactions", 0)
                        ),
                        "gapfilled_reactions": _safe_int(
                            user_meta.get("gapfilled_reactions", 0)
                        ),
                        "num_genes": _safe_int(user_meta.get("num_genes", 0)),
                        "num_compounds": _safe_int(user_meta.get("num_compounds", 0)),
                        "num_reactions": _safe_int(user_meta.get("num_reactions", 0)),
                        "num_biomasses": _safe_int(user_meta.get("num_biomasses", 0)),
                        "num_biomass_compounds": _safe_int(
                            user_meta.get("num_biomass_compounds", 0)
                        ),
                        "num_compartments": _safe_int(user_meta.get("num_compartments", 0)),
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
        Also repairs folder metadata if missing (one-time fix for models
        saved without stats).
        """
        model_obj = self.get_model_raw(model_ref)
        formatted = self._format_model_data(model_ref, model_obj)

        # Auto-repair: update folder metadata if it's missing stats
        try:
            self._ensure_folder_metadata(model_ref, formatted)
        except Exception:
            pass  # non-critical, don't block model view

        return formatted

    def _ensure_folder_metadata(self, model_ref: str, formatted: dict):
        """Update the modelfolder metadata with model stats if missing."""
        # Check current folder metadata
        folder_result = self.ws.ls({"paths": [model_ref]})
        if not folder_result:
            return

        # Get parent folder metadata via ls on parent
        parent = model_ref.rsplit("/", 1)[0] + "/"
        parent_result = self.ws.ls({"paths": [parent]})
        if not parent_result or parent not in parent_result:
            return

        folder_name = model_ref.rstrip("/").split("/")[-1]
        for entry in parent_result[parent]:
            if entry[0] == folder_name:
                user_meta = entry[7] if isinstance(entry[7], dict) else {}
                if user_meta.get("num_reactions"):
                    return  # metadata already present
                break

        # Metadata missing — update it
        meta = {
            "num_reactions": str(len(formatted.get("reactions", []))),
            "num_compounds": str(len(formatted.get("compounds", []))),
            "num_genes": str(len(formatted.get("genes", []))),
            "num_compartments": str(len(formatted.get("compartments", []))),
            "num_biomasses": str(len(formatted.get("biomasses", []))),
            "name": folder_name,
            "source": "ModelSEED",
        }
        self.ws.update_metadata({
            "objects": [[model_ref, meta]],
        })

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

        Gapfill solution data can be stored in two formats:
        1. Legacy KBase format: gapfillingSolutions array on each gapfilling entry
        2. ModelSEEDpy format: reaction-level gapfill_data on modelreactions,
           keyed by gapfill ID (created by MSModelUtil.create_kb_gapfilling_data)
        """
        model_path = f"{model_ref}/model"
        result = self.ws.get({"objects": [model_path]})

        model_obj = self._parse_ws_data(result)

        # Build index: gapfill_id -> [{reaction, direction, compartment}]
        # from modelreactions gapfill_data (ModelSEEDpy format)
        gf_rxn_index = {}
        for rxn in model_obj.get("modelreactions", []):
            gf_data = rxn.get("gapfill_data", {})
            for gfid, sol_data in gf_data.items():
                if gfid not in gf_rxn_index:
                    gf_rxn_index[gfid] = []
                # sol_data is {"0": [direction, integrated_flag, features]}
                for sol_idx, sol_info in sol_data.items():
                    direction = sol_info[0] if isinstance(sol_info, list) else "="
                    # Extract compartment from reaction ID (e.g., rxn00001_c0 -> c0)
                    rxn_id = rxn.get("id", "")
                    compartment = ""
                    if "_" in rxn_id:
                        compartment = rxn_id.rsplit("_", 1)[-1]
                    gf_rxn_index[gfid].append({
                        "reaction": rxn_id,
                        "direction": direction,
                        "compartment": compartment,
                    })

        gapfillings = []
        for gf in model_obj.get("gapfillings", []):
            gfid = gf.get("id", "")

            # Try legacy format first (gapfillingSolutions array)
            solutions = []
            for sol in gf.get("gapfillingSolutions", gf.get("solutions", [])):
                sol_rxns = []
                for rxn in sol.get("gapfillingSolutionReactions", sol.get("reactions", [])):
                    sol_rxns.append({
                        "reaction": rxn.get("reaction_ref", rxn.get("reaction", "")),
                        "direction": rxn.get("direction", "="),
                        "compartment": rxn.get("compartment_ref", rxn.get("compartment", "")),
                    })
                solutions.append(sol_rxns)

            # Fall back to modelreactions gapfill_data (ModelSEEDpy format)
            if not solutions and gfid in gf_rxn_index:
                solutions = [gf_rxn_index[gfid]]

            gapfillings.append({
                "rundate": gf.get("rundate", ""),
                "id": gfid,
                "ref": gf.get("ref", f"{model_ref}/gapfill.{gfid}"),
                "media_ref": gf.get("media_ref", ""),
                "integrated": gf.get("integrated", False),
                "integrated_solution": gf.get("integrated_solution", 0),
                "solution_reactions": solutions,
            })

        return gapfillings

    def manage_gapfill_solutions(
        self, model_ref: str, commands: dict[str, str], selected_solutions: dict | None = None
    ) -> dict:
        """Manage gapfilling solutions (integrate/unintegrate/delete).

        Commands: {gapfill_id: "I"|"U"|"D"} (integrate/unintegrate/delete).
        Modifies the model in-place in the workspace and returns updated gapfill data.
        """
        if selected_solutions is None:
            selected_solutions = {}

        # Read the model object
        model_obj = self.get_model_raw(model_ref)
        gapfillings = model_obj.get("gapfillings", [])
        model_reactions = model_obj.get("modelreactions", [])

        results = {}

        # Partition commands
        for gf_id, cmd in commands.items():
            cmd = cmd.upper()
            gf_entry = self._find_gapfill(gapfillings, gf_id)
            if not gf_entry:
                results[gf_id] = {"error": f"Gapfill {gf_id} not found"}
                continue

            if cmd == "D":
                # Delete: unintegrate first if needed, then remove
                if gf_entry.get("integrated"):
                    self._unintegrate_gapfill(gf_entry, model_reactions)
                gapfillings.remove(gf_entry)
                # Delete workspace gapfill objects
                self._delete_gapfill_objects(model_ref, gf_id)
                results[gf_id] = {"id": gf_id, "status": "deleted"}

            elif cmd == "I":
                # Integrate: add gapfill reactions to model
                sol_idx = selected_solutions.get(gf_id, 0)
                self._integrate_gapfill(gf_entry, model_reactions, sol_idx)
                results[gf_id] = self._format_gapfill_entry(gf_entry, model_ref)

            elif cmd == "U":
                # Unintegrate: remove gapfill reactions from model
                self._unintegrate_gapfill(gf_entry, model_reactions)
                results[gf_id] = self._format_gapfill_entry(gf_entry, model_ref)

        # Only save if no errors occurred (atomic operation)
        errors = {k: v for k, v in results.items() if "error" in v}
        if errors:
            raise ValueError(f"Gapfill management errors: {errors}")

        model_obj["gapfillings"] = gapfillings
        model_obj["modelreactions"] = model_reactions
        self._save_model(model_ref, model_obj)

        return results

    def _find_gapfill(self, gapfillings: list, gf_id: str) -> dict | None:
        """Find a gapfill entry by ID."""
        for gf in gapfillings:
            if gf.get("id") == gf_id or gf.get("gapfill_id") == gf_id:
                return gf
        return None

    def _integrate_gapfill(
        self, gf_entry: dict, model_reactions: list, solution_idx: int = 0
    ) -> None:
        """Integrate a gapfill solution into the model.

        Adds reactions from the selected solution to model_reactions and
        marks the gapfill as integrated.
        """
        solutions = gf_entry.get("gapfillingSolutions", gf_entry.get("solutions", []))
        if solution_idx >= len(solutions):
            solution_idx = 0

        if not solutions:
            gf_entry["integrated"] = True
            gf_entry["integrated_solution"] = solution_idx
            return

        solution = solutions[solution_idx]
        gf_id = gf_entry.get("id", "")

        # Build set of existing reaction IDs for quick lookup
        existing_rxn_ids = {rxn.get("id", "") for rxn in model_reactions}

        for sol_rxn in solution.get("gapfillingSolutionReactions", solution.get("reactions", [])):
            rxn_ref = sol_rxn.get("reaction_ref", sol_rxn.get("reaction", ""))
            rxn_id = rxn_ref.split("/")[-1] if "/" in rxn_ref else rxn_ref
            direction = sol_rxn.get("direction", ">")
            compartment_ref = sol_rxn.get("compartment_ref", sol_rxn.get("compartment", ""))
            compartment = compartment_ref.split("/")[-1] if "/" in compartment_ref else compartment_ref

            # Build full reaction ID (e.g., rxn00001_c0)
            full_rxn_id = f"{rxn_id}_{compartment}" if compartment else rxn_id

            if full_rxn_id in existing_rxn_ids:
                # Reaction exists — widen direction if needed
                for rxn in model_reactions:
                    if rxn.get("id") == full_rxn_id:
                        if rxn.get("direction") != "=" and rxn.get("direction") != direction:
                            rxn["direction"] = "="
                        # Track gapfill source
                        gf_data = rxn.setdefault("gapfill_data", {})
                        gf_data[gf_id] = {str(solution_idx): [direction, 1, []]}
                        break
            else:
                # New reaction — add to model
                new_rxn = {
                    "id": full_rxn_id,
                    "reaction_ref": rxn_ref,
                    "direction": direction,
                    "modelcompartment_ref": f"~/modelcompartments/id/{compartment}",
                    "modelReactionReagents": sol_rxn.get("modelReactionReagents", []),
                    "modelReactionProteins": [],
                    "gapfill_data": {gf_id: {str(solution_idx): [direction, 1, []]}},
                }
                model_reactions.append(new_rxn)
                existing_rxn_ids.add(full_rxn_id)

        gf_entry["integrated"] = True
        gf_entry["integrated_solution"] = solution_idx

    def _unintegrate_gapfill(self, gf_entry: dict, model_reactions: list) -> None:
        """Unintegrate a gapfill solution from the model.

        Removes or narrows reactions that were added by this gapfill,
        unless another integrated gapfill also covers them.
        """
        if not gf_entry.get("integrated"):
            return

        gf_id = gf_entry.get("id", "")

        rxns_to_remove = []
        for rxn in model_reactions:
            gf_data = rxn.get("gapfill_data", {})
            if gf_id not in gf_data:
                continue

            # Get the direction this gapfill added
            gf_info = gf_data[gf_id]
            gf_direction = None
            if isinstance(gf_info, dict):
                for sol_key, sol_val in gf_info.items():
                    if isinstance(sol_val, list) and len(sol_val) > 0:
                        gf_direction = sol_val[0]
                    elif isinstance(sol_val, str):
                        gf_direction = sol_val.split(":")[1] if ":" in sol_val else sol_val
            elif isinstance(gf_info, str):
                parts = gf_info.split(":")
                gf_direction = parts[1] if len(parts) > 1 else ">"

            # Remove this gapfill's entry
            del gf_data[gf_id]

            # Check if any other integrated gapfill covers the same direction
            other_covers = False
            for other_id, other_info in gf_data.items():
                if isinstance(other_info, dict):
                    for sol_val in other_info.values():
                        if isinstance(sol_val, list) and len(sol_val) > 1 and sol_val[1]:
                            other_covers = True
                            break

            if not other_covers and gf_direction:
                current_dir = rxn.get("direction", "=")
                if current_dir == gf_direction:
                    # This gapfill was the sole source — remove the reaction
                    rxns_to_remove.append(rxn)
                elif current_dir == "=" and gf_direction == ">":
                    rxn["direction"] = "<"
                elif current_dir == "=" and gf_direction == "<":
                    rxn["direction"] = ">"

        for rxn in rxns_to_remove:
            model_reactions.remove(rxn)

        gf_entry["integrated"] = False
        gf_entry["integrated_solution"] = -1

    def _delete_gapfill_objects(self, model_ref: str, gf_id: str) -> None:
        """Delete gapfill workspace objects."""
        paths = [
            f"{model_ref}/gapfilling/{gf_id}",
            f"{model_ref}/gapfilling/{gf_id}.fluxtbl",
            f"{model_ref}/gapfilling/{gf_id}.jobresult",
            f"{model_ref}/gapfilling/{gf_id}.gftbl",
        ]
        try:
            self.ws.delete({"objects": paths})
        except Exception:
            pass  # Non-critical if workspace objects don't exist

    def _save_model(self, model_ref: str, model_obj: dict) -> None:
        """Save modified model back to workspace."""
        model_path = f"{model_ref}/model"
        self.ws.create({
            "objects": [[model_path, "model", {}, json.dumps(model_obj)]],
            "overwrite": True,
        })

    def _format_gapfill_entry(self, gf_entry: dict, model_ref: str) -> dict:
        """Format a gapfill entry for API response."""
        solutions = []
        for sol in gf_entry.get("gapfillingSolutions", gf_entry.get("solutions", [])):
            sol_rxns = []
            for rxn in sol.get("gapfillingSolutionReactions", sol.get("reactions", [])):
                sol_rxns.append({
                    "reaction": rxn.get("reaction_ref", rxn.get("reaction", "")),
                    "direction": rxn.get("direction", "="),
                    "compartment": rxn.get("compartment_ref", rxn.get("compartment", "")),
                })
            solutions.append(sol_rxns)

        return {
            "rundate": gf_entry.get("rundate", ""),
            "id": gf_entry.get("id", ""),
            "ref": gf_entry.get("ref", f"{model_ref}/gapfilling/{gf_entry.get('id', '')}"),
            "media_ref": gf_entry.get("media_ref", ""),
            "integrated": gf_entry.get("integrated", False),
            "integrated_solution": gf_entry.get("integrated_solution", 0),
            "solution_reactions": solutions,
        }

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
