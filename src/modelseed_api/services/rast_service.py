"""RAST integration service.

Two methods, two backends, neither touching MSSeedSupportServer:

1. **`RastService.list_jobs()`** queries the RAST job database directly
   over MySQL (chestnut hosts `RastProdJobCache` + `WebAppBackend2`).
   Conduit from poplar to chestnut:3306 opened by Dan 2026-05-27.
2. **`RastService.get_genome()`** reads RAST annotation files directly
   from the FIGV-format filesystem at `MODELSEED_RAST_JOBS_DIR` via
   `RastFigvReader`, then translates the result into a KBase Genome dict
   ready for our reconstruction pipeline.

After 2026-05-27, modelseed-api has no MSSS dependency.

The translator is implemented as a module-level pure function
`translate_rast_to_kbase_genome()` so it can be unit-tested against saved
fixture data. Output shape mirrors `BVBRCUtils.build_kbase_genome_from_api()`
in KBUtilLib (`src/kbutillib/bvbrc_utils.py:170`).
"""

from __future__ import annotations

import datetime
import hashlib
import logging
import re
from typing import Any

from modelseed_api.config import settings

logger = logging.getLogger("modelseed_api.rast")


# =====================================================================
# RastService: direct MySQL listing + filesystem genome fetch
# =====================================================================


class RastService:
    """RAST integration: direct MySQL for listings, filesystem reader for genomes.

    - `list_jobs(...)` queries `RastProdJobCache.Job` joined with
      `WebAppBackend2.User` directly on chestnut MySQL. Real-time, no
      proxy, no staleness.
    - `get_genome(...)` reads `<MODELSEED_RAST_JOBS_DIR>/<job_id>/` via
      `RastFigvReader`. No network, no DB.

    Neither method touches MSSS. The `ms_fba` JSON-RPC service can be
    decommissioned once this is in production for a few days.
    """

    def list_jobs(
        self,
        username: str,
    ) -> list[dict[str, Any]]:
        """Return all RAST annotation jobs owned by `username`.

        Queries chestnut MySQL directly:
        1. `WebAppBackend2.User` to map login -> internal `_id`
        2. `RastProdJobCache.Job` to fetch jobs owned by that `_id`

        Real-time, sub-millisecond. No MSSS, no staleness.

        The cross-DB query uses fully-qualified table names so a single
        connection (and single set of credentials) suffices. The
        `modelseed` MySQL user must have SELECT on both DBs.

        PATRIC tokens encode the username as `jplfaria@patricbrc.org`
        but the RAST `WebAppBackend2.User` table stores bare logins
        (`jplfaria`). We strip the `@<domain>` suffix here so callers
        can pass either form transparently. RAST tokens always have
        the bare form and pass through unchanged.

        Raises:
            RuntimeError: if the DB host or credentials aren't configured.
        """
        if not settings.rast_db_host:
            raise RuntimeError(
                "RAST database not configured (set MODELSEED_RAST_DB_HOST)"
            )

        # Strip @patricbrc.org-style suffix; RAST stores bare usernames.
        bare_username = username.split("@", 1)[0]

        import pymysql

        conn = pymysql.connect(
            host=settings.rast_db_host,
            port=settings.rast_db_port,
            user=settings.rast_db_user,
            password=settings.rast_db_password,
            database=settings.rast_db_name,
            connect_timeout=10,
            read_timeout=30,
            cursorclass=pymysql.cursors.DictCursor,
        )

        try:
            with conn.cursor() as cur:
                # User -> internal _id (User table lives in WebAppBackend2).
                cur.execute(
                    "SELECT _id FROM WebAppBackend2.User WHERE login = %s",
                    (bare_username,),
                )
                row = cur.fetchone()
                if not row:
                    return []
                user_id = row["_id"]

                # Jobs owned by that internal id (Job table lives in RastProdJobCache).
                cur.execute(
                    """
                    SELECT id, owner, project_name, created_on, last_modified,
                           genome_bp_count, genome_contig_count, genome_id,
                           genome_name, type
                    FROM RastProdJobCache.Job
                    WHERE owner = %s
                    ORDER BY last_modified DESC
                    """,
                    (user_id,),
                )
                rows = cur.fetchall()
        finally:
            conn.close()

        return [
            {
                "owner": bare_username,
                "project": r.get("project_name", "") or "",
                "id": str(r.get("id", "")),
                "creation_time": str(r.get("created_on", "")),
                "mod_time": str(r.get("last_modified", "")),
                "genome_size": r.get("genome_bp_count", 0) or 0,
                "contig_count": r.get("genome_contig_count", 0) or 0,
                "genome_id": r.get("genome_id", "") or "",
                "genome_name": r.get("genome_name", "") or "",
                "type": r.get("type", "") or "",
            }
            for r in rows
        ]

    def get_genome(
        self,
        rast_token: str,
        genome_id: str,
        job_id: str | None = None,
        *,
        timeout: float = 180.0,
    ) -> dict[str, Any]:
        """Fetch a RAST-annotated genome from disk and translate it.

        Reads the FIGV-format files at
        `<MODELSEED_RAST_JOBS_DIR>/<job_id>/rp/<genome_id>/` directly;
        no MSSS dependency. The route handler is expected to have already
        verified that `settings.rast_jobs_dir` is set and exists, but we
        guard here too for direct service-layer callers.

        Returns a KBase Genome dict ready for
        `MSReconstructionUtils.get_msgenome_from_dict()`.

        Raises:
            FileNotFoundError: if the job directory or genome subdirectory
                does not exist on disk.
            ValueError: if `job_id` is None (filesystem reader requires it).
        """
        if not settings.rast_jobs_dir:
            raise RuntimeError(
                "RAST jobs directory not configured (set MODELSEED_RAST_JOBS_DIR); "
                "this deployment is not set up for RAST genome retrieval."
            )
        if job_id is None:
            raise ValueError(
                "job_id is required when reading from filesystem; "
                "the legacy MSSS path could derive it from the source field, "
                "but the filesystem reader needs it explicitly."
            )

        from modelseed_api.services.rast_figv_reader import RastFigvReader
        reader = RastFigvReader(settings.rast_jobs_dir)
        rast_genome = reader.read_rast_genome(job_id, genome_id)
        return translate_rast_to_kbase_genome(rast_genome, job_id=job_id)


# =====================================================================
# RAST to KBase Genome translator (pure function, unit-testable)
# =====================================================================


# Strand mapping: RAST "for"/"rev" to KBase "+"/"-"
_RAST_DIRECTION_TO_STRAND = {"for": "+", "rev": "-"}

# Feature TYPE mapping: RAST to KBase
# RAST gives "peg" (protein-encoding gene), "rna", "repeat", etc.
# KBase wants "gene", "CDS", "rRNA"/"tRNA", "repeat_region", etc.
_RAST_TYPE_TO_KBASE = {
    "peg": "gene",
    "rna": "rRNA",
    "repeat": "repeat_region",
}

# When RAST has no real ROLE for a feature, the value is the literal "NONE".
_NONE_ROLE_SENTINEL = "NONE"


def translate_rast_to_kbase_genome(
    rast_genome: dict[str, Any],
    job_id: str | None = None,
) -> dict[str, Any]:
    """Translate a `RastGenome` dict (MSSS response) into a KBase Genome dict.

    The output shape mirrors what `BVBRCUtils.build_kbase_genome_from_api()`
    produces in KBUtilLib so the rest of the reconstruction pipeline doesn't
    care which path the genome came from.

    Pure function: no I/O, deterministic for a given input.
    """
    if not isinstance(rast_genome, dict):
        raise TypeError(f"rast_genome must be a dict, got {type(rast_genome).__name__}")

    genome_id = rast_genome.get("genome")
    if not genome_id:
        raise ValueError("RastGenome missing required field 'genome' (the genome ID)")

    raw_name = rast_genome.get("name") or ""
    scientific_name = _clean_scientific_name(raw_name)

    raw_taxonomy = rast_genome.get("taxonomy") or ""
    taxonomy_str, domain = _parse_taxonomy(raw_taxonomy)

    source, source_id = _parse_source(
        rast_genome.get("source") or "", fallback_id=genome_id
    )
    if job_id is None:
        job_id = source_id

    raw_contigs = rast_genome.get("DNAsequence") or []
    real_contigs = [s for s in raw_contigs if s]
    contig_lengths = [len(s) for s in real_contigs]

    contig_ids = _extract_contig_ids_from_features(rast_genome.get("features") or [])
    if real_contigs and len(contig_ids) != len(contig_lengths):
        contig_ids = [f"contig_{i}" for i in range(len(contig_lengths))]

    if real_contigs:
        h = hashlib.md5()
        for s in real_contigs:
            h.update(s.encode("utf-8"))
        genome_md5 = h.hexdigest()
    else:
        genome_md5 = hashlib.md5(genome_id.encode("utf-8")).hexdigest()

    dna_size = int(rast_genome.get("size") or 0)
    if dna_size == 0 and contig_lengths:
        dna_size = sum(contig_lengths)

    gc_content = float(rast_genome.get("gc") or 0.5)

    warnings: list[str] = []
    if not real_contigs:
        warnings.append(
            "RAST returned no contig sequences (DNAsequence empty or [None]); "
            "contig_ids derived from feature locations, contig_lengths empty."
        )

    raw_features = rast_genome.get("features") or []
    coding_features: list[dict[str, Any]] = []
    non_coding_features: list[dict[str, Any]] = []
    cdss: list[dict[str, Any]] = []
    feature_counts: dict[str, int] = {
        "CDS": 0,
        "gene": 0,
        "ncRNA": 0,
        "non-protein_encoding_gene": 0,
        "protein_encoding_gene": 0,
        "rRNA": 0,
        "regulatory": 0,
        "repeat_region": 0,
        "tRNA": 0,
        "tmRNA": 0,
    }

    for raw_feat in raw_features:
        if not isinstance(raw_feat, dict):
            continue
        kb_feat = _translate_feature(raw_feat, genome_id=genome_id, source=source)
        if kb_feat is None:
            continue
        rast_type = _first(raw_feat.get("TYPE")) or ""
        if rast_type == "peg":
            cds_id = f"{kb_feat['id']}_CDS_1"
            # KBase per-feature `cdss` is a list of CDS IDs linking this
            # gene to its CDS object(s) in the top-level `cdss` array.
            # cobrakbase 0.3.x reads this strictly; 0.4.x is more lenient.
            kb_feat["cdss"] = [cds_id]
            coding_features.append(kb_feat)
            cdss.append(_build_cds_from_feature(kb_feat))
            feature_counts["gene"] += 1
            feature_counts["protein_encoding_gene"] += 1
            feature_counts["CDS"] += 1
        else:
            # Non-coding features get an empty cdss list (still required field).
            kb_feat["cdss"] = []
            non_coding_features.append(kb_feat)
            kb_type = kb_feat.get("type", "")
            if kb_type in feature_counts:
                feature_counts[kb_type] += 1
            feature_counts["non-protein_encoding_gene"] += 1

    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    kbase_genome: dict[str, Any] = {
        "id": genome_id,
        "scientific_name": scientific_name,
        "domain": domain,
        "taxonomy": taxonomy_str,
        "genetic_code": 11,
        "dna_size": dna_size,
        "num_contigs": len(contig_ids) if contig_ids else len(contig_lengths),
        "contig_ids": contig_ids,
        "contig_lengths": contig_lengths,
        "gc_content": gc_content,
        "md5": genome_md5,
        "molecule_type": "DNA",
        "source": source,
        "source_id": source_id,
        "assembly_ref": "",
        "external_source_origination_date": now_iso,
        "notes": (
            f"Genome imported from RAST job {job_id}"
            if job_id
            else f"Genome imported from RAST (genome_id={genome_id})"
        ),
        "features": coding_features,
        "non_coding_features": non_coding_features,
        "cdss": cdss,
        "mrnas": [],
        "feature_counts": feature_counts,
        "publications": [],
        "genome_tiers": ["ExternalDB", "User"],
        "warnings": warnings,
        "taxon_ref": "",
    }

    return kbase_genome


# =====================================================================
# Translator helpers (also pure, separately testable)
# =====================================================================


def _first(v: Any) -> Any:
    """RAST features wrap every value in a single-element list. Unwrap safely."""
    if isinstance(v, list):
        return v[0] if v else None
    return v


def _clean_scientific_name(name: str) -> str:
    """Collapse RAST's redundant duplications in the genome name.

    Real example: "Helicobacter Helicobacter pylori Helicobacter pylori 26695"
    becomes "Helicobacter pylori 26695". Strategy: walk from the right keeping
    tokens, stop the first time we see a duplicate token. Falls back to the
    original string if no clear pattern.
    """
    if not name or not name.strip():
        return "Unknown organism"
    parts = name.strip().split()
    if not parts:
        return "Unknown organism"
    seen: set[str] = set()
    keep_reversed: list[str] = []
    for tok in reversed(parts):
        if tok in seen:
            break
        seen.add(tok)
        keep_reversed.append(tok)
    cleaned = " ".join(reversed(keep_reversed))
    return cleaned or name


def _parse_taxonomy(raw: str) -> tuple[str, str]:
    """Parse RAST's pipe-delimited taxonomy into KBase string + domain."""
    if not raw or not raw.strip():
        return "", "Bacteria"
    parts = [p.strip() for p in raw.split("|") if p.strip()]
    if not parts:
        return "", "Bacteria"
    taxonomy_str = "; ".join(parts)
    first = parts[0]
    if first in {"Bacteria", "Archaea", "Eukaryota"}:
        domain = first
    elif first.lower().startswith("euk"):
        domain = "Eukaryota"
    elif first.lower().startswith("arch"):
        domain = "Archaea"
    else:
        domain = "Bacteria"
    return taxonomy_str, domain


def _parse_source(raw: str, *, fallback_id: str) -> tuple[str, str]:
    """Parse RAST's source field 'RAST:JOBID' into (source_name, source_id)."""
    if not raw:
        return "RAST", fallback_id
    m = re.match(r"^([^:]+):(\S+)$", raw)
    if m:
        return m.group(1), m.group(2)
    return raw or "RAST", fallback_id


def _extract_contig_ids_from_features(features: list[Any]) -> list[str]:
    """Discover contig identifiers by parsing them out of feature LOCATION strings.

    RAST LOCATION format is "CONTIG_START_STOP" (e.g. "NC_000915.1_1496135_1495812").
    We extract the leading contig portion (everything before the last two
    underscore-separated numeric tokens), preserving order of first appearance.
    """
    seen: list[str] = []
    seen_set: set[str] = set()
    for feat in features:
        if not isinstance(feat, dict):
            continue
        loc = _first(feat.get("LOCATION"))
        if not isinstance(loc, str):
            continue
        contig = _contig_from_location_string(loc)
        if contig and contig not in seen_set:
            seen.append(contig)
            seen_set.add(contig)
    return seen


def _contig_from_location_string(loc: str) -> str:
    """'NC_000915.1_1496135_1495812' becomes 'NC_000915.1'."""
    parts = loc.rsplit("_", 2)
    if (
        len(parts) == 3
        and parts[1].lstrip("-").isdigit()
        and parts[2].lstrip("-").isdigit()
    ):
        return parts[0]
    return loc


def _parse_location_field(loc: Any, direction_raw: Any, length_raw: Any) -> list[list[Any]]:
    """Build a KBase location list from RAST LOCATION + DIRECTION + LENGTH.

    KBase shape: [[contig_id, start, strand, length]]
    Single-segment only (RAST features in this dataset are single-segment).
    """
    loc_str = _first(loc) if loc else None
    if not isinstance(loc_str, str):
        return []
    contig = _contig_from_location_string(loc_str)
    parts = loc_str.rsplit("_", 2)
    try:
        start = int(parts[-2])
    except (ValueError, IndexError):
        start = 0
    direction = _first(direction_raw) or "for"
    strand = _RAST_DIRECTION_TO_STRAND.get(direction, "+")
    length_val = _first(length_raw)
    try:
        length = int(length_val)
    except (TypeError, ValueError):
        length = 0
    return [[contig, start, strand, length]]


def _translate_feature(
    raw_feat: dict[str, Any],
    *,
    genome_id: str,
    source: str,
) -> dict[str, Any] | None:
    """Translate a single RAST feature record into a KBase feature dict.

    Returns None if the feature is unrecognizable (no ID).
    """
    feat_id = _first(raw_feat.get("ID"))
    if not feat_id:
        return None

    rast_type = _first(raw_feat.get("TYPE")) or ""
    kb_type = _RAST_TYPE_TO_KBASE.get(rast_type, "gene")

    raw_roles = raw_feat.get("ROLES") or []
    functions = [r for r in raw_roles if isinstance(r, str) and r != _NONE_ROLE_SENTINEL]

    raw_aliases = raw_feat.get("ALIASES") or []
    aliases: list[list[str]] = []
    for alias in raw_aliases:
        if not isinstance(alias, str) or not alias.strip():
            continue
        if ":" in alias:
            t, _, v = alias.partition(":")
            aliases.append([t.strip(), v.strip()])
        else:
            aliases.append(["synonym", alias.strip()])

    protein_translation = _first(raw_feat.get("SEQUENCE")) or ""
    if not isinstance(protein_translation, str):
        protein_translation = ""
    protein_translation_length = len(protein_translation)
    protein_md5 = (
        hashlib.md5(protein_translation.encode("utf-8")).hexdigest()
        if protein_translation
        else ""
    )

    dna_sequence = ""

    md5 = (
        protein_md5
        if protein_md5
        else hashlib.md5(feat_id.encode("utf-8")).hexdigest()
    )

    location = _parse_location_field(
        raw_feat.get("LOCATION"),
        raw_feat.get("DIRECTION"),
        raw_feat.get("LENGTH"),
    )

    return {
        "id": feat_id,
        "type": kb_type,
        "location": location,
        "functions": functions,
        "aliases": aliases,
        "dna_sequence": dna_sequence,
        "dna_sequence_length": int(_first(raw_feat.get("LENGTH")) or 0),
        "md5": md5,
        "protein_translation": protein_translation,
        "protein_translation_length": protein_translation_length,
        "protein_md5": protein_md5,
    }


def _build_cds_from_feature(feature: dict[str, Any]) -> dict[str, Any]:
    """Build a CDS dict from a translated feature dict.

    KBase models CDS as a separate object that mirrors the protein-coding
    feature; reconstruction code inspects either or both depending on the
    template.
    """
    return {
        "id": f"{feature['id']}_CDS_1",
        "type": "CDS",
        "parent_gene": feature["id"],
        "location": feature.get("location") or [],
        "dna_sequence": feature.get("dna_sequence") or "",
        "dna_sequence_length": feature.get("dna_sequence_length") or 0,
        "md5": feature.get("md5") or "",
        "protein_translation": feature.get("protein_translation") or "",
        "protein_translation_length": feature.get("protein_translation_length") or 0,
        "protein_md5": feature.get("protein_md5") or "",
        "functions": feature.get("functions") or [],
        "aliases": feature.get("aliases") or [],
    }
