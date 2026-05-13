"""Unit tests for the RAST to KBase Genome translator.

Pure-function tests: no network, no DB. Drive everything from a saved real
production fixture (`tests/live/fixtures/rast_genome_pylori.json`) which is
the actual response we got from MSSS getRastGenomeData for Helicobacter pylori
26695 (job 297911, RAST genome 85962.43).

Field-by-field assertions ensure the translator output matches the shape that
`MSReconstructionUtils.get_msgenome_from_dict()` expects.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any

import pytest

from modelseed_api.services.rast_service import (
    _build_cds_from_feature,
    _clean_scientific_name,
    _contig_from_location_string,
    _extract_contig_ids_from_features,
    _parse_location_field,
    _parse_source,
    _parse_taxonomy,
    _translate_feature,
    translate_rast_to_kbase_genome,
)

pytestmark = pytest.mark.unit


FIXTURE_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "live"
    / "fixtures"
    / "rast_genome_pylori.json"
)


@pytest.fixture(scope="module")
def fixture() -> dict[str, Any]:
    """The real Helicobacter pylori RastGenome response from production."""
    with open(FIXTURE_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def translated(fixture: dict[str, Any]) -> dict[str, Any]:
    """The translator output for the fixture, computed once and shared."""
    return translate_rast_to_kbase_genome(fixture, job_id="297911")


# ---------------------------------------------------------------------
# Top-level shape: every required field present with the right type
# ---------------------------------------------------------------------


REQUIRED_TOP_LEVEL_FIELDS = {
    "id": str,
    "scientific_name": str,
    "domain": str,
    "taxonomy": str,
    "genetic_code": int,
    "dna_size": int,
    "num_contigs": int,
    "contig_ids": list,
    "contig_lengths": list,
    "gc_content": float,
    "md5": str,
    "molecule_type": str,
    "source": str,
    "source_id": str,
    "assembly_ref": str,
    "external_source_origination_date": str,
    "notes": str,
    "features": list,
    "non_coding_features": list,
    "cdss": list,
    "mrnas": list,
    "feature_counts": dict,
    "publications": list,
    "genome_tiers": list,
    "warnings": list,
    "taxon_ref": str,
}


@pytest.mark.parametrize("field,expected_type", list(REQUIRED_TOP_LEVEL_FIELDS.items()))
def test_top_level_field_present_with_correct_type(
    translated: dict[str, Any], field: str, expected_type: type
) -> None:
    """Each KBase Genome field exists and has the correct Python type."""
    assert field in translated, f"missing required field {field!r}"
    val = translated[field]
    assert isinstance(val, expected_type), (
        f"field {field!r}: expected {expected_type.__name__}, got {type(val).__name__}"
    )


# ---------------------------------------------------------------------
# scientific_name parsing
# ---------------------------------------------------------------------


def test_scientific_name_collapses_redundant_genus(translated: dict[str, Any]) -> None:
    """Real input was 'Helicobacter Helicobacter pylori Helicobacter pylori 26695'."""
    assert translated["scientific_name"] == "Helicobacter pylori 26695"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Escherichia coli K-12 MG1655", "Escherichia coli K-12 MG1655"),
        (
            "Helicobacter Helicobacter pylori Helicobacter pylori 26695",
            "Helicobacter pylori 26695",
        ),
        ("Bacillus subtilis 168", "Bacillus subtilis 168"),
        ("Mycoplasma", "Mycoplasma"),
        ("", "Unknown organism"),
        ("   ", "Unknown organism"),
    ],
)
def test_scientific_name_edge_cases(raw: str, expected: str) -> None:
    assert _clean_scientific_name(raw) == expected


# ---------------------------------------------------------------------
# Taxonomy parsing
# ---------------------------------------------------------------------


def test_taxonomy_string_uses_kbase_separator(translated: dict[str, Any]) -> None:
    """KBase convention: '; ' separator, not RAST's '|'."""
    if translated["taxonomy"]:
        assert "|" not in translated["taxonomy"]


@pytest.mark.parametrize(
    "raw,exp_str,exp_domain",
    [
        ("Bacteria", "Bacteria", "Bacteria"),
        (
            "Bacteria|Proteobacteria|Helicobacter",
            "Bacteria; Proteobacteria; Helicobacter",
            "Bacteria",
        ),
        ("Archaea|Euryarchaeota", "Archaea; Euryarchaeota", "Archaea"),
        ("Eukaryota|Metazoa", "Eukaryota; Metazoa", "Eukaryota"),
        ("", "", "Bacteria"),
        ("|||", "", "Bacteria"),
    ],
)
def test_parse_taxonomy(raw: str, exp_str: str, exp_domain: str) -> None:
    s, d = _parse_taxonomy(raw)
    assert s == exp_str
    assert d == exp_domain


# ---------------------------------------------------------------------
# Source parsing
# ---------------------------------------------------------------------


def test_source_parsed_correctly(translated: dict[str, Any]) -> None:
    """RAST source 'RAST:297911' becomes source='RAST' source_id='297911'."""
    assert translated["source"] == "RAST"
    assert translated["source_id"] == "297911"


@pytest.mark.parametrize(
    "raw,fallback,exp_source,exp_id",
    [
        ("RAST:297911", "g", "RAST", "297911"),
        ("RAST:fig|85962.43", "g", "RAST", "fig|85962.43"),
        ("RAST", "g", "RAST", "g"),
        ("", "g", "RAST", "g"),
        ("WeirdSource:abc123", "g", "WeirdSource", "abc123"),
    ],
)
def test_parse_source(raw: str, fallback: str, exp_source: str, exp_id: str) -> None:
    s, sid = _parse_source(raw, fallback_id=fallback)
    assert s == exp_source
    assert sid == exp_id


# ---------------------------------------------------------------------
# Genome ID + invariants
# ---------------------------------------------------------------------


def test_genome_id_passed_through(translated: dict[str, Any]) -> None:
    assert translated["id"] == "85962.43"


def test_domain_inferred_from_taxonomy(translated: dict[str, Any]) -> None:
    """The fixture taxonomy starts with 'Bacteria'."""
    assert translated["domain"] == "Bacteria"


def test_genetic_code_default_bacterial(translated: dict[str, Any]) -> None:
    """RAST doesn't supply genetic_code; default is 11 for bacteria."""
    assert translated["genetic_code"] == 11


def test_molecule_type_is_dna(translated: dict[str, Any]) -> None:
    assert translated["molecule_type"] == "DNA"


def test_genome_tiers(translated: dict[str, Any]) -> None:
    assert translated["genome_tiers"] == ["ExternalDB", "User"]


def test_notes_mentions_job_id(translated: dict[str, Any]) -> None:
    assert "297911" in translated["notes"]


def test_iso_timestamp_format(translated: dict[str, Any]) -> None:
    """external_source_origination_date is ISO 8601 UTC."""
    val = translated["external_source_origination_date"]
    assert val.endswith("Z")
    # YYYY-MM-DDTHH:MM:SSZ length is 20
    assert len(val) == 20


# ---------------------------------------------------------------------
# Feature segregation: PEGs vs everything else
# ---------------------------------------------------------------------


def test_features_only_contain_pegs(
    fixture: dict[str, Any], translated: dict[str, Any]
) -> None:
    """All RAST 'peg' features land in features[]; nothing else."""
    raw_pegs = sum(
        1 for f in fixture["features"] if (f.get("TYPE") or [""])[0] == "peg"
    )
    assert len(translated["features"]) == raw_pegs


def test_non_coding_features_contain_everything_else(
    fixture: dict[str, Any], translated: dict[str, Any]
) -> None:
    """Non-PEG features (rna, repeat) land in non_coding_features[]."""
    raw_non_pegs = sum(
        1
        for f in fixture["features"]
        if (f.get("TYPE") or [""])[0] != "peg" and f.get("ID")
    )
    assert len(translated["non_coding_features"]) == raw_non_pegs


def test_one_cds_per_peg(translated: dict[str, Any]) -> None:
    """Every protein-coding gene gets exactly one CDS entry."""
    assert len(translated["cdss"]) == len(translated["features"])


def test_feature_count_matches_fixture(
    fixture: dict[str, Any], translated: dict[str, Any]
) -> None:
    """Total features (coding + non-coding) equals the input count
    (modulo any features dropped for missing ID)."""
    raw_with_id = sum(1 for f in fixture["features"] if f.get("ID"))
    total = len(translated["features"]) + len(translated["non_coding_features"])
    assert total == raw_with_id


def test_feature_counts_breakdown(translated: dict[str, Any]) -> None:
    """feature_counts dict has the expected populated keys."""
    fc = translated["feature_counts"]
    # Real fixture: 1687 PEGs, 86 repeats, 40 RNAs
    assert fc["gene"] == 1687
    assert fc["protein_encoding_gene"] == 1687
    assert fc["CDS"] == 1687
    assert fc["repeat_region"] == 86
    assert fc["rRNA"] == 40
    assert fc["non-protein_encoding_gene"] == 86 + 40


# ---------------------------------------------------------------------
# Per-feature field mapping (PEG case)
# ---------------------------------------------------------------------


def test_first_peg_id_passed_through(
    fixture: dict[str, Any], translated: dict[str, Any]
) -> None:
    raw_first_peg = next(
        f for f in fixture["features"] if (f.get("TYPE") or [""])[0] == "peg"
    )
    expected_id = raw_first_peg["ID"][0]
    found = next(f for f in translated["features"] if f["id"] == expected_id)
    assert found is not None


def test_peg_has_kbase_type_gene(translated: dict[str, Any]) -> None:
    for f in translated["features"][:50]:
        assert f["type"] == "gene"


def test_peg_has_protein_translation(translated: dict[str, Any]) -> None:
    """Most PEGs in the fixture have SEQUENCE populated."""
    with_seq = sum(1 for f in translated["features"] if f["protein_translation"])
    # We expect ~all PEGs to have a sequence (1687)
    assert with_seq >= 1500


def test_peg_protein_md5_matches_sequence(translated: dict[str, Any]) -> None:
    """protein_md5 is the actual md5 of protein_translation when present."""
    for f in translated["features"][:20]:
        seq = f["protein_translation"]
        if seq:
            expected = hashlib.md5(seq.encode()).hexdigest()
            assert f["protein_md5"] == expected, f"md5 mismatch on {f['id']}"


def test_peg_protein_translation_length_matches(translated: dict[str, Any]) -> None:
    for f in translated["features"][:20]:
        assert f["protein_translation_length"] == len(f["protein_translation"])


def test_functions_drop_NONE_sentinel(translated: dict[str, Any]) -> None:
    """RAST puts the literal string 'NONE' for unannotated features.
    Translator must drop it from functions[]."""
    for f in translated["features"]:
        assert "NONE" not in f["functions"]


def test_aliases_normalized_to_pairs(translated: dict[str, Any]) -> None:
    """Each alias entry must be a [type, value] pair (list of length 2)."""
    for f in translated["features"][:50]:
        for alias in f.get("aliases", []):
            assert isinstance(alias, list) and len(alias) == 2
            assert all(isinstance(x, str) for x in alias)


def test_md5_always_populated(translated: dict[str, Any]) -> None:
    """Every feature must have a non-empty md5 (used by KBase as a stable identifier)."""
    for f in translated["features"]:
        assert f["md5"], f"empty md5 on {f['id']}"


# ---------------------------------------------------------------------
# Per-feature field mapping (non-coding case)
# ---------------------------------------------------------------------


def test_non_coding_features_have_no_protein(translated: dict[str, Any]) -> None:
    """RNAs and repeats don't have protein sequences in RAST."""
    for f in translated["non_coding_features"]:
        assert f["protein_translation"] == ""
        assert f["protein_translation_length"] == 0
        assert f["protein_md5"] == ""


def test_non_coding_kbase_type_mapping(translated: dict[str, Any]) -> None:
    """RAST 'rna' becomes KBase 'rRNA'; 'repeat' becomes 'repeat_region'."""
    types = {f["type"] for f in translated["non_coding_features"]}
    assert types <= {"rRNA", "repeat_region", "gene"}
    assert "rRNA" in types
    assert "repeat_region" in types


# ---------------------------------------------------------------------
# Location parsing
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "loc,expected",
    [
        ("NC_000915.1_1496135_1495812", "NC_000915.1"),
        ("contig1_100_200", "contig1"),
        ("plasmid_X_5_15", "plasmid_X"),
        ("malformed", "malformed"),
    ],
)
def test_contig_from_location_string(loc: str, expected: str) -> None:
    assert _contig_from_location_string(loc) == expected


def test_parse_location_with_reverse_strand() -> None:
    """For reverse-strand features, KBase 'start' is the 5' end which is the
    HIGHER coordinate. RAST encodes that as the second-to-last token in the
    LOCATION string (1496135 here, before the lower 1495812)."""
    result = _parse_location_field(
        ["NC_000915.1_1496135_1495812"], ["rev"], [323]
    )
    assert result == [["NC_000915.1", 1496135, "-", 323]]


def test_parse_location_with_forward_strand() -> None:
    result = _parse_location_field(
        ["contigA_100_500"], ["for"], [400]
    )
    assert result == [["contigA", 100, "+", 400]]


def test_parse_location_handles_missing_fields() -> None:
    """No location string at all: returns empty list, not crash."""
    assert _parse_location_field(None, None, None) == []


def test_first_peg_location_correct(translated: dict[str, Any]) -> None:
    """First PEG in fixture (fig|85962.43.peg.1507) on NC_000915.1, reverse strand,
    5' end at 1496135, length 323 (so 3' end at 1495812)."""
    f = next(
        feat
        for feat in translated["features"]
        if feat["id"] == "fig|85962.43.peg.1507"
    )
    assert f["location"] == [["NC_000915.1", 1496135, "-", 323]]


# ---------------------------------------------------------------------
# Contig handling
# ---------------------------------------------------------------------


def test_contig_ids_extracted_from_features(translated: dict[str, Any]) -> None:
    """For Helicobacter pylori (single chromosome), exactly one contig."""
    assert "NC_000915.1" in translated["contig_ids"]


def test_contig_lengths_empty_when_no_real_contigs(translated: dict[str, Any]) -> None:
    """Fixture has DNAsequence=[None]; contig_lengths should be empty."""
    assert translated["contig_lengths"] == []


def test_warning_when_no_contig_sequences(translated: dict[str, Any]) -> None:
    """Translator records a warning when DNA sequences are missing."""
    assert any("contig sequences" in w.lower() for w in translated["warnings"])


def test_extract_contig_ids_from_synthetic_features() -> None:
    """Multiple unique contig IDs returned in order of first appearance."""
    feats = [
        {"LOCATION": ["chrA_1_100"]},
        {"LOCATION": ["chrA_200_300"]},
        {"LOCATION": ["chrB_50_150"]},
        {"LOCATION": ["chrA_400_500"]},
    ]
    assert _extract_contig_ids_from_features(feats) == ["chrA", "chrB"]


# ---------------------------------------------------------------------
# CDS structure
# ---------------------------------------------------------------------


def test_cds_id_pattern(translated: dict[str, Any]) -> None:
    """Each CDS id is parent_id + '_CDS_1'."""
    for cds, gene in zip(translated["cdss"], translated["features"]):
        assert cds["id"] == f"{gene['id']}_CDS_1"
        assert cds["parent_gene"] == gene["id"]
        assert cds["type"] == "CDS"


def test_cds_inherits_protein_translation(translated: dict[str, Any]) -> None:
    """CDS protein_translation matches its parent gene's."""
    for cds, gene in zip(translated["cdss"][:20], translated["features"][:20]):
        assert cds["protein_translation"] == gene["protein_translation"]
        assert cds["protein_md5"] == gene["protein_md5"]


# ---------------------------------------------------------------------
# Idempotency + determinism
# ---------------------------------------------------------------------


def test_translator_is_idempotent(fixture: dict[str, Any]) -> None:
    """Translating the same input twice gives equivalent output, modulo
    the timestamp field which is wall-clock-derived."""
    a = translate_rast_to_kbase_genome(fixture, job_id="297911")
    b = translate_rast_to_kbase_genome(fixture, job_id="297911")
    a_no_ts = {k: v for k, v in a.items() if k != "external_source_origination_date"}
    b_no_ts = {k: v for k, v in b.items() if k != "external_source_origination_date"}
    assert a_no_ts == b_no_ts


def test_translator_does_not_mutate_input(fixture: dict[str, Any]) -> None:
    """Pure function: input is untouched."""
    snapshot = json.dumps(fixture, sort_keys=True)
    translate_rast_to_kbase_genome(fixture, job_id="297911")
    assert json.dumps(fixture, sort_keys=True) == snapshot


# ---------------------------------------------------------------------
# Defensive: empty / malformed inputs
# ---------------------------------------------------------------------


def test_translator_requires_genome_id() -> None:
    with pytest.raises(ValueError, match="missing required field 'genome'"):
        translate_rast_to_kbase_genome({}, job_id=None)


def test_translator_rejects_non_dict() -> None:
    with pytest.raises(TypeError):
        translate_rast_to_kbase_genome("not a dict", job_id=None)  # type: ignore[arg-type]


def test_translator_minimal_input() -> None:
    """Bare minimum: just a genome ID, everything else defaults sensibly."""
    out = translate_rast_to_kbase_genome({"genome": "test.1"}, job_id=None)
    assert out["id"] == "test.1"
    assert out["features"] == []
    assert out["non_coding_features"] == []
    assert out["cdss"] == []
    assert out["scientific_name"] == "Unknown organism"
    assert out["domain"] == "Bacteria"
    assert out["genetic_code"] == 11


def test_translator_handles_empty_features_list() -> None:
    out = translate_rast_to_kbase_genome(
        {
            "genome": "test.1",
            "name": "Test organism",
            "taxonomy": "Bacteria|Test",
            "features": [],
            "DNAsequence": [],
        },
        job_id="999",
    )
    assert out["features"] == []
    assert out["feature_counts"]["gene"] == 0


def test_translate_feature_returns_none_for_no_id() -> None:
    assert _translate_feature({"TYPE": ["peg"]}, genome_id="x", source="RAST") is None


def test_build_cds_handles_minimal_feature() -> None:
    """CDS builder doesn't crash on a feature with only an id."""
    cds = _build_cds_from_feature({"id": "g1"})
    assert cds["id"] == "g1_CDS_1"
    assert cds["type"] == "CDS"
    assert cds["protein_translation"] == ""
