from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_access.entities import User
from app.models.family.entities import (
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
    PasswordResetToken,
    PersonAccountLink,
    PlanFeatureLimit,
    RegistrationAttachment,
    RegistrationStatusHistory,
    SubscriptionPlan,
    SupportAccessGrant,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class FamilyRepository:
    """Queries plus a few plain writes (FA permissions). Use cases own transactions; never commit here.

    Tenant rule: every query on a clan-owned resource takes clan_id and filters by it.
    Global resources (registrations, plans, reset tokens, email logs) are not clan-owned.
    The only clan-owned lookup without clan_id is get_invitation_by_token_hash: the
    caller only holds the token at that point; it must check invitation.clan_id after.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ----- Business registration (global, before a clan exists) -----

    async def get_registration_by_id(
        self, registration_id: uuid.UUID
    ) -> BusinessRegistration | None:
        stmt = select(BusinessRegistration).where(
            BusinessRegistration.registration_id == registration_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_registration_by_tracking_hash(
        self, tracking_code_hash: str
    ) -> BusinessRegistration | None:
        stmt = select(BusinessRegistration).where(
            BusinessRegistration.tracking_code_hash == tracking_code_hash
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_registrations(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[BusinessRegistration]:
        stmt = select(BusinessRegistration)
        if status is not None:
            stmt = stmt.where(BusinessRegistration.status == status)
        stmt = (
            stmt.order_by(BusinessRegistration.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_registration_status_history(
        self, registration_id: uuid.UUID
    ) -> list[RegistrationStatusHistory]:
        stmt = (
            select(RegistrationStatusHistory)
            .where(RegistrationStatusHistory.registration_id == registration_id)
            .order_by(RegistrationStatusHistory.changed_at.asc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_registration_attachments(
        self, registration_id: uuid.UUID
    ) -> list[RegistrationAttachment]:
        stmt = select(RegistrationAttachment).where(
            RegistrationAttachment.registration_id == registration_id
        )
        return list((await self._session.execute(stmt)).scalars().all())

    # ----- Plans (global catalog) -----

    async def get_plan_by_id(self, plan_id: uuid.UUID) -> SubscriptionPlan | None:
        stmt = select(SubscriptionPlan).where(SubscriptionPlan.plan_id == plan_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_plan_by_code(self, code: str) -> SubscriptionPlan | None:
        stmt = select(SubscriptionPlan).where(SubscriptionPlan.code == code)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_active_plans(self) -> list[SubscriptionPlan]:
        stmt = (
            select(SubscriptionPlan)
            .where(SubscriptionPlan.status == "ACTIVE")
            .order_by(SubscriptionPlan.price.asc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_plan_feature_limits(self, plan_id: uuid.UUID) -> list[PlanFeatureLimit]:
        stmt = select(PlanFeatureLimit).where(PlanFeatureLimit.plan_id == plan_id)
        return list((await self._session.execute(stmt)).scalars().all())

    # ----- Clan -----

    async def get_clan_by_id(self, clan_id: uuid.UUID) -> Clan | None:
        stmt = select(Clan).where(Clan.clan_id == clan_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_clan_by_code(self, clan_code: str) -> Clan | None:
        stmt = select(Clan).where(Clan.clan_code == clan_code)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_clan_by_registration_id(self, registration_id: uuid.UUID) -> Clan | None:
        """Idempotency check: one registration creates at most one clan."""
        stmt = select(Clan).where(Clan.registration_id == registration_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_clan_profile(self, clan_id: uuid.UUID) -> ClanProfile | None:
        stmt = select(ClanProfile).where(ClanProfile.clan_id == clan_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_active_subscription(self, clan_id: uuid.UUID) -> ClanSubscription | None:
        now = _now()
        stmt = (
            select(ClanSubscription)
            .where(
                ClanSubscription.clan_id == clan_id,
                ClanSubscription.status == "ACTIVE",
                ClanSubscription.starts_at <= now,
                ClanSubscription.ends_at > now,
            )
            .order_by(ClanSubscription.ends_at.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_subscriptions(self, clan_id: uuid.UUID) -> list[ClanSubscription]:
        stmt = (
            select(ClanSubscription)
            .where(ClanSubscription.clan_id == clan_id)
            .order_by(ClanSubscription.starts_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    # ----- Owner and membership -----

    async def get_active_owner(self, clan_id: uuid.UUID) -> ClanOwnershipHistory | None:
        stmt = select(ClanOwnershipHistory).where(
            ClanOwnershipHistory.clan_id == clan_id,
            ClanOwnershipHistory.ended_at.is_(None),
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_ownership_history(
        self, clan_id: uuid.UUID
    ) -> list[ClanOwnershipHistory]:
        stmt = (
            select(ClanOwnershipHistory)
            .where(ClanOwnershipHistory.clan_id == clan_id)
            .order_by(ClanOwnershipHistory.started_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_membership(
        self, clan_id: uuid.UUID, user_id: uuid.UUID
    ) -> ClanMembership | None:
        stmt = select(ClanMembership).where(
            ClanMembership.clan_id == clan_id,
            ClanMembership.user_id == user_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_memberships(
        self,
        clan_id: uuid.UUID,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ClanMembership]:
        stmt = select(ClanMembership).where(ClanMembership.clan_id == clan_id)
        if status is not None:
            stmt = stmt.where(ClanMembership.status == status)
        stmt = stmt.limit(limit).offset(offset)
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_active_memberships_for_user(
        self, user_id: uuid.UUID
    ) -> list[ClanMembership]:
        """Which clans a user belongs to; used to pick the tenant, not to read clan data."""
        stmt = select(ClanMembership).where(
            ClanMembership.user_id == user_id,
            ClanMembership.status == "ACTIVE",
            ClanMembership.revoked_at.is_(None),
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_memberships_with_clans(
        self, user_id: uuid.UUID
    ) -> list[tuple[ClanMembership, Clan]]:
        """The caller's own non-revoked memberships with their clan (for GET /auth/me)."""
        stmt = (
            select(ClanMembership, Clan)
            .join(Clan, Clan.clan_id == ClanMembership.clan_id)
            .where(
                ClanMembership.user_id == user_id,
                ClanMembership.revoked_at.is_(None),
                ClanMembership.status != "REVOKED",
            )
            .order_by(Clan.name, Clan.clan_id)
        )
        return [(row[0], row[1]) for row in (await self._session.execute(stmt)).all()]

    # ----- Clan user list (Mốc F). Always filtered by clan_id. -----

    async def list_clan_members(
        self,
        clan_id: uuid.UUID,
        *,
        membership_status: str | None,
        limit: int,
        offset: int,
    ) -> list[tuple[ClanMembership, User]]:
        stmt = (
            select(ClanMembership, User)
            .join(User, User.user_id == ClanMembership.user_id)
            .where(ClanMembership.clan_id == clan_id)
        )
        if membership_status is not None:
            stmt = stmt.where(ClanMembership.status == membership_status)
        stmt = (
            stmt.order_by(User.display_name, User.user_id).limit(limit).offset(offset)
        )
        return [(r[0], r[1]) for r in (await self._session.execute(stmt)).all()]

    async def count_clan_members(
        self, clan_id: uuid.UUID, *, membership_status: str | None
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(ClanMembership)
            .where(ClanMembership.clan_id == clan_id)
        )
        if membership_status is not None:
            stmt = stmt.where(ClanMembership.status == membership_status)
        return int((await self._session.execute(stmt)).scalar_one())

    async def list_active_fa_user_ids(
        self, clan_id: uuid.UUID, user_ids: list[uuid.UUID]
    ) -> set[uuid.UUID]:
        """Which of these users hold a non-revoked FA assignment in this clan (one query)."""
        if not user_ids:
            return set()
        stmt = select(FamilyAdminAssignment.user_id).where(
            FamilyAdminAssignment.clan_id == clan_id,
            FamilyAdminAssignment.revoked_at.is_(None),
            FamilyAdminAssignment.user_id.in_(user_ids),
        )
        return set((await self._session.execute(stmt)).scalars().all())

    # ----- Family Admin permission writes (Mốc F). Flush only; the caller commits. -----

    async def lock_active_fa_assignments(
        self, clan_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[FamilyAdminAssignment]:
        """Non-revoked assignments of the user in this clan, row-locked (FOR NO KEY UPDATE),
        in a fixed order. Serializes concurrent permission updates for that user."""
        stmt = (
            select(FamilyAdminAssignment)
            .where(
                FamilyAdminAssignment.clan_id == clan_id,
                FamilyAdminAssignment.user_id == user_id,
                FamilyAdminAssignment.revoked_at.is_(None),
            )
            .order_by(FamilyAdminAssignment.assignment_id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_assignment_permission_codes(self, assignment_id: uuid.UUID) -> set[str]:
        stmt = select(FamilyAdminPermission.permission_code).where(
            FamilyAdminPermission.assignment_id == assignment_id
        )
        return set((await self._session.execute(stmt)).scalars().all())

    async def add_fa_permissions(
        self, assignment_id: uuid.UUID, codes: list[str], *, granted_by: uuid.UUID, now: datetime
    ) -> None:
        for code in codes:
            self._session.add(
                FamilyAdminPermission(
                    assignment_id=assignment_id,
                    permission_code=code,
                    granted_by=granted_by,
                    granted_at=now,
                )
            )
        await self._session.flush()

    async def delete_fa_permissions(self, assignment_id: uuid.UUID, codes: list[str]) -> None:
        if not codes:
            return
        await self._session.execute(
            delete(FamilyAdminPermission).where(
                FamilyAdminPermission.assignment_id == assignment_id,
                FamilyAdminPermission.permission_code.in_(codes),
            )
        )

    # ----- Family Admin -----

    async def get_fa_assignment(
        self, clan_id: uuid.UUID, assignment_id: uuid.UUID
    ) -> FamilyAdminAssignment | None:
        stmt = select(FamilyAdminAssignment).where(
            FamilyAdminAssignment.clan_id == clan_id,
            FamilyAdminAssignment.assignment_id == assignment_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_active_fa_assignments(
        self,
        clan_id: uuid.UUID,
        *,
        user_id: uuid.UUID | None = None,
    ) -> list[FamilyAdminAssignment]:
        stmt = select(FamilyAdminAssignment).where(
            FamilyAdminAssignment.clan_id == clan_id,
            FamilyAdminAssignment.revoked_at.is_(None),
        )
        if user_id is not None:
            stmt = stmt.where(FamilyAdminAssignment.user_id == user_id)
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_fa_permission_codes(
        self, clan_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[str]:
        """Permission codes from all active FA assignments of a user in one clan."""
        stmt = (
            select(FamilyAdminPermission.permission_code)
            .join(
                FamilyAdminAssignment,
                FamilyAdminAssignment.assignment_id == FamilyAdminPermission.assignment_id,
            )
            .where(
                FamilyAdminAssignment.clan_id == clan_id,
                FamilyAdminAssignment.user_id == user_id,
                FamilyAdminAssignment.revoked_at.is_(None),
            )
            .distinct()
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_fa_permissions(
        self, clan_id: uuid.UUID, assignment_id: uuid.UUID
    ) -> list[FamilyAdminPermission]:
        stmt = (
            select(FamilyAdminPermission)
            .join(
                FamilyAdminAssignment,
                FamilyAdminAssignment.assignment_id == FamilyAdminPermission.assignment_id,
            )
            .where(
                FamilyAdminAssignment.clan_id == clan_id,
                FamilyAdminPermission.assignment_id == assignment_id,
            )
        )
        return list((await self._session.execute(stmt)).scalars().all())

    # ----- Invitation -----

    async def get_invitation(
        self, clan_id: uuid.UUID, invitation_id: uuid.UUID
    ) -> AccountInvitation | None:
        stmt = select(AccountInvitation).where(
            AccountInvitation.clan_id == clan_id,
            AccountInvitation.invitation_id == invitation_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_invitation_by_token_hash(
        self, token_hash: str
    ) -> AccountInvitation | None:
        """Entry point for an invite link; caller must check clan_id/expiry/used_at."""
        stmt = select(AccountInvitation).where(AccountInvitation.token_hash == token_hash)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_pending_invitations(
        self, clan_id: uuid.UUID
    ) -> list[AccountInvitation]:
        stmt = (
            select(AccountInvitation)
            .where(
                AccountInvitation.clan_id == clan_id,
                AccountInvitation.used_at.is_(None),
                AccountInvitation.expires_at > _now(),
            )
            .order_by(AccountInvitation.created_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    # ----- Password reset (user-scoped, not clan-owned) -----

    async def get_reset_by_token_hash(self, token_hash: str) -> PasswordResetToken | None:
        stmt = select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_latest_unused_reset(
        self, user_id: uuid.UUID
    ) -> PasswordResetToken | None:
        stmt = (
            select(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user_id,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > _now(),
            )
            .order_by(PasswordResetToken.created_at.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    # ----- Person-account link -----

    async def get_person_link_by_user(
        self, clan_id: uuid.UUID, user_id: uuid.UUID
    ) -> PersonAccountLink | None:
        stmt = select(PersonAccountLink).where(
            PersonAccountLink.clan_id == clan_id,
            PersonAccountLink.user_id == user_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_person_link_by_person(
        self, clan_id: uuid.UUID, person_id: uuid.UUID
    ) -> PersonAccountLink | None:
        stmt = select(PersonAccountLink).where(
            PersonAccountLink.clan_id == clan_id,
            PersonAccountLink.person_id == person_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    # ----- Support access -----

    async def get_active_support_grant(
        self, clan_id: uuid.UUID, system_admin_user_id: uuid.UUID
    ) -> SupportAccessGrant | None:
        now = _now()
        stmt = (
            select(SupportAccessGrant)
            .where(
                SupportAccessGrant.clan_id == clan_id,
                SupportAccessGrant.system_admin_user_id == system_admin_user_id,
                SupportAccessGrant.revoked_at.is_(None),
                SupportAccessGrant.starts_at <= now,
                SupportAccessGrant.expires_at > now,
            )
            .order_by(SupportAccessGrant.expires_at.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_support_grants(self, clan_id: uuid.UUID) -> list[SupportAccessGrant]:
        stmt = (
            select(SupportAccessGrant)
            .where(SupportAccessGrant.clan_id == clan_id)
            .order_by(SupportAccessGrant.starts_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    # ----- Email delivery (global log, linked by registration/user/invitation/reset) -----

    async def get_email_log(self, email_id: uuid.UUID) -> EmailDeliveryLog | None:
        stmt = select(EmailDeliveryLog).where(EmailDeliveryLog.email_id == email_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_email_logs_for_registration(
        self, registration_id: uuid.UUID
    ) -> list[EmailDeliveryLog]:
        stmt = (
            select(EmailDeliveryLog)
            .where(EmailDeliveryLog.registration_id == registration_id)
            .order_by(EmailDeliveryLog.created_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_retryable_email_logs(self, *, limit: int = 50) -> list[EmailDeliveryLog]:
        stmt = (
            select(EmailDeliveryLog)
            .where(EmailDeliveryLog.status.in_(("QUEUED", "FAILED")))
            .order_by(EmailDeliveryLog.created_at.asc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def list_email_attempts(self, email_id: uuid.UUID) -> list[EmailDeliveryAttempt]:
        stmt = (
            select(EmailDeliveryAttempt)
            .where(EmailDeliveryAttempt.email_id == email_id)
            .order_by(EmailDeliveryAttempt.attempt_number.asc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    # ----- Authorization helpers (C2) -----

    async def list_active_fa_grants(
        self, clan_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[tuple[uuid.UUID, uuid.UUID | None, str]]:
        """(assignment_id, branch_id, permission_code) for the user's non-revoked FA
        assignments in this clan. branch_id=None means the assignment covers the clan."""
        stmt = (
            select(
                FamilyAdminAssignment.assignment_id,
                FamilyAdminAssignment.branch_id,
                FamilyAdminPermission.permission_code,
            )
            .join(
                FamilyAdminPermission,
                FamilyAdminPermission.assignment_id == FamilyAdminAssignment.assignment_id,
            )
            .where(
                FamilyAdminAssignment.clan_id == clan_id,
                FamilyAdminAssignment.user_id == user_id,
                FamilyAdminAssignment.revoked_at.is_(None),
            )
        )
        return [(r[0], r[1], r[2]) for r in (await self._session.execute(stmt)).all()]
