"""The handoff documents for the Frontend carry request/response examples. They must hold NO real or secret
data: no password, no token, no real e-mail address, no id that looks real.

The scan is deliberately tolerant: any prose, table or code is fine as long as it contains none of the
shapes below. It is strict about those shapes:
  * a temporary-password-looking string: exactly 16 letters and digits with an upper case letter, a lower
    case letter and a digit (what the generator makes, docs/api_contract.md decision 63);
  * a JWT (three base64url parts, the first starting with `eyJ`);
  * a 43-character base64url token (what a session token or a tracking code looks like);
  * `Bearer` followed by anything but a `<placeholder>`;
  * an e-mail address whose domain is not a reserved example domain;
  * a UUID that is not one of the placeholder ids (`00000000-0000-4000-8000-` plus 12 digits). This last rule
    applies to the new business handoff only: the older auth handoff (Mốc D, F) carries sample ids that are
    made up but do not follow the placeholder shape, and it is not rewritten here.
The generator that produced the examples ran the real routers on fake repositories and a fake identity
provider; it is not part of the repository."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[1] / "docs"
FILES = {"handoff_frontend_business.md": True, "handoff_frontend.md": False}  # name -> are ids checked too

PASSWORD_LIKE = re.compile(r"(?<![A-Za-z0-9_-])(?=[A-Za-z0-9]*[A-Z])(?=[A-Za-z0-9]*[a-z])(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{16}(?![A-Za-z0-9_-])")
JWT = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}")
TOKEN_43 = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])")
BEARER = re.compile(r"Bearer\s+(?!<)\S+")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
PLACEHOLDER_UUID = re.compile(r"^00000000-0000-4000-8000-\d{12}$")
RESERVED_DOMAINS = {"example.test", "example.com", "example.org", "example.net"}


def findings(text: str, *, ids: bool = True) -> list[str]:
    """Everything in `text` that looks real or secret (an empty list means clean)."""
    out = []
    out += [f"password-like string {m.group(0)[:4]}…" for m in PASSWORD_LIKE.finditer(text)]
    out += [f"JWT {m.group(0)[:8]}…" for m in JWT.finditer(text)]
    out += [f"43-character token {m.group(0)[:4]}…" for m in TOKEN_43.finditer(text)]
    out += [f"bearer value {m.group(0)[:14]}…" for m in BEARER.finditer(text)]
    out += [f"e-mail on a real domain: …@{m.group(1)}" for m in EMAIL.finditer(text) if m.group(1).lower() not in RESERVED_DOMAINS]
    if ids:
        out += [f"id that is not a placeholder: {m.group(0)}" for m in UUID.finditer(text) if not PLACEHOLDER_UUID.match(m.group(0))]
    return out


@pytest.mark.parametrize("name, ids", FILES.items())
def test_the_handoff_documents_hold_no_real_or_secret_data(name, ids):
    text = (DOCS / name).read_text(encoding="utf-8")
    assert findings(text, ids=ids) == []


def test_the_business_handoff_shows_its_secrets_only_as_placeholders():
    text = (DOCS / "handoff_frontend_business.md").read_text(encoding="utf-8")
    for placeholder in ("<temporary-password-shown-once>", "<tracking-code-shown-once>", "<access-token>", "<uuid-1>"):
        assert placeholder in text, placeholder
    assert re.search(r'"temporary_password": null', text)  # a replay and a clean-up-only retry show null, never a value


@pytest.mark.parametrize("sample, fragment", [
    ("temporary_password: Kq7Wm2Xp9Tr4Vz8N", "password-like"),
    ("token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdEFGH", "JWT"),
    ("code " + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0uVw", "43-character"),
    ("Authorization: Bearer abc123def456", "bearer value"),
    ("someone@gmail.com", "real domain"),
    ("owner@example.test and someone@company.vn", "real domain"),
    ("id 3f2b4e5c-1111-4222-8333-444455556666", "not a placeholder"),
])
def test_the_scan_catches_what_it_is_meant_to_catch(sample, fragment):
    assert any(fragment in f for f in findings(sample)), findings(sample)


@pytest.mark.parametrize("sample", [
    "owner@example.test", "Authorization: Bearer <access-token>", "00000000-0000-4000-8000-000000000012",
    "TEMPORARY_PASSWORD_EXPIRED and Idempotency-Replayed and ProvisioningJobResponse",
    "`POST /admin/clans/{id}/owner/temporary-password`", "A-brand-new-pass-1", "request_id 00000000-0000-4000-8000-000000000021",
    "2026-10-08T09:00:00Z", "0123456789abcdef",
])
def test_the_scan_leaves_valid_content_alone(sample):
    assert findings(sample) == []
