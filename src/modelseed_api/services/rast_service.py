"""RAST integration service.

Both methods wrap MSSeedSupportServer (MSSS) over JSON-RPC:

1. **`RastService.list_jobs()`** wraps `list_rast_jobs`. We tried direct
   MySQL access from poplar but `bio-admin.cels.anl.gov:3306` is firewalled.
   MSSS reaches the DB fine from branch, so we proxy through it.
2. **`RastService.get_genome()`** wraps `getRastGenomeData` and translates
   the response into a KBase Genome dict ready for our reconstruction
   pipeline.

This service is a pure proxy. Eventually MSSS itself can be retired
(it's on EOL hardware) and we'd port the logic, but that requires moving
the underlying RAST data files to a host poplar can reach.

The translator is implemented as a module-level pure function
`translate_rast_to_kbase_genome()` so it can be unit-tested against saved
fixture data without touching MSSS at all. Output shape mirrors
`BVBRCUtils.build_kbase_genome_from_api()` in KBUtilLib
(`src/kbutillib/bvbrc_utils.py:170`).
"""

from __future__ import annotations

import datetime
import hashlib
import logging
import re
from typing import Any

import httpx

from modelseed_api.config import settings

logger = logging.getLogger("modelseed_api.rast")


# =====================================================================
# RastService: DB listing + MSSS-backed genome fetch
# =====================================================================


class RastService:
    """Read-only proxy to MSSeedSupportServer."""

    def list_jobs(
        self,
        rast_token: str,
        *,
        timeout: float = 60.0,
    ) -> list[dict[str, Any]]:
        """Return all RAST annotation jobs the token's user owns.

        Wraps MSSS `MSSeedSupportServer.list_rast_jobs`. MSSS uses the
        `Authorization` header to identify the user; the response is a
        list-of-list-of-dicts (KBase JSON-RPC style) which we flatten and
        normalize into our flat list of job dicts.

        Raises:
            RuntimeError: if MSSS is unreachable or returns an error.
        """
        if not settings.modelseed_msss_url:
            raise RuntimeError(
                "MSSS URL not configured (set MODELSEED_MSSS_URL); "
                "cannot list RAST jobs."
            )

        result = _call_msss_jsonrpc(
            url=settings.modelseed_msss_url,
            method="MSSeedSupportServer.list_rast_jobs",
            params=[{}],
            token=rast_token,
            timeout=timeout,
        )

        # MSSS returns the rows as a single list. Normalize each row's
        # field types (MSSS gives stringy ints) to match the previous
        # DB-query shape so existing API consumers don't see a change.
        if not isinstance(result, list):
            return []

        def _to_int(v: Any) -> int:
            try:
                return int(v)
            except (TypeError, ValueError):
                return 0

        return [
            {
                "owner": str(row.get("owner") or ""),
                "project": str(row.get("project") or row.get("project_name") or ""),
                "id": str(row.get("id") or ""),
                "creation_time": str(row.get("creation_time") or row.get("created_on") or ""),
                "mod_time": str(row.get("mod_time") or row.get("last_modified") or ""),
                "genome_size": _to_int(row.get("genome_size") or row.get("genome_bp_count")),
                "contig_count": _to_int(row.get("contig_count") or row.get("genome_contig_count")),
                "genome_id": str(row.get("genome_id") or ""),
                "genome_name": str(row.get("genome_name") or ""),
                "type": str(row.get("type") or ""),
            }
            for row in result
            if isinstance(row, dict)
        ]

    def get_genome(
        self,
        rast_token: str,
        genome_id: str,
        job_id: str | None = None,
        *,
        timeout: float = 180.0,
    ) -> dict[str, Any]:
        """Fetch a RAST-annotated genome via MSSS and translate it.

        Returns a KBase Genome dict ready for
        `MSReconstructionUtils.get_msgenome_from_dict()`.

        Raises:
            RuntimeError: if MSSS is unreachable or returns an error.
            ValueError:   if the genome ID is not found.
        """
        if not settings.modelseed_msss_url:
            raise RuntimeError(
                "MSSS URL not configured (set MODELSEED_MSSS_URL); "
                "cannot fetch RAST genome data."
            )

        rast_genome = _call_msss_jsonrpc(
            url=settings.modelseed_msss_url,
            method="MSSeedSupportServer.getRastGenomeData",
            params=[{
                "genome": genome_id,
                "getSequences": 1,
                "getDNASequence": 1,
            }],
            token=rast_token,
            timeout=timeout,
        )

        if job_id is None:
            source = rast_genome.get("source", "")
            m = re.match(r"RAST:(\S+)", source) if source else None
            job_id = m.group(1) if m else None

        return translate_rast_to_kbase_genome(rast_genome, job_id=job_id)


# =====================================================================
# JSON-RPC client for MSSS
# =====================================================================


def _call_msss_jsonrpc(
    *,
    url: str,
    method: str,
    params: list[Any],
    token: str,
    timeout: float = 60.0,
) -> Any:
    """POST a JSON-RPC v1.1 call to MSSS and return the unwrapped result.

    MSSS authenticates via Authorization header (RAST tokens only; PATRIC
    tokens are rejected with "Username not found"). Method names follow
    KBase convention: "PackageName.method_name".
    """
    body = {
        "version": "1.1",
        "method": method,
        "params": params,
        "id": method,
    }
    headers = {"Content-Type": "application/json", "Authorization": token}
    try:
        r = httpx.post(url, json=body, headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"MSSS call failed ({method}): {exc}") from exc

    try:
        envelope = r.json()
    except ValueError as exc:
        raise RuntimeError(
            f"MSSS returned non-JSON response ({method}, status {r.status_code}): "
            f"{r.text[:300]}"
        ) from exc

    if "error" in envelope:
        err = envelope["error"]
        msg = (
            err.get("message")
            or err.get("error")
            or str(err)
        )
        raise RuntimeError(f"MSSS {method} error: {str(msg)[:500]}")

    result = envelope.get("result")
    if not isinstance(result, list) or not result:
        raise RuntimeError(
            f"MSSS {method} returned unexpected result shape: "
            f"{type(result).__name__}"
        )
    return result[0]


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
