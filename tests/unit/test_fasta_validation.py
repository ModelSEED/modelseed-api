"""Unit tests for genome_fasta content validation."""

from __future__ import annotations

import gzip
import io
import zipfile

import pytest

from modelseed_api.services.fasta_validation import validate_fasta_text

pytestmark = pytest.mark.unit

_DNA = ">contig1 Bacteroides fragilis\nACGTACGTNNACGT\nGATTACA\n>contig2\nacgtacgt\n"


def _as_browser_text(data: bytes) -> str:
    # FileReader.readAsText on a binary upload: invalid UTF-8 becomes U+FFFD.
    return data.decode("utf-8", errors="replace")


class TestAccepts:
    @pytest.mark.parametrize(
        "text",
        [
            ">p1\nMKKLVAVLIVSLAVALSALAVA",
            _DNA,
            ">p1 desc\nMKK*\n>p2\nMK-LV.A\n",
            ">c1\r\nACGT\r\nACGT\r\n",
            "\ufeff>c1\nACGT\n",
            "\n\n  >c1\nACGT\n",
            ">c1\nACGT ACGT\tACGT\n",
            ">a\n>b\nMKK",
        ],
    )
    def test_valid_fasta(self, text):
        validate_fasta_text(text)

    def test_stray_undecodable_chars_in_header_description(self):
        # Production case: a valid genome whose header description had a few
        # non-UTF-8 characters (decoded as U+FFFD). The build succeeded.
        text = ">BA000030  (9,025,608 \ufffd\ufffd\ufffd\ufffd\ufffd)\n" + "ACGT" * 5000
        validate_fasta_text(text)


class TestRejectsBinary:
    def test_gzipped_fasta_read_as_text(self):
        # Production case: an NCBI .fsa_nt.gz uploaded without decompressing.
        buf = io.BytesIO()
        with gzip.GzipFile(filename="FQXK01.1.fsa_nt", mode="wb", fileobj=buf) as gz:
            gz.write((_DNA * 200).encode())
        with pytest.raises(ValueError, match="gzip-compressed.*Decompress"):
            validate_fasta_text(_as_browser_text(buf.getvalue()))

    def test_zipped_fasta_read_as_text(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("genome.fna", _DNA * 200)
        with pytest.raises(ValueError, match="zip archive"):
            validate_fasta_text(_as_browser_text(buf.getvalue()))

    def test_replacement_characters(self):
        with pytest.raises(ValueError, match="binary file"):
            validate_fasta_text(">c1\nAC\ufffdGT\n")

    def test_control_characters(self):
        with pytest.raises(ValueError, match="binary file"):
            validate_fasta_text(">c1\nAC\x00GT\n")


class TestRejectsMalformed:
    @pytest.mark.parametrize("text", ["", "   \n\t\n", "\ufeff"])
    def test_empty(self, text):
        with pytest.raises(ValueError, match="No sequences found"):
            validate_fasta_text(text)

    def test_headers_without_sequence(self):
        with pytest.raises(ValueError, match="No sequences found.*no sequence data"):
            validate_fasta_text(">c1\n>c2\n")

    @pytest.mark.parametrize(
        "text",
        [
            "ACGTACGT\n",
            "/alice/modelseed/genome.fna",
            "LOCUS       NC_000913  4641652 bp    DNA\n",
        ],
    )
    def test_missing_header(self, text):
        with pytest.raises(ValueError, match="must start with a '>' header"):
            validate_fasta_text(text)

    def test_gff3_with_embedded_fasta(self):
        # Production case: a GFF3 upload "completed" with 6 reactions and 0
        # genes because the annotation lines skewed DNA detection.
        text = "##gff-version 3\nctg1\tProdigal\tCDS\t1\t90\t.\t+\t0\tID=g1\n##FASTA\n>ctg1\nACGT\n"
        with pytest.raises(ValueError, match="got '##gff-version 3'"):
            validate_fasta_text(text)

    def test_stray_junk_in_sequence_line_of_large_file(self):
        # Below the binary threshold, but sequence lines are still checked.
        text = ">c1\n" + "ACGT\n" * 5000 + "AC\ufffdGT\n"
        with pytest.raises(ValueError, match="line 5002 is not a valid sequence line"):
            validate_fasta_text(text)

    def test_genbank_style_sequence_line(self):
        with pytest.raises(ValueError, match="line 2 is not a valid sequence line"):
            validate_fasta_text(">c1\n        1 agcttttcat tctgactgca\n")

    def test_duplicate_ids(self):
        with pytest.raises(ValueError, match="duplicate sequence IDs: 'p1'"):
            validate_fasta_text(">p1 first\nMKK\n>p2\nMKK\n>p1 again\nLAV\n")

    def test_duplicate_ids_truncated_listing(self):
        text = "".join(f">p{i}\nMKK\n>p{i}\nMKK\n" for i in range(7))
        with pytest.raises(ValueError, match=r"and 2 more"):
            validate_fasta_text(text)
