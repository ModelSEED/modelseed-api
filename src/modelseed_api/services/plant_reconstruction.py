"""Plant genome annotation + model reconstruction via PlantSEED.

Shared body of the `modelseed.plant_reconstruct` Celery task and the
`plant_reconstruct.py` subprocess job script, so the two paths can't drift.

Pipeline:
  1. Write the protein FASTA to the directory shared with the PlantSEED
     server, re-headering every sequence as `<query_species>||<gene>`.
  2. PlantSEED `annotate`: place proteins into curated orthogroups and
     assign PlantSEED roles (minutes for a full proteome).
  3. PlantSEED `reconstruct`: build the KBase FBAModel from the annotation.
  4. Save the annotated genome, the model, and its cobra JSON under
     `/<user>/plantseed/<genome>/`, the same layout the microbial
     reconstruction writes plus a `genome` object.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from pathlib import Path

from modelseed_api.config import settings

logger = logging.getLogger(__name__)

_SAFE_ID = re.compile(r"[^A-Za-z0-9_.\-]+")


def safe_id(label: str) -> str:
    return _SAFE_ID.sub("_", label).strip("._") or "plant_genome"


def username_from_token(token: str) -> str:
    for part in token.split("|"):
        if part.startswith("un="):
            return part[3:]
    return ""


def parse_protein_fasta(fasta: str) -> list[tuple[str, str]]:
    """Return [(gene_id, sequence)], dropping any `<species>||` header prefix."""
    records: list[tuple[str, str]] = []
    gene_id: str | None = None
    seq: list[str] = []
    for raw in fasta.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            if gene_id:
                records.append((gene_id, "".join(seq)))
            header = line[1:].strip()
            token = header.split()[0] if header else ""
            gene_id = token.split("||", 1)[1] if "||" in token else token
            seq = []
        else:
            seq.append("".join(line.split()))
    if gene_id:
        records.append((gene_id, "".join(seq)))
    return [(g, s.rstrip("*")) for g, s in records if g and s.rstrip("*")]


def write_query_fasta(records: list[tuple[str, str]], query_species: str, path: Path) -> None:
    with open(path, "w") as fh:
        for gene_id, seq in records:
            fh.write(f">{query_species}||{gene_id}\n")
            for i in range(0, len(seq), 80):
                fh.write(seq[i:i + 80] + "\n")


def _protein_for_gene(gene_id: str, proteins: dict[str, str]) -> tuple[str, str] | None:
    """Pick the input protein for an annotated gene.

    PlantSEED annotates at gene level ('Potri.014G034700') while proteomes
    are usually transcript level ('Potri.014G034700.1.p'); take an exact
    match, else the lexically first transcript of that gene.
    """
    if gene_id in proteins:
        return gene_id, proteins[gene_id]
    prefix = gene_id + "."
    candidates = sorted(p for p in proteins if p.startswith(prefix))
    return (candidates[0], proteins[candidates[0]]) if candidates else None


def build_genome_object(
    genome_id: str,
    scientific_name: str,
    annotated: dict,
    proteins: dict[str, str],
    annotation_summary: dict,
) -> dict:
    """KBase-Genome-shaped object holding the PlantSEED annotation."""
    features = []
    for ftr in annotated.get("features", []):
        functions = list(ftr.get("functions") or [])
        feature = {
            "id": ftr["id"],
            "type": "gene",
            "function": " / ".join(functions),
            "functions": functions,
        }
        match = _protein_for_gene(ftr["id"], proteins)
        if match:
            protein_id, seq = match
            feature["protein_translation"] = seq
            feature["protein_translation_length"] = len(seq)
            feature["md5"] = hashlib.md5(seq.encode()).hexdigest()
            if protein_id != ftr["id"]:
                feature["aliases"] = [protein_id]
        features.append(feature)
    return {
        "id": genome_id,
        "scientific_name": scientific_name,
        "domain": "Plant",
        "taxonomy": "Eukaryota; Viridiplantae",
        "source": "PlantSEED",
        "source_id": genome_id,
        "features": features,
        "annotation_summary": annotation_summary,
    }


def _cobra_json(model_obj: dict) -> str:
    """cobra JSON for the plant model, with bio1 as objective.

    `from_kbase_json` (not a bare FBAModelBuilder) is required: it adds the
    default sinks that plant biomass needs to carry flux.
    """
    import cobra.io
    from cobrakbase.core.kbasefba.fbamodel_builder import FBAModelBuilder

    model = FBAModelBuilder.from_kbase_json(model_obj, None).build()
    if "bio1" not in {r.id for r in model.reactions}:
        raise RuntimeError(
            "PlantSEED model has no 'bio1' biomass reaction; reconstruction "
            "produced an incomplete model."
        )
    model.objective = "bio1"
    return json.dumps(cobra.io.model_to_dict(model))


def _ensure_home_folder(ws, username: str, home: str) -> None:
    """Create /<user>/<home> if missing; PATRIC refuses writes beneath a missing folder."""
    root = f"/{username}/"
    try:
        listing = ws.ls({"paths": [root]}) or {}
        names = {item[0] for items in listing.values() for item in items}
    except Exception:
        names = set()
    if home not in names:
        ws.create({"objects": [[f"/{username}/{home}", "folder", {}, ""]]})


def _cleanup(*paths: Path) -> None:
    for p in paths:
        try:
            shutil.rmtree(p)
        except OSError:
            pass


def run_plant_reconstruct(
    token: str,
    genome: str,
    genome_fasta: str,
    query_species: str | None = None,
    output_path: str | None = None,
    job_id: str = "manual",
    progress_cb=None,
    client=None,
) -> dict:
    from modelseed_api.services.plantseed_client import PlantSEEDClient, PlantSEEDServiceError
    from modelseed_api.services.storage_factory import get_storage_service

    def _progress(msg: str) -> None:
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass

    genome_id = safe_id(genome)
    query_species = query_species or genome_id
    username = username_from_token(token)
    if not output_path:
        if not username:
            raise ValueError("output_path is required when the token carries no username")
        output_path = f"/{username}/{settings.plantseed_home_dir}/{genome_id}"
    output_path = output_path.rstrip("/")

    records = parse_protein_fasta(genome_fasta)
    if not records:
        raise ValueError("genome_fasta contains no protein sequences")
    proteins = dict(records)

    client = client or PlantSEEDClient.from_settings()
    work_dir = client.jobs_dir / f"plant-{job_id}"
    work_dir.mkdir(parents=True, exist_ok=True)
    work_dir.chmod(0o755)
    query_path = work_dir / "query.faa"
    write_query_fasta(records, query_species, query_path)
    query_path.chmod(0o644)
    run_dirs = [work_dir]

    try:
        _progress(
            f"Annotating {len(records)} proteins against PlantSEED "
            "(several minutes for a full proteome)..."
        )
        ann = client.annotate(query_path, query_species)
        annotated_server_path = ann.get("genome_path")
        if not annotated_server_path:
            raise PlantSEEDServiceError("PlantSEED annotate returned no genome_path")
        annotated_path = client.to_local_path(annotated_server_path)
        run_dirs.append(annotated_path.parent)
        annotated = json.loads(annotated_path.read_text())
        n_annotated = ann.get("n_annotated_features", len(annotated.get("features", [])))
        if not annotated.get("features"):
            raise RuntimeError(
                f"PlantSEED annotated none of the {len(records)} proteins; check "
                "that genome_fasta is a plant proteome."
            )

        _progress(f"Building model from {n_annotated} annotated genes...")
        rec = client.reconstruct(annotated_server_path, genome_id)
        model_server_path = rec.get("model_path")
        if not model_server_path:
            raise PlantSEEDServiceError("PlantSEED reconstruct returned no model_path")
        model_path = client.to_local_path(model_server_path)
        run_dirs.append(model_path.parent)
        model_obj = json.loads(model_path.read_text())

        annotation_summary = {
            "n_proteins": len(records),
            "n_query_genes_searched": ann.get("n_query_genes_searched"),
            "n_query_genes_placed": ann.get("n_query_genes_placed"),
            "n_annotated_features": n_annotated,
            "status_counts": ann.get("status_counts"),
            "query_species": query_species,
            "annotation_sha256": ann.get("sha256"),
            "model_sha256": rec.get("sha256"),
        }
        genome_obj = build_genome_object(
            genome_id, genome, annotated, proteins, annotation_summary
        )

        model_obj["id"] = genome_id
        model_obj["name"] = genome
        model_obj["genome_ref"] = f"{output_path}/genome"
        cobra_json = _cobra_json(model_obj)

        n_reactions = len(model_obj.get("modelreactions", []))
        n_compounds = len(model_obj.get("modelcompounds", []))
        n_biomasses = len(model_obj.get("biomasses", []))
        n_genes = len(json.loads(cobra_json).get("genes", []))
        n_compartments = len(model_obj.get("modelcompartments", []))

        _progress("Saving annotated genome and model...")
        ws = get_storage_service(token)
        if username and output_path.startswith(f"/{username}/{settings.plantseed_home_dir}/"):
            _ensure_home_folder(ws, username, settings.plantseed_home_dir)

        folder_meta = {
            "id": genome_id,
            "name": genome,
            "source_id": genome_id,
            "source": "PlantSEED",
            "type": "Plant",
            "genome_ref": f"{output_path}/genome",
            "organism_name": genome,
            "taxonomy": genome_obj["taxonomy"],
            "domain": genome_obj["domain"],
            "plantseed": "1",
            "num_reactions": str(n_reactions),
            "num_compounds": str(n_compounds),
            "num_genes": str(n_genes),
            "num_compartments": str(n_compartments),
            "num_biomasses": str(n_biomasses),
            "integrated_gapfills": "0",
            "unintegrated_gapfills": "0",
            "fba_count": "0",
        }
        genome_meta = {
            "id": genome_id,
            "scientific_name": genome,
            "domain": genome_obj["domain"],
            "source": "PlantSEED",
            "num_features": str(len(genome_obj["features"])),
            "num_proteins": str(len(records)),
        }
        ws.create({
            "objects": [
                [output_path, "modelfolder", folder_meta, ""],
                [f"{output_path}/genome", "genome", genome_meta, json.dumps(genome_obj)],
                [f"{output_path}/model", "model", {}, json.dumps(model_obj)],
                [f"{output_path}/cobra_model", "string", {}, cobra_json],
            ],
            "overwrite": 1,
        })
        try:
            from modelseed_api.jobs.tasks import _merge_ws_metadata
            _merge_ws_metadata(ws, output_path, folder_meta)
        except Exception as e:
            logger.warning("Failed to update folder metadata for %s: %s", output_path, e)
    finally:
        _cleanup(*run_dirs)

    return {
        "status": "success",
        "genome_id": genome_id,
        "output_path": output_path,
        "template_type": "plant",
        "reactions": n_reactions,
        "metabolites": n_compounds,
        "genes": n_genes,
        "classification": "Plant",
        "annotation": annotation_summary,
    }
