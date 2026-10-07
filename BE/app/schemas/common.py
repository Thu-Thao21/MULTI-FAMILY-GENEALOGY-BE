"""Shared Pydantic types for Sprint-1 API contracts (plan section 6 and 8)."""

from __future__ import annotations

import re
import unicodedata
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

# ----- Text types -----
#
# ONE-LINE text (Email, Str255) is cleaned after the length/format checks:
#   * control characters (Unicode category Cc: NUL, tab, newline, DEL, C1) are rejected with
#     422. A NUL character in a varchar makes the database driver raise, which would
#     otherwise surface as a 500 from a public endpoint;
#   * the text is normalized to NFC, so the composed and the decomposed spelling of the same
#     Vietnamese word are one string (PostgreSQL does not normalize, and the unique index on
#     pending registrations compares plain lower() text);
#   * Str255 also collapses runs of whitespace inside the text to one space.
# Email is trimmed but NOT lower-cased (team decision, api_contract.md section 6).
#
# These rules must NEVER be applied to secrets (passwords, ID tokens, tracking codes, oob
# codes): those use Password / SecretToken below, which do not touch the value at all. A
# test proves it (tests/test_text_types.py). Multi-line text uses MultilineText.

MAX_TEXT_255 = 255
MAX_MULTILINE = 2000
LF, CRLF, TAB = chr(10), chr(13) + chr(10), chr(9)


def _reject_control_characters(value: str, *, allowed: str = "") -> None:
    for ch in value:
        if ch not in allowed and unicodedata.category(ch) == "Cc":
            raise ValueError("control characters are not allowed")


def _clean_one_line(value: str) -> str:
    _reject_control_characters(value)
    value = unicodedata.normalize("NFC", value)
    value = re.sub(r"\s+", " ", value).strip()
    if not value or len(value) > MAX_TEXT_255:
        raise ValueError("invalid length after normalization")
    return value


def _clean_email(value: str) -> str:
    _reject_control_characters(value)
    value = unicodedata.normalize("NFC", value)
    if len(value) > MAX_TEXT_255:
        raise ValueError("invalid length after normalization")
    return value


def _clean_multiline(value: str) -> str:
    # Windows clients send CRLF: store LF. A lone CR is still a control character.
    value = value.replace(CRLF, LF)
    _reject_control_characters(value, allowed=LF + TAB)
    value = unicodedata.normalize("NFC", value).strip()
    if not value or len(value) > MAX_MULTILINE:
        raise ValueError("invalid length after normalization")
    return value


Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        max_length=MAX_TEXT_255,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    ),
    AfterValidator(_clean_email),
]

# One-line free text (names, places). Trimmed, no control characters, NFC, inner whitespace
# collapsed. Never used for passwords or tokens.
Str255 = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TEXT_255),
    AfterValidator(_clean_one_line),
]
# Multi-line free text: the reason fields (PATCH /admin/users/{id}/status and the registration
# review). Newline and tab are allowed, NUL and every other control character are not: a NUL
# would make the database driver raise, which used to surface as a 500.
MultilineText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_MULTILINE),
    AfterValidator(_clean_multiline),
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
