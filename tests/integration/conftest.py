"""Shared fixtures for integration tests — real filesystem, temp dirs."""

import json
import os

import pytest


SAMPLE_MODEL = {
    "id": "test_model",
    "name": "Test Model",
    "genome_ref": "/local/genomes/83333.1/genome||",
    "modelcompartments": [
        {"id": "c0", "label": "Cytosol", "pH": 7.0, "potential": 0},
        {"id": "e0", "label": "Extracellular", "pH": 7.0, "potential": 0},
    ],
    "modelcompounds": [
        {"id": "cpd00001_c0", "name": "H2O", "formula": "H2O", "charge": 0},
        {"id": "cpd00002_c0", "name": "ATP", "formula": "C10H12N5O13P3", "charge": -4},
    ],
    "modelreactions": [
        {
            "id": "rxn00001_c0",
            "name": "ATP hydrolysis",
            "direction": ">",
            "reaction_ref": "~/template/reactions/id/rxn00001",
            "modelReactionReagents": [
                {"coefficient": -1, "modelcompound_ref": "~/modelcompounds/id/cpd00002_c0"},
                {"coefficient": -1, "modelcompound_ref": "~/modelcompounds/id/cpd00001_c0"},
            ],
            "modelReactionProteins": [],
            "gapfill_data": {},
        }
    ],
    "biomasses": [
        {
            "id": "bio1",
            "name": "Biomass",
            "biomasscompounds": [
                {"modelcompound_ref": "~/modelcompounds/id/cpd00001_c0", "coefficient": -10},
            ],
        }
    ],
    "gapfillings": [],
    "fbaFormulations": [],
    "fba_studies": [],
}


@pytest.fixture
def local_data_dir(tmp_path, monkeypatch):
    """Set up environment for local storage and return the data directory path."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("MODELSEED_STORAGE_BACKEND", "local")
    monkeypatch.setenv("MODELSEED_LOCAL_DATA_DIR", str(data_dir))
    # Patch the settings singleton directly
    from modelseed_api.config import settings

    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "local_data_dir", str(data_dir))
    return data_dir


@pytest.fixture
def local_storage(local_data_dir):
    """Return a LocalStorageService instance backed by a temp directory."""
    from modelseed_api.services.local_storage_service import LocalStorageService

    return LocalStorageService(token="test-token", data_dir=str(local_data_dir))


@pytest.fixture
def sample_model_json():
    """JSON string of a minimal valid model."""
    return json.dumps(SAMPLE_MODEL)


@pytest.fixture
def populated_storage(local_storage, sample_model_json):
    """Local storage with a pre-created model folder + model object."""
    local_storage.create({
        "objects": [["/local/modelseed/TestModel", "modelfolder", {
            "id": "TestModel",
            "name": "TestModel",
            "num_reactions": "1",
            "num_compounds": "2",
            "num_genes": "0",
            "num_compartments": "2",
            "num_biomasses": "1",
        }, None]],
    })
    local_storage.create({
        "objects": [["/local/modelseed/TestModel/model", "model", {}, sample_model_json]],
        "overwrite": True,
    })
    return local_storage


@pytest.fixture
def job_store_dir(tmp_path, monkeypatch):
    """Return a temp directory configured for JobStore."""
    job_dir = tmp_path / "jobs"
    job_dir.mkdir()
    from modelseed_api.config import settings

    monkeypatch.setattr(settings, "job_store_dir", str(job_dir))
    return job_dir
