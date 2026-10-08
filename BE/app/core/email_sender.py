"""Sending the temporary password to a new Owner (Mốc E6): an abstract interface, nothing real yet.

Only the Noop sender exists. It sends nothing, keeps nothing and logs nothing, so the System Admin
passes the password on by hand until a real sender is chosen (D04, KI-26). The password is handed
to `send_*` and to nothing else: an implementation must not store or log it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

DeliveryStatus = Literal["QUEUED", "SENT", "FAILED", "BOUNCED"]


@dataclass(frozen=True)
class EmailDeliveryResult:
    """status is None when nothing was sent (the Noop sender)."""

    status: DeliveryStatus | None


class EmailSender(Protocol):
    async def send_owner_temporary_password(
        self, *, to_email: str, display_name: str, temporary_password: str, expires_at: datetime
    ) -> EmailDeliveryResult: ...


class NoopEmailSender:
    """Sends nothing. Holds no state, so the password cannot be kept by accident."""

    __slots__ = ()

    async def send_owner_temporary_password(
        self, *, to_email: str, display_name: str, temporary_password: str, expires_at: datetime
    ) -> EmailDeliveryResult:
        return EmailDeliveryResult(status=None)


_sender: EmailSender = NoopEmailSender()


def get_email_sender() -> EmailSender:
    """FastAPI dependency. Tests override it."""
    return _sender
