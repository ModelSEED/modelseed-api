"""Pydantic models for RAST legacy endpoints."""

from pydantic import BaseModel


class RASTJob(BaseModel):
    """A RAST annotation job from the legacy RastProdJobCache database."""

    owner: str
    project: str
    id: str
    creation_time: str
    mod_time: str
    genome_size: int
    contig_count: int
    genome_id: str
    genome_name: str
    type: str
