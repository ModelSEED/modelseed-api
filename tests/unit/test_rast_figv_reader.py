"""Unit tests for `RastFigvReader` (the FIGV-on-disk replacement for MSSS).

These tests use a small in-tree fixture directory that mirrors the FIGV
file layout for one job. They do not require the production NFS mount.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from modelseed_api.services.rast_figv_reader import (
    RastFigvReader,
    _parse_location_endpoints,
)
from modelseed_api.services.rast_service import translate_rast_to_kbase_genome


# ---------------------------------------------------------------
# Fixture builders (pytest tmp_path, no on-disk fixture needed)
# ---------------------------------------------------------------


def _build_minimal_job_tree(
    base: Path,
    *,
    job_id: str = "999001",
    genome_id: str = "1234567.1",
    user: str = "testuser",
    organism_name: str = "Escherichia coli K-12",
    taxonomy: str = "Bacteria; Proteobacteria; Escherichia coli",
    contigs: list[tuple[str, str]] | None = None,
    pegs: list[tuple[str, str, str, str]] | None = None,
) -> Path:
    """Build a fake FIGV job tree under `base` and return the jobs_dir.

    pegs items are (peg_id, location, protein_seq, function).
    """
    jobs_dir = base / "jobs"
    job_path = jobs_dir / job_id
    rp_path = job_path / "rp" / genome_id
    peg_dir = rp_path / "Features" / "peg"
    peg_dir.mkdir(parents=True)

    (job_path / "USER").write_text(user)
    (job_path / "GENOME").write_text(organism_name)
    (job_path / "GENOME_ID").write_text(genome_id)
    (job_path / "TAXONOMY").write_text(taxonomy)
    (rp_path / "GENOME").write_text(organism_name)
    (rp_path / "TAXONOMY").write_text(taxonomy)
    (rp_path / "GENETIC_CODE").write_text("11")

    if contigs is None:
        contigs = [("NC_TEST.1", "ATGCATGC" * 100)]
    contigs_text = "\n".join(f">{cid}\n{seq}" for cid, seq in contigs) + "\n"
    (rp_path / "contigs").write_text(contigs_text)

    if pegs is None:
        pegs = [
            ("fig|1234567.1.peg.1", "NC_TEST.1_1_30",  "MASKE",  "Hypothetical protein"),
            ("fig|1234567.1.peg.2", "NC_TEST.1_60_31", "MQYAA",  "Aspartokinase (EC 2.7.2.4)"),
        ]
    tbl_lines = [f"{pid}\t{loc}\t" for pid, loc, _, _ in pegs]
    (peg_dir / "tbl").write_text("\n".join(tbl_lines) + "\n")
    fasta_lines = []
    for pid, _, seq, _ in pegs:
        fasta_lines.append(f">{pid}")
        fasta_lines.append(seq)
    (peg_dir / "fasta").write_text("\n".join(fasta_lines) + "\n")
    pf_lines = [f"{pid}\t{func}" for pid, _, _, func in pegs]
    (rp_path / "proposed_functions").write_text("\n".join(pf_lines) + "\n")

    return jobs_dir


# ---------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------


class TestPathResolution:
    def test_resolve_direct_hit(self, tmp_path):
        jobs_dir = _build_minimal_job_tree(tmp_path)
        reader = RastFigvReader(jobs_dir)
        path = reader._resolve_job_path("999001")
        assert path == jobs_dir / "999001"

    def test_resolve_missing_raises(self, tmp_path):
        jobs_dir = _build_minimal_job_tree(tmp_path)
        reader = RastFigvReader(jobs_dir)
        with pytest.raises(FileNotFoundError):
            reader._resolve_job_path("nonexistent_job")

    def test_resolve_caches_results(self, tmp_path):
        jobs_dir = _build_minimal_job_tree(tmp_path)
        reader = RastFigvReader(jobs_dir)
        first = reader._resolve_job_path("999001")
        assert "999001" in reader._path_cache
        # Subsequent call is the cached value (still a valid Path).
        assert reader._resolve_job_path("999001") == first


# ---------------------------------------------------------------
# Read methods (top-level RastGenome shape)
# ---------------------------------------------------------------


class TestReadRastGenome:
    def test_returns_required_top_level_fields(self, tmp_path):
        jobs_dir = _build_minimal_job_tree(tmp_path)
        reader = RastFigvReader(jobs_dir)
        result = reader.read_rast_genome("999001", "1234567.1")
        for field in (
            "genome", "name", "taxonomy", "source",
            "size", "gc", "DNAsequence", "features",
        ):
            assert field in result, f"missing field: {field}"

    def test_genome_id_passed_through(self, tmp_path):
        jobs_dir = _build_minimal_job_tree(tmp_path)
        result = RastFigvReader(jobs_dir).read_rast_genome("999001", "1234567.1")
        assert result["genome"] == "1234567.1"

    def test_source_format(self, tmp_path):
        jobs_dir = _build_minimal_job_tree(tmp_path)
        result = RastFigvReader(jobs_dir).read_rast_genome("999001", "1234567.1")
        assert result["source"] == "RAST:999001"

    def test_taxonomy_normalized_to_pipe_delimited(self, tmp_path):
        # On disk it's semicolon-delimited; MSSS-output convention is pipe.
        jobs_dir = _build_minimal_job_tree(
            tmp_path, taxonomy="Bacteria; Proteobacteria; Escherichia coli"
        )
        result = RastFigvReader(jobs_dir).read_rast_genome("999001", "1234567.1")
        assert "|" in result["taxonomy"]
        assert ";" not in result["taxonomy"]

    def test_contigs_loaded_correctly(self, tmp_path):
        jobs_dir = _build_minimal_job_tree(
            tmp_path,
            contigs=[("CONTIG_A", "AAAATTTT"), ("CONTIG_B", "GGGGCCCC")],
        )
        result = RastFigvReader(jobs_dir).read_rast_genome("999001", "1234567.1")
        assert len(result["DNAsequence"]) == 2
        assert result["DNAsequence"][0] == "AAAATTTT"
        assert result["DNAsequence"][1] == "GGGGCCCC"

    def test_size_is_sum_of_contig_lengths(self, tmp_path):
        jobs_dir = _build_minimal_job_tree(
            tmp_path,
            contigs=[("CONTIG_A", "A" * 100), ("CONTIG_B", "T" * 200)],
        )
        result = RastFigvReader(jobs_dir).read_rast_genome("999001", "1234567.1")
        assert result["size"] == 300

    def test_gc_computed_from_contigs(self, tmp_path):
        # 50% GC by construction
        jobs_dir = _build_minimal_job_tree(
            tmp_path, contigs=[("C", "ATGC" * 25)]
        )
        result = RastFigvReader(jobs_dir).read_rast_genome("999001", "1234567.1")
        assert 0.49 < result["gc"] < 0.51

    def test_no_contigs_yields_default_gc(self, tmp_path):
        jobs_dir = _build_minimal_job_tree(tmp_path, contigs=[])
        # No contigs file written, so DNAsequence will be empty; gc defaults to 0.5
        # Need to overwrite the contigs file to be empty (writer adds default).
        (jobs_dir / "999001" / "rp" / "1234567.1" / "contigs").write_text("")
        result = RastFigvReader(jobs_dir).read_rast_genome("999001", "1234567.1")
        assert result["DNAsequence"] == []
        assert result["gc"] == 0.5


# ---------------------------------------------------------------
# Feature shape (the per-feature dict consumed by _translate_feature)
# ---------------------------------------------------------------


class TestFeatureShape:
    def test_feature_count_matches_pegs(self, tmp_path):
        pegs = [(f"fig|1234567.1.peg.{i}", f"NC.1_{i*30+1}_{i*30+30}", "MASKE", "Test")
                for i in range(1, 6)]
        jobs_dir = _build_minimal_job_tree(tmp_path, pegs=pegs)
        result = RastFigvReader(jobs_dir).read_rast_genome("999001", "1234567.1")
        assert len(result["features"]) == 5

    def test_feature_id_wrapped_in_list(self, tmp_path):
        jobs_dir = _build_minimal_job_tree(tmp_path)
        result = RastFigvReader(jobs_dir).read_rast_genome("999001", "1234567.1")
        f = result["features"][0]
        assert isinstance(f["ID"], list)
        assert f["ID"][0].startswith("fig|")

    def test_feature_type_is_peg(self, tmp_path):
        jobs_dir = _build_minimal_job_tree(tmp_path)
        result = RastFigvReader(jobs_dir).read_rast_genome("999001", "1234567.1")
        assert result["features"][0]["TYPE"] == ["peg"]

    def test_feature_genome_matches(self, tmp_path):
        jobs_dir = _build_minimal_job_tree(tmp_path)
        result = RastFigvReader(jobs_dir).read_rast_genome("999001", "1234567.1")
        assert result["features"][0]["GENOME"] == ["1234567.1"]

    def test_feature_source_matches_job(self, tmp_path):
        jobs_dir = _build_minimal_job_tree(tmp_path)
        result = RastFigvReader(jobs_dir).read_rast_genome("999001", "1234567.1")
        assert result["features"][0]["SOURCE"] == ["RAST:999001"]

    def test_feature_location_preserved(self, tmp_path):
        jobs_dir = _build_minimal_job_tree(
            tmp_path,
            pegs=[("fig|1234567.1.peg.1", "NC_TEST.1_100_500", "MASKE", "Test")],
        )
        result = RastFigvReader(jobs_dir).read_rast_genome("999001", "1234567.1")
        assert result["features"][0]["LOCATION"] == ["NC_TEST.1_100_500"]

    def test_forward_strand_direction(self, tmp_path):
        jobs_dir = _build_minimal_job_tree(
            tmp_path,
            pegs=[("fig|1234567.1.peg.1", "NC.1_100_500", "MASKE", "Test")],
        )
        result = RastFigvReader(jobs_dir).read_rast_genome("999001", "1234567.1")
        assert result["features"][0]["DIRECTION"] == ["for"]

    def test_reverse_strand_direction(self, tmp_path):
        jobs_dir = _build_minimal_job_tree(
            tmp_path,
            pegs=[("fig|1234567.1.peg.1", "NC.1_500_100", "MASKE", "Test")],
        )
        result = RastFigvReader(jobs_dir).read_rast_genome("999001", "1234567.1")
        assert result["features"][0]["DIRECTION"] == ["rev"]

    def test_min_max_location_extracted(self, tmp_path):
        jobs_dir = _build_minimal_job_tree(
            tmp_path,
            pegs=[("fig|1234567.1.peg.1", "NC.1_500_100", "MASKE", "Test")],
        )
        f = RastFigvReader(jobs_dir).read_rast_genome("999001", "1234567.1")["features"][0]
        assert f["MIN LOCATION"] == ["100"]
        assert f["MAX LOCATION"] == ["500"]

    def test_protein_sequence_attached(self, tmp_path):
        jobs_dir = _build_minimal_job_tree(
            tmp_path,
            pegs=[("fig|1234567.1.peg.1", "NC.1_1_30", "MWXYZ", "Test")],
        )
        f = RastFigvReader(jobs_dir).read_rast_genome("999001", "1234567.1")["features"][0]
        assert f["SEQUENCE"] == ["MWXYZ"]

    def test_function_becomes_role(self, tmp_path):
        jobs_dir = _build_minimal_job_tree(
            tmp_path,
            pegs=[("fig|1234567.1.peg.1", "NC.1_1_30", "M", "Aspartokinase (EC 2.7.2.4)")],
        )
        f = RastFigvReader(jobs_dir).read_rast_genome("999001", "1234567.1")["features"][0]
        assert f["ROLES"] == ["Aspartokinase (EC 2.7.2.4)"]

    def test_missing_function_uses_none_sentinel(self, tmp_path):
        jobs_dir = _build_minimal_job_tree(tmp_path)
        # Wipe the proposed_functions file
        (jobs_dir / "999001" / "rp" / "1234567.1" / "proposed_functions").write_text("")
        f = RastFigvReader(jobs_dir).read_rast_genome("999001", "1234567.1")["features"][0]
        # Translator filters "NONE" out, so we use the same sentinel here.
        assert f["ROLES"] == ["NONE"]


# ---------------------------------------------------------------
# End-to-end: reader output feeds the translator
# ---------------------------------------------------------------


class TestReaderFeedsTranslator:
    def test_translator_accepts_reader_output(self, tmp_path):
        """Crucial: the dict our reader returns is a valid input to translate_rast_to_kbase_genome."""
        jobs_dir = _build_minimal_job_tree(tmp_path)
        rast_dict = RastFigvReader(jobs_dir).read_rast_genome("999001", "1234567.1")
        kbase = translate_rast_to_kbase_genome(rast_dict, job_id="999001")
        assert kbase["id"] == "1234567.1"
        assert kbase["source"] == "RAST"
        assert kbase["source_id"] == "999001"
        assert kbase["genetic_code"] == 11
        assert isinstance(kbase["features"], list)
        assert len(kbase["features"]) >= 1
        # Coding feature should have a CDS entry too.
        assert len(kbase["cdss"]) >= 1
        # Every feature should have the required KBase fields.
        for f in kbase["features"]:
            for key in ("id", "type", "location", "functions", "protein_translation", "md5"):
                assert key in f

    def test_translator_filters_none_role_from_features(self, tmp_path):
        # Feature with NONE function should have empty `functions` list after translation.
        jobs_dir = _build_minimal_job_tree(tmp_path)
        (jobs_dir / "999001" / "rp" / "1234567.1" / "proposed_functions").write_text("")
        rast_dict = RastFigvReader(jobs_dir).read_rast_genome("999001", "1234567.1")
        kbase = translate_rast_to_kbase_genome(rast_dict, job_id="999001")
        for f in kbase["features"]:
            assert f["functions"] == []  # NONE was filtered


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------


class TestLocationParser:
    def test_forward_strand(self):
        assert _parse_location_endpoints("NC_000913.3_337_2799") == (337, 2799)

    def test_reverse_strand(self):
        assert _parse_location_endpoints("NC_000913.3_2799_337") == (2799, 337)

    def test_simple_contig_id(self):
        assert _parse_location_endpoints("CONTIG_100_500") == (100, 500)

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError):
            _parse_location_endpoints("no_underscores")

    def test_non_numeric_raises(self):
        with pytest.raises(ValueError):
            _parse_location_endpoints("NC_000913.3_abc_def")
