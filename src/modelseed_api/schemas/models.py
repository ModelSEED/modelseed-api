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
    """Data for an FBA study result (summary — no flux values)."""

    rundate: str
    id: str
    ref: str
    objective: float
    media_ref: str
    objective_function: str


class FBADetail(BaseModel):
    """Full FBA result including flux data."""

    id: str
    model_ref: str
    media_ref: str
    objectiveValue: float
    status: str
    rundate: str
    fluxes: dict[str, float]


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
    owner: Optional[str] = None
    creation_date: Optional[str] = None
    modified: Optional[str] = None
    wsid: Optional[str] = None
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


# Edit schemas — reaction operations


class ReactionToAdd(BaseModel):
    """Add a reaction from the ModelSEED biochemistry database."""

    reaction_id: str  # biochem ID, e.g., "rxn00001"
    compartment: str = "c0"
    direction: Optional[str] = None  # ">", "<", "=" — None = use DB default
    gpr: Optional[str] = None  # e.g., "gene1 or (gene2 and gene3)"


class ReactionToModify(BaseModel):
    """Modify an existing reaction in the model."""

    reaction_id: str  # model reaction ID, e.g., "rxn00001_c0"
    direction: Optional[str] = None
    name: Optional[str] = None
    gpr: Optional[str] = None  # empty string = clear GPR


# Edit schemas — compound operations


class CompoundToAdd(BaseModel):
    """Add a compound from the ModelSEED biochemistry database."""

    compound_id: str  # biochem ID, e.g., "cpd00001"
    compartment: str = "c0"
    name: Optional[str] = None  # override DB name
    formula: Optional[str] = None
    charge: Optional[float] = None


class CompoundToModify(BaseModel):
    """Modify an existing compound in the model."""

    compound_id: str  # model compound ID, e.g., "cpd00001_c0"
    name: Optional[str] = None
    formula: Optional[str] = None
    charge: Optional[float] = None


# Edit schemas — biomass operations


class BiomassCompoundChange(BaseModel):
    """Modify a compound's coefficient in a biomass reaction."""

    compound_id: str  # model compound ID, e.g., "cpd00001_c0"
    coefficient: float  # 0 = remove from biomass


class BiomassChange(BaseModel):
    """Changes to a biomass reaction."""

    biomass_id: str  # e.g., "bio1"
    name: Optional[str] = None
    compound_changes: list[BiomassCompoundChange] = []


class BiomassToAdd(BaseModel):
    """Add a new biomass reaction."""

    name: str = "New Biomass"
    compounds: list[BiomassCompoundChange] = []


# Request/response schemas


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
    """Request to edit a model. All operations applied atomically."""

    model: str  # workspace ref (required)
    reactions_to_add: list[ReactionToAdd] = []
    reactions_to_remove: list[str] = []  # model reaction IDs
    reactions_to_modify: list[ReactionToModify] = []
    compounds_to_add: list[CompoundToAdd] = []
    compounds_to_remove: list[str] = []  # model compound IDs
    compounds_to_modify: list[CompoundToModify] = []
    biomass_changes: list[BiomassChange] = []
    biomasses_to_add: list[BiomassToAdd] = []
    biomasses_to_remove: list[str] = []


class EditModelResponse(BaseModel):
    """Summary of all edits applied."""

    model: str
    reactions_added: list[str] = []
    reactions_removed: list[str] = []
    reactions_modified: list[str] = []
    compounds_added: list[str] = []
    compounds_removed: list[str] = []
    compounds_modified: list[str] = []
    biomasses_added: list[str] = []
    biomasses_modified: list[str] = []
    biomasses_removed: list[str] = []
    warnings: list[str] = []


class ManageGapfillsRequest(BaseModel):
    """Request to manage gapfill solutions."""

    model: str
    commands: dict[str, str]  # {gapfill_id: command (D/I/U)}
    selected_solutions: Optional[dict[str, int]] = None
