"""Business registration / clan provisioning contracts (plan section 7, 8).

Never exposed: tracking_code_hash, attachment storage_key, raw ORM rows.
tracking_code (plain) appears only once, in BusinessRegistrationCreateResponse.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Literal, Optional

from pydantic import Field, StringConstraints, model_validator

from app.schemas.auth import ClanStatus
from app.schemas.common import (
    Email,
    PageParams,
    Phone,
    ReasonText,
    RequestModel,
    ResponseModel,
    SecretToken,
    Str255,
    UtcDatetime,
)

RegistrationStatus = Literal[
    "DRAFT", "PENDING", "APPROVED", "NEED_SUPPLEMENT", "REJECTED", "CANCELLED"
]
ReviewDecision = Literal["APPROVED", "REJECTED"]
SubscriptionStatus = Literal["PENDING", "ACTIVE", "EXPIRED", "SUSPENDED", "CANCELLED"]
# No DB table yet: provisioning jobs need a migration (plan section 7).
ProvisioningJobStatus = Literal["PENDING", "RUNNING", "SUCCEEDED", "FAILED_RETRYABLE", "FAILED"]
ClanCode = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=50, pattern=r"^[A-Z0-9_-]+$"),
]


# ----- GET /service-plans (Guest) -----


class PlanFeaturePublic(ResponseModel):
    feature_code: str
    enabled: bool
    limit_value: Optional[Decimal] = None


class ServicePlanResponse(ResponseModel):
    plan_id: uuid.UUID
    code: str
    name: str
    description: Optional[str] = None
    price: Decimal = Field(description="Serialized as a decimal string, e.g. \"199000.00\".")
    billing_period_months: int
    max_members: Optional[int] = None
    max_family_admins: Optional[int] = None
    storage_mb: Optional[int] = None
    features: list[PlanFeaturePublic] = Field(default_factory=list)


# ----- POST /business-registrations (Guest) -----


class BusinessRegistrationCreateRequest(RequestModel):
    representative_name: Str255
    representative_email: Email
    representative_phone: Optional[Phone] = None
    clan_name: Str255
    origin_place: Optional[Str255] = None
    requested_plan_id: uuid.UUID


class BusinessRegistrationCreateResponse(ResponseModel):
    """201. tracking_code is shown once; the server stores only its hash."""

    registration_id: uuid.UUID
    tracking_code: str
    status: RegistrationStatus
    created_at: UtcDatetime


# ----- POST /business-registrations/track (Guest) -----


class BusinessRegistrationTrackRequest(RequestModel):
    tracking_code: SecretToken


class BusinessRegistrationTrackResponse(ResponseModel):
    clan_name: str
    status: RegistrationStatus
    public_reason: Optional[str] = Field(
        default=None, description="Only the reason allowed to be published (e.g. rejection)."
    )
    submitted_at: UtcDatetime
    updated_at: UtcDatetime


# ----- GET /admin/business-registrations[/{id}] (SA) -----


class BusinessRegistrationListQuery(PageParams):
    status: Optional[RegistrationStatus] = None


class BusinessRegistrationSummary(ResponseModel):
    registration_id: uuid.UUID
    clan_name: str
    representative_name: str
    representative_email: str
    requested_plan_id: uuid.UUID
    status: RegistrationStatus
    created_at: UtcDatetime
    reviewed_at: Optional[UtcDatetime] = None


class RegistrationStatusHistoryItem(ResponseModel):
    from_status: Optional[RegistrationStatus] = None
    to_status: RegistrationStatus
    changed_by: Optional[uuid.UUID] = None
    reason: Optional[str] = None
    changed_at: UtcDatetime


class RegistrationAttachmentItem(ResponseModel):
    """storage_key is intentionally omitted; downloads go through a signed URL later."""

    attachment_id: uuid.UUID
    file_name: str
    mime_type: Optional[str] = None
    uploaded_at: UtcDatetime


class BusinessRegistrationDetail(BusinessRegistrationSummary):
    representative_phone: Optional[str] = None
    origin_place: Optional[str] = None
    reviewed_by: Optional[uuid.UUID] = None
    rejection_reason: Optional[str] = None
    updated_at: UtcDatetime
    clan_id: Optional[uuid.UUID] = Field(
        default=None, description="Set once the Business (clan) has been created."
    )
    status_history: list[RegistrationStatusHistoryItem] = Field(default_factory=list)
    attachments: list[RegistrationAttachmentItem] = Field(default_factory=list)


# ----- POST /admin/business-registrations/{id}/review (SA) -----


class RegistrationReviewRequest(RequestModel):
    decision: ReviewDecision
    reason: Optional[ReasonText] = None

    @model_validator(mode="after")
    def _reason_required_on_reject(self) -> "RegistrationReviewRequest":
        if self.decision == "REJECTED" and not self.reason:
            raise ValueError("reason is required when decision is REJECTED")
        return self


class RegistrationReviewResponse(ResponseModel):
    registration_id: uuid.UUID
    status: RegistrationStatus
    reviewed_by: uuid.UUID
    reviewed_at: UtcDatetime


# ----- POST /admin/business-registrations/{id}/business (SA, Idempotency-Key) -----


class BusinessCreateRequest(RequestModel):
    clan_code: Optional[ClanCode] = Field(
        default=None, description="Optional; the server generates one when omitted."
    )


class BusinessCreateResponse(ResponseModel):
    """201. Clan starts PENDING; no permission is granted from Guest payload."""

    clan_id: uuid.UUID
    clan_code: str
    clan_status: ClanStatus
    subscription_id: uuid.UUID
    plan_id: uuid.UUID
    subscription_status: SubscriptionStatus
    starts_at: UtcDatetime
    ends_at: UtcDatetime


# ----- POST /admin/clans/{id}/owner (SA, Idempotency-Key) -> 202 -----


class OwnerProvisionRequest(RequestModel):
    """All fields optional: defaults to the registration representative."""

    email: Optional[Email] = None
    display_name: Optional[Str255] = None
    phone: Optional[Phone] = None


class ProvisioningJobAccepted(ResponseModel):
    job_id: uuid.UUID
    status: ProvisioningJobStatus


# ----- GET /admin/provisioning-jobs/{id} (SA) -----


class ProvisioningJobResponse(ResponseModel):
    """Never contains the temporary password or the Firebase UID secret material."""

    job_id: uuid.UUID
    job_type: Literal["OWNER_PROVISIONING"]
    clan_id: uuid.UUID
    status: ProvisioningJobStatus
    user_id: Optional[uuid.UUID] = None
    email_delivery_status: Optional[Literal["QUEUED", "SENT", "FAILED", "BOUNCED"]] = None
    attempt_count: int = Field(ge=0)
    error_code: Optional[str] = None
    created_at: UtcDatetime
    updated_at: UtcDatetime


# ----- POST /admin/clans/{id}/activate (SA, waits for D03) -----


class ClanActivateResponse(ResponseModel):
    clan_id: uuid.UUID
    status: ClanStatus
    activated_at: Optional[UtcDatetime] = None
