"""C03 - Genealogy Controller package."""

from app.controllers.genealogy.controller import GenealogyController
from app.controllers.genealogy.router import router

__all__ = ["GenealogyController", "router"]
