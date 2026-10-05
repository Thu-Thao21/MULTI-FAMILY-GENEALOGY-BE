"""Shared Pydantic types for Sprint-1 API contracts (plan section 6 and 8)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Generic, TypeVar

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    SecretStr,
    StringConstraints,
)

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


class RequestModel(BaseModel):
    """Base for request bodies: unknown fields are rejected (422)."""

    model_config = ConfigDict(extra="forbid")


class ResponseModel(BaseModel):
    """Base for responses. from_attributes lets use cases build it from ORM rows,
    so only declared fields leave the API (never the raw ORM object)."""

    model_config = ConfigDict(from_attributes=True)


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# Timezone-aware datetime, normalized to UTC, serialized as ISO 8601 with "Z".
# Naive datetimes are rejected.
UtcDatetime = Annotated[
    AwareDatetime,
    AfterValidator(_to_utc),
    PlainSerializer(_iso_utc, return_type=str, when_used="json"),
]

# Email: trim only, NO lowercase (team decision pending, see plan section 6).
# Simple regex on purpose; email-validator is not a dependency.
Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=255,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    ),
]

# Free text that is trimmed (names, reasons). Never used for passwords or tokens.
Str255 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
ReasonText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]
# Phone: digits, spaces, +, -, (, ). DB column is varchar(30).
Phone = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=6, max_length=30, pattern=r"^\+?[0-9 ()\-]{6,30}$"
    ),
]


# Secrets are never trimmed and never echoed in repr/logs.
# Firebase requires at least 6 characters; upper bound only limits payload size.
Password = Annotated[SecretStr, Field(min_length=6, max_length=4096)]
# Firebase ID tokens, oob codes, tracking codes.
SecretToken = Annotated[SecretStr, Field(min_length=1, max_length=8192)]


class PageParams(BaseModel):
    """Query parameters for list endpoints."""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


T = TypeVar("T")


class Page(ResponseModel, Generic[T]):
    """List response envelope: {items, total, page, page_size}."""

    items: list[T]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=MAX_PAGE_SIZE)
