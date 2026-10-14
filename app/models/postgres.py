"""Compatibility layer mapping old model names to Sprint 1 & Sprint 2 domain models.

All actual models are declared in:
- app.models.user_access.entities (Auth, Users, Roles, Sessions)
- app.models.family.entities (Clans, Memberships, Subscriptions, Provisioning)
- app.models.genealogy.entities (Branches, Persons, Relationships, PersonClosure)
"""

from __future__ import annotations

from app.models.family.entities import (
    Clan,
    ClanMembership,
    ClanOwnershipHistory,
    ClanProfile,
    ClanSubscription,
    FamilyAdminAssignment,
    IdempotencyKey,
    ProvisioningJob,
)
from app.models.genealogy.entities import (
    Branch,
    FamilyBranch,
    Person,
    PersonClosure,
    Relationship,
)
from app.models.user_access.entities import (
    AuditLog,
    LoginHistory,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
    UserSession,
)

# Aliases used in Sprint 2 codebase
Account = User
AccountRole = UserRole
AccountSession = UserSession
Family = Clan
FamilyMembership = ClanMembership
Member = ClanMembership

__all__ = [
    "Account",
    "AccountRole",
    "AccountSession",
    "Family",
    "FamilyMembership",
    "AuditLog",
    "Branch",
    "Clan",
    "ClanMembership",
    "ClanOwnershipHistory",
    "ClanProfile",
    "ClanSubscription",
    "FamilyAdminAssignment",
    "FamilyBranch",
    "IdempotencyKey",
    "LoginHistory",
    "Permission",
    "Person",
    "PersonClosure",
    "ProvisioningJob",
    "Relationship",
    "Role",
    "RolePermission",
    "User",
    "UserRole",
    "UserSession",
]