"""Live integration tests against the real PATRIC workspace.

Run with: PATRIC_TOKEN="un=...token..." python -m pytest tests/test_live_integration.py -v -s

These tests make real calls to the PATRIC workspace service and require
a valid authentication token.
"""

import json
import os
import sys

import pytest

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from modelseed_api.auth.dependencies import _extract_username
from modelseed_api.services.workspace_service import WorkspaceService
from modelseed_api.services.model_service import ModelService


TOKEN = os.environ.get("PATRIC_TOKEN", "")
SKIP_REASON = "PATRIC_TOKEN not set"


@pytest.fixture
def token():
    if not TOKEN:
        pytest.skip(SKIP_REASON)
    return TOKEN


@pytest.fixture
def username(token):
    return _extract_username(token)


@pytest.fixture
def ws(token):
    return WorkspaceService(token)


@pytest.fixture
def model_svc(token):
    return ModelService(token)


class TestTokenParsing:
    def test_extract_username(self, token, username):
        print(f"  Username: {username}")
        assert username
        assert "@" in username or len(username) > 2


class TestWorkspaceProxy:
    def test_ls_home(self, ws, username):
        """List the user's home workspace directory."""
        path = f"/{username}/"
        result = ws.ls({"paths": [path]})
        print(f"  Home dir contents ({path}):")
        assert result is not None
        assert path in result
        for item in result[path]:
            print(f"    {item[1]:20s} {item[0]}")

    def test_ls_modelseed(self, ws, username):
        """List the user's modelseed directory (where models live)."""
        path = f"/{username}/modelseed/"
        result = ws.ls({"paths": [path]})
        print(f"  Modelseed dir ({path}):")
        if result and path in result:
            for item in result[path]:
                print(f"    {item[1]:20s} {item[0]}")
        else:
            print("    (empty or doesn't exist)")

    def test_ls_public_media(self, ws):
        """List public media folder."""
        path = "/chenry/public/modelsupport/media/"
        result = ws.ls({"paths": [path]})
        print(f"  Public media ({path}):")
        if result and path in result:
            count = len(result[path])
            print(f"    {count} media items")
            for item in result[path][:5]:
                print(f"    {item[0]}")
            if count > 5:
                print(f"    ... and {count - 5} more")
        else:
            print("    (empty or doesn't exist)")

    def test_get_metadata(self, ws, username):
        """Get metadata for the user's modelseed folder."""
        path = f"/{username}/modelseed"
        result = ws.get({"objects": [path], "metadata_only": True})
        print(f"  Metadata for {path}:")
        if result:
            meta = result[0]
            if isinstance(meta, list) and len(meta) > 0:
                actual_meta = meta[0] if isinstance(meta[0], list) else meta
                print(f"    Name: {actual_meta[0] if len(actual_meta) > 0 else 'N/A'}")
                print(f"    Type: {actual_meta[1] if len(actual_meta) > 1 else 'N/A'}")


class TestModelService:
    def test_list_models(self, model_svc, username):
        """List all user models via ModelService."""
        models = model_svc.list_models(username=username)
        print(f"  Found {len(models)} models:")
        for m in models[:10]:
            print(f"    {m['name']:40s} rxns={m['num_reactions']} genes={m['num_genes']} gapfills={m['integrated_gapfills']}")
        if len(models) > 10:
            print(f"    ... and {len(models) - 10} more")
        assert isinstance(models, list)

    def test_get_first_model(self, model_svc, username):
        """Get full data for the first model found."""
        models = model_svc.list_models(username=username)
        if not models:
            pytest.skip("No models found for user")

        first = models[0]
        print(f"  Loading model: {first['name']} ({first['ref']})")
        model_data = model_svc.get_model(first["ref"])

        print(f"    Reactions:    {len(model_data['reactions'])}")
        print(f"    Compounds:    {len(model_data['compounds'])}")
        print(f"    Genes:        {len(model_data['genes'])}")
        print(f"    Compartments: {len(model_data['compartments'])}")
        print(f"    Biomasses:    {len(model_data['biomasses'])}")

        assert model_data["ref"] == first["ref"]
        assert len(model_data["reactions"]) >= 0
        assert len(model_data["compounds"]) >= 0

    def test_list_gapfills(self, model_svc, username):
        """List gapfill solutions for the first model."""
        models = model_svc.list_models(username=username)
        if not models:
            pytest.skip("No models found for user")

        first = models[0]
        gapfills = model_svc.list_gapfill_solutions(first["ref"])
        print(f"  Gapfills for {first['name']}: {len(gapfills)}")
        for gf in gapfills[:3]:
            print(f"    {gf['id']} integrated={gf['integrated']} media={gf.get('media_ref', 'N/A')}")

    def test_list_fba(self, model_svc, username):
        """List FBA studies for the first model."""
        models = model_svc.list_models(username=username)
        if not models:
            pytest.skip("No models found for user")

        first = models[0]
        fbas = model_svc.list_fba_studies(first["ref"])
        print(f"  FBA studies for {first['name']}: {len(fbas)}")
        for fba in fbas[:3]:
            print(f"    {fba['id']} objective={fba.get('objective', 'N/A')}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
