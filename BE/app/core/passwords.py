"""The temporary password of a new Owner (Mốc E6).

16 characters from `secrets`: at least one upper-case letter, one lower-case letter and one digit
(and one symbol when `require_symbol` is on), then shuffled so the guaranteed characters are not at
fixed places. The letters and digits that look alike when read aloud or copied by hand are left out
(I, O, l, 0, 1). About 93 bits with the default character set.

The password exists only in memory and in the ONE response that shows it. It is never stored (not in
the database, not in a log, an audit row, an idempotency row, a job, an error or a document).
"""

from __future__ import annotations

import secrets

PASSWORD_LENGTH = 16
UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"  # no I, O
LOWER = "abcdefghijkmnopqrstuvwxyz"  # no l
DIGITS = "23456789"  # no 0, 1
SYMBOLS = "!@#$%&*-_=+?"


def generate_temporary_password(*, require_symbol: bool = False) -> str:
    classes = [UPPER, LOWER, DIGITS] + ([SYMBOLS] if require_symbol else [])
    pool = "".join(classes)
    chars = [secrets.choice(group) for group in classes]  # one of each required class
    chars += [secrets.choice(pool) for _ in range(PASSWORD_LENGTH - len(chars))]
    # Fisher-Yates with secrets.randbelow: an unbiased shuffle from the same secure source.
    for i in range(len(chars) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        chars[i], chars[j] = chars[j], chars[i]
    return "".join(chars)
