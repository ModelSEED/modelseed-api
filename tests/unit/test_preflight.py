"""Unit tests for pre-flight validation helpers.

Mocks out workspace and BV-BRC clients so the tests can run anywhere
without network access. Live integration coverage is in
tests/live/test_preflight.py.
"""

from __future__ import annotations

import pytest

from modelseed_api.schemas.errors import StructuredValidationError
from modelseed_api.services import preflight
from modelseed_api.services.workspace_service import WorkspaceError


class _FakeWs:
    """Minimal WorkspaceService stub. behaviors: dict mapping
    method name -> callable returning the result or raising."""

    def __init__(self, behaviors: dict) -> None:
        self._b = behaviors

    def get(self, params):
        return self._b["get"](params)

    def ls(self, params):
        return self._b.get("ls", lambda p: [])(params)


# ─────────────────────────────────────────────────────────────────────
# validate_model_exists
# ─────────────────────────────────────────────────────────────────────


def _patch_storage(monkeypatch, ws):
    monkeypatch.setattr(
        preflight,
        "get_storage_service",
        lambda token: ws,
        raising=False,
    )
    # The import inside preflight is local; patch it where it lands.
    import modelseed_api.services.storage_factory as sf
    monkeypatch.setattr(sf, "get_storage_service", lambda token: ws)


def test_validate_model_exists_happy_path(monkeypatch):
    ws = _FakeWs({"get": lambda p: [("path", '{"id":"m"}')]})
    _patch_storage(monkeypatch, ws)
    preflight.validate_model_exists("/u/modelseed/x", "tok")


def test_validate_model_exists_not_found(monkeypatch):
    def raise_nf(p):
        raise WorkspaceError("_ERROR_Object not found!_ERROR_")
    ws = _FakeWs({"get": raise_nf})
    _patch_storage(monkeypatch, ws)
    with pytest.raises(StructuredValidationError) as exc_info:
        preflight.validate_model_exists("/u/modelseed/x", "tok")
    assert exc_info.value.status_code == 404
    assert exc_info.value.error.code == "MODEL_NOT_FOUND"
    assert "/u/modelseed/x" in exc_info.value.error.message
    assert exc_info.value.error.field == "model"


def test_validate_model_exists_empty_result_is_not_found(monkeypatch):
    ws = _FakeWs({"get": lambda p: []})
    _patch_storage(monkeypatch, ws)
    with pytest.raises(StructuredValidationError) as exc_info:
        preflight.validate_model_exists("/u/modelseed/x", "tok")
    assert exc_info.value.status_code == 404
    assert exc_info.value.error.code == "MODEL_NOT_FOUND"


def test_validate_model_exists_token_expired(monkeypatch):
    def raise_tok(p):
        raise WorkspaceError("Token validation failed: Token expired")
    ws = _FakeWs({"get": raise_tok})
    _patch_storage(monkeypatch, ws)
    with pytest.raises(StructuredValidationError) as exc_info:
        preflight.validate_model_exists("/u/modelseed/x", "tok")
    assert exc_info.value.status_code == 401
    assert exc_info.value.error.code == "TOKEN_EXPIRED"


def test_validate_model_exists_other_workspace_error_propagates(monkeypatch):
    def raise_other(p):
        raise WorkspaceError("Internal server error (HTTP 500)")
    ws = _FakeWs({"get": raise_other})
    _patch_storage(monkeypatch, ws)
    with pytest.raises(WorkspaceError, match="Internal server error"):
        preflight.validate_model_exists("/u/modelseed/x", "tok")


# ─────────────────────────────────────────────────────────────────────
# validate_media_exists
# ─────────────────────────────────────────────────────────────────────


def test_validate_media_exists_builtin_name_is_trusted(monkeypatch):
    # Built-in media names (no leading "/") are not workspace paths.
    # Validator must short-circuit without making a workspace call.
    def boom(p):
        pytest.fail("workspace must not be called for built-in media name")
    ws = _FakeWs({"get": boom})
    _patch_storage(monkeypatch, ws)
    preflight.validate_media_exists("Complete", "tok")


def test_validate_media_exists_workspace_happy(monkeypatch):
    ws = _FakeWs({"get": lambda p: [("path", '{"compounds":[]}')]})
    _patch_storage(monkeypatch, ws)
    preflight.validate_media_exists("/u/media/MyMedia", "tok")


def test_validate_media_exists_workspace_not_found(monkeypatch):
    def raise_nf(p):
        raise WorkspaceError("_ERROR_Object not found!_ERROR_")
    ws = _FakeWs({"get": raise_nf})
    _patch_storage(monkeypatch, ws)
    with pytest.raises(StructuredValidationError) as exc_info:
        preflight.validate_media_exists("/u/media/Missing", "tok")
    assert exc_info.value.error.code == "MEDIA_NOT_FOUND"
    assert exc_info.value.error.field == "media"


# ─────────────────────────────────────────────────────────────────────
# validate_token
# ─────────────────────────────────────────────────────────────────────


def test_validate_token_empty_is_expired():
    with pytest.raises(StructuredValidationError) as exc_info:
        preflight.validate_token("")
    assert exc_info.value.status_code == 401
    assert exc_info.value.error.code == "TOKEN_EXPIRED"


def test_validate_token_workspace_ok(monkeypatch):
    ws = _FakeWs({"ls": lambda p: []})
    _patch_storage(monkeypatch, ws)
    preflight.validate_token("un=alice|tokenid=abc")


def test_validate_token_workspace_token_failed(monkeypatch):
    def raise_tok(p):
        raise WorkspaceError("Token validation failed: Token expired")
    ws = _FakeWs({"ls": raise_tok})
    _patch_storage(monkeypatch, ws)
    with pytest.raises(StructuredValidationError) as exc_info:
        preflight.validate_token("un=alice|tokenid=abc")
    assert exc_info.value.error.code == "TOKEN_EXPIRED"
    assert exc_info.value.status_code == 401


# ─────────────────────────────────────────────────────────────────────
# validate_genome_exists
# ─────────────────────────────────────────────────────────────────────
# These rely on patching BVBRCUtils inside the function. Keeping the
# patch local because the helper imports kbutillib at call time.


class _FakeBvbrc:
    def __init__(self, behavior):
        self._b = behavior

    def build_kbase_genome_from_api(self, genome_id: str):
        return self._b(genome_id)


def _patch_bvbrc(monkeypatch, behavior):
    def fake_init_kwargs(token):
        return {"token": token}
    import modelseed_api.jobs.tasks as tasks_mod
    monkeypatch.setattr(tasks_mod, "_init_kwargs", fake_init_kwargs)
    import kbutillib
    monkeypatch.setattr(kbutillib, "BVBRCUtils", lambda **kw: _FakeBvbrc(behavior))


def test_validate_genome_exists_happy(monkeypatch):
    _patch_bvbrc(monkeypatch, lambda g: {"scientific_name": "E. coli"})
    preflight.validate_genome_exists("83332.12", "tok")


def test_validate_genome_exists_value_error_no_genome(monkeypatch):
    def raise_nf(g):
        raise ValueError(f"No genome found with ID {g}")
    _patch_bvbrc(monkeypatch, raise_nf)
    with pytest.raises(StructuredValidationError) as exc_info:
        preflight.validate_genome_exists("9999999.9", "tok")
    assert exc_info.value.status_code == 404
    assert exc_info.value.error.code == "GENOME_NOT_FOUND"
    assert "9999999.9" in exc_info.value.error.message
    assert exc_info.value.error.field == "genome"


def test_validate_genome_exists_strips_source_prefix(monkeypatch):
    seen = {}
    def remember(g):
        seen["g"] = g
        return {"scientific_name": "E. coli"}
    _patch_bvbrc(monkeypatch, remember)
    preflight.validate_genome_exists("PATRIC:83332.12", "tok")
    assert seen["g"] == "83332.12"


def test_validate_genome_exists_500_is_not_found(monkeypatch):
    def raise_500(g):
        raise RuntimeError("HTTPError 500 Internal Server Error from BV-BRC")
    _patch_bvbrc(monkeypatch, raise_500)
    with pytest.raises(StructuredValidationError) as exc_info:
        preflight.validate_genome_exists("1589.518", "tok")
    assert exc_info.value.error.code == "GENOME_NOT_FOUND"


def test_validate_genome_exists_transient_error_is_skipped_not_failed(monkeypatch):
    # Transient (non-not-found) errors must not 4xx the user: it isn't
    # their fault that BV-BRC blipped. Preflight is best-effort.
    def raise_transient(g):
        raise RuntimeError("Connection timeout, retry later")
    _patch_bvbrc(monkeypatch, raise_transient)
    # Should NOT raise.
    preflight.validate_genome_exists("83332.12", "tok")
