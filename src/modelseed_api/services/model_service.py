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
from modelseed_api.services.storage_factory import get_storage_service


def _safe_int(val, default=0):
    """Safely convert a value to int, returning default on failure."""
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _build_equation(reagents: list[dict], cpd_names: dict[str, str], direction: str) -> str:
    """Synthesize a human-readable equation string from modelReactionReagents."""
    lhs = []
    rhs = []
    for r in reagents:
        coeff = r.get("coefficient", 0)
        cpd_id = r.get("modelcompound_ref", "").split("/")[-1]
        name = cpd_names.get(cpd_id, cpd_id)
        abs_coeff = abs(coeff)
        term = f"({abs_coeff}) {name}" if abs_coeff != 1 else name
        if coeff < 0:
            lhs.append(term)
        elif coeff > 0:
            rhs.append(term)
    arrow = {"<": "<=", ">": "=>", "=": "<=>"}.get(direction, "<=>")
    return f"{' + '.join(lhs)} {arrow} {' + '.join(rhs)}"


class ModelService:
    """Service for model-related workspace operations.

    Wraps workspace calls to provide model-specific CRUD and query operations.
    This replicates the synchronous parts of ProbModelSEEDHelper.pm.
    """

    def __init__(self, token: str):
        self.ws = get_storage_service(token)
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
                # Skip entries with empty path (corrupt/legacy workspace data)
                if not obj_meta[2]:
                    continue
                # Deduplicate: workspace can return the same object under
                # different names (e.g. ".name" and "name") or types
                model_id = user_meta.get("id", obj_meta[0])
                if any(m["id"] == model_id for m in models):
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
                        "organism_name": user_meta.get("organism_name"),
                        "taxonomy": user_meta.get("taxonomy"),
                        "domain": user_meta.get("domain"),
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
        Also merges folder metadata (organism, taxonomy, etc.) and repairs
        missing stats (one-time fix for models saved without stats).
        """
        model_obj = self.get_model_raw(model_ref)
        formatted = self._format_model_data(model_ref, model_obj)

        # Fetch folder metadata once for both merging and repair
        try:
            user_meta = self._get_folder_metadata(model_ref)
            if user_meta is not None:
                # Merge organism/taxonomy info into response
                formatted["id"] = user_meta.get("id")
                formatted["name"] = user_meta.get("name")
                formatted["organism_name"] = user_meta.get("organism_name")
                formatted["taxonomy"] = user_meta.get("taxonomy")
                formatted["domain"] = user_meta.get("domain")
                formatted["type"] = user_meta.get("type")
                formatted["source"] = user_meta.get("source")
                formatted["genome_ref"] = user_meta.get("genome_ref")

                # Auto-repair: update folder metadata if it's missing stats or organism
                if not user_meta.get("num_reactions") or not user_meta.get("organism_name"):
                    self._repair_folder_metadata(model_ref, formatted, model_obj)
        except Exception:
            pass  # non-critical, don't block model view

        return formatted

    def _get_folder_metadata(self, model_ref: str) -> dict | None:
        """Fetch user metadata dict for a model folder."""
        parent = model_ref.rsplit("/", 1)[0] + "/"
        folder_name = model_ref.rstrip("/").split("/")[-1]
        parent_result = self.ws.ls({"paths": [parent]})
        if not parent_result or parent not in parent_result:
            return None
        for entry in parent_result[parent]:
            if entry[0] == folder_name:
                return entry[7] if isinstance(entry[7], dict) else {}
        return None

    def _repair_folder_metadata(
        self, model_ref: str, formatted: dict, model_obj: dict | None = None
    ):
        """Update the modelfolder metadata with model stats and organism info if missing."""
        folder_name = model_ref.rstrip("/").split("/")[-1]
        meta = {
            "num_reactions": str(len(formatted.get("reactions", []))),
            "num_compounds": str(len(formatted.get("compounds", []))),
            "num_genes": str(len(formatted.get("genes", []))),
            "num_compartments": str(len(formatted.get("compartments", []))),
            "num_biomasses": str(len(formatted.get("biomasses", []))),
            "name": folder_name,
            "source": "ModelSEED",
        }

        # Also repair organism info from the model object if missing
        if model_obj and (not formatted.get("organism_name") or not formatted.get("genome_ref")):
            genome_ref = model_obj.get("genome_ref", "")
            if genome_ref and not formatted.get("genome_ref"):
                meta["genome_ref"] = genome_ref
                formatted["genome_ref"] = genome_ref
            if genome_ref and not formatted.get("organism_name"):
                # Extract organism name from genome_ref path (last segment)
                genome_name = genome_ref.rstrip("/").split("/")[-1]
                meta["organism_name"] = genome_name
                formatted["organism_name"] = genome_name

        self.ws.update_metadata({
            "objects": [[model_ref, meta]],
        })

    def _format_model_data(self, ref: str, model_obj: dict) -> dict:
        """Format raw model object into ModelData shape."""
        # Build compound ID→name lookup for equation synthesis and biomass
        cpd_name_map: dict[str, str] = {}
        for cpd in model_obj.get("modelcompounds", []):
            cpd_name_map[cpd.get("id", "")] = cpd.get("name", cpd.get("id", ""))

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

            # Synthesize equation string from reagents
            equation = _build_equation(reagents, cpd_name_map, rxn.get("direction", "="))

            # Build GPR string from nested protein/subunit/feature_refs
            rxn_genes = []
            gpr_parts = []
            for prot in rxn.get("modelReactionProteins", []):
                subunit_parts = []
                for subunit in prot.get("modelReactionProteinSubunits", []):
                    gene_ids = []
                    for fref in subunit.get("feature_refs", []):
                        gene_id = fref.split("/")[-1] if "/" in fref else fref
                        if gene_id:
                            rxn_genes.append(gene_id)
                            gene_ids.append(gene_id)
                    if gene_ids:
                        subunit_parts.append(" or ".join(gene_ids) if len(gene_ids) > 1 else gene_ids[0])
                if subunit_parts:
                    gpr_parts.append(
                        "(" + " and ".join(subunit_parts) + ")" if len(subunit_parts) > 1 else subunit_parts[0]
                    )
            gpr = " or ".join(gpr_parts) if len(gpr_parts) > 1 else (gpr_parts[0] if gpr_parts else "")

            reactions.append(
                {
                    "id": rxn.get("id", ""),
                    "name": rxn.get("name", ""),
                    "stoichiometry": stoich,
                    "direction": rxn.get("direction", "="),
                    "equation": equation,
                    "gpr": gpr,
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
                cpd_id = bc.get("modelcompound_ref", "").split("/")[-1]
                bio_cpds.append(
                    [
                        cpd_id,
                        bc.get("coefficient", 0),
                        bc.get("compartment", ""),
                        cpd_name_map.get(cpd_id, cpd_id),
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
            if not isinstance(gf_data, dict):
                continue
            for gfid, sol_data in gf_data.items():
                if gfid not in gf_rxn_index:
                    gf_rxn_index[gfid] = []
                rxn_id = rxn.get("id", "")
                compartment = rxn_id.rsplit("_", 1)[-1] if "_" in rxn_id else ""

                if isinstance(sol_data, str):
                    # Legacy format: "added:>" or "reversed:<"
                    direction = sol_data.split(":")[-1] if ":" in sol_data else "="
                    gf_rxn_index[gfid].append({
                        "reaction": rxn_id,
                        "direction": direction,
                        "compartment": compartment,
                    })
                elif isinstance(sol_data, dict):
                    # ModelSEEDpy format: {"0": [direction, integrated_flag, features]}
                    for sol_idx, sol_info in sol_data.items():
                        direction = sol_info[0] if isinstance(sol_info, list) else "="
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

    # ------------------------------------------------------------------
    # Model editing
    # ------------------------------------------------------------------

    # Standard compartment labels
    _COMPARTMENT_NAMES = {
        "c": "Cytoplasm",
        "e": "Extracellular",
        "p": "Periplasm",
        "m": "Mitochondria",
        "x": "Peroxisome",
        "n": "Nucleus",
        "v": "Vacuole",
        "g": "Golgi",
        "r": "Endoplasmic reticulum",
        "d": "Plastid",
    }

    def edit_model(self, model_ref: str, edits) -> dict:
        """Apply all edits atomically to a model.

        1. Load model from workspace
        2. Validate all edits (references exist, no conflicts)
        3. Apply all mutations to the model dict
        4. Save model back to workspace
        5. Update folder metadata
        6. Return summary
        """
        from modelseed_api.schemas.models import EditModelResponse
        from modelseed_api.services import biochem_service

        model_obj = self.get_model_raw(model_ref)
        response = EditModelResponse(model=model_ref)

        # Build indexes for validation
        existing_rxns = {r["id"] for r in model_obj.get("modelreactions", [])}
        existing_cpds = {c["id"] for c in model_obj.get("modelcompounds", [])}
        existing_bios = {b["id"] for b in model_obj.get("biomasses", [])}

        errors = []

        # Validate reaction removals
        for rxn_id in edits.reactions_to_remove:
            if rxn_id not in existing_rxns:
                errors.append(f"Reaction '{rxn_id}' not found in model")

        # Validate reaction additions
        for rxn in edits.reactions_to_add:
            full_id = f"{rxn.reaction_id}_{rxn.compartment}"
            if full_id in existing_rxns:
                errors.append(f"Reaction '{full_id}' already exists in model")
            db_rxn = biochem_service.get_reaction_raw(rxn.reaction_id)
            if not db_rxn:
                errors.append(f"Reaction '{rxn.reaction_id}' not found in biochemistry database")
            if rxn.direction and rxn.direction not in (">", "<", "="):
                errors.append(f"Invalid direction '{rxn.direction}' for reaction '{rxn.reaction_id}'")

        # Validate reaction modifications
        for mod in edits.reactions_to_modify:
            if mod.reaction_id not in existing_rxns:
                errors.append(f"Reaction '{mod.reaction_id}' not found in model")
            if mod.direction and mod.direction not in (">", "<", "="):
                errors.append(f"Invalid direction '{mod.direction}'")

        # Validate compound removals
        for cpd_id in edits.compounds_to_remove:
            if cpd_id not in existing_cpds:
                errors.append(f"Compound '{cpd_id}' not found in model")

        # Validate compound additions
        for cpd in edits.compounds_to_add:
            full_id = f"{cpd.compound_id}_{cpd.compartment}"
            if full_id in existing_cpds:
                errors.append(f"Compound '{full_id}' already exists in model")

        # Validate compound modifications
        for mod in edits.compounds_to_modify:
            if mod.compound_id not in existing_cpds:
                errors.append(f"Compound '{mod.compound_id}' not found in model")

        # Validate biomass modifications
        for change in edits.biomass_changes:
            if change.biomass_id not in existing_bios:
                errors.append(f"Biomass '{change.biomass_id}' not found in model")

        # Validate biomass removals
        for bio_id in edits.biomasses_to_remove:
            if bio_id not in existing_bios:
                errors.append(f"Biomass '{bio_id}' not found in model")

        if errors:
            raise ValueError("; ".join(errors))

        # --- Mutation phase (all validated) ---
        self._edit_add_reactions(model_obj, edits.reactions_to_add, response)
        self._edit_remove_reactions(model_obj, edits.reactions_to_remove, response)
        self._edit_modify_reactions(model_obj, edits.reactions_to_modify, response)
        self._edit_add_compounds(model_obj, edits.compounds_to_add, response)
        self._edit_remove_compounds(model_obj, edits.compounds_to_remove, response)
        self._edit_modify_compounds(model_obj, edits.compounds_to_modify, response)
        self._edit_add_biomasses(model_obj, edits.biomasses_to_add, response)
        self._edit_modify_biomasses(model_obj, edits.biomass_changes, response)
        self._edit_remove_biomasses(model_obj, edits.biomasses_to_remove, response)

        # --- Persist ---
        self._save_model(model_ref, model_obj)
        self._update_model_metadata(model_ref, model_obj)

        return response

    def _edit_add_reactions(self, model_obj, reactions, response):
        """Add reactions from the biochemistry database to the model."""
        from modelseed_api.services import biochem_service

        for rxn in reactions:
            db_rxn = biochem_service.get_reaction_raw(rxn.reaction_id)
            if not db_rxn:
                continue

            # Ensure compartments exist
            self._ensure_compartment_exists(model_obj, rxn.compartment)
            # Extracellular compartment for transport reactions
            comp_idx = int(rxn.compartment[1:]) if len(rxn.compartment) > 1 else 0
            ext_compartment = f"e{comp_idx}"

            # Build reagents from stoichiometry, auto-adding missing compounds
            reagents = []
            for s in db_rxn.get("stoichiometry", []):
                cpd_id = s["compound"]
                if s.get("compartment", 0) == 0:
                    cpd_compartment = rxn.compartment
                else:
                    cpd_compartment = ext_compartment
                    self._ensure_compartment_exists(model_obj, ext_compartment)

                full_cpd_id = self._ensure_compound_exists(
                    model_obj, cpd_id, cpd_compartment
                )
                reagents.append({
                    "modelcompound_ref": f"~/modelcompounds/id/{full_cpd_id}",
                    "coefficient": s["coefficient"],
                })

            full_rxn_id = f"{rxn.reaction_id}_{rxn.compartment}"
            direction = rxn.direction or db_rxn.get("reversibility", "=")

            model_rxn = {
                "id": full_rxn_id,
                "name": db_rxn.get("name", ""),
                "reaction_ref": f"~/reactions/id/{rxn.reaction_id}",
                "direction": direction,
                "modelcompartment_ref": f"~/modelcompartments/id/{rxn.compartment}",
                "modelReactionReagents": reagents,
                "modelReactionProteins": self._parse_gpr_to_proteins(rxn.gpr),
                "gapfill_data": {},
                "probability": 0,
                "protons": 0,
                "maxforflux": 1000000,
                "maxrevflux": 1000000,
                "imported_gpr": rxn.gpr or "",
                "aliases": [],
                "dblinks": {},
                "string_attributes": {},
                "numerical_attributes": {},
                "pathway": "",
                "reference": "",
            }
            model_obj.setdefault("modelreactions", []).append(model_rxn)
            response.reactions_added.append(full_rxn_id)

    def _edit_remove_reactions(self, model_obj, reaction_ids, response):
        """Remove reactions by model ID."""
        ids_to_remove = set(reaction_ids)
        original = model_obj.get("modelreactions", [])
        model_obj["modelreactions"] = [
            r for r in original if r["id"] not in ids_to_remove
        ]
        for rxn_id in reaction_ids:
            response.reactions_removed.append(rxn_id)

    def _edit_modify_reactions(self, model_obj, modifications, response):
        """Modify existing reactions: direction, name, GPR."""
        rxn_index = {r["id"]: r for r in model_obj.get("modelreactions", [])}
        for mod in modifications:
            rxn = rxn_index.get(mod.reaction_id)
            if not rxn:
                continue
            if mod.direction is not None:
                rxn["direction"] = mod.direction
            if mod.name is not None:
                rxn["name"] = mod.name
            if mod.gpr is not None:
                rxn["modelReactionProteins"] = self._parse_gpr_to_proteins(
                    mod.gpr if mod.gpr else None
                )
                rxn["imported_gpr"] = mod.gpr
            response.reactions_modified.append(mod.reaction_id)

    def _edit_add_compounds(self, model_obj, compounds, response):
        """Add compounds to the model from biochem DB or custom."""
        from modelseed_api.services import biochem_service

        for cpd in compounds:
            db_cpd = biochem_service.get_compound_raw(cpd.compound_id)
            self._ensure_compartment_exists(model_obj, cpd.compartment)

            full_id = f"{cpd.compound_id}_{cpd.compartment}"
            new_cpd = {
                "id": full_id,
                "name": cpd.name or (db_cpd.get("name", "") if db_cpd else cpd.compound_id),
                "formula": cpd.formula or (db_cpd.get("formula", "") if db_cpd else ""),
                "charge": cpd.charge if cpd.charge is not None else (
                    db_cpd.get("charge", 0) if db_cpd else 0
                ),
                "modelcompartment_ref": f"~/modelcompartments/id/{cpd.compartment}",
                "compound_ref": f"~/compounds/id/{cpd.compound_id}",
                "maxuptake": 0,
                "aliases": [],
                "dblinks": {},
                "string_attributes": {},
                "numerical_attributes": {},
            }
            model_obj.setdefault("modelcompounds", []).append(new_cpd)
            response.compounds_added.append(full_id)

    def _edit_remove_compounds(self, model_obj, compound_ids, response):
        """Remove compounds by model ID. Warns if compound is used by a reaction."""
        ids_to_remove = set(compound_ids)

        # Check for compounds used by reactions
        used_by_rxn = set()
        for rxn in model_obj.get("modelreactions", []):
            for reagent in rxn.get("modelReactionReagents", []):
                ref = reagent.get("modelcompound_ref", "")
                cpd_id = ref.split("/")[-1]
                if cpd_id in ids_to_remove:
                    used_by_rxn.add(cpd_id)

        if used_by_rxn:
            raise ValueError(
                f"Cannot remove compounds still used by reactions: {', '.join(used_by_rxn)}"
            )

        original = model_obj.get("modelcompounds", [])
        model_obj["modelcompounds"] = [
            c for c in original if c["id"] not in ids_to_remove
        ]
        for cpd_id in compound_ids:
            response.compounds_removed.append(cpd_id)

    def _edit_modify_compounds(self, model_obj, modifications, response):
        """Modify existing compounds: name, formula, charge."""
        cpd_index = {c["id"]: c for c in model_obj.get("modelcompounds", [])}
        for mod in modifications:
            cpd = cpd_index.get(mod.compound_id)
            if not cpd:
                continue
            if mod.name is not None:
                cpd["name"] = mod.name
            if mod.formula is not None:
                cpd["formula"] = mod.formula
            if mod.charge is not None:
                cpd["charge"] = mod.charge
            response.compounds_modified.append(mod.compound_id)

    def _edit_add_biomasses(self, model_obj, biomasses, response):
        """Add new biomass reactions."""
        existing_ids = {b["id"] for b in model_obj.get("biomasses", [])}
        for i, bio in enumerate(biomasses):
            # Auto-generate ID
            n = len(existing_ids) + 1
            bio_id = f"bio{n}"
            while bio_id in existing_ids:
                n += 1
                bio_id = f"bio{n}"
            existing_ids.add(bio_id)

            bio_cpds = []
            for cc in bio.compounds:
                bio_cpds.append({
                    "modelcompound_ref": f"~/modelcompounds/id/{cc.compound_id}",
                    "coefficient": cc.coefficient,
                })

            new_bio = {
                "id": bio_id,
                "name": bio.name,
                "biomasscompounds": bio_cpds,
                "dna": 0,
                "rna": 0,
                "protein": 0,
                "cellwall": 0,
                "lipid": 0,
                "cofactor": 0,
                "other": 1,
                "energy": 0,
            }
            model_obj.setdefault("biomasses", []).append(new_bio)
            response.biomasses_added.append(bio_id)

    def _edit_modify_biomasses(self, model_obj, changes, response):
        """Modify biomass compound coefficients. Coefficient=0 removes the compound."""
        bio_index = {b["id"]: b for b in model_obj.get("biomasses", [])}
        for change in changes:
            bio = bio_index.get(change.biomass_id)
            if not bio:
                continue

            if change.name is not None:
                bio["name"] = change.name

            for cc in change.compound_changes:
                cpd_ref = f"~/modelcompounds/id/{cc.compound_id}"
                found = False
                for bc in bio.get("biomasscompounds", []):
                    if bc.get("modelcompound_ref", "").endswith(f"/{cc.compound_id}"):
                        if cc.coefficient == 0:
                            bio["biomasscompounds"].remove(bc)
                        else:
                            bc["coefficient"] = cc.coefficient
                        found = True
                        break
                if not found and cc.coefficient != 0:
                    bio.setdefault("biomasscompounds", []).append({
                        "modelcompound_ref": cpd_ref,
                        "coefficient": cc.coefficient,
                    })

            response.biomasses_modified.append(change.biomass_id)

    def _edit_remove_biomasses(self, model_obj, biomass_ids, response):
        """Remove biomass reactions by ID."""
        ids_to_remove = set(biomass_ids)
        original = model_obj.get("biomasses", [])
        model_obj["biomasses"] = [
            b for b in original if b["id"] not in ids_to_remove
        ]
        for bio_id in biomass_ids:
            response.biomasses_removed.append(bio_id)

    def _ensure_compound_exists(self, model_obj, compound_id, compartment):
        """Ensure a compound exists in modelcompounds, adding from biochem DB if needed."""
        from modelseed_api.services import biochem_service

        full_id = f"{compound_id}_{compartment}"
        existing = {c["id"] for c in model_obj.get("modelcompounds", [])}
        if full_id in existing:
            return full_id

        db_cpd = biochem_service.get_compound_raw(compound_id)
        new_cpd = {
            "id": full_id,
            "name": db_cpd.get("name", compound_id) if db_cpd else compound_id,
            "formula": db_cpd.get("formula", "") if db_cpd else "",
            "charge": db_cpd.get("charge", 0) if db_cpd else 0,
            "modelcompartment_ref": f"~/modelcompartments/id/{compartment}",
            "compound_ref": f"~/compounds/id/{compound_id}",
            "maxuptake": 0,
            "aliases": [],
            "dblinks": {},
            "string_attributes": {},
            "numerical_attributes": {},
        }
        model_obj.setdefault("modelcompounds", []).append(new_cpd)
        return full_id

    def _ensure_compartment_exists(self, model_obj, compartment_id):
        """Ensure a compartment exists in modelcompartments, adding if needed."""
        existing = {c["id"] for c in model_obj.get("modelcompartments", [])}
        if compartment_id in existing:
            return

        label = compartment_id[0] if compartment_id else "c"
        comp_index = int(compartment_id[1:]) if len(compartment_id) > 1 else 0
        name = self._COMPARTMENT_NAMES.get(label, "Unknown")

        new_comp = {
            "id": compartment_id,
            "label": label,
            "name": name,
            "pH": 7.0,
            "potential": 0.0,
            "compartmentIndex": comp_index,
            "compartment_ref": f"~/compartments/id/{label}",
        }
        model_obj.setdefault("modelcompartments", []).append(new_comp)

    def _parse_gpr_to_proteins(self, gpr):
        """Convert GPR string to workspace nested protein/subunit/feature structure.

        OR groups -> separate modelReactionProtein entries
        AND groups -> subunits within the same protein entry
        """
        if not gpr or not gpr.strip():
            return []

        # Split on " or " for protein alternatives
        or_groups = [g.strip().strip("()") for g in gpr.split(" or ")]

        proteins = []
        for group in or_groups:
            and_genes = [g.strip().strip("()") for g in group.split(" and ")]
            subunits = []
            for gene in and_genes:
                if gene:
                    subunits.append({
                        "role": "",
                        "triggering": 1,
                        "optionalSubunit": 0,
                        "note": "",
                        "feature_refs": [f"~/genome/features/id/{gene}"],
                    })
            if subunits:
                proteins.append({
                    "note": "",
                    "modelReactionProteinSubunits": subunits,
                })

        return proteins

    def _update_model_metadata(self, model_ref, model_obj):
        """Update folder metadata counts after editing."""
        meta = {
            "num_reactions": str(len(model_obj.get("modelreactions", []))),
            "num_compounds": str(len(model_obj.get("modelcompounds", []))),
            "num_biomasses": str(len(model_obj.get("biomasses", []))),
        }
        try:
            self.ws.update_metadata({"objects": [[model_ref, meta]]})
        except Exception:
            pass  # non-critical

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

        # Merge both keys — legacy models use fbaFormulations, new ones use fba_studies
        all_fba = model_obj.get("fbaFormulations", []) + model_obj.get("fba_studies", [])
        seen_ids: set[str] = set()
        fbas = []
        for fba in all_fba:
            fba_id = fba.get("id", "")
            if fba_id in seen_ids:
                continue
            seen_ids.add(fba_id)
            fbas.append(
                {
                    "rundate": fba.get("rundate", ""),
                    "id": fba_id,
                    "ref": fba.get("ref", f"{model_ref}/fba.{fba_id}"),
                    "objective": fba.get("objectiveValue", fba.get("objective", 0.0)),
                    "media_ref": fba.get("media_ref", ""),
                    "objective_function": fba.get("objectiveFunction", fba.get("objective_function", "")),
                }
            )

        return fbas

    def get_fba_detail(self, model_ref: str, fba_id: str) -> dict:
        """Fetch full FBA result including flux data.

        The actual FBA object (with fluxes) is stored as a separate workspace
        object at {model_ref}/{fba_id}, while the model's fba_studies array
        only contains summary metadata (no fluxes).
        """
        fba_path = f"{model_ref}/{fba_id}"
        result = self.ws.get({"objects": [fba_path]})
        fba_obj = self._parse_ws_data(result)

        fluxes = fba_obj.get("fluxes", {})

        # For old PATRIC models, flux data may be in a separate .fluxtbl file
        if not fluxes:
            try:
                tbl_result = self.ws.get({"objects": [f"{fba_path}.fluxtbl"]})
                tbl_data = tbl_result[0][1]  # raw string
                fluxes = self._parse_fluxtbl(tbl_data)
            except Exception:
                pass  # .fluxtbl may not exist

        return {
            "id": fba_obj.get("id", fba_id),
            "model_ref": fba_obj.get("model_ref", model_ref),
            "media_ref": fba_obj.get("media_ref", ""),
            "objectiveValue": float(fba_obj.get("objectiveValue", 0.0)),
            "status": fba_obj.get("status", ""),
            "rundate": fba_obj.get("rundate", ""),
            "fluxes": {k: float(v) for k, v in fluxes.items()},
        }

    @staticmethod
    def _parse_fluxtbl(tbl_data: str) -> dict[str, float]:
        """Parse a tab-delimited flux table (legacy PATRIC format).

        Format: reaction_id<TAB>flux_value per line, with optional header.
        """
        fluxes: dict[str, float] = {}
        for line in tbl_data.strip().splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                try:
                    fluxes[parts[0]] = float(parts[1])
                except ValueError:
                    continue  # skip header or malformed lines
        return fluxes
