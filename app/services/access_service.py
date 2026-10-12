"""Compatibility bridge: AccessService is now located at app.services.auth_access."""

from app.services.auth_access import AccessService, get_default_permission_codes

__all__ = ["AccessService", "get_default_permission_codes"]
