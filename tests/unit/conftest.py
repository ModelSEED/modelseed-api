"""Shared fixtures for unit tests — hardcoded sample data, no I/O."""

import pytest


@pytest.fixture
def minimal_model_obj():
    """Minimal workspace model object with 3 reactions, 5 compounds, 2 compartments, 1 biomass."""
    return {
        "id": "test_model",
        "name": "Test Organism Model",
        "genome_ref": "/local/genomes/83333.1/genome||",
        "modelcompartments": [
            {"id": "c0", "label": "Cytosol", "pH": 7.0, "potential": 0},
            {"id": "e0", "label": "Extracellular", "pH": 7.0, "potential": 0},
        ],
        "modelcompounds": [
            {
                "id": "cpd00001_c0",
                "name": "H2O",
                "formula": "H2O",
                "charge": 0,
                "modelcompartment_ref": "~/modelcompartments/id/c0",
                "compound_ref": "~/compounds/id/cpd00001",
            },
            {
                "id": "cpd00002_c0",
                "name": "ATP",
                "formula": "C10H12N5O13P3",
                "charge": -4,
                "modelcompartment_ref": "~/modelcompartments/id/c0",
                "compound_ref": "~/compounds/id/cpd00002",
            },
            {
                "id": "cpd00008_c0",
                "name": "ADP",
                "formula": "C10H12N5O10P2",
                "charge": -3,
                "modelcompartment_ref": "~/modelcompartments/id/c0",
                "compound_ref": "~/compounds/id/cpd00008",
            },
            {
                "id": "cpd00009_c0",
                "name": "Pi",
                "formula": "HO4P",
                "charge": -2,
                "modelcompartment_ref": "~/modelcompartments/id/c0",
                "compound_ref": "~/compounds/id/cpd00009",
            },
            {
                "id": "cpd00027_e0",
                "name": "D-Glucose",
                "formula": "C6H12O6",
                "charge": 0,
                "modelcompartment_ref": "~/modelcompartments/id/e0",
                "compound_ref": "~/compounds/id/cpd00027",
            },
        ],
        "modelreactions": [
            {
                "id": "rxn00001_c0",
                "name": "ATP hydrolysis",
                "direction": ">",
                "reaction_ref": "~/template/reactions/id/rxn00001",
                "modelReactionReagents": [
                    {
                        "coefficient": -1,
                        "modelcompound_ref": "~/modelcompounds/id/cpd00002_c0",
                    },
                    {
                        "coefficient": -1,
                        "modelcompound_ref": "~/modelcompounds/id/cpd00001_c0",
                    },
                    {
                        "coefficient": 1,
                        "modelcompound_ref": "~/modelcompounds/id/cpd00008_c0",
                    },
                    {
                        "coefficient": 1,
                        "modelcompound_ref": "~/modelcompounds/id/cpd00009_c0",
                    },
                ],
                "modelReactionProteins": [
                    {
                        "note": "",
                        "modelReactionProteinSubunits": [
                            {
                                "role": "ATP synthase alpha",
                                "feature_refs": [
                                    "~/genome/features/id/fig|83333.1.peg.1"
                                ],
                            }
                        ],
                    }
                ],
                "gapfill_data": {},
            },
            {
                "id": "rxn00002_c0",
                "name": "Phosphorylation",
                "direction": "=",
                "reaction_ref": "~/template/reactions/id/rxn00002",
                "modelReactionReagents": [
                    {
                        "coefficient": -2,
                        "modelcompound_ref": "~/modelcompounds/id/cpd00002_c0",
                    },
                    {
                        "coefficient": 2,
                        "modelcompound_ref": "~/modelcompounds/id/cpd00008_c0",
                    },
                ],
                "modelReactionProteins": [
                    {
                        "note": "",
                        "modelReactionProteinSubunits": [
                            {
                                "role": "subunit A",
                                "feature_refs": [
                                    "~/genome/features/id/fig|83333.1.peg.2"
                                ],
                            },
                            {
                                "role": "subunit B",
                                "feature_refs": [
                                    "~/genome/features/id/fig|83333.1.peg.3"
                                ],
                            },
                        ],
                    }
                ],
                "gapfill_data": {},
            },
            {
                "id": "rxn00003_c0",
                "name": "No-gene reaction",
                "direction": "<",
                "reaction_ref": "~/template/reactions/id/rxn00003",
                "modelReactionReagents": [
                    {
                        "coefficient": -1,
                        "modelcompound_ref": "~/modelcompounds/id/cpd00001_c0",
                    },
                    {
                        "coefficient": 1,
                        "modelcompound_ref": "~/modelcompounds/id/cpd00009_c0",
                    },
                ],
                "modelReactionProteins": [],
                "gapfill_data": {},
            },
        ],
        "biomasses": [
            {
                "id": "bio1",
                "name": "Biomass",
                "biomasscompounds": [
                    {
                        "modelcompound_ref": "~/modelcompounds/id/cpd00002_c0",
                        "coefficient": -0.5,
                    },
                    {
                        "modelcompound_ref": "~/modelcompounds/id/cpd00001_c0",
                        "coefficient": -10,
                    },
                    {
                        "modelcompound_ref": "~/modelcompounds/id/cpd00009_c0",
                        "coefficient": 1.0,
                    },
                ],
            }
        ],
        "gapfillings": [],
        "fbaFormulations": [],
        "fba_studies": [],
    }


@pytest.fixture
def cpd_name_map():
    """Compound ID to name mapping for equation building."""
    return {
        "cpd00001_c0": "H2O",
        "cpd00002_c0": "ATP",
        "cpd00008_c0": "ADP",
        "cpd00009_c0": "Pi",
        "cpd00027_e0": "D-Glucose",
    }


@pytest.fixture
def gapfill_model_legacy():
    """Model with legacy KBase gapfillingSolutions format."""
    return {
        "modelreactions": [
            {"id": "rxn00062_c0", "gapfill_data": {}},
            {"id": "rxn00100_c0", "gapfill_data": {}},
        ],
        "gapfillings": [
            {
                "id": "gf.0",
                "rundate": "2026-01-01",
                "media_ref": "/media/Complete||",
                "integrated": True,
                "integrated_solution": 0,
                "fba_ref": "",
                "gapfillingSolutions": [
                    {
                        "gapfillingSolutionReactions": [
                            {
                                "reaction_ref": "~/fbamodel/template/reactions/id/rxn00062",
                                "direction": ">",
                                "compartment_ref": "~/compartments/id/c",
                                "compartmentIndex": 0,
                            },
                            {
                                "reaction_ref": "~/fbamodel/template/reactions/id/rxn00100",
                                "direction": "=",
                                "compartment_ref": "~/compartments/id/c",
                                "compartmentIndex": 0,
                            },
                        ]
                    }
                ],
            }
        ],
    }


@pytest.fixture
def gapfill_model_mspy_string():
    """Model with ModelSEEDpy string gapfill_data format."""
    return {
        "modelreactions": [
            {"id": "rxn00062_c0", "gapfill_data": {"gf.0": "added:>"}},
            {"id": "rxn00100_c0", "gapfill_data": {"gf.0": "added:="}},
        ],
        "gapfillings": [
            {
                "id": "gf.0",
                "rundate": "2026-01-01",
                "media_ref": "/media/Complete||",
                "integrated": True,
                "integrated_solution": 0,
                "fba_ref": "",
            }
        ],
    }


@pytest.fixture
def gapfill_model_mspy_dict():
    """Model with ModelSEEDpy dict gapfill_data format."""
    return {
        "modelreactions": [
            {"id": "rxn00062_c0", "gapfill_data": {"gf.0": {"0": [">", 1, []]}}},
            {"id": "rxn00100_c0", "gapfill_data": {"gf.0": {"0": ["=", 1, []]}}},
        ],
        "gapfillings": [
            {
                "id": "gf.0",
                "rundate": "2026-01-01",
                "media_ref": "/media/Complete||",
                "integrated": True,
                "integrated_solution": 0,
                "fba_ref": "",
            }
        ],
    }


@pytest.fixture
def gapfill_model_solutiondata():
    """Model with stringified solutiondata format."""
    import json

    return {
        "modelreactions": [
            {"id": "rxn00062_c0", "gapfill_data": {}},
            {"id": "rxn00100_c0", "gapfill_data": {}},
        ],
        "gapfillings": [
            {
                "id": "gf.0",
                "rundate": "2026-01-01",
                "media_ref": "/media/Complete||",
                "integrated": True,
                "integrated_solution": 0,
                "fba_ref": "",
                "solutiondata": json.dumps(
                    [
                        {
                            "reactions": [
                                {
                                    "reaction": "rxn00062",
                                    "direction": ">",
                                    "compartment": "c",
                                    "compartmentIndex": 0,
                                },
                                {
                                    "reaction": "rxn00100",
                                    "direction": "=",
                                    "compartment": "c",
                                    "compartmentIndex": 0,
                                },
                            ]
                        }
                    ]
                ),
            }
        ],
    }
