"""Compatibility bridge: Genealogy schemas are now located at app.schemas.genealogy."""

from app.schemas.genealogy import (
    AncestorDescendantResponse,
    PersonCreate,
    PersonResponse,
    PersonUpdate,
    RelationshipCreate,
    RelationshipPath,
    RelationshipResponse,
    TreeDataResponse,
    TreeNode,
)

__all__ = [
    "PersonResponse",
    "PersonCreate",
    "PersonUpdate",
    "AncestorDescendantResponse",
    "RelationshipCreate",
    "RelationshipResponse",
    "TreeNode",
    "TreeDataResponse",
    "RelationshipPath",
]
