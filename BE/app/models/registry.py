"""Import all Sprint-1 ORM models so Alembic sees a single MetaData.

Order matters only for readability: ForeignKey("clans.clan_id") in user_access
(audit_logs, user_roles) resolves once app.models.family is imported here.
"""

from app.models.base import Base
from app.models.family.entities import (  # noqa: F401
    AccountInvitation,
    BusinessRegistration,
    Clan,
    ClanMembership,
    ClanOwnershipHistory,
    ClanProfile,
    ClanSubscription,
    EmailDeliveryAttempt,
    EmailDeliveryLog,
    FamilyAdminAssignment,
    FamilyAdminPermission,
    IdempotencyKey,
    PasswordResetToken,
    PersonAccountLink,
    PlanFeatureLimit,
    ProvisioningJob,
    RegistrationAttachment,
    RegistrationStatusHistory,
    SubscriptionPlan,
    SupportAccessGrant,
)
from app.models.user_access.entities import (  # noqa: F401
    AuditLog,
    CredentialMetadata,
    LoginHistory,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
    UserSession,
)

target_metadata = Base.metadata
