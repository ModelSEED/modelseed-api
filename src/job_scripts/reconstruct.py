"""Model reconstruction job script.

Runs outside the API service process.
Builds a metabolic model from a BV-BRC genome ID or protein FASTA.

Pipeline:
  1. Fetch genome from BV-BRC API (or parse FASTA)
  2. Classify genome type (auto) or use explicit template
  3. Build model via KBUtilLib
  4. Optionally gapfill
  5. Save model to workspace

Usage:
    python reconstruct.py --job-id <id> --token <token> --params <json> --job-store-dir <dir>
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def update_job(job_file, updates):
    """Update job JSON file with new fields."""
    if job_file.exists():
        job = json.loads(job_file.read_text())
        job.update(updates)
        job_file.write_text(json.dumps(job, indent=2))


def merge_ws_metadata(ws, obj_path, new_meta):
    """Merge new metadata into existing workspace metadata."""
    existing = {}
    try:
        obj_path = obj_path.rstrip("/")
        parent = obj_path.rsplit("/", 1)[0] + "/"
        obj_name = obj_path.rsplit("/", 1)[1]
        result = ws.ls({"paths": [parent]})
        if result:
            for items in result.values():
                for item in items:
                    if item[0] == obj_name and len(item) > 7 and isinstance(item[7], dict):
                        existing = item[7]
                        break
                if existing:
                    break
    except Exception:
        pass
    merged = {**existing, **new_meta}
    ws.update_metadata({"objects": [[obj_path, merged]]})


def main():
    parser = argparse.ArgumentParser(description="Model reconstruction job")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--job-store-dir", required=True)
    args = parser.parse_args()

    store_dir = Path(args.job_store_dir)
    job_file = store_dir / f"{args.job_id}.json"
    now = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d-%H:%M:%S")

    update_job(job_file, {"status": "in-progress", "start_time": now()})

    # Support @filename for large params (FASTA content)
    if args.params.startswith("@"):
        params = json.loads(Path(args.params[1:]).read_text())
    else:
        params = json.loads(args.params)

    genome_id = params.get("genome", "")
    genome_fasta = params.get("genome_fasta")
    template_type = params.get("template_type", "auto")
    atp_safe = params.get("atp_safe", True)
    gapfill = params.get("gapfill", False)
    media_ref = params.get("media")
    output_path = params.get("output_path")

    if not genome_id:
        raise ValueError("genome is required")

    # Compute default output path from username + genome ID
    if not output_path:
        # Extract username from token: "un=user@patricbrc.org|..."
        username = ""
        for part in args.token.split("|"):
            if part.startswith("un="):
                username = part[3:]
                break
        if username:
            output_path = f"/{username}/modelseed/{genome_id}"
    if ":" in genome_id:
        genome_id = genome_id.split(":", 1)[1]

    try:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from modelseed_api.config import settings
        from modelseed_api.services.storage_factory import get_storage_service
        from modelseed_api.jobs.tasks import (
            _load_template, _get_classifier, _classify_genome,
            _load_media, _resolve_media_ref, TEMPLATE_FILES,
        )

        os.environ.setdefault("KB_AUTH_TOKEN", "unused")

        # Load template: defer when "auto"
        update_job(job_file, {"progress": "Loading templates..."})
        if template_type == "auto":
            gs_template_obj = None
        else:
            gs_template_obj = _load_template(template_type)

        if genome_fasta:
            # ── FASTA path ──
            update_job(job_file, {"progress": "Parsing FASTA..."})
            from modelseedpy.core.msgenome import MSGenome, parse_fasta_str
            from modelseedpy.core.msbuilder import MSBuilder

            ms_genome = MSGenome()
            ms_genome.features += parse_fasta_str(genome_fasta)
            if not ms_genome.features:
                raise ValueError("No protein sequences found in genome_fasta")
            print(f"Parsed {len(ms_genome.features)} protein sequences from FASTA")

            organism_name = genome_id
            taxonomy = ""
            domain = ""

            update_job(job_file, {"progress": "Annotating & building model..."})
            model = MSBuilder.build_metabolic_model(
                genome_id, ms_genome,
                template=gs_template_obj,
                annotate_with_rast=True,
                gapfill_model=False,
            )

            from modelseedpy.core.msmodelutl import MSModelUtil
            mdlutl = MSModelUtil.get(model)
            output = {
                "Reactions": len(model.reactions),
                "Model genes": len(model.genes),
                "Class": template_type,
            }
        else:
            # ── BV-BRC path ──
            from kbutillib import BVBRCUtils, MSReconstructionUtils

            kwargs = dict(
                config_file=False,
                token_file=None,
                kbase_token_file=None,
                token={"patric": args.token, "kbase": "unused"},
                modelseed_path=settings.modelseed_db_path,
                cb_annotation_ontology_api_path=settings.cb_annotation_ontology_api_path,
            )

            update_job(job_file, {"progress": "Fetching genome..."})
            bvbrc = BVBRCUtils(**kwargs)
            kbase_genome = bvbrc.build_kbase_genome_from_api(genome_id)

            organism_name = kbase_genome.get("scientific_name", "")
            taxonomy = kbase_genome.get("taxonomy", "")
            domain = kbase_genome.get("domain", "")

            update_job(job_file, {"progress": "Converting genome..."})
            recon = MSReconstructionUtils(**kwargs)
            genome = recon.get_msgenome_from_dict(kbase_genome)

            core_template = _load_template("core")

            # Classify genome locally (if auto) to avoid KBUtilLib workspace call
            resolved_type = template_type
            class_name = None
            if template_type == "auto":
                update_job(job_file, {"progress": "Classifying genome..."})
                class_name, resolved_type = _classify_genome(genome)
                gs_template_obj = _load_template(resolved_type)
                print(f"Auto-classified as {class_name}, using template {resolved_type}")

            update_job(job_file, {"progress": "Building model..."})
            output, mdlutl = recon.build_metabolic_model(
                genome=genome,
                genome_classifier=None,
                core_template=core_template,
                gs_template_obj=gs_template_obj,
                gs_template=resolved_type,
                atp_safe=atp_safe,
            )

            # Set classification from our local classifier (KBUtilLib skips it
            # when we pass genome_classifier=None)
            if class_name:
                output["Class"] = class_name

            if mdlutl is None:
                result_data = {
                    "status": "skipped",
                    "comments": output.get("Comments", []),
                }
                update_job(job_file, {
                    "status": "completed",
                    "completed_time": now(),
                    "result": result_data,
                })
                print(f"Model skipped: {result_data}")
                return

        # Resolve template for gapfilling if auto was used
        if gs_template_obj is None:
            _class_to_type = {
                "Gram Negative": "gn", "Gram Positive": "gp", "Archaea": "ar",
            }
            resolved_type = _class_to_type.get(output.get("Class", ""), "gn")
            gs_template_obj = _load_template(resolved_type)

        # Gapfill if requested
        gapfill_count = 0
        if gapfill:
            update_job(job_file, {"progress": "Running gapfilling..."})
            from modelseedpy.core.msmedia import MSMedia

            ms_media = None
            ws_media_path = _resolve_media_ref(media_ref)
            if ws_media_path:
                ms_media = _load_media(ws_media_path, args.token)

            if ms_media is None:
                ms_media = MSMedia("Complete", "Complete")

            # Use KBUtilLib's gapfill_metabolic_model which handles everything:
            # ATP tests, auto_sink, run_multi_gapfill, growth verification.
            gf_output, solutions, _, _ = recon.gapfill_metabolic_model(
                mdlutl=mdlutl,
                genome=genome,
                media_objs=[ms_media],
                templates=[gs_template_obj],
                core_template=core_template,
                atp_safe=True,
            )
            gapfill_count = gf_output.get("GS GF") or 0
            print(f"Gapfill: GS_GF={gapfill_count} Growth={gf_output.get('Growth')}")

            # Ensure demand reactions for auto_sink compounds that the
            # gapfiller uses internally but may not include in the solution.
            # The KBase pipeline gets these via the solver; we add them
            # explicitly so FBA can drain biomass byproducts.
            auto_sink = ["cpd11416", "cpd01042", "cpd02701", "cpd15302", "cpd03091"]
            for cpd_id in auto_sink:
                met_id = f"{cpd_id}_c0"
                dm_id = f"DM_{met_id}"
                if met_id in mdlutl.model.metabolites and dm_id not in mdlutl.model.reactions:
                    met = mdlutl.model.metabolites.get_by_id(met_id)
                    mdlutl.add_exchanges_for_metabolites(
                        [met], uptake=0, excretion=1000, prefix="DM_", prefix_name="Demand for "
                    )

        # Compute stats
        n_reactions = output.get("Reactions", len(mdlutl.model.reactions))
        n_genes = output.get("Model genes", len(mdlutl.model.genes))
        n_metabolites = len(mdlutl.model.metabolites)
        n_compartments = len(mdlutl.model.compartments)
        classification = output.get("Class", template_type)

        # Save model to storage
        if output_path:
            update_job(job_file, {"progress": "Saving model..."})
            ws = get_storage_service(args.token)

            import cobra.io
            mdlutl.model.objective = "bio1"
            cobra_json = json.dumps(cobra.io.model_to_dict(mdlutl.model))

            if not hasattr(mdlutl.model, 'get_data'):
                from cobrakbase.core.kbasefba.fbamodel_from_cobra import CobraModelConverter
                mdlutl.model = CobraModelConverter(mdlutl.model).build()
            mdlutl.save_attributes()
            ws_data = mdlutl.model.get_data()

            if gapfill_count > 0:
                mdlutl.create_kb_gapfilling_data(ws_data)

            model_data = json.dumps(ws_data)
            n_biomasses = len(ws_data.get("biomasses", []))

            folder_meta = {
                "id": genome_id,
                "name": organism_name or genome_id,
                "source_id": genome_id,
                "source": "ModelSEED",
                "type": classification,
                "genome_ref": genome_id,
                "organism_name": organism_name,
                "taxonomy": taxonomy,
                "domain": domain,
                "num_reactions": str(n_reactions),
                "num_compounds": str(n_metabolites),
                "num_genes": str(n_genes),
                "num_compartments": str(n_compartments),
                "num_biomasses": str(n_biomasses),
                "integrated_gapfills": str(gapfill_count),
                "unintegrated_gapfills": "0",
                "fba_count": "0",
            }

            ws.create({
                "objects": [
                    [output_path, "modelfolder", folder_meta, ""],
                    [f"{output_path}/model", "model", {}, model_data],
                    [f"{output_path}/cobra_model", "string", {}, cobra_json],
                ],
                "overwrite": 1,
            })

            try:
                merge_ws_metadata(ws, output_path, folder_meta)
            except Exception as e:
                print(f"Warning: failed to update folder metadata: {e}")

        result_data = {
            "status": "success",
            "genome_id": genome_id,
            "reactions": n_reactions,
            "metabolites": n_metabolites,
            "genes": n_genes,
            "classification": classification,
            "core_gapfilling": output.get("Core GF", 0),
            "gapfilled": gapfill,
            "gapfill_solutions": gapfill_count,
            "atp_safe": atp_safe,
            "template_type": template_type,
            "reconstruction_output": output,
        }

        update_job(job_file, {
            "status": "completed",
            "completed_time": now(),
            "result": result_data,
        })

        print(f"Reconstruction completed: {n_reactions} reactions, "
              f"{n_genes} genes, class={classification}")

    except Exception as e:
        update_job(job_file, {
            "status": "failed",
            "error": str(e),
            "completed_time": now(),
        })
        print(f"Reconstruction failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        pass
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            _args = dict(zip(sys.argv[1::2], sys.argv[2::2]))
            _jf = Path(_args.get("--job-store-dir", "/tmp/modelseed-jobs")) / f"{_args.get('--job-id', 'unknown')}.json"
            if _jf.exists():
                update_job(_jf, {"status": "failed", "error": str(e)})
        except Exception:
            pass
