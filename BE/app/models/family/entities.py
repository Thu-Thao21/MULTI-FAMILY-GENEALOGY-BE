"""Sprint-1 B2 family models. Source of truth: docs/schema_family.txt (Neon inspect).

Foreign keys to tables that are not mapped yet (persons, branches, ownership_transfers)
are kept as plain UUID columns without ForeignKey(); each one is marked
"UNMAPPED FK" below with its DB constraint name. Declare the ForeignKey once the
target table gets a model.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


def _now_ts() -> Mapped[datetime]:
    """NOT NULL timestamptz with DEFAULT CURRENT_TIMESTAMP."""
    return mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


def _req_ts() -> Mapped[datetime]:
    """NOT NULL timestamptz without default."""
    return mapped_column(DateTime(timezone=True), nullable=False)


def _opt_ts() -> Mapped[Optional[datetime]]:
    return mapped_column(DateTime(timezone=True), nullable=True)


def _fk(target: str, name: str, ondelete: str | None = None) -> ForeignKey:
    return ForeignKey(target, name=name, ondelete=ondelete)


# ---------------------------------------------------------------------------
# Business registration
# ---------------------------------------------------------------------------


class BusinessRegistration(Base):
    """Maps public.business_registrations."""

    __tablename__ = "business_registrations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT', 'PENDING', 'APPROVED', 'NEED_SUPPLEMENT', "
            "'REJECTED', 'CANCELLED')",
            name="business_registrations_status_check",
        ),
        UniqueConstraint(
            "tracking_code_hash", name="business_registrations_tracking_code_hash_key"
        ),
        # Migration 0003: two PENDING registrations with the same e-mail and clan name,
        # ignoring case, cannot coexist. The application answers 409 DUPLICATE_RESOURCE.
        Index(
            "uq_registration_pending_same_applicant",
            text("lower(representative_email)"),
            text("lower(clan_name)"),
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
        ),
    )

    registration_id: Mapped[uuid.UUID] = _uuid_pk()
    requested_plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        _fk("subscription_plans.plan_id", "business_registrations_requested_plan_id_fkey"),
        nullable=False,
    )
    representative_name: Mapped[str] = mapped_column(String(255), nullable=False)
    representative_email: Mapped[str] = mapped_column(String(255), nullable=False)
    representative_phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    clan_name: Mapped[str] = mapped_column(String(255), nullable=False)
    origin_place: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'PENDING'::character varying"),
    )
    tracking_code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    reviewed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        _fk("users.user_id", "business_registrations_reviewed_by_fkey", "SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[Optional[datetime]] = _opt_ts()
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _now_ts()
    updated_at: Mapped[datetime] = _now_ts()


class RegistrationStatusHistory(Base):
    """Maps public.registration_status_history."""

    __tablename__ = "registration_status_history"

    history_id: Mapped[uuid.UUID] = _uuid_pk()
    registration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        _fk(
            "business_registrations.registration_id",
            "registration_status_history_registration_id_fkey",
            "CASCADE",
        ),
        nullable=False,
    )
    from_status: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    changed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        _fk("users.user_id", "registration_status_history_changed_by_fkey", "SET NULL"),
        nullable=True,
    )
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    changed_at: Mapped[datetime] = _now_ts()


class RegistrationAttachment(Base):
    """Maps public.registration_attachments."""

    __tablename__ = "registration_attachments"

    attachment_id: Mapped[uuid.UUID] = _uuid_pk()
    registration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        _fk(
            "business_registrations.registration_id",
            "registration_attachments_registration_id_fkey",
            "CASCADE",
        ),
        nullable=False,
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    uploaded_at: Mapped[datetime] = _now_ts()


# ---------------------------------------------------------------------------
# Clan, profile, plans and subscriptions
# ---------------------------------------------------------------------------


class Clan(Base):
    """Maps public.clans."""

    __tablename__ = "clans"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'ACTIVE', 'SUSPENDED', 'EXPIRED', 'LOCKED', 'INACTIVE')",
            name="clans_status_check",
        ),
        UniqueConstraint("clan_code", name="clans_clan_code_key"),
        UniqueConstraint("registration_id", name="clans_registration_id_key"),
    )

    clan_id: Mapped[uuid.UUID] = _uuid_pk()
    registration_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        _fk(
            "business_registrations.registration_id",
            "clans_registration_id_fkey",
            "SET NULL",
        ),
        nullable=True,
    )
    clan_code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'PENDING'::character varying"),
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        _fk("users.user_id", "clans_created_by_fkey", "SET NULL"),
        nullable=True,
    )
    activated_at: Mapped[Optional[datetime]] = _opt_ts()
    suspended_at: Mapped[Optional[datetime]] = _opt_ts()
    created_at: Mapped[datetime] = _now_ts()
    updated_at: Mapped[datetime] = _now_ts()


class ClanProfile(Base):
    """Maps public.clan_profiles. PK is also FK to clans (1-1)."""

    __tablename__ = "clan_profiles"

    clan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        _fk("clans.clan_id", "clan_profiles_clan_id_fkey", "CASCADE"),
        primary_key=True,
    )
    origin_place: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    history: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ancestral_house_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # UNMAPPED FK: clan_profiles_founder_person_id_fkey -> persons.person_id
    # (ON DELETE SET NULL). persons has no model yet, so no ForeignKey() here.
    founder_person_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    public_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = _now_ts()


class SubscriptionPlan(Base):
    """Maps public.subscription_plans."""

    __tablename__ = "subscription_plans"
    __table_args__ = (
        CheckConstraint(
            "billing_period_months > 0",
            name="subscription_plans_billing_period_months_check",
        ),
        CheckConstraint("price >= 0", name="subscription_plans_price_check"),
        CheckConstraint(
            "status IN ('ACTIVE', 'INACTIVE', 'RETIRED')",
            name="subscription_plans_status_check",
        ),
        UniqueConstraint("code", name="subscription_plans_code_key"),
    )

    plan_id: Mapped[uuid.UUID] = _uuid_pk()
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, server_default=text("0")
    )
    billing_period_months: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("12")
    )
    max_members: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_family_admins: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    storage_mb: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'ACTIVE'::character varying"),
    )
    created_at: Mapped[datetime] = _now_ts()
    updated_at: Mapped[datetime] = _now_ts()


class PlanFeatureLimit(Base):
    """Maps public.plan_feature_limits."""

    __tablename__ = "plan_feature_limits"
    __table_args__ = (
        UniqueConstraint(
            "plan_id", "feature_code", name="plan_feature_limits_plan_id_feature_code_key"
        ),
    )

    plan_feature_id: Mapped[uuid.UUID] = _uuid_pk()
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        _fk("subscription_plans.plan_id", "plan_feature_limits_plan_id_fkey", "CASCADE"),
        nullable=False,
    )
    feature_code: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    # DB type is numeric without precision/scale.
    limit_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(), nullable=True)
    # "metadata" is reserved on DeclarativeBase classes, so the Python attribute is
    # renamed; the DB column name stays "metadata".
    feature_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )


class ClanSubscription(Base):
    """Maps public.clan_subscriptions."""

    __tablename__ = "clan_subscriptions"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="clan_subscriptions_check"),
        CheckConstraint(
            "status IN ('PENDING', 'ACTIVE', 'EXPIRED', 'SUSPENDED', 'CANCELLED')",
            name="clan_subscriptions_status_check",
        ),
        Index("idx_clan_subscriptions_clan", "clan_id", "status"),
    )

    subscription_id: Mapped[uuid.UUID] = _uuid_pk()
    clan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        _fk("clans.clan_id", "clan_subscriptions_clan_id_fkey", "CASCADE"),
        nullable=False,
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        _fk("subscription_plans.plan_id", "clan_subscriptions_plan_id_fkey"),
        nullable=False,
    )
    starts_at: Mapped[datetime] = _req_ts()
    ends_at: Mapped[datetime] = _req_ts()
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    auto_renew: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = _now_ts()


# ---------------------------------------------------------------------------
# Owner, membership, Family Admin
# ---------------------------------------------------------------------------


class ClanOwnershipHistory(Base):
    """Maps public.clan_ownership_history (replaces legacy clan_ownerships).

    DB enforces one active owner per clan via partial unique index
    uq_active_clan_owner (clan_id) WHERE ended_at IS NULL.
    """

    __tablename__ = "clan_ownership_history"
    __table_args__ = (
        Index(
            "uq_active_clan_owner",
            "clan_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
    )

    ownership_id: Mapped[uuid.UUID] = _uuid_pk()
    clan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        _fk("clans.clan_id", "clan_ownership_history_clan_id_fkey", "CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        _fk("users.user_id", "clan_ownership_history_user_id_fkey"),
        nullable=False,
    )
    # UNMAPPED FK: clan_ownership_history_transfer_id_fkey ->
    # ownership_transfers.transfer_id (ON DELETE SET NULL). No model yet.
    transfer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    started_at: Mapped[datetime] = _req_ts()
    ended_at: Mapped[Optional[datetime]] = _opt_ts()


class ClanMembership(Base):
    """Maps public.clan_memberships."""

    __tablename__ = "clan_memberships"
    __table_args__ = (
        CheckConstraint(
            "status IN ('INVITED', 'ACTIVE', 'SUSPENDED', 'REVOKED')",
            name="clan_memberships_status_check",
        ),
        UniqueConstraint("clan_id", "user_id", name="clan_memberships_clan_id_user_id_key"),
    )

    membership_id: Mapped[uuid.UUID] = _uuid_pk()
    clan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        _fk("clans.clan_id", "clan_memberships_clan_id_fkey", "CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        _fk("users.user_id", "clan_memberships_user_id_fkey", "CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'ACTIVE'::character varying"),
    )
    joined_at: Mapped[Optional[datetime]] = _opt_ts()
    revoked_at: Mapped[Optional[datetime]] = _opt_ts()


class FamilyAdminAssignment(Base):
    """Maps public.family_admin_assignments."""

    __tablename__ = "family_admin_assignments"
    __table_args__ = (
        # Migration 0002 (KI-08): at most one ACTIVE assignment per (clan, user, branch); a NULL
        # branch_id (clan-wide) counts as one value. Needs PostgreSQL 15+. The membership row
        # lock in the use case stays: it turns the race into a clean 409 instead of an
        # IntegrityError, and the index is the last line of defence.
        Index(
            "uq_family_admin_active_assignment",
            "clan_id",
            "user_id",
            "branch_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
            postgresql_nulls_not_distinct=True,
        ),
    )

    assignment_id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        _fk("users.user_id", "family_admin_assignments_user_id_fkey", "CASCADE"),
        nullable=False,
    )
    clan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        _fk("clans.clan_id", "family_admin_assignments_clan_id_fkey", "CASCADE"),
        nullable=False,
    )
    # UNMAPPED FK: family_admin_assignments_branch_id_fkey -> branches.branch_id
    # (ON DELETE CASCADE). branches has no model yet.
    branch_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    assigned_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        _fk("users.user_id", "family_admin_assignments_assigned_by_fkey", "SET NULL"),
        nullable=True,
    )
    revoked_at: Mapped[Optional[datetime]] = _opt_ts()
    created_at: Mapped[datetime] = _now_ts()


class FamilyAdminPermission(Base):
    """Maps public.family_admin_permissions. Composite PK (assignment_id, permission_code)."""

    __tablename__ = "family_admin_permissions"

    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        _fk(
            "family_admin_assignments.assignment_id",
            "family_admin_permissions_assignment_id_fkey",
            "CASCADE",
        ),
        primary_key=True,
    )
    permission_code: Mapped[str] = mapped_column(String(100), primary_key=True)
    granted_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        _fk("users.user_id", "family_admin_permissions_granted_by_fkey", "SET NULL"),
        nullable=True,
    )
    granted_at: Mapped[datetime] = _now_ts()


# ---------------------------------------------------------------------------
# Invitation, reset, person link, support access
# ---------------------------------------------------------------------------


class AccountInvitation(Base):
    """Maps public.account_invitations."""

    __tablename__ = "account_invitations"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('MEMBER_ACTIVATION', 'FAMILY_ADMIN_INVITE', 'OWNER_INVITE', "
            "'ACCOUNT_ACTIVATION')",
            name="account_invitations_purpose_check",
        ),
        UniqueConstraint("token_hash", name="account_invitations_token_hash_key"),
    )

    invitation_id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        _fk("users.user_id", "account_invitations_user_id_fkey", "SET NULL"),
        nullable=True,
    )
    clan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        _fk("clans.clan_id", "account_invitations_clan_id_fkey", "CASCADE"),
        nullable=False,
    )
    # UNMAPPED FK: fk_invitation_person -> persons.person_id (ON DELETE SET NULL).
    person_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[str] = mapped_column(String(50), nullable=False)
    expires_at: Mapped[datetime] = _req_ts()
    used_at: Mapped[Optional[datetime]] = _opt_ts()
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        _fk("users.user_id", "account_invitations_created_by_fkey", "SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = _now_ts()


class PasswordResetToken(Base):
    """Maps public.password_reset_tokens."""

    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        CheckConstraint(
            "attempt_count >= 0", name="password_reset_tokens_attempt_count_check"
        ),
        CheckConstraint(
            "requested_channel IN ('EMAIL', 'SMS', 'ADMIN_TEMP')",
            name="password_reset_tokens_requested_channel_check",
        ),
        UniqueConstraint("token_hash", name="password_reset_tokens_token_hash_key"),
        Index("idx_password_reset_user", "user_id", text("created_at DESC")),
    )

    reset_id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        _fk("users.user_id", "password_reset_tokens_user_id_fkey", "CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    verification_code_hash: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    requested_channel: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'EMAIL'::character varying"),
    )
    expires_at: Mapped[datetime] = _req_ts()
    used_at: Mapped[Optional[datetime]] = _opt_ts()
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = _now_ts()


class PersonAccountLink(Base):
    """Maps public.person_account_links (replaces legacy member_accounts)."""

    __tablename__ = "person_account_links"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'ACTIVE', 'REVOKED')",
            name="person_account_links_status_check",
        ),
        UniqueConstraint(
            "person_id", "clan_id", name="person_account_links_person_id_clan_id_key"
        ),
        UniqueConstraint(
            "user_id", "clan_id", name="person_account_links_user_id_clan_id_key"
        ),
    )

    link_id: Mapped[uuid.UUID] = _uuid_pk()
    # UNMAPPED FK: person_account_links_person_id_fkey -> persons.person_id
    # (ON DELETE CASCADE). persons has no model yet.
    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        _fk("users.user_id", "person_account_links_user_id_fkey", "CASCADE"),
        nullable=False,
    )
    clan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        _fk("clans.clan_id", "person_account_links_clan_id_fkey", "CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'ACTIVE'::character varying"),
    )
    linked_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        _fk("users.user_id", "person_account_links_linked_by_fkey", "SET NULL"),
        nullable=True,
    )
    linked_at: Mapped[datetime] = _now_ts()
    revoked_at: Mapped[Optional[datetime]] = _opt_ts()


class SupportAccessGrant(Base):
    """Maps public.support_access_grants."""

    __tablename__ = "support_access_grants"
    __table_args__ = (
        CheckConstraint("expires_at > starts_at", name="support_access_grants_check"),
    )

    grant_id: Mapped[uuid.UUID] = _uuid_pk()
    system_admin_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        _fk(
            "users.user_id",
            "support_access_grants_system_admin_user_id_fkey",
            "CASCADE",
        ),
        nullable=False,
    )
    clan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        _fk("clans.clan_id", "support_access_grants_clan_id_fkey", "CASCADE"),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    approved_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        _fk("users.user_id", "support_access_grants_approved_by_fkey", "SET NULL"),
        nullable=True,
    )
    starts_at: Mapped[datetime] = _now_ts()
    expires_at: Mapped[datetime] = _req_ts()
    revoked_at: Mapped[Optional[datetime]] = _opt_ts()


# ---------------------------------------------------------------------------
# Email delivery
# ---------------------------------------------------------------------------


class EmailDeliveryLog(Base):
    """Maps public.email_delivery_logs. Not a durable outbox."""

    __tablename__ = "email_delivery_logs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('QUEUED', 'SENT', 'FAILED', 'BOUNCED')",
            name="email_delivery_logs_status_check",
        ),
    )

    email_id: Mapped[uuid.UUID] = _uuid_pk()
    registration_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        _fk(
            "business_registrations.registration_id",
            "email_delivery_logs_registration_id_fkey",
            "SET NULL",
        ),
        nullable=True,
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        _fk("users.user_id", "email_delivery_logs_user_id_fkey", "SET NULL"),
        nullable=True,
    )
    invitation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        _fk(
            "account_invitations.invitation_id",
            "email_delivery_logs_invitation_id_fkey",
            "SET NULL",
        ),
        nullable=True,
    )
    reset_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        _fk(
            "password_reset_tokens.reset_id",
            "email_delivery_logs_reset_id_fkey",
            "SET NULL",
        ),
        nullable=True,
    )
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False)
    email_type: Mapped[str] = mapped_column(String(100), nullable=False)
    subject: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'QUEUED'::character varying"),
    )
    provider_message_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    sent_at: Mapped[Optional[datetime]] = _opt_ts()
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _now_ts()


class EmailDeliveryAttempt(Base):
    """Maps public.email_delivery_attempts. status has no CHECK in DB."""

    __tablename__ = "email_delivery_attempts"
    __table_args__ = (
        CheckConstraint(
            "attempt_number > 0", name="email_delivery_attempts_attempt_number_check"
        ),
        UniqueConstraint(
            "email_id",
            "attempt_number",
            name="email_delivery_attempts_email_id_attempt_number_key",
        ),
    )

    attempt_id: Mapped[uuid.UUID] = _uuid_pk()
    email_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        _fk(
            "email_delivery_logs.email_id",
            "email_delivery_attempts_email_id_fkey",
            "CASCADE",
        ),
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_message_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempted_at: Mapped[datetime] = _now_ts()


# ---------------------------------------------------------------------------
# Owner provisioning and idempotency (Mốc E, migration 0003)
# ---------------------------------------------------------------------------


class ProvisioningJob(Base):
    """Maps public.provisioning_jobs (migration 0003).

    The durable record of "create the Owner account": a Firebase user and a set of DB rows
    that no single transaction can cover. Holds NO password (the temporary password exists
    only in memory and in the one response that shows it).

    firebase_uid is always 'own-' || job_id (CHECK): a retry can find the user this job
    created, and a clean-up may delete only that uid, never a user found by e-mail.
    """

    __tablename__ = "provisioning_jobs"
    __table_args__ = (
        CheckConstraint("job_type IN ('OWNER_PROVISIONING')", name="provisioning_jobs_job_type_check"),
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED_RETRYABLE', 'FAILED')",
            name="provisioning_jobs_status_check",
        ),
        CheckConstraint("attempt_count >= 0", name="provisioning_jobs_attempt_count_check"),
        CheckConstraint(
            "firebase_uid = 'own-' || job_id::text", name="provisioning_jobs_firebase_uid_check"
        ),
        CheckConstraint(
            "needs_cleanup = false OR (status = 'FAILED' AND firebase_user_created)",
            name="provisioning_jobs_needs_cleanup_check",
        ),
        CheckConstraint(
            "status <> 'RUNNING' OR lease_expires_at IS NOT NULL",
            name="provisioning_jobs_running_lease_check",
        ),
        # One job per clan unless it failed for good; a failed job that still needs a
        # Firebase clean-up keeps blocking the clan and the e-mail.
        Index(
            "uq_provisioning_job_live_per_clan",
            "clan_id",
            unique=True,
            postgresql_where=text(
                "status IN ('PENDING', 'RUNNING', 'FAILED_RETRYABLE', 'SUCCEEDED') OR needs_cleanup"
            ),
        ),
        Index(
            "uq_provisioning_job_live_email",
            text("lower(email)"),
            unique=True,
            postgresql_where=text("status IN ('PENDING', 'RUNNING', 'FAILED_RETRYABLE') OR needs_cleanup"),
        ),
        Index("idx_provisioning_jobs_clan_created", "clan_id", text("created_at DESC")),
    )

    job_id: Mapped[uuid.UUID] = _uuid_pk()
    job_type: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default=text("'OWNER_PROVISIONING'::character varying")
    )
    clan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        _fk("clans.clan_id", "provisioning_jobs_clan_id_fkey", "CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'PENDING'::character varying")
    )
    requested_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        _fk("users.user_id", "provisioning_jobs_requested_by_fkey", "SET NULL"),
        nullable=True,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    firebase_uid: Mapped[str] = mapped_column(String(255), nullable=False)
    firebase_user_created: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    needs_cleanup: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        _fk("users.user_id", "provisioning_jobs_user_id_fkey", "SET NULL"),
        nullable=True,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    lease_expires_at: Mapped[Optional[datetime]] = _opt_ts()
    error_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = _now_ts()
    updated_at: Mapped[datetime] = _now_ts()
    completed_at: Mapped[Optional[datetime]] = _opt_ts()


class IdempotencyKey(Base):
    """Maps public.idempotency_keys (migration 0003).

    One row per (actor, endpoint, Idempotency-Key). request_hash covers the path parameters
    and the normalized body. response_body NEVER holds a password.
    """

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint(
            "actor_id", "endpoint", "idempotency_key", name="uq_idempotency_actor_endpoint_key"
        ),
        CheckConstraint(
            "status IN ('IN_PROGRESS', 'COMPLETED')", name="idempotency_keys_status_check"
        ),
        CheckConstraint(
            "char_length(idempotency_key) BETWEEN 8 AND 128",
            name="idempotency_keys_key_length_check",
        ),
        CheckConstraint(
            "char_length(request_hash) = 64", name="idempotency_keys_request_hash_check"
        ),
        CheckConstraint(
            "status <> 'COMPLETED' OR response_status IS NOT NULL",
            name="idempotency_keys_completed_check",
        ),
    )

    idempotency_id: Mapped[uuid.UUID] = _uuid_pk()
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        _fk("users.user_id", "idempotency_keys_actor_id_fkey", "CASCADE"),
        nullable=False,
    )
    endpoint: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'IN_PROGRESS'::character varying")
    )
    resource_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    response_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    response_body: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = _now_ts()
    expires_at: Mapped[datetime] = _req_ts()
