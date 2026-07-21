"""Single entry point for FASTA-based genome annotation.

Both protein and DNA inputs go through the same JSON-RPC service
(`GenomeAnnotation.run_pipeline` at tutorial.theseed.org); the only
difference is which pipeline stages get invoked. DNA input runs gene
calling (prodigal + glimmer3) before annotation; protein input skips
straight to annotation. Callers see one function and one return type
regardless of input.

The stage lists mirror the legacy ProbModelSEED definitions:
`Bio::KBase::constants::contig_annotation_pipeline` and
`Bio::KBase::constants::gene_annotation_pipeline` (see
`/Users/jplfaria/repos/ProbModelSEED/lib/Bio/KBase/constants.pm`).
"""

from __future__ import annotations

import logging
import re
import time

from modelseedpy.core.msgenome import MSFeature, MSGenome
from modelseedpy.core.rpcclient import RPCClient

logger = logging.getLogger(__name__)

RAST_URL = "https://tutorial.theseed.org/services/genome_annotation"

# tutorial.theseed.org returns transient 5xx (most commonly 504 Gateway
# Timeout when the kmer service is under load) and also intermittently
# times out at the socket layer or fails DNS resolution. Same input that
# just failed usually succeeds on retry within seconds. Retry all shapes
# so users don't see them as job failures. Non-transient errors (4xx,
# schema errors, etc.) raise on the first attempt.
_TRANSIENT_5XX = ("500", "502", "503", "504")
# Substrings that indicate a socket/DNS/connection-layer transient rather
# than an application-level error. Match against str(exc) OR type(exc)
# __name__ (see is_transient below).
_TRANSIENT_MARKERS = (
    "tutorial.theseed.org",  # any RAST connection issue = transient
    "Read timed out",
    "Max retries exceeded",
    "Temporary failure in name resolution",
    "Connection reset by peer",
    "Connection aborted",
)
_TRANSIENT_EXC_NAMES = frozenset({
    "ReadTimeout",
    "ReadTimeoutError",
    "ConnectionError",
    "MaxRetryError",
    "ProtocolError",
    "NewConnectionError",
    "NameResolutionError",
})
_MAX_RETRIES = 3
_BACKOFF_SECONDS = (5, 15)  # waits between attempts 1->2 and 2->3

_PROTEIN_STAGES = [
    {"name": "annotate_proteins_kmer_v2", "kmer_v2_parameters": {}},
    {
        "name": "annotate_proteins_kmer_v1",
        "kmer_v1_parameters": {"annotate_hypothetical_only": 1},
    },
    {
        "name": "annotate_proteins_similarity",
        "similarity_parameters": {"annotate_hypothetical_only": 1},
    },
]

_DNA_STAGES = [
    {"name": "call_features_CDS_prodigal"},
    {
        "name": "call_features_CDS_glimmer3",
        "failure_is_not_fatal": 1,
        "glimmer3_parameters": {},
    },
    *_PROTEIN_STAGES,
    {
        "name": "resolve_overlapping_features",
        "resolve_overlapping_features_parameters": {},
    },
    {"name": "renumber_features"},
    {"name": "annotate_null_to_hypothetical"},
]

_FUNCTION_SPLIT = re.compile(r"; | / | @")


def _parse_fasta_records(fasta_str: str) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    current_id: str | None = None
    current_seq: list[str] = []
    for line in fasta_str.splitlines():
        line = line.rstrip()
        if line.startswith(">"):
            if current_id is not None:
                records.append((current_id, "".join(current_seq)))
            header = line[1:].strip()
            current_id = header.split()[0] if header else ""
            current_seq = []
        elif line:
            current_seq.append(line.strip())
    if current_id is not None:
        records.append((current_id, "".join(current_seq)))
    return [r for r in records if r[0] and r[1]]


def looks_like_dna(fasta_str: str) -> bool:
    """Heuristic: >=90% of non-header chars are ACGTUN (case-insensitive)."""
    seq_chars = [
        c
        for line in fasta_str.splitlines()
        if not line.startswith(">")
        for c in line.strip()
        if not c.isspace()
    ]
    if not seq_chars:
        return False
    nt_chars = sum(1 for c in seq_chars if c.upper() in "ACGTUN")
    return nt_chars / len(seq_chars) >= 0.9


def _build_msgenome(annotated: dict) -> MSGenome:
    ms_genome = MSGenome()
    for f in annotated.get("features", []):
        feature = MSFeature(
            f["id"],
            f.get("protein_translation", ""),
            f.get("function", ""),
        )
        fn = f.get("function")
        if fn:
            for term in _FUNCTION_SPLIT.split(fn):
                term = term.strip()
                if term:
                    feature.add_ontology_term("RAST", term)
        ms_genome.features += [feature]
    return ms_genome


def annotate_fasta(
    fasta_str: str,
    *,
    scientific_name: str = "Unknown organism",
    domain: str = "Bacteria",
    genetic_code: int = 11,
    taxonomy: str = "",
    timeout: int = 600,
) -> MSGenome:
    """Annotate a FASTA string and return an MSGenome ready for MSBuilder.

    Auto-detects DNA vs protein input. DNA goes through gene calling
    (prodigal + glimmer3) before annotation; protein skips straight to
    annotation. Both use the same anonymous RAST endpoint and return
    the same MSGenome shape.

    Raises ValueError if the FASTA is empty or RAST returns no features.
    """
    records = _parse_fasta_records(fasta_str)
    if not records:
        raise ValueError("No sequences found in genome_fasta")

    is_dna = looks_like_dna(fasta_str)
    logger.info(
        "Annotating FASTA with %d records (mode=%s)",
        len(records),
        "contigs/DNA" if is_dna else "proteins",
    )

    if is_dna:
        genome_dict = {
            "id": "input_genome",
            "scientific_name": scientific_name,
            "domain": domain,
            "genetic_code": genetic_code,
            "taxonomy": taxonomy,
            "source": "RAST",
            "contigs": [{"id": rid, "dna": seq} for rid, seq in records],
            "features": [],
        }
        stages = _DNA_STAGES
    else:
        genome_dict = {
            "id": "input_genome",
            "scientific_name": scientific_name,
            "domain": domain,
            "genetic_code": genetic_code,
            "taxonomy": taxonomy,
            "source": "RAST",
            "contigs": [],
            "features": [
                {"id": rid, "protein_translation": seq} for rid, seq in records
            ],
        }
        stages = _PROTEIN_STAGES

    client = RPCClient(RAST_URL, timeout=timeout)
    result = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            result = client.call(
                "GenomeAnnotation.run_pipeline",
                [genome_dict, {"stages": stages}],
            )
            break
        except Exception as exc:
            msg = str(exc)
            is_transient = (
                any(code in msg for code in _TRANSIENT_5XX)
                or any(marker in msg for marker in _TRANSIENT_MARKERS)
                or type(exc).__name__ in _TRANSIENT_EXC_NAMES
            )
            if not is_transient or attempt == _MAX_RETRIES:
                raise
            wait = _BACKOFF_SECONDS[attempt - 1]
            logger.warning(
                "RAST annotation transient failure (attempt %d/%d): %s. "
                "Retrying in %ds.",
                attempt,
                _MAX_RETRIES,
                msg.splitlines()[0][:200],
                wait,
            )
            time.sleep(wait)
    annotated = result[0]

    ms_genome = _build_msgenome(annotated)
    if not ms_genome.features:
        raise ValueError(
            "RAST annotation returned no features. For DNA input, this "
            "usually means gene calling found nothing (check the input is "
            "real genomic DNA, not a short fragment). For protein input, "
            "check that the FASTA actually contains protein sequences."
        )
    n_features = len(ms_genome.features)
    n_with_function = sum(1 for f in ms_genome.features if f.ontology_terms.get("RAST"))
    logger.info(
        "Annotation produced %d features (%d with assigned function)",
        n_features,
        n_with_function,
    )
    # Zero functional roles -> downstream MSGenomeClassifier and MSBuilder
    # both fail in confusing ways (auto template path crashes inside
    # predict_phenotype.py:96 with a misleading "wasn't annotated with RAST"
    # error; explicit template path silently builds a 0-gene model with
    # just universal scaffold reactions). Catch this case here with a
    # clean error instead.
    if n_with_function == 0:
        raise ValueError(
            f"RAST annotation produced {n_features} feature(s) but none "
            f"matched any functional roles. This usually means the input "
            f"is too small for RAST to find characteristic kmers (try a "
            f"larger genome), or the organism is too far from anything in "
            f"RAST's reference set, or (for protein input) the sequences "
            f"aren't functional proteins."
        )
    return ms_genome
