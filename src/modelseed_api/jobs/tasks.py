"""Celery tasks for the modelseed worker.

Each task runs on the 'modelseed' queue in the shared bioseed Redis scheduler.
Tasks mirror the subprocess job scripts (src/job_scripts/) to ensure parity.
"""

from __future__ import annotations

import json
import logging
import os

from modelseed_api.config import settings

# Celery is optional — only needed when running as a Celery worker.
# Job scripts import helpers from this module without Celery installed.
try:
    from modelseed_api.jobs.celery_app import app
except ImportError:
    # Create a stub so @app.task decorators don't crash at import time
    class _StubApp:
        @staticmethod
        def task(*args, **kwargs):
            def decorator(fn):
                return fn
            return decorator
    app = _StubApp()

logger = logging.getLogger(__name__)

# Paths from centralized config (set via MODELSEED_ env vars or .env file)
TEMPLATES_DIR = settings.templates_path
MODELSEED_DB_PATH = settings.modelseed_db_path
CB_ANNO_ONT_PATH = settings.cb_annotation_ontology_api_path

# Map template type to local file
TEMPLATE_FILES = {
    "core": "Core-V6.json",
    "gp": "GramPosModelTemplateV7.json",
    "gn": "GramNegModelTemplateV7.json",
    "grampos": "GramPosModelTemplateV7.json",
    "gramneg": "GramNegModelTemplateV7.json",
    "ar": "ArchaeaTemplateV6.json",
    "archaea": "ArchaeaTemplateV6.json",
}


def _merge_ws_metadata(ws, obj_path: str, new_meta: dict):
    """Merge new metadata into existing workspace metadata.

    PATRIC workspace update_metadata replaces the entire user_meta dict,
    so we must read existing metadata first, merge, then write back.
    ls on a folder lists its children, so we ls the parent and find our item.
    """
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


def _load_template(template_type: str):
    """Load a template from local JSON file using MSTemplateBuilder."""
    from modelseedpy import MSTemplateBuilder

    filename = TEMPLATE_FILES.get(template_type)
    if not filename:
        raise ValueError(f"Unknown template type: {template_type}")

    path = os.path.join(TEMPLATES_DIR, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Template file not found: {path}")

    with open(path) as f:
        template_data = json.load(f)

    template = MSTemplateBuilder.from_dict(template_data).build()
    return template


_classifier = None  # Module-level cache


def _get_classifier():
    """Load genome classifier, downloading on first use (~25MB)."""
    global _classifier
    if _classifier is None:
        from modelseedpy.helpers import get_classifier
        logger.info("Loading genome classifier (will download ~25MB on first use)...")
        _classifier = get_classifier("knn_ACNP_RAST_filter_01_17_2023")
        logger.info("Genome classifier loaded successfully")
    return _classifier


# Map classifier single-letter codes to human-readable class names and template types
_CLASS_MAP = {
    "P": ("Gram Positive", "gp"),
    "N": ("Gram Negative", "gn"),
    "--": ("Gram Negative", "gn"),
    "A": ("Archaea", "ar"),
}


def _classify_genome(genome):
    """Classify genome and return (class_name, template_type) or raise on unsupported.

    Runs the ML classifier locally so we can load templates from local files
    instead of letting KBUtilLib call the KBase workspace.
    Returns e.g. ("Gram Negative", "gn") or ("Archaea", "ar").
    Raises ValueError for Cyanobacteria or unknown classes.
    """
    classifier = _get_classifier()
    raw_class = classifier.classify(genome)
    logger.info("Classifier returned: %s", raw_class)

    if raw_class == "C":
        raise ValueError("Cyanobacteria not yet supported")

    entry = _CLASS_MAP.get(raw_class)
    if entry is None:
        raise ValueError(f"Unrecognized genome class: {raw_class}")

    return entry


def _init_kwargs(token: str) -> dict:
    """Common kwargs for KBUtilLib initialization."""
    # WORKAROUND: cobrakbase requires non-empty KB_AUTH_TOKEN
    os.environ.setdefault("KB_AUTH_TOKEN", "unused")
    return dict(
        config_file=False,
        token_file=None,
        kbase_token_file=None,
        token={"patric": token, "kbase": "unused"},
        modelseed_path=MODELSEED_DB_PATH,
        cb_annotation_ontology_api_path=CB_ANNO_ONT_PATH,
    )


class ModelNotFoundError(RuntimeError):
    """Raised when a workspace model the user asked to operate on is absent.

    Translated from the underlying WorkspaceError('Object not found') which
    propagates as an inscrutable '_ERROR_Object not found!_ERROR_' to users.
    The message here is what celery surfaces to the UI as the failure reason.
    """


class GenomeNotFoundError(RuntimeError):
    """Raised when a BV-BRC genome lookup fails to find the requested ID.

    The upstream failure shape varies: BVBRCUtils raises
    ``ValueError("No genome found with ID ...")`` for some IDs, and the
    BV-BRC API returns HTTP 500 (sometimes 404) for others. Both shapes
    funnel through ``_fetch_bvbrc_genome`` and become this exception with
    a user-actionable message.
    """


_BVBRC_NOT_FOUND_MARKERS: tuple[str, ...] = (
    "No genome found with ID",  # BVBRCUtils ValueError for unknown ID
    " 500 ",                    # HTTPError 5xx codes (with spaces to avoid
    " 404 ",                    # matching unrelated digits)
    "Internal Server Error",
    "Not Found",
)


def _fetch_bvbrc_genome(bvbrc, genome_id: str) -> dict:
    """Fetch a KBase-format genome dict from BV-BRC.

    Translates the several shapes of not-found error that BV-BRC and
    KBUtilLib can surface into a single :class:`GenomeNotFoundError` with
    a message that tells the user what to do (check the ID, or use the
    RAST job flow).

    Pulled out of ``reconstruct`` so the translation can be unit-tested
    without dragging in the rest of the build pipeline.
    """
    try:
        return bvbrc.build_kbase_genome_from_api(genome_id)
    except Exception as exc:
        msg = str(exc)
        looks_like_not_found = (
            "HTTPError" in type(exc).__name__
            or any(marker in msg for marker in _BVBRC_NOT_FOUND_MARKERS)
        )
        if looks_like_not_found:
            raise GenomeNotFoundError(
                f"Genome '{genome_id}' could not be fetched from BV-BRC. "
                f"Check the genome ID is correct (BV-BRC format, e.g. "
                f"'83332.12'). If you meant a RAST job id, use the RAST "
                f"job submission flow instead."
            ) from exc
        raise


def _fetch_model_obj(ws, model_ref: str, token: str) -> dict:
    """Fetch model JSON from workspace, handling Shock URLs.

    Raises ModelNotFoundError with a user-actionable message when the model
    doesn't exist; this is the single biggest source of confusing 5xx-style
    task failures on the live site (top hit: bioinfoc@bvbrc cycling gapfill/
    FBA on /<user>/modelseed/<name>/model paths whose reconstruct never
    completed or saved to that path).
    """
    from modelseed_api.services.workspace_service import WorkspaceError

    try:
        result = ws.get({"objects": [f"{model_ref}/model"]})
    except WorkspaceError as exc:
        if "Object not found" in str(exc):
            raise ModelNotFoundError(
                f"No model found at '{model_ref}/model'. Check that your "
                f"reconstruct job completed successfully and saved a model "
                f"to this path, or pass a different ref."
            ) from exc
        raise
    if not result:
        raise ModelNotFoundError(
            f"No model found at '{model_ref}/model'. Check that your "
            f"reconstruct job completed successfully and saved a model "
            f"to this path, or pass a different ref."
        )

    raw_data = result[0][1] if len(result[0]) > 1 else "{}"
    if isinstance(raw_data, str):
        if raw_data.startswith("http") and "shock" in raw_data:
            import requests
            resp = requests.get(
                raw_data.rstrip("/") + "?download",
                headers={"Authorization": f"OAuth {token}"},
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()
        return json.loads(raw_data)
    if isinstance(raw_data, dict):
        return raw_data
    return {}


def _patch_model_for_builder(model_obj: dict) -> dict:
    """Add default optional fields that FBAModelBuilder expects but old models lack.

    cobrakbase FBAModelBuilder accesses 'optionalSubunit' with a hard key
    lookup (not .get()), so models missing this @optional field crash with
    KeyError('optionalSubunit'). This patches the data in place.
    """
    for rxn in model_obj.get("modelreactions", []):
        for prot in rxn.get("modelReactionProteins", []):
            for sub in prot.get("modelReactionProteinSubunits", []):
                sub.setdefault("optionalSubunit", 0)
    return model_obj


def _load_media(media_ref: str, token: str):
    """Load media from workspace and convert to MSMedia object.

    Uses the storage service (our API proxy) rather than PatricWSUtils
    directly, because the old workspace API sometimes returns empty data
    for public media while our proxy handles it correctly.
    """
    from modelseed_api.services.storage_factory import get_storage_service
    from modelseedpy.core.msmedia import MSMedia, MediaCompound

    ws = get_storage_service(token)
    result = ws.get({"objects": [media_ref]})
    if not result or not result[0]:
        raise ValueError(f"Media not found: {media_ref}")

    raw = result[0][1] if len(result[0]) > 1 else ""

    # Handle Shock URLs
    if isinstance(raw, str) and raw.startswith("http") and "shock" in raw:
        import requests as _req
        resp = _req.get(
            raw.rstrip("/") + "?download",
            headers={"Authorization": f"OAuth {token}"},
            timeout=60,
        )
        resp.raise_for_status()
        raw = resp.text

    # Parse media (JSON or TSV format)
    media_compounds = []
    if isinstance(raw, str):
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                media_compounds = obj.get("mediacompounds", [])
        except (json.JSONDecodeError, TypeError):
            # TSV format: id\tname\tconcentration\tminflux\tmaxflux
            lines = raw.strip().split("\n")
            for line in lines[1:]:
                cols = line.split("\t")
                if len(cols) >= 5:
                    media_compounds.append({
                        "compound_ref": "~/compounds/" + cols[0],
                        "concentration": float(cols[2]) if cols[2] else 0.001,
                        "minFlux": float(cols[3]) if cols[3] else -100,
                        "maxFlux": float(cols[4]) if cols[4] else 100,
                    })
    elif isinstance(raw, dict):
        media_compounds = raw.get("mediacompounds", [])

    if not media_compounds:
        raise ValueError(f"No media compounds found in {media_ref}")

    # Convert to MSMedia
    media_name = media_ref.rstrip("/").split("/")[-1]
    ms_media = MSMedia(media_name, name=media_name)
    for mc in media_compounds:
        cpd_id = mc.get("compound_ref", "").split("/")[-1] if "compound_ref" in mc else mc.get("id", "")
        if cpd_id:
            ms_media.mediacompounds.append(
                MediaCompound(
                    cpd_id,
                    -1 * mc.get("maxFlux", 100),
                    -1 * mc.get("minFlux", -100),
                    concentration=mc.get("concentration", 0.001),
                )
            )
    logger.info("Loaded media %s: %d compounds", media_ref, len(ms_media.mediacompounds))
    return ms_media


def _resolve_media_ref(media_ref: str) -> str | None:
    """Resolve media reference to a workspace path.

    Returns None for 'Complete', empty, or ANY path ending in '/Complete'
    (case-insensitive). 'Complete' means all exchanges open; there's no
    workspace object to load. The path-ending check exists because the
    frontend defaults to the canonical public path
    `/chenry/public/modelsupport/media/Complete`; loading that path
    fails (the workspace object has no parseable compound list) so we
    treat it identically to the bare keyword.

    Bare names (no '/') are resolved under the public media folder.
    """
    if not media_ref or media_ref.lower() == "complete":
        return None
    if media_ref.rstrip("/").lower().endswith("/complete"):
        return None
    if "/" in media_ref:
        return media_ref  # Already a workspace path
    # Bare name. Look under public media folder.
    from modelseed_api.config import settings
    return f"{settings.public_media_path}/{media_ref}"


def _apply_media(cobra_model, ms_media):
    """Apply MSMedia constraints to a cobra.Model.

    Closes all exchange reactions then opens only those whose compounds
    appear in the media, using cobra's native ``model.medium`` property.
    """
    rxn_ids = {r.id for r in cobra_model.reactions}
    medium = {}
    for cpd in ms_media.mediacompounds:
        exc_rxn_id = f"EX_{cpd.id}_e0"
        if exc_rxn_id in rxn_ids:
            medium[exc_rxn_id] = cpd.maxFlux or 1000.0
    if medium:
        cobra_model.medium = medium
        logger.info("Applied media: %d exchange reactions open", len(medium))
    else:
        logger.warning("Media had no matching exchange reactions — running with default bounds")


def _fix_gapfilling_metadata(ws_data: dict, media_workspace_ref: str | None) -> None:
    """Override gapfilling metadata produced by ModelSEEDpy.

    ModelSEEDpy's MSModelUtil.create_kb_gapfilling_data() sets:
      - ``id`` to the media name (e.g. "Carbon-D-Glucose")
      - ``media_ref`` to "KBaseMedia/Empty" when our MSMedia lacks an
        ``info`` attribute (which it always does in our pipeline because
        we build MSMedia from workspace TSV)
      - empty ``rundate``

    This rewrites those fields to use sequential ``gf.N`` IDs, the real
    workspace ``media_ref`` we passed in, and the current ISO 8601
    timestamp.  It also rekeys ``gapfill_data`` on each model reaction
    to match the new IDs so the link stays intact.
    """
    from datetime import datetime, timezone

    gapfillings = ws_data.get("gapfillings") or []
    if not gapfillings:
        return

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    media_ref_clean = (media_workspace_ref or "").strip() or "Complete"

    # Find the next available gf.N index (preserve any pre-existing gf.N entries)
    used_indexes = set()
    for gf in gapfillings:
        existing_id = str(gf.get("id", ""))
        if existing_id.startswith("gf."):
            try:
                used_indexes.add(int(existing_id[3:]))
            except ValueError:
                pass
    next_idx = 0

    id_remap: dict[str, str] = {}
    for gf in gapfillings:
        old_id = str(gf.get("id", ""))
        # Skip entries that already look like proper gf.N
        if old_id.startswith("gf.") and old_id[3:].isdigit():
            new_id = old_id
        else:
            while next_idx in used_indexes:
                next_idx += 1
            new_id = f"gf.{next_idx}"
            used_indexes.add(next_idx)
            next_idx += 1

        if old_id and old_id != new_id:
            id_remap[old_id] = new_id

        gf["id"] = new_id
        gf["gapfill_id"] = new_id
        if not gf.get("media_ref") or gf["media_ref"] == "KBaseMedia/Empty":
            gf["media_ref"] = media_ref_clean
        if not gf.get("rundate"):
            gf["rundate"] = now_iso

    # Rekey gapfill_data on each model reaction
    if id_remap:
        for rxn in ws_data.get("modelreactions", []):
            gd = rxn.get("gapfill_data")
            if not isinstance(gd, dict):
                continue
            for old_id, new_id in id_remap.items():
                if old_id in gd and new_id not in gd:
                    gd[new_id] = gd.pop(old_id)


def _set_biomass_objective(model) -> None:
    """Set the model objective to bio1 if present, otherwise fall back to the first
    biomass-like reaction. Silently skips if no biomass reaction is found."""
    if "bio1" in {r.id for r in model.reactions}:
        model.objective = "bio1"
        return
    biomass_rxns = [r for r in model.reactions if "bio" in r.id.lower()]
    if biomass_rxns:
        model.objective = biomass_rxns[0].id

@app.task(bind=True, name="modelseed.reconstruct")
def reconstruct(
    self,
    token: str,
    genome: str = "",
    genome_fasta: str | None = None,
    rast_job_id: str | None = None,
    rast_genome_id: str | None = None,
    template_type: str = "auto",
    atp_safe: bool = True,
    gapfill: bool = False,
    media: str | None = None,
    output_path: str | None = None,
    # Legacy aliases
    genome_id: str = "",
    media_ref: str | None = None,
):
    """Build a metabolic model from one of three input modes.

    Three input modes (mutually exclusive, exactly one resolves):
      1. **BV-BRC genome ID** (default): pulls the genome via BV-BRC API,
         converts to MSGenome, runs reconstruction. `genome` is the BV-BRC
         genome ID (e.g. "83332.12").
      2. **Protein FASTA** (when `genome_fasta` is set): uses MSBuilder
         directly with annotate_with_rast. `genome` becomes a display name.
      3. **RAST job** (when `rast_job_id` is set): fetches the already-
         annotated genome via MSSS getRastGenomeData, translates to KBase
         Genome dict, feeds into reconstruction. `rast_genome_id` is also
         required to pick the genome inside the RAST job. `genome` is a
         display name. RAST token (the request `token`) is passed to MSSS.

    When template_type is "auto" (default), the genome classifier auto-detects
    the organism type (gram-neg, gram-pos, archaea). Users can bypass the
    classifier by specifying "gn", "gp", or "ar" explicitly.
    """
    # Resolve parameter aliases
    genome_id = genome or genome_id
    media_ref = media or media_ref
    if not genome_id:
        raise ValueError("genome (or genome_id) is required")
    # Strip source prefix if frontend sends "PATRIC:469009.4" or "RAST:12345"
    if ":" in genome_id:
        genome_id = genome_id.split(":", 1)[1]

    # When rast_job_id is set, the saved model should be named after the RAST
    # genome, not the user-supplied display name.
    output_id_for_path = rast_genome_id if rast_job_id else genome_id

    # Compute default output path from username + ID
    if not output_path:
        username = ""
        for part in token.split("|"):
            if part.startswith("un="):
                username = part[3:]
                break
        if username:
            output_path = f"/{username}/modelseed/{output_id_for_path}"

    # Load template: defer when "auto" (classifier will pick the right one)
    self.update_state(state="PROGRESS", meta={"status": "Loading templates..."})
    if template_type == "auto":
        gs_template_obj = None
    else:
        gs_template_obj = _load_template(template_type)

    if rast_job_id:
        # RAST-job path: fetch annotated genome via MSSS, translate, run
        # the same reconstruction as BV-BRC. Skips both BV-BRC fetch and
        # FASTA re-annotation; the genome already has functions assigned.
        if not rast_genome_id:
            raise ValueError(
                "rast_genome_id is required when rast_job_id is set"
            )
        self.update_state(
            state="PROGRESS",
            meta={"status": f"Fetching RAST genome {rast_genome_id}..."},
        )
        from modelseed_api.services.rast_service import RastService
        from kbutillib import MSReconstructionUtils

        kwargs = _init_kwargs(token)
        rast_svc = RastService()
        kbase_genome = rast_svc.get_genome(
            rast_token=token,
            genome_id=rast_genome_id,
            job_id=rast_job_id,
        )

        organism_name = kbase_genome.get("scientific_name", "")
        taxonomy = kbase_genome.get("taxonomy", "")
        domain = kbase_genome.get("domain", "")

        # Same conversion + build path as the BV-BRC branch from here.
        self.update_state(state="PROGRESS", meta={"status": "Converting genome..."})
        recon = MSReconstructionUtils(**kwargs)
        genome = recon.get_msgenome_from_dict(kbase_genome)

        core_template = _load_template("core")

        class_name = None
        resolved_type = template_type
        if template_type == "auto":
            self.update_state(state="PROGRESS", meta={"status": "Classifying genome..."})
            class_name, resolved_type = _classify_genome(genome)
            gs_template_obj = _load_template(resolved_type)
            logger.info(
                "Auto-classified RAST genome as %s, using template %s",
                class_name,
                resolved_type,
            )

        self.update_state(state="PROGRESS", meta={"status": "Building model..."})
        output, mdlutl = recon.build_metabolic_model(
            genome=genome,
            genome_classifier=None,
            core_template=core_template,
            gs_template_obj=gs_template_obj,
            gs_template=resolved_type,
            atp_safe=atp_safe,
        )
        if class_name:
            output["Class"] = class_name

        if mdlutl is None:
            return {
                "status": "failed",
                "error": "Reconstruction returned no model",
                "output": output,
            }

        # Override genome_id used downstream so saved metadata reflects the
        # RAST genome rather than the user-supplied display name.
        genome_id = rast_genome_id

    elif genome_fasta:
        # ── FASTA path: unified DNA+protein annotation via tutorial.theseed.org
        # then MSBuilder. DNA/protein detection and RAST pipeline-stage
        # selection happen inside annotate_fasta; the rest of the path is
        # input-type-agnostic.
        from modelseed_api.services.genome_annotator import annotate_fasta
        from modelseedpy.core.msbuilder import MSBuilder

        self.update_state(state="PROGRESS", meta={"status": "Annotating genome..."})
        ms_genome = annotate_fasta(genome_fasta, scientific_name=genome_id)
        logger.info(
            "Annotated FASTA -> %d features (%d with assigned function)",
            len(ms_genome.features),
            sum(1 for f in ms_genome.features if f.ontology_terms.get("RAST")),
        )

        organism_name = genome_id  # Use the genome field as display name
        taxonomy = ""
        domain = ""

        # Annotation is already done; tell MSBuilder to skip its internal
        # RAST call. template=None triggers auto-selection when "auto".
        self.update_state(state="PROGRESS", meta={"status": "Building model..."})
        model = MSBuilder.build_metabolic_model(
            genome_id,
            ms_genome,
            template=gs_template_obj,  # None when auto, loaded template when explicit
            annotate_with_rast=False,
            gapfill_model=False,  # We handle gapfill separately below
        )

        from modelseedpy.core.msmodelutl import MSModelUtil
        mdlutl = MSModelUtil.get(model)
        n_reactions = len(model.reactions)
        n_genes = len(model.genes)
        output = {
            "Reactions": n_reactions,
            "Model genes": n_genes,
            "Class": template_type,
        }
    else:
        # ── BV-BRC path: KBUtilLib pipeline ──
        from kbutillib import BVBRCUtils, MSReconstructionUtils

        kwargs = _init_kwargs(token)

        # Step 1: Fetch genome from BV-BRC API
        self.update_state(state="PROGRESS", meta={"status": "Fetching genome..."})
        bvbrc = BVBRCUtils(**kwargs)
        kbase_genome = _fetch_bvbrc_genome(bvbrc, genome_id)

        # Extract organism/taxonomy info from genome
        organism_name = kbase_genome.get("scientific_name", "")
        taxonomy = kbase_genome.get("taxonomy", "")
        domain = kbase_genome.get("domain", "")

        # Step 2: Convert to MSGenome
        self.update_state(state="PROGRESS", meta={"status": "Converting genome..."})
        recon = MSReconstructionUtils(**kwargs)
        genome = recon.get_msgenome_from_dict(kbase_genome)

        core_template = _load_template("core")

        # Step 4: Classify genome (if auto) and build model
        # We classify ourselves and load templates from local files to avoid
        # KBUtilLib calling the KBase workspace (which requires a KBase token).
        class_name = None
        if template_type == "auto":
            self.update_state(state="PROGRESS", meta={"status": "Classifying genome..."})
            class_name, resolved_type = _classify_genome(genome)
            gs_template_obj = _load_template(resolved_type)
            logger.info("Auto-classified as %s, using template %s", class_name, resolved_type)

        self.update_state(state="PROGRESS", meta={"status": "Building model..."})
        output, mdlutl = recon.build_metabolic_model(
            genome=genome,
            genome_classifier=None,
            core_template=core_template,
            gs_template_obj=gs_template_obj,
            gs_template=template_type if template_type != "auto" else resolved_type,
            atp_safe=atp_safe,
        )

        # Set classification from our local classifier (KBUtilLib skips it
        # when we pass genome_classifier=None)
        if class_name:
            output["Class"] = class_name

        if mdlutl is None:
            return {
                "status": "skipped",
                "comments": output.get("Comments", []),
            }

    # If auto classification was used, gs_template_obj was already resolved
    # before build_metabolic_model(). For FASTA path with auto, resolve now.
    if gs_template_obj is None:
        _class_to_type = {
            "Gram Negative": "gn", "Gram Positive": "gp", "Archaea": "ar",
        }
        resolved_type = _class_to_type.get(output.get("Class", ""), "gn")
        gs_template_obj = _load_template(resolved_type)

    # Step 5: Gapfill if requested
    gapfill_count = 0
    if gapfill:
        self.update_state(state="PROGRESS", meta={"status": "Running gapfilling..."})
        from modelseedpy.core.msmedia import MSMedia

        # Load media from workspace if specified
        ms_media = None
        ws_media_path = _resolve_media_ref(media_ref)
        if ws_media_path:
            ms_media = _load_media(ws_media_path, token)

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
            atp_safe=atp_safe,
        )
        gapfill_count = gf_output.get("GS GF") or 0
        logger.info("Gapfill: GS_GF=%s Growth=%s", gapfill_count, gf_output.get("Growth"))

    # Compute model stats
    n_reactions = output.get("Reactions", len(mdlutl.model.reactions))
    n_genes = output.get("Model genes", len(mdlutl.model.genes))
    n_metabolites = len(mdlutl.model.metabolites)
    n_compartments = len(mdlutl.model.compartments)
    classification = output.get("Class", template_type)

    # Step 6: Save model to storage
    if output_path:
        self.update_state(state="PROGRESS", meta={"status": "Saving model..."})
        from modelseed_api.services.storage_factory import get_storage_service
        ws = get_storage_service(token)

        # Save cobra JSON BEFORE CobraModelConverter (which loses exchange
        # bounds and breaks FBA). cobra.io roundtrip is lossless.
        import cobra.io
        _set_biomass_objective(mdlutl.model)
        cobra_json = json.dumps(cobra.io.model_to_dict(mdlutl.model))

        if not hasattr(mdlutl.model, 'get_data'):
            from cobrakbase.core.kbasefba.fbamodel_from_cobra import CobraModelConverter
            mdlutl.model = CobraModelConverter(mdlutl.model).build()
        mdlutl.save_attributes()
        ws_data = mdlutl.model.get_data()

        # Persist gapfilling solution data to model object
        if gapfill_count > 0:
            mdlutl.create_kb_gapfilling_data(ws_data)
            _fix_gapfilling_metadata(ws_data, _resolve_media_ref(media_ref))

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
            _merge_ws_metadata(ws, output_path, folder_meta)
            logger.info("Updated folder metadata for %s", output_path)
        except Exception as e:
            logger.warning("Failed to update folder metadata for %s: %s", output_path, e)

    return {
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


@app.task(bind=True, name="modelseed.gapfill")
def gapfill(
    self,
    token: str,
    model: str = "",
    media: str | None = None,
    template_type: str = "gn",
    # Legacy aliases (kept for in-flight tasks during deploy)
    model_ref: str = "",
    media_ref: str | None = None,
):
    """Run gapfilling on a model.

    Mirrors src/job_scripts/gapfill.py for full parity.
    """
    # Resolve parameter aliases (dispatcher sends 'model'/'media',
    # legacy callers may send 'model_ref'/'media_ref')
    model_ref = model or model_ref
    media_ref = media or media_ref
    if not model_ref:
        raise ValueError("model (or model_ref) is required")

    _init_kwargs(token)  # sets KB_AUTH_TOKEN

    self.update_state(state="PROGRESS", meta={"status": "Loading model..."})

    from modelseed_api.services.storage_factory import get_storage_service
    ws = get_storage_service(token)
    model_obj = _fetch_model_obj(ws, model_ref, token)

    # Prefer cobra_model (lossless cobra JSON) over FBAModelBuilder.
    # FBAModelBuilder's round-trip loses exchange bounds and can produce
    # infeasible models, preventing gapfill from finding any solution.
    self.update_state(state="PROGRESS", meta={"status": "Converting model..."})
    from modelseedpy.core.msmodelutl import MSModelUtil

    fba_model = None
    try:
        cobra_result = ws.get({"objects": [f"{model_ref}/cobra_model"]})
        if cobra_result and cobra_result[0]:
            raw = cobra_result[0][1] if len(cobra_result[0]) > 1 else None
            if raw and isinstance(raw, str) and not raw.startswith("http"):
                import cobra.io
                fba_model = cobra.io.model_from_dict(json.loads(raw))
                fba_model.objective = "bio1"
                logger.info("Loaded cobra_model from workspace (lossless)")
    except Exception:
        pass  # cobra_model not available

    if fba_model is None:
        from cobrakbase.core.kbasefba.fbamodel_builder import FBAModelBuilder
        fba_model = FBAModelBuilder(_patch_model_for_builder(model_obj)).build()
        logger.info("Loaded model via FBAModelBuilder (fallback)")

    mdlutl = MSModelUtil.get(fba_model)

    # Load template
    self.update_state(state="PROGRESS", meta={"status": "Loading template..."})
    template = _load_template(template_type)

    # Load media if specified
    # "Complete" means all exchanges open — pass empty MSMedia to MSGapfill.
    ms_media = None
    ws_media_path = _resolve_media_ref(media_ref)
    if ws_media_path:
        self.update_state(state="PROGRESS", meta={"status": "Loading media..."})
        ms_media = _load_media(ws_media_path, token)

    # Run gapfilling via KBUtilLib's gapfill_metabolic_model which handles
    # ATP tests, auto_sink, run_multi_gapfill, and growth verification.
    self.update_state(state="PROGRESS", meta={"status": "Running gapfilling..."})
    from modelseedpy.core.msmedia import MSMedia

    if ms_media is None:
        ms_media = MSMedia("Complete", "Complete")

    core_template = _load_template("core")
    kwargs = _init_kwargs(token)
    from kbutillib import MSReconstructionUtils
    recon = MSReconstructionUtils(**kwargs)

    gf_output, solutions, _, _ = recon.gapfill_metabolic_model(
        mdlutl=mdlutl,
        genome=None,
        media_objs=[ms_media],
        templates=[template],
        core_template=core_template,
        atp_safe=True,
    )

    solutions_count = gf_output.get("GS GF") or 0
    added_reactions = []
    for media_key in solutions:
        sol = solutions[media_key]
        for rxn_id in sol.get("new", {}):
            added_reactions.append(rxn_id)
        for rxn_id in sol.get("reversed", {}):
            added_reactions.append(rxn_id)
    logger.info("Gapfill result: %s", gf_output.get("Growth"))

    # Save gapfilled model back to workspace
    if solutions_count > 0:
        self.update_state(state="PROGRESS", meta={"status": "Saving model..."})

        # Save cobra JSON BEFORE any lossy conversion — cobra.io
        # roundtrip is lossless and preserves exchange bounds.
        import cobra.io
        fba_model.objective = "bio1"
        cobra_json = json.dumps(cobra.io.model_to_dict(fba_model))

        # If fba_model came from cobra.io (not FBAModelBuilder), it
        # won't have get_data(). Convert back to workspace format.
        if not hasattr(fba_model, 'get_data'):
            from cobrakbase.core.kbasefba.fbamodel_from_cobra import CobraModelConverter
            # Preserve gapfilling data — the new MSModelUtil from the
            # converted model would have an empty integrated_gapfillings list,
            # losing the solution we just integrated.
            old_integrated = mdlutl.integrated_gapfillings
            fba_model = CobraModelConverter(fba_model).build()
            mdlutl = MSModelUtil.get(fba_model)
            mdlutl.integrated_gapfillings = old_integrated

        ws_data = fba_model.get_data()
        # Preserve KBase-specific fields that cobra.io roundtrip loses:
        # gapfillings, fbaFormulations/fba_studies, and reaction gapfill_data.
        for key in ("gapfillings", "fbaFormulations", "fba_studies"):
            if key in model_obj and model_obj[key]:
                ws_data.setdefault(key, [])
                existing_ids = {g.get("id") for g in ws_data[key]}
                for entry in model_obj[key]:
                    if entry.get("id") not in existing_ids:
                        ws_data[key].append(entry)
        # Restore gapfill_data on reactions from original model data
        old_gf_data = {}
        for rxn in model_obj.get("modelreactions", []):
            if rxn.get("gapfill_data"):
                old_gf_data[rxn["id"]] = rxn["gapfill_data"]
        if old_gf_data:
            for rxn in ws_data.get("modelreactions", []):
                if rxn["id"] in old_gf_data:
                    rxn.setdefault("gapfill_data", {}).update(old_gf_data[rxn["id"]])
        mdlutl.create_kb_gapfilling_data(ws_data)
        _fix_gapfilling_metadata(ws_data, _resolve_media_ref(media_ref))

        model_data = json.dumps(ws_data)
        ws.create({
            "objects": [
                [f"{model_ref}/model", "model", {}, model_data],
                [f"{model_ref}/cobra_model", "string", {}, cobra_json],
            ],
            "overwrite": 1,
        })

        n_gapfillings = len(ws_data.get("gapfillings", []))
        try:
            _merge_ws_metadata(ws, model_ref, {
                "num_reactions": str(len(fba_model.reactions)),
                "num_compounds": str(len(fba_model.metabolites)),
                "integrated_gapfills": str(n_gapfillings),
            })
            logger.info("Updated gapfill metadata for %s: %d gapfillings", model_ref, n_gapfillings)
        except Exception as e:
            logger.warning("Failed to update gapfill metadata for %s: %s", model_ref, e)

    return {
        "status": "success",
        "model_ref": model_ref,
        "solutions_count": solutions_count,
        "added_reactions": len(added_reactions),
        "added_reaction_ids": added_reactions,
    }


@app.task(bind=True, name="modelseed.fba")
def run_fba(
    self,
    token: str,
    model: str = "",
    media: str | None = None,
    # Legacy aliases
    model_ref: str = "",
    media_ref: str | None = None,
):
    """Run flux balance analysis on a model.

    Mirrors src/job_scripts/run_fba.py for full parity.
    """
    # Resolve parameter aliases
    model_ref = model or model_ref
    media_ref = media or media_ref
    if not model_ref:
        raise ValueError("model (or model_ref) is required")

    self.update_state(state="PROGRESS", meta={"status": "Loading model..."})

    from modelseed_api.services.storage_factory import get_storage_service

    ws = get_storage_service(token)

    # Prefer cobra_model (lossless cobra JSON) over workspace format.
    # CobraModelConverter.get_data() loses exchange bounds, making FBA
    # return 0 for all models. cobra.io roundtrip is lossless.
    cobra_model = None
    try:
        cobra_result = ws.get({"objects": [f"{model_ref}/cobra_model"]})
        if cobra_result and cobra_result[0]:
            raw = cobra_result[0][1] if len(cobra_result[0]) > 1 else None
            if raw and isinstance(raw, str) and not raw.startswith("http"):
                import cobra.io
                cobra_model = cobra.io.model_from_dict(json.loads(raw))
                cobra_model.objective = "bio1"
                logger.info("Loaded cobra_model from workspace for %s", model_ref)
    except Exception:
        pass  # cobra_model not available, fall back to workspace format

    if cobra_model is None:
        # Use FBAModelBuilder (same as gapfill) for a working cobra model,
        # then save cobra_model for future FBA runs (lazy migration).
        import cobra.io
        from cobrakbase.core.kbasefba.fbamodel_builder import FBAModelBuilder

        model_obj = _fetch_model_obj(ws, model_ref, token)
        cobra_model = FBAModelBuilder(_patch_model_for_builder(model_obj)).build()
        cobra_model.objective = "bio1"

        # Persist cobra_model so future FBA runs are fast + lossless
        try:
            cobra_json = json.dumps(cobra.io.model_to_dict(cobra_model))
            ws.create({
                "objects": [[
                    f"{model_ref}/cobra_model", "string", {}, cobra_json,
                ]],
                "overwrite": 1,
            })
            logger.info("Migrated: saved cobra_model for %s", model_ref)
        except Exception:
            logger.warning("Could not save cobra_model for %s", model_ref, exc_info=True)

        logger.info("Loaded model via FBAModelBuilder (fallback) for %s", model_ref)
    else:
        # Still need model_obj for saving FBA study back to model
        model_obj = _fetch_model_obj(ws, model_ref, token)

    # Load and apply media constraints if specified
    ws_media_path = _resolve_media_ref(media_ref)
    if ws_media_path:
        self.update_state(state="PROGRESS", meta={"status": "Loading media..."})
        ms_media = _load_media(ws_media_path, token)
        _apply_media(cobra_model, ms_media)
        logger.info("Loaded media from %s for FBA on %s", ws_media_path, model_ref)

    # Run FBA
    self.update_state(state="PROGRESS", meta={"status": "Running FBA..."})
    solution = cobra_model.optimize()

    # Collect flux results
    fluxes = {}
    for rxn in cobra_model.reactions:
        if abs(solution.fluxes[rxn.id]) > 1e-6:
            fluxes[rxn.id] = round(solution.fluxes[rxn.id], 6)

    objective_value = round(solution.objective_value, 6) if solution.objective_value else 0

    # Determine next FBA ID (fba.0, fba.1, ...)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Use whichever key the model already has (fbaFormulations for legacy models)
    fba_key = "fbaFormulations" if "fbaFormulations" in model_obj else "fba_studies"
    existing_studies = model_obj.get(fba_key, [])
    fba_idx = len(existing_studies)
    fba_id = f"fba.{fba_idx}"

    # Build FBA study record for the model object
    fba_record = {
        "id": fba_id,
        "ref": f"{model_ref}/{fba_id}",
        "media_ref": media_ref or "Complete",
        "objectiveValue": objective_value,
        "objective_function": "bio1",
        "rundate": now,
    }

    # Build KBase-compatible FBAReactionVariables / FBACompoundVariables
    # so Vibhav's frontend can parse flux data via parseReactionFluxes()
    fba_rxn_vars = []
    fba_cpd_vars = []
    for rxn in cobra_model.reactions:
        flux = solution.fluxes[rxn.id]
        fba_rxn_vars.append({
            "modelreaction_ref": f"~/modelreactions/id/{rxn.id}",
            "value": round(flux, 6),
            "lowerBound": rxn.lower_bound,
            "upperBound": rxn.upper_bound,
            "class": "Blocked" if abs(flux) < 1e-6 else ("Positive" if flux > 0 else "Negative"),
            "name": rxn.name or rxn.id,
        })
    for met in cobra_model.metabolites:
        if met.id.endswith("_e0"):
            exc_rxn_id = f"EX_{met.id}"
            if exc_rxn_id in solution.fluxes:
                flux = solution.fluxes[exc_rxn_id]
                fba_cpd_vars.append({
                    "modelcompound_ref": f"~/modelcompounds/id/{met.id}",
                    "value": round(flux, 6),
                    "lowerBound": -1000,
                    "upperBound": 1000,
                    "class": "Blocked" if abs(flux) < 1e-6 else ("Uptake" if flux < 0 else "Secretion"),
                    "name": met.name or met.id,
                })

    # Save FBA result object to workspace
    self.update_state(state="PROGRESS", meta={"status": "Saving FBA results..."})
    fba_result_obj = {
        "id": fba_id,
        "model_ref": model_ref,
        "media_ref": media_ref or "Complete",
        "objectiveValue": objective_value,
        "status": solution.status,
        "nonzero_fluxes": len(fluxes),
        "fluxes": fluxes,
        "FBAReactionVariables": fba_rxn_vars,
        "FBACompoundVariables": fba_cpd_vars,
        "rundate": now,
    }
    ws.create({
        "objects": [[
            f"{model_ref}/{fba_id}",
            "fba",
            {},
            json.dumps(fba_result_obj),
        ]],
        "overwrite": 1,
    })

    # Append FBA study to model and save back (use the same key the model uses)
    if fba_key not in model_obj:
        model_obj[fba_key] = []
    model_obj[fba_key].append(fba_record)
    ws.create({
        "objects": [[
            f"{model_ref}/model",
            "model",
            {},
            json.dumps(model_obj),
        ]],
        "overwrite": 1,
    })

    # Update folder metadata with FBA count
    try:
        _merge_ws_metadata(ws, model_ref, {
            "fba_count": str(fba_idx + 1),
        })
    except Exception as e:
        logger.warning("Failed to update fba_count metadata for %s: %s", model_ref, e)

    return {
        "status": "success",
        "model_ref": model_ref,
        "fba_id": fba_id,
        "objective_value": objective_value,
        "status_fba": solution.status,
        "nonzero_fluxes": len(fluxes),
    }


# ─────────────────────────────────────────────────────────────────────
# Bulk reconstruction (Phase 3)
# ─────────────────────────────────────────────────────────────────────


def _reconstruct_one_genome(
    *,
    genome_id: str,
    annotations: dict,
    template_type: str,
    atp_safe: bool,
    do_gapfill: bool,
    gapfill_media: str | None,
    do_fva: bool,
    kwargs: dict,
    data_dir: str,
    translator,
):
    """Build (and optionally gapfill + FVA) one model from PRD-shape annotations.

    Returns (mdlutl, summary_dict, fva_rich_map, fva_min_map, unmapped_gene_ids).
    Raises on per-genome failure; the caller wraps each call in try/except so
    one bad input doesn't abort the rest of the batch.
    """
    from kbutillib import MSReconstructionUtils
    from modelseedpy.core.annotationontology import AnnotationOntology
    from modelseedpy.core.msbuilder import MSBuilder

    # 1. Build AnnotationOntology from PRD payload + run upstream translation
    anno_ont = AnnotationOntology.from_prd_input(
        genome_id=genome_id,
        annotations=annotations,
        data_dir=data_dir,
        translator=translator,
    )
    incoming_gene_ids = set(annotations.keys())

    # 2. Build the model from the annotation ontology using MSBuilder. The
    #    fix-merged msbuilder.py:789 path now finds features correctly.
    msgenome = anno_ont.get_msgenome(merge_all=True)
    msgenome.annoont = anno_ont

    # 3. Pick template. "auto" runs the classifier; otherwise load the named one.
    if template_type == "auto":
        class_name, resolved_type = _classify_genome(msgenome)
    else:
        resolved_type = template_type
        class_name = None
    gs_template_obj = _load_template(resolved_type)
    core_template = _load_template("core")

    # 4. Compute reactions-to-add from the annotation ontology, then build.
    recon = MSReconstructionUtils(**kwargs)
    # Shim: compute_ontology_model_changes calls self.print_json_debug_file at
    # line 379 but the method is defined nowhere in KBUtilLib (dead reference,
    # likely a refactor leftover). Bind a no-op so the call works.
    # Upstream fix tracked separately; remove this once it lands.
    if not hasattr(recon, "print_json_debug_file"):
        recon.print_json_debug_file = lambda *a, **kw: None
    reactions_to_add = recon.compute_ontology_model_changes(
        anno_ont=anno_ont,
        annotation_priority=["PRD"],
    )
    output, mdlutl = recon.build_metabolic_model(
        genome=msgenome,
        genome_classifier=None,
        core_template=core_template,
        gs_template_obj=gs_template_obj,
        gs_template=resolved_type,
        atp_safe=atp_safe,
        reactions_to_add=reactions_to_add,
    )
    if class_name:
        output["Class"] = class_name

    # 5. Optional gapfill.
    gapfill_count = 0
    if do_gapfill:
        ms_media = _load_media(gapfill_media, kwargs.get("token", ""))
        gf_output, _solutions, _osol, _osol_media = recon.gapfill_metabolic_model(
            mdlutl=mdlutl,
            genome=msgenome,
            media_objs=[ms_media],
            templates=[gs_template_obj],
            core_template=core_template,
            atp_safe=atp_safe,
        )
        gapfill_count = gf_output.get("GS GF") or 0

    # 6. Optional FVA (rich + minimal media). Skipped silently when disabled
    #    or when the model has no objective (FVA needs one to run sensibly).
    from modelseed_api.services.bulk_export import compute_fva_classes
    fva_rich: dict = {}
    fva_min: dict = {}
    if do_fva:
        # Configure model objective for FVA; both runs use the same model
        # but with different media bounds applied (handled by media-pkg).
        _set_biomass_objective(mdlutl.model)
        try:
            fva_rich = compute_fva_classes(mdlutl.model, media_or_setup="rich")
            fva_min = compute_fva_classes(mdlutl.model, media_or_setup="minimal")
        except Exception as exc:
            logger.warning("FVA failed for %s, leaving columns empty: %s", genome_id, exc)

    # 7. Identify unmapped genes (in PRD payload but didn't land on any reaction).
    mapped_gene_ids = {g.id for g in mdlutl.model.genes}
    unmapped_gene_ids = sorted(incoming_gene_ids - mapped_gene_ids)

    summary = {
        "status": "success",
        "genome_id": genome_id,
        "reactions": len(mdlutl.model.reactions),
        "metabolites": len(mdlutl.model.metabolites),
        "genes": len(mdlutl.model.genes),
        "unmapped_genes": len(unmapped_gene_ids),
        "classification": output.get("Class", resolved_type),
        "gapfilled": do_gapfill,
        "gapfill_solutions": gapfill_count,
        "fva": do_fva,
    }
    return mdlutl, summary, fva_rich, fva_min, unmapped_gene_ids


def _run_bulk_reconstruct(
    token: str,
    genomes: list,
    template_type: str = "auto",
    atp_safe: bool = True,
    gapfill: bool = False,
    gapfill_media: str | None = None,
    fva: bool = True,
    output_path: str | None = None,
    job_id: str = "manual",
    progress_cb=None,
) -> dict:
    """Body of the bulk-reconstruct workflow. Reusable from both the
    Celery task and the subprocess job-script entry points; uses a
    `progress_cb(str)` callback so the Celery wrapper can mirror status
    updates without requiring the subprocess path to fake a Celery context.
    """
    import cobra.io
    from kbutillib import KBAnnotationUtils
    from modelseed_api.services.bulk_export import (
        build_genes_rows,
        build_reactions_rows,
        write_combined_csvs,
    )
    from modelseed_api.services.storage_factory import get_storage_service

    def _progress(msg: str) -> None:
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass
        logger.info(msg)

    if not genomes:
        raise ValueError("genomes list is empty")

    # Derive default output path from username + job_id.
    if not output_path:
        username = ""
        for part in token.split("|"):
            if part.startswith("un="):
                username = part[3:]
                break
        if not username:
            raise ValueError(
                "Could not derive username from token; pass output_path explicitly"
            )
        output_path = f"/{username}/modelseed/bulk_{job_id}"

    # Shared setup.
    kwargs = _init_kwargs(token)
    kbann = KBAnnotationUtils(**kwargs)
    translator = kbann.translate_term_to_modelseed
    data_dir = str(kbann.annoontology_dir / "data")

    ws = get_storage_service(token)
    _progress(f"Preparing batch of {len(genomes)} genome(s)...")

    all_rxn_rows: list = []
    all_gene_rows: list = []
    per_genome_results: dict = {}
    succeeded = 0
    failed = 0

    for idx, item in enumerate(genomes, start=1):
        gid = item.get("genome_id") or item.get("id") or f"genome_{idx}"
        annotations = item.get("annotations") or {}
        _progress(f"[{idx}/{len(genomes)}] reconstructing {gid}...")
        try:
            mdlutl, summary, fva_rich, fva_min, unmapped = _reconstruct_one_genome(
                genome_id=gid,
                annotations=annotations,
                template_type=template_type,
                atp_safe=atp_safe,
                do_gapfill=gapfill,
                gapfill_media=gapfill_media,
                do_fva=fva,
                kwargs=kwargs,
                data_dir=data_dir,
                translator=translator,
            )
            all_rxn_rows.extend(
                build_reactions_rows(mdlutl.model, gid, fva_rich, fva_min)
            )
            all_gene_rows.extend(
                build_genes_rows(mdlutl.model, gid, fva_rich, fva_min, unmapped)
            )

            try:
                cobra_json = json.dumps(cobra.io.model_to_dict(mdlutl.model))
                ws.create({
                    "objects": [
                        [f"{output_path}/model_{gid}.json", "string", {}, cobra_json],
                    ],
                    "overwrite": 1,
                })
            except Exception as exc:
                logger.exception("Failed to save model JSON for %s: %s", gid, exc)
                summary["save_warning"] = str(exc)

            per_genome_results[gid] = summary
            succeeded += 1
        except Exception as exc:
            logger.exception("bulk_reconstruct failed for genome %s: %s", gid, exc)
            per_genome_results[gid] = {
                "status": "failed",
                "genome_id": gid,
                "error": f"{type(exc).__name__}: {exc}",
            }
            failed += 1

    _progress("Writing combined CSVs...")
    import tempfile
    with tempfile.TemporaryDirectory() as tdir:
        rxn_path, gene_path = write_combined_csvs(all_rxn_rows, all_gene_rows, tdir)
        rxn_text = rxn_path.read_text()
        gene_text = gene_path.read_text()
    try:
        ws.create({
            "objects": [
                [output_path, "folder",
                 {"job_id": job_id, "kind": "bulk_reconstruct"}, ""],
                [f"{output_path}/reactions.csv", "string",
                 {"rows": str(len(all_rxn_rows))}, rxn_text],
                [f"{output_path}/genes.csv", "string",
                 {"rows": str(len(all_gene_rows))}, gene_text],
            ],
            "overwrite": 1,
        })
    except Exception as exc:
        logger.exception("Failed to write combined CSVs to workspace: %s", exc)

    return {
        "status": "success" if failed == 0 else "partial",
        "total": len(genomes),
        "succeeded": succeeded,
        "failed": failed,
        "output_path": output_path,
        "per_genome": per_genome_results,
        "reactions_rows": len(all_rxn_rows),
        "genes_rows": len(all_gene_rows),
    }


@app.task(bind=True, name="modelseed.bulk_reconstruct")
def bulk_reconstruct(
    self,
    token: str,
    genomes: list,
    template_type: str = "auto",
    atp_safe: bool = True,
    gapfill: bool = False,
    gapfill_media: str | None = None,
    fva: bool = True,
    output_path: str | None = None,
):
    """Celery wrapper around the bulk-reconstruct workflow.

    See docs/BULK_RECONSTRUCT.md for the request shape, output layout,
    and expected timings. The workflow itself lives in
    `_run_bulk_reconstruct` so the subprocess job script can reuse it.
    """
    job_id = getattr(self.request, "id", "") or "manual"

    def _cb(msg: str) -> None:
        self.update_state(state="PROGRESS", meta={"status": msg})

    return _run_bulk_reconstruct(
        token=token,
        genomes=genomes,
        template_type=template_type,
        atp_safe=atp_safe,
        gapfill=gapfill,
        gapfill_media=gapfill_media,
        fva=fva,
        output_path=output_path,
        job_id=job_id,
        progress_cb=_cb,
    )
