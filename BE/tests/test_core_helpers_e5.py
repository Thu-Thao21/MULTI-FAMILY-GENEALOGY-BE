"""Small helpers of Mốc E, step E5: calendar months and generated clan codes (no database)."""

from __future__ import annotations

import calendar
import inspect
import re
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import TypeAdapter, ValidationError

import app.core.clan_code as clan_code_module
from app.core.clan_code import (
    CLAN_CODE_ALPHABET,
    CLAN_CODE_LENGTH,
    CLAN_CODE_PREFIX,
    generate_clan_code,
)
from app.core.dates import add_months
from app.schemas.business import ClanCode

UTC = timezone.utc


def d(y, m, day, *, h=0, mi=0, s=0, us=0, tz=UTC):
    return datetime(y, m, day, h, mi, s, us, tzinfo=tz)


# ------------------------------------------------------------------ add_months


@pytest.mark.parametrize("start, months, expected", [
    # end of month: the day is clamped, never carried into the next month
    (d(2026, 1, 31), 1, d(2026, 2, 28)),
    (d(2026, 1, 30), 1, d(2026, 2, 28)),
    (d(2026, 1, 29), 1, d(2026, 2, 28)),
    (d(2026, 1, 28), 1, d(2026, 2, 28)),
    (d(2026, 3, 31), 1, d(2026, 4, 30)),
    (d(2026, 5, 31), 1, d(2026, 6, 30)),
    (d(2026, 8, 31), 6, d(2027, 2, 28)),
    (d(2026, 12, 31), 2, d(2027, 2, 28)),
    (d(2026, 1, 31), 3, d(2026, 4, 30)),
    (d(2026, 1, 31), 2, d(2026, 3, 31)),  # a long month stays long
    # leap years
    (d(2028, 1, 31), 1, d(2028, 2, 29)),
    (d(2028, 1, 30), 1, d(2028, 2, 29)),
    (d(2028, 2, 29), 12, d(2029, 2, 28)),
    (d(2028, 2, 29), 48, d(2032, 2, 29)),
    (d(2028, 2, 29), 1, d(2028, 3, 29)),
    (d(2027, 2, 28), 12, d(2028, 2, 28)),  # 28 Feb stays 28 Feb even into a leap year
    (d(2100, 1, 31), 1, d(2100, 2, 28)),  # 2100 is NOT a leap year
    (d(2000, 1, 31), 1, d(2000, 2, 29)),  # 2000 is
    # across the year
    (d(2026, 11, 15), 3, d(2027, 2, 15)),
    (d(2026, 12, 31), 1, d(2027, 1, 31)),
    (d(2026, 12, 15), 13, d(2028, 1, 15)),
    (d(2026, 10, 7), 12, d(2027, 10, 7)),
    (d(2026, 10, 7), 24, d(2028, 10, 7)),
    (d(2026, 10, 7), 1200, d(2126, 10, 7)),
    # zero
    (d(2026, 1, 31), 0, d(2026, 1, 31)),
])
def test_calendar_months_clamp_the_day_and_cross_years(start, months, expected):
    assert add_months(start, months) == expected


def test_the_time_of_day_microseconds_and_time_zone_are_kept():
    tz = timezone(timedelta(hours=7))
    start = d(2026, 1, 31, h=23, mi=59, s=58, us=123456, tz=tz)
    result = add_months(start, 1)
    assert result == d(2026, 2, 28, h=23, mi=59, s=58, us=123456, tz=tz)
    assert result.tzinfo == tz and result.utcoffset() == timedelta(hours=7)


def test_the_result_is_always_the_requested_month_and_the_clamped_day():
    """Every day of four years against every length from 0 to 40 months."""
    day = d(2024, 1, 1)
    while day.year < 2028:
        for months in range(0, 41):
            result = add_months(day, months)
            index = day.year * 12 + day.month - 1 + months
            assert (result.year, result.month) == (index // 12, index % 12 + 1), (day, months)
            assert result.day == min(day.day, calendar.monthrange(result.year, result.month)[1]), (day, months)
        day += timedelta(days=1)


def test_a_month_is_never_shorter_than_it_was_so_the_plan_never_ends_early():
    for months in (1, 2, 3, 6, 12):
        start = d(2026, 1, 31)
        assert add_months(start, months) > start


@pytest.mark.parametrize("bad", [-1, 1.5, "1", None, True])
def test_months_must_be_a_non_negative_integer(bad):
    with pytest.raises(ValueError):
        add_months(d(2026, 1, 31), bad)


# ------------------------------------------------------------------ clan codes


def test_a_generated_code_is_clan_dash_plus_eight_characters_of_the_safe_alphabet():
    code = generate_clan_code()
    assert re.fullmatch(r"CLAN-[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{8}", code) and len(code) == 13
    assert (CLAN_CODE_PREFIX, CLAN_CODE_LENGTH) == ("CLAN-", 8)


def test_the_alphabet_has_no_ambiguous_character_and_no_repeat():
    assert len(CLAN_CODE_ALPHABET) == 31 == len(set(CLAN_CODE_ALPHABET))
    assert not set("ILO01ilo") & set(CLAN_CODE_ALPHABET)
    assert set(CLAN_CODE_ALPHABET) == set("ABCDEFGHJKMNPQRSTUVWXYZ") | set("23456789")


def test_a_generated_code_is_always_accepted_as_a_clan_code():
    adapter = TypeAdapter(ClanCode)
    for _ in range(200):
        code = generate_clan_code()
        assert adapter.validate_python(code) == code


def test_a_clan_code_the_schema_would_refuse_is_still_refused():
    for bad in ("clan-abc", "AB", "A" * 51, "CLAN ABC", "CLAN.ABC"):
        with pytest.raises(ValidationError):
            TypeAdapter(ClanCode).validate_python(bad)


def test_codes_are_random_every_character_is_used_and_nothing_repeats_in_5000():
    codes = [generate_clan_code() for _ in range(5000)]
    assert len(set(codes)) == 5000
    used = {ch for code in codes for ch in code[len(CLAN_CODE_PREFIX):]}
    assert used == set(CLAN_CODE_ALPHABET)


def test_each_character_is_drawn_with_secrets_choice_from_the_alphabet(monkeypatch):
    drawn = []

    def fake_choice(seq):
        drawn.append(seq)
        return seq[0]

    monkeypatch.setattr(clan_code_module.secrets, "choice", fake_choice)
    assert generate_clan_code() == "CLAN-AAAAAAAA"
    assert drawn == [CLAN_CODE_ALPHABET] * 8


def test_the_generator_does_not_use_the_random_module():
    source = inspect.getsource(clan_code_module)
    assert "import random" not in source and "random." not in source.replace("secrets", "")
