from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    """Query-only repository. Use cases own transactions; do not commit here.

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
