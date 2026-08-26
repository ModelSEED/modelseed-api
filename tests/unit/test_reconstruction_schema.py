"""Unit tests for ReconstructionRequest schema validation."""
import pytest
from pydantic import ValidationError
from modelseed_api.schemas.jobs import ReconstructionRequest


class TestGenomeFastaValidation:
    def test_none_is_valid(self):
        req = ReconstructionRequest(genome="83333.1", genome_fasta=None)
        assert req.genome_fasta is None

    def test_valid_protein_fasta(self):
        req = ReconstructionRequest(genome="custom", genome_fasta=">p1\nMKKLVAV")
        assert req.genome_fasta is not None

    def test_valid_dna_fasta(self):
        req = ReconstructionRequest(genome="custom", genome_fasta=">contig1\nACGTACGT")
        assert req.genome_fasta is not None

    def test_headers_only_rejected(self):
        with pytest.raises(ValidationError, match="FASTA"):
            ReconstructionRequest(genome="custom", genome_fasta=">c1\n>c2\n")

    def test_path_string_rejected(self):
        with pytest.raises(ValidationError, match="FASTA"):
            ReconstructionRequest(genome="custom", genome_fasta="/user/data/genome.fasta")

    def test_whitespace_only_rejected(self):
        with pytest.raises(ValidationError, match="FASTA"):
            ReconstructionRequest(genome="custom", genome_fasta="   \n   ")
