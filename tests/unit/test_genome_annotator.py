"""Unit tests for the unified FASTA annotator.

The RPC call is mocked: these tests check that the right pipeline stages
get selected (DNA vs protein), the right genome dict gets sent, and the
response is converted into an MSGenome correctly. Live RAST hits are
covered by the integration tests, not here.
"""

from __future__ import annotations

import pytest

from modelseed_api.services.genome_annotator import (
    _DNA_STAGES,
    _PROTEIN_STAGES,
    _parse_fasta_records,
    annotate_fasta,
    looks_like_dna,
)


class TestLooksLikeDna:
    def test_pure_dna(self):
        assert looks_like_dna(">c1\nACGTACGTACGT")

    def test_pure_dna_lowercase(self):
        assert looks_like_dna(">c1\nacgtacgtacgt")

    def test_pure_dna_with_n(self):
        assert looks_like_dna(">c1\nACGTNNACGT")

    def test_rna(self):
        assert looks_like_dna(">c1\nACGUACGUACGU")

    def test_protein(self):
        assert not looks_like_dna(">p1\nMKKLVAVLIVSLAVALSALAVA")

    def test_protein_with_some_acgt_residues(self):
        # Real proteins often contain runs of A/C/G/T amino acids; the
        # heuristic must not misclassify these as DNA.
        assert not looks_like_dna(">p1\nMKKACGTACGTPLQRSVWHEDFY")

    def test_empty(self):
        assert not looks_like_dna("")

    def test_headers_only(self):
        assert not looks_like_dna(">c1\n>c2\n")


class TestParseFastaRecords:
    def test_single_record(self):
        assert _parse_fasta_records(">a\nMKKK") == [("a", "MKKK")]

    def test_multi_record(self):
        recs = _parse_fasta_records(">a desc\nMKK\nLAV\n>b\nQQQ")
        assert recs == [("a", "MKKLAV"), ("b", "QQQ")]

    def test_drops_empty_sequences(self):
        # Headers with no sequence are dropped (they'd crash downstream).
        assert _parse_fasta_records(">a\n>b\nMKK") == [("b", "MKK")]

    def test_strips_whitespace(self):
        assert _parse_fasta_records(">a\n  MKK  \n  LAV  \n") == [("a", "MKKLAV")]


class TestAnnotateFastaProteinPath:
    def test_sends_protein_stages_and_features(self, monkeypatch):
        captured = {}

        class FakeClient:
            def __init__(self, url, timeout=600):
                captured["url"] = url

            def call(self, method, params):
                captured["method"] = method
                captured["genome_dict"] = params[0]
                captured["stages"] = params[1]["stages"]
                return [{
                    "features": [
                        {"id": "p1", "protein_translation": "MKK",
                         "function": "Pyruvate kinase"},
                    ],
                }]

        monkeypatch.setattr(
            "modelseed_api.services.genome_annotator.RPCClient", FakeClient,
        )

        ms_genome = annotate_fasta(">p1\nMKKLVAVLIVSLAVALSALAVA")

        assert captured["method"] == "GenomeAnnotation.run_pipeline"
        assert captured["stages"] == _PROTEIN_STAGES
        assert captured["genome_dict"]["contigs"] == []
        assert captured["genome_dict"]["features"] == [
            {"id": "p1", "protein_translation": "MKKLVAVLIVSLAVALSALAVA"},
        ]
        assert len(ms_genome.features) == 1
        feat = ms_genome.features.get_by_id("p1")
        assert feat.seq == "MKK"
        assert feat.ontology_terms["RAST"] == ["Pyruvate kinase"]


class TestAnnotateFastaDnaPath:
    def test_sends_contig_stages_and_contigs(self, monkeypatch):
        captured = {}

        class FakeClient:
            def __init__(self, url, timeout=600):
                pass

            def call(self, method, params):
                captured["stages"] = params[1]["stages"]
                captured["genome_dict"] = params[0]
                return [{
                    "features": [
                        {"id": "g.peg.1", "protein_translation": "MKKL",
                         "function": "Hypothetical protein"},
                        {"id": "g.peg.2", "protein_translation": "QRSP",
                         "function": "FunctionA / FunctionB"},
                    ],
                }]

        monkeypatch.setattr(
            "modelseed_api.services.genome_annotator.RPCClient", FakeClient,
        )

        dna = "ACGT" * 50
        ms_genome = annotate_fasta(f">contig1\n{dna}")

        assert captured["stages"] == _DNA_STAGES
        assert captured["genome_dict"]["features"] == []
        assert captured["genome_dict"]["contigs"] == [
            {"id": "contig1", "dna": dna},
        ]
        assert len(ms_genome.features) == 2
        # Slash-separated functions split into multiple RAST ontology terms.
        feat2 = ms_genome.features.get_by_id("g.peg.2")
        assert feat2.ontology_terms["RAST"] == ["FunctionA", "FunctionB"]


class TestAnnotateFastaEdgeCases:
    def test_empty_fasta_raises(self):
        with pytest.raises(ValueError, match="No sequences"):
            annotate_fasta("")

    def test_no_features_returned_raises(self, monkeypatch):
        class EmptyClient:
            def __init__(self, url, timeout=600):
                pass

            def call(self, method, params):
                return [{"features": []}]

        monkeypatch.setattr(
            "modelseed_api.services.genome_annotator.RPCClient", EmptyClient,
        )

        with pytest.raises(ValueError, match="no features"):
            annotate_fasta(">p1\nMKKLVAVLIVSLAVALSALAVA")
