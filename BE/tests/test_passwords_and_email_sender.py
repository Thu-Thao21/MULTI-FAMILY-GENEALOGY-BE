"""The temporary password generator and the Noop e-mail sender (Mốc E6a), without a database."""

from __future__ import annotations

import inspect
import logging
import re
from datetime import datetime, timezone

import pytest

import app.core.passwords as passwords_module
from app.core.config import settings
from app.core.email_sender import EmailDeliveryResult, NoopEmailSender, get_email_sender
from app.core.passwords import DIGITS, LOWER, PASSWORD_LENGTH, SYMBOLS, UPPER, generate_temporary_password


# ------------------------------------------------------------------ the password


def test_a_password_is_16_characters_with_an_upper_a_lower_and_a_digit():
    for _ in range(500):
        p = generate_temporary_password()
        assert len(p) == PASSWORD_LENGTH == 16
        assert re.fullmatch(r"[A-Za-z0-9]{16}", p)
        assert any(c in UPPER for c in p) and any(c in LOWER for c in p) and any(c in DIGITS for c in p)


def test_with_the_symbol_option_it_also_holds_a_symbol_and_is_still_16_characters():
    for _ in range(500):
        p = generate_temporary_password(require_symbol=True)
        assert len(p) == 16 and any(c in SYMBOLS for c in p)
        assert any(c in UPPER for c in p) and any(c in LOWER for c in p) and any(c in DIGITS for c in p)
        assert all(c in UPPER + LOWER + DIGITS + SYMBOLS for c in p)


def test_without_the_option_there_is_never_a_symbol():
    assert not any(c in SYMBOLS for _ in range(500) for c in generate_temporary_password())


def test_the_option_defaults_to_off_in_the_settings():
    assert settings.OWNER_TEMP_PASSWORD_REQUIRE_SYMBOL is False


def test_the_characters_people_confuse_are_left_out():
    assert not set("IOl01") & set(UPPER + LOWER + DIGITS)
    assert len(set(UPPER)) == 24 and len(set(LOWER)) == 25 and len(set(DIGITS)) == 8


def test_the_guaranteed_characters_are_not_at_fixed_places():
    """The required classes are drawn first and then SHUFFLED: any class can open the password."""
    first = {("U" if p[0] in UPPER else "L" if p[0] in LOWER else "D") for p in (generate_temporary_password() for _ in range(600))}
    last = {("U" if p[-1] in UPPER else "L" if p[-1] in LOWER else "D") for p in (generate_temporary_password() for _ in range(600))}
    assert first == last == {"U", "L", "D"}


def test_every_position_can_hold_every_class():
    positions = [set() for _ in range(16)]
    for _ in range(2000):
        for i, c in enumerate(generate_temporary_password()):
            positions[i].add("D" if c in DIGITS else "U" if c in UPPER else "L")
    assert all(s == {"U", "L", "D"} for s in positions)


def test_passwords_are_random_and_do_not_repeat():
    batch = {generate_temporary_password() for _ in range(5000)}
    assert len(batch) == 5000


def test_it_draws_from_the_secrets_module_only(monkeypatch):
    draws = {"choice": 0, "randbelow": 0}
    real_choice, real_below = passwords_module.secrets.choice, passwords_module.secrets.randbelow

    def choice(seq):
        draws["choice"] += 1
        return real_choice(seq)

    def below(n):
        draws["randbelow"] += 1
        return real_below(n)

    monkeypatch.setattr(passwords_module.secrets, "choice", choice)
    monkeypatch.setattr(passwords_module.secrets, "randbelow", below)
    generate_temporary_password()
    assert draws == {"choice": 16, "randbelow": 15}  # 16 characters, a 15-step shuffle
    source = inspect.getsource(passwords_module)
    assert "import random" not in source and "random." not in source.replace("secrets.", "")


# ------------------------------------------------------------------ the sender


async def test_the_noop_sender_sends_nothing_and_reports_no_status():
    sender = NoopEmailSender()
    result = await sender.send_owner_temporary_password(
        to_email="owner@example.test", display_name="Owner", temporary_password="Kq7Wm2Xp9Tr4Vz8N",
        expires_at=datetime(2026, 10, 11, tzinfo=timezone.utc))
    assert result == EmailDeliveryResult(status=None)


async def test_the_noop_sender_keeps_nothing_and_logs_nothing(caplog):
    caplog.set_level(logging.DEBUG)
    sender = NoopEmailSender()
    secret = "Kq7Wm2Xp9Tr4Vz8N"
    result = await sender.send_owner_temporary_password(
        to_email="owner@example.test", display_name="Owner", temporary_password=secret, expires_at=datetime.now(timezone.utc))
    assert not hasattr(sender, "__dict__") and NoopEmailSender.__slots__ == ()  # no attribute can hold the password
    assert secret not in repr(sender) and secret not in repr(result)
    assert secret not in caplog.text and "owner@example.test" not in caplog.text


def test_the_dependency_hands_out_the_noop_sender():
    assert isinstance(get_email_sender(), NoopEmailSender)


def test_the_only_sender_that_exists_is_the_noop_one():
    import app.core.email_sender as module

    senders = [n for n, c in inspect.getmembers(module, inspect.isclass) if n.endswith("EmailSender") and n != "EmailSender"]
    assert senders == ["NoopEmailSender"]
