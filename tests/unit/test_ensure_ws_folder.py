"""Tests for _ensure_ws_folder.

Regression for ModelSEED/modelseed-api-ops#11: PATRIC workspace returns
"Insufficient permissions" instead of "Not Found" when creating inside
a missing intermediate directory, which hits first-time users who have
not yet had a /username/modelseed folder created.
"""
from unittest.mock import MagicMock

from modelseed_api.jobs.tasks import _ensure_ws_folder


def test_creates_folder():
    ws = MagicMock()
    _ensure_ws_folder(ws, "/alice/modelseed")
    ws.create.assert_called_once_with(
        {"objects": [["/alice/modelseed", "folder", {}, ""]], "overwrite": 1}
    )


def test_strips_trailing_slash():
    ws = MagicMock()
    _ensure_ws_folder(ws, "/alice/modelseed/")
    ws.create.assert_called_once_with(
        {"objects": [["/alice/modelseed", "folder", {}, ""]], "overwrite": 1}
    )


def test_noop_for_root_and_empty():
    ws = MagicMock()
    _ensure_ws_folder(ws, "")
    _ensure_ws_folder(ws, "/")
    _ensure_ws_folder(ws, "//")
    ws.create.assert_not_called()


def test_noop_for_none():
    ws = MagicMock()
    _ensure_ws_folder(ws, None)
    ws.create.assert_not_called()
