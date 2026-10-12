"""Compatibility re-export pointing to M03 Genealogy Model (app.models.genealogy)."""

from app.models.genealogy.entities import (
    Branch,
    FamilyBranch,
    Person,
    PersonClosure,
    Relationship,
)

__all__ = [
    "Branch",
    "FamilyBranch",
    "Person",
    "PersonClosure",
    "Relationship",
]
