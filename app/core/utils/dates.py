"""Calendar arithmetic that the standard library does not have."""

from __future__ import annotations

import calendar
from datetime import datetime


def add_months(moment: datetime, months: int) -> datetime:
    """`moment` plus a number of CALENDAR months, keeping the time of day and the time zone.

    The day of the month is clamped to the length of the target month, never carried over into
    the next one: 31 Jan + 1 month is 28 Feb (29 in a leap year), 29 Feb + 12 months is 28 Feb.
    """
    if isinstance(months, bool) or not isinstance(months, int) or months < 0:
        raise ValueError("months must be a non-negative integer")
    index = moment.year * 12 + (moment.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)
