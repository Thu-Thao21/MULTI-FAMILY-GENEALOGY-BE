"""Compatibility bridge: GenealogyService is now located at app.services.genealogy."""

from app.services.genealogy import GenealogyService

__all__ = ["GenealogyService"]
