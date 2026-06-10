"""Unit tests for user-facing error translation in tasks.

These cover the conversions of raw upstream exceptions (WorkspaceError,
BV-BRC HTTPError) into clean message classes that get surfaced through
the celery task failure path.
"""

from __future__ import annotations

import pytest

from modelseed_api.jobs.tasks import (
    GenomeNotFoundError,
    ModelNotFoundError,
    _fetch_bvbrc_genome,
    _fetch_model_obj,
)
from modelseed_api.services.workspace_service import WorkspaceError


class FakeWs:
    def __init__(self, behavior):
        self._behavior = behavior

    def get(self, params):
        return self._behavior()


class TestFetchModelObjErrorTranslation:
    def test_workspace_object_not_found_becomes_clean_error(self):
        def raise_not_found():
            raise WorkspaceError("_ERROR_Object not found!_ERROR_")

        ws = FakeWs(raise_not_found)
        with pytest.raises(ModelNotFoundError) as exc_info:
            _fetch_model_obj(ws, "/u/modelseed/x", "tok")
        msg = str(exc_info.value)
        # Surface the path so the user knows exactly what to fix.
        assert "/u/modelseed/x/model" in msg
        # Tell them what to do.
        assert "reconstruct" in msg.lower()

    def test_other_workspace_error_propagates_unchanged(self):
        def raise_other():
            raise WorkspaceError("permission denied")

        ws = FakeWs(raise_other)
        with pytest.raises(WorkspaceError, match="permission denied"):
            _fetch_model_obj(ws, "/u/modelseed/x", "tok")

    def test_empty_result_becomes_clean_error(self):
        ws = FakeWs(lambda: [])
        with pytest.raises(ModelNotFoundError) as exc_info:
            _fetch_model_obj(ws, "/u/modelseed/x", "tok")
        assert "/u/modelseed/x/model" in str(exc_info.value)

    def test_happy_path_returns_parsed_dict(self):
        ws = FakeWs(lambda: [("path", '{"id": "model1", "reactions": []}')])
        result = _fetch_model_obj(ws, "/u/modelseed/x", "tok")
        assert result == {"id": "model1", "reactions": []}


class TestGenomeNotFoundErrorIsImportable:
    def test_class_exists_and_is_runtime_error_subclass(self):
        assert issubclass(GenomeNotFoundError, RuntimeError)


class _FakeBvbrc:
    """Stand-in for kbutillib.BVBRCUtils that records call args and
    raises whatever the test wires up."""

    def __init__(self, behavior):
        self._behavior = behavior
        self.calls: list[str] = []

    def build_kbase_genome_from_api(self, genome_id: str):
        self.calls.append(genome_id)
        return self._behavior()


class TestFetchBvbrcGenomeErrorTranslation:
    """`_fetch_bvbrc_genome` should translate every not-found shape that
    BV-BRC and KBUtilLib are known to surface into GenomeNotFoundError,
    and let everything else propagate unchanged.
    """

    def test_value_error_no_genome_found_becomes_clean_error(self):
        # BVBRCUtils raises this for IDs like "9999999.9".
        bv = _FakeBvbrc(lambda: (_ for _ in ()).throw(
            ValueError("No genome found with ID 9999999.9")
        ))
        with pytest.raises(GenomeNotFoundError) as exc_info:
            _fetch_bvbrc_genome(bv, "9999999.9")
        msg = str(exc_info.value)
        assert "9999999.9" in msg
        assert "BV-BRC" in msg
        assert "RAST" in msg  # we tell the user about the RAST flow

    def test_http_500_becomes_clean_error(self):
        bv = _FakeBvbrc(lambda: (_ for _ in ()).throw(
            RuntimeError("HTTPError 500 Internal Server Error from /data-api")
        ))
        with pytest.raises(GenomeNotFoundError):
            _fetch_bvbrc_genome(bv, "1589.518")

    def test_http_404_becomes_clean_error(self):
        bv = _FakeBvbrc(lambda: (_ for _ in ()).throw(
            RuntimeError("HTTPError 404 Not Found")
        ))
        with pytest.raises(GenomeNotFoundError):
            _fetch_bvbrc_genome(bv, "missing.1")

    def test_httperror_class_name_match(self):
        # Some upstream stacks raise a class actually named HTTPError.
        class HTTPError(Exception):
            pass

        bv = _FakeBvbrc(lambda: (_ for _ in ()).throw(HTTPError("oops")))
        with pytest.raises(GenomeNotFoundError):
            _fetch_bvbrc_genome(bv, "x")

    def test_unrelated_runtime_error_propagates_unchanged(self):
        # Anything that doesn't look like not-found is a real bug we want
        # to see, not silence behind a user-friendly message.
        bv = _FakeBvbrc(lambda: (_ for _ in ()).throw(
            RuntimeError("BVBRC API returned malformed feature record")
        ))
        with pytest.raises(RuntimeError, match="malformed feature record"):
            _fetch_bvbrc_genome(bv, "83332.12")

    def test_keyerror_propagates_unchanged(self):
        bv = _FakeBvbrc(lambda: (_ for _ in ()).throw(
            KeyError("'protein_translation'")
        ))
        with pytest.raises(KeyError):
            _fetch_bvbrc_genome(bv, "83332.12")

    def test_happy_path_returns_genome_dict(self):
        bv = _FakeBvbrc(lambda: {"scientific_name": "E. coli", "features": []})
        out = _fetch_bvbrc_genome(bv, "83332.12")
        assert out["scientific_name"] == "E. coli"
        assert bv.calls == ["83332.12"]


class TestAnnotateFastaRetriesOnTransient:
    def test_504_retries_then_succeeds(self, monkeypatch):
        from modelseed_api.services import genome_annotator

        attempts = {"count": 0}

        class FlakyClient:
            def __init__(self, url, timeout=600):
                pass

            def call(self, method, params):
                attempts["count"] += 1
                if attempts["count"] < 2:
                    raise RuntimeError(
                        "HTTPError: 504 Server Error: Gateway Timeout"
                    )
                return [{
                    "features": [
                        {"id": "p1", "protein_translation": "MKK",
                         "function": "Pyruvate kinase"},
                    ],
                }]

        monkeypatch.setattr(genome_annotator, "RPCClient", FlakyClient)
        # Speed up the test by zeroing the backoff.
        monkeypatch.setattr(genome_annotator, "_BACKOFF_SECONDS", (0, 0))

        ms_genome = genome_annotator.annotate_fasta(">p1\nMKKLVAVLIVSLAVAL")
        assert attempts["count"] == 2
        assert len(ms_genome.features) == 1

    def test_504_all_attempts_fails_with_original_exception(self, monkeypatch):
        from modelseed_api.services import genome_annotator

        class AlwaysFlakyClient:
            def __init__(self, url, timeout=600):
                pass

            def call(self, method, params):
                raise RuntimeError("HTTPError: 504 Gateway Timeout")

        monkeypatch.setattr(genome_annotator, "RPCClient", AlwaysFlakyClient)
        monkeypatch.setattr(genome_annotator, "_BACKOFF_SECONDS", (0, 0))

        with pytest.raises(RuntimeError, match="504"):
            genome_annotator.annotate_fasta(">p1\nMKKLVAVLIVSLAVAL")

    def test_non_transient_error_raises_immediately_no_retry(self, monkeypatch):
        from modelseed_api.services import genome_annotator

        attempts = {"count": 0}

        class BadRequestClient:
            def __init__(self, url, timeout=600):
                pass

            def call(self, method, params):
                attempts["count"] += 1
                raise RuntimeError("Invalid stage name 'bogus'")

        monkeypatch.setattr(genome_annotator, "RPCClient", BadRequestClient)
        monkeypatch.setattr(genome_annotator, "_BACKOFF_SECONDS", (0, 0))

        with pytest.raises(RuntimeError, match="Invalid stage"):
            genome_annotator.annotate_fasta(">p1\nMKKLVAVLIVSLAVAL")
        # No retries for non-5xx errors.
        assert attempts["count"] == 1
