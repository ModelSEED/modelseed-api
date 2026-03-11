"""Pydantic schemas for model-related data structures.

These match the type definitions in ProbModelSEED.spec exactly.
Field names are preserved for frontend compatibility.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class GapfillReaction(BaseModel):
    """A single reaction added during gapfilling."""

    reaction: str
    direction: str  # '<', '=', '>'
    compartment: str


class GapfillData(BaseModel):
    """Data for a gapfilling solution."""

    rundate: str
    id: str
    ref: str
    media_ref: str
    integrated: bool
    integrated_solution: int
    solution_reactions: list[list[GapfillReaction]]


class FBAData(BaseModel):
    """Data for an FBA study result."""

    rundate: str
    id: str
    ref: str
    objective: float
    media_ref: str
    objective_function: str


class ModelStats(BaseModel):
    """Summary statistics for a metabolic model.

    Returned by list_models. The frontend sanitizeModel() function
    (ModelSEED-UI/app/services/ms.js:240) accesses these fields directly.
    """

    rundate: str
    id: str
    source: Optional[str] = None
    source_id: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = None
    ref: str
    genome_ref: Optional[str] = None
    template_ref: Optional[str] = None
    fba_count: int = 0
    integrated_gapfills: int = 0
    unintegrated_gapfills: int = 0
    gene_associated_reactions: int = 0
    gapfilled_reactions: int = 0
    num_genes: int = 0
    num_compounds: int = 0
    num_reactions: int = 0
    num_biomasses: int = 0
    num_biomass_compounds: int = 0
    num_compartments: int = 0
    # Additional fields the frontend may use
    status: Optional[str] = None
    expression_data: Optional[list[Any]] = None


class ModelReaction(BaseModel):
    """A reaction in a metabolic model."""

    id: str
    name: str
    stoichiometry: list[Any]  # [coefficient, cpd_id, compartment, compartment_index, name]
    direction: str
    gpr: str
    genes: list[str]


class ModelCompound(BaseModel):
    """A compound (metabolite) in a metabolic model."""

    id: str
    name: str
    formula: Optional[str] = None
    charge: Optional[float] = None


class ModelGene(BaseModel):
    """A gene in a metabolic model."""

    id: str
    reactions: list[str]


class ModelCompartment(BaseModel):
    """A compartment in a metabolic model."""

    id: str
    name: str
    pH: Optional[float] = None
    potential: Optional[float] = None


class ModelBiomass(BaseModel):
    """A biomass reaction in a metabolic model."""

    id: str
    compounds: list[Any]  # [compound_id, coefficient, compartment]


class ModelData(BaseModel):
    """Full model data including reactions, compounds, genes, compartments, biomasses.

    Returned by get_model.
    """

    ref: str
    reactions: list[ModelReaction]
    compounds: list[ModelCompound]
    genes: list[ModelGene]
    compartments: list[ModelCompartment]
    biomasses: list[ModelBiomass]


class SimpleEditOutput(BaseModel):
    """Summary of a model edit."""

    id: str
    timestamp: str
    reactions_removed: list[str] = []
    reactions_added: list[str] = []
    reactions_modified: list[str] = []
    biomass_added: list[str] = []
    biomass_changed: list[str] = []
    biomass_removed: list[str] = []


class DetailedEditOutput(BaseModel):
    """Detailed model edit with full reaction/biomass data."""

    id: str
    timestamp: str
    reactions_removed: list[dict[str, str]] = []
    reactions_added: list[dict[str, str]] = []
    reactions_modified: list[dict[str, str]] = []
    biomass_added: list[dict[str, str]] = []
    biomass_changed: list[dict[str, str]] = []
    biomass_removed: list[dict[str, str]] = []


# Request schemas


class CopyModelRequest(BaseModel):
    """Request to copy a model."""

    model: str  # source reference
    destination: Optional[str] = None
    destname: Optional[str] = None
    copy_genome: bool = False
    to_kbase: bool = False
    workspace_url: Optional[str] = None
    kbase_username: Optional[str] = None
    kbase_password: Optional[str] = None
    plantseed: bool = False


class EditModelRequest(BaseModel):
    """Request to edit a model."""

    model: str
    biomass_changes: list[Any] = []
    reactions_to_remove: list[str] = []
    reactions_to_add: list[Any] = []
    reactions_to_modify: list[Any] = []


class ManageGapfillsRequest(BaseModel):
    """Request to manage gapfill solutions."""

    model: str
    commands: dict[str, str]  # {gapfill_id: command (D/I/U)}
    selected_solutions: Optional[dict[str, int]] = None
