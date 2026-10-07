"""The text types of app/schemas/common.py (Mốc E, step E3).

One-line text (Email, Str255) is cleaned: control characters rejected, NFC, whitespace
collapsed (Str255 only). Multi-line text (MultilineText) allows newline and tab but never NUL.
Secrets (passwords, ID tokens, oob codes, tracking codes) must NEVER go through any of it: the
value has to arrive byte for byte. This file proves both halves, and fences the set of fields
that use the cleaners so it cannot grow by accident.
"""

from __future__ import annotations

import importlib
import pkgutil
import unicodedata
from typing import get_args

import pytest
from pydantic import BaseModel, SecretStr, TypeAdapter, ValidationError
from pydantic.functional_validators import AfterValidator

import app.schemas
from app.schemas import common
from app.schemas.auth import (
    ChangePasswordRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    SessionCreateRequest,
)
from app.schemas.business import (
    BusinessRegistrationCreateRequest,
    BusinessRegistrationTrackRequest,
    OwnerProvisionRequest,
)
from app.schemas.common import Email, MultilineText, Password, SearchText, SecretToken, Str255, UserSearchText

LF, CR, TAB, NUL = "\n", "\r", "\t", "\x00"
ONE_LINE_CLEANERS = {common._clean_one_line, common._clean_email}
SEARCH_CLEANERS = {common._clean_search}  # E4: search boxes (never stored, never logged)
CLEANERS = ONE_LINE_CLEANERS | {common._clean_multiline} | SEARCH_CLEANERS


def ok(type_, value):
    return TypeAdapter(type_).validate_python(value)


def rejected(type_, value) -> bool:
    try:
        TypeAdapter(type_).validate_python(value)
    except ValidationError:
        return True
    return False


# ------------------------------------------------------------------ Str255


def test_str255_trims_collapses_and_normalizes():
    assert ok(Str255, "  Họ   Nguyễn   Văn  ") == "Họ Nguyễn Văn"
    nfd = unicodedata.normalize("NFD", "Nguyễn Ạ")
    assert nfd != unicodedata.normalize("NFC", nfd)
    assert ok(Str255, nfd) == unicodedata.normalize("NFC", "Nguyễn Ạ")


@pytest.mark.parametrize("bad", [NUL, "a" + NUL + "b", LF, "a" + LF + "b", TAB, "a" + TAB + "b", CR,
                                 "\x1b[31m", "\x7f", "\x85", "\x9f", "a\x00"])
def test_str255_rejects_control_characters(bad):
    assert rejected(Str255, bad), repr(bad)


def test_str255_keeps_its_length_rules():
    assert ok(Str255, "x" * 255) == "x" * 255
    assert rejected(Str255, "x" * 256) and rejected(Str255, "") and rejected(Str255, "   ")


def test_str255_never_trims_into_an_accepted_empty_value():
    assert rejected(Str255, "   ")  # only whitespace of any kind


# ------------------------------------------------------------------ Email


def test_email_is_trimmed_and_normalized_but_never_lower_cased():
    assert ok(Email, "  Ann@Example.TEST ") == "Ann@Example.TEST"
    composed = unicodedata.normalize("NFC", "josé@exämple.test")
    assert ok(Email, unicodedata.normalize("NFD", "josé@exämple.test")) == composed


@pytest.mark.parametrize("bad", ["a" + NUL + "@b.co", "a@b.co" + NUL, "a\x01@b.co", "a@b\x7f.co", "a@b.co\x85x"])
def test_email_rejects_control_characters(bad):
    assert rejected(Email, bad), repr(bad)


@pytest.mark.parametrize("bad", ["plain", "a@b", "a@@b.co", "a b@c.co", "@b.co", "a@.co", "a@b.", "x" * 251 + "@b.co"])
def test_email_keeps_its_format_rules(bad):
    assert rejected(Email, bad)


# ------------------------------------------------------------------ MultilineText


def test_multiline_text_keeps_newlines_and_tabs():
    assert ok(MultilineText, f"first line{LF}\tsecond line") == f"first line{LF}\tsecond line"


def test_multiline_text_turns_crlf_into_lf_and_trims():
    assert ok(MultilineText, f"  a{CR}{LF}b  ") == f"a{LF}b"


@pytest.mark.parametrize("bad", [NUL, "a" + NUL + "b", CR, "a" + CR + "b", "\x07", "\x1b", "\x7f", "\x85"])
def test_multiline_text_still_rejects_nul_and_every_other_control_character(bad):
    assert rejected(MultilineText, bad), repr(bad)


def test_multiline_text_is_normalized_and_bounded():
    nfd = unicodedata.normalize("NFD", "Lý do: thiếu giấy tờ")
    assert ok(MultilineText, nfd) == unicodedata.normalize("NFC", nfd)
    assert ok(MultilineText, "x" * 2000) and rejected(MultilineText, "x" * 2001) and rejected(MultilineText, "  ")


def test_exactly_the_reason_fields_use_multiline_text():
    """The reason fields are the multi-line text of the API; nothing else may use it by accident."""
    users = {
        (model.__name__, name)
        for model in all_models()
        for name, field in model.model_fields.items()
        if _uses(field, {common._clean_multiline})
    }
    assert users == {
        ("UserStatusUpdateRequest", "reason"),
        ("RegistrationReviewRequest", "reason"),
    }


def test_the_old_reason_type_is_gone():
    assert not hasattr(common, "ReasonText")


@pytest.mark.parametrize("bad", ["a" + NUL + "b", NUL, "bell\x07", "lone" + CR + "cr", "\x1b[0m", "x" * 2001, "   "])
def test_a_status_reason_with_a_control_character_is_refused(bad):
    from app.schemas.users import UserStatusUpdateRequest

    with pytest.raises(ValidationError):
        UserStatusUpdateRequest(status="LOCKED", reason=bad)


def test_a_status_reason_may_span_lines():
    from app.schemas.users import UserStatusUpdateRequest

    model = UserStatusUpdateRequest(status="LOCKED", reason=f"  line one{CR}{LF}	line two  ")
    assert model.reason == f"line one{LF}	line two"


def test_a_review_reason_is_multi_line_text_too():
    from app.schemas.business import RegistrationReviewRequest

    ok_model = RegistrationReviewRequest(decision="REJECTED", reason=f"missing{LF}documents")
    assert ok_model.reason == f"missing{LF}documents"
    with pytest.raises(ValidationError):
        RegistrationReviewRequest(decision="REJECTED", reason="a" + NUL)
    with pytest.raises(ValidationError):
        RegistrationReviewRequest(decision="REJECTED")  # the reason is still required when rejecting
    assert RegistrationReviewRequest(decision="APPROVED").reason is None


# ------------------------------------------------------------------ secrets are never touched


TRICKY = [
    "  leading and trailing  ",
    "inner   spaces",
    "tab\there",
    "line\nbreak",
    "nul" + NUL + "byte",
    "bell\x07",
    unicodedata.normalize("NFD", "Nguyễn-pass"),
    " nbsp ",
    "x" * 300,
]


@pytest.mark.parametrize("value", TRICKY, ids=[repr(v)[:24] for v in TRICKY])
def test_secret_types_return_the_value_byte_for_byte(value):
    assert ok(SecretToken, value).get_secret_value() == value
    if len(value) >= 6:
        assert ok(Password, value).get_secret_value() == value


@pytest.mark.parametrize("value", TRICKY, ids=[repr(v)[:24] for v in TRICKY])
def test_every_secret_field_of_the_request_models_keeps_its_value(value):
    long = value if len(value) >= 6 else value + "padding"
    assert SessionCreateRequest(id_token=value).id_token.get_secret_value() == value
    assert BusinessRegistrationTrackRequest(tracking_code=value).tracking_code.get_secret_value() == value
    reset = PasswordResetConfirmRequest(oob_code=value, new_password=long)
    assert reset.oob_code.get_secret_value() == value and reset.new_password.get_secret_value() == long
    change = ChangePasswordRequest(new_password=long, recent_id_token=value)
    assert change.new_password.get_secret_value() == long and change.recent_id_token.get_secret_value() == value


def test_the_tracking_code_of_a_wrong_guess_is_not_cleaned_into_a_right_one():
    """If the cleaners ran on the code, a code with a trailing space would match the real one."""
    model = BusinessRegistrationTrackRequest(tracking_code="  Abc\tdef  ")
    assert model.tracking_code.get_secret_value() == "  Abc\tdef  "


def test_the_secret_types_carry_no_cleaning_validator():
    for secret_type in (Password, SecretToken):
        validators = [m.func for m in secret_type.__metadata__ if isinstance(m, AfterValidator)]
        assert not CLEANERS & set(validators)


# ------------------------------------------------------------------ SearchText / UserSearchText (E4)


def test_search_text_is_trimmed_collapsed_and_normalized_but_never_lower_cased():
    nfd = unicodedata.normalize("NFD", "Nguyễn")
    assert ok(SearchText, "  Họ   Nguyễn  ") == "Họ Nguyễn"
    assert ok(SearchText, nfd) == unicodedata.normalize("NFC", "Nguyễn")
    assert ok(SearchText, "MiXeD") == "MiXeD"  # case is the database's job (ILIKE)


@pytest.mark.parametrize("bad", [NUL, "a" + NUL, "a\x07b", "a\x7fb", "a\x1bb", "a" + LF + "b", "a" + TAB + "b", "a" + CR + "b"])
def test_search_text_rejects_every_control_character_including_nul(bad):
    assert rejected(SearchText, bad) and rejected(UserSearchText, bad)


@pytest.mark.parametrize("value, accepted", [("", False), ("a", False), (" a ", False), ("ab", True), ("x" * 100, True), ("x" * 101, False)])
def test_search_text_is_2_to_100_characters_after_trimming(value, accepted):
    assert rejected(SearchText, value) is not accepted


@pytest.mark.parametrize("value, accepted", [("", True), ("   ", True), ("a", True), ("x" * 255, True), ("x" * 256, False)])
def test_user_search_text_keeps_the_old_rules_0_to_255(value, accepted):
    """GET /admin/users?q= keeps its behaviour: an empty q is still "no filter"."""
    assert rejected(UserSearchText, value) is not accepted
    if accepted:
        assert ok(UserSearchText, value) == value.strip()


def test_search_text_does_not_change_the_wildcards_it_receives():
    # LIKE characters are escaped by the repository, not removed here.
    assert ok(SearchText, "50%_\\") == "50%_\\"


# ------------------------------------------------------------------ the set of fields that use the cleaners


def _metadata_of(annotation) -> list:
    """Annotated metadata anywhere inside a type, so Optional[Str255] is seen through."""
    found = list(getattr(annotation, "__metadata__", ()))
    for arg in get_args(annotation):
        found += _metadata_of(arg)
    return found


def _uses(field, cleaners=None) -> bool:
    cleaners = CLEANERS if cleaners is None else cleaners
    items = list(field.metadata) + _metadata_of(field.annotation)
    return any(isinstance(m, AfterValidator) and m.func in cleaners for m in items)


def _uses_cleaner(field) -> bool:
    return _uses(field)


def all_models() -> list[type[BaseModel]]:
    found: list[type[BaseModel]] = []
    for info in pkgutil.iter_modules(app.schemas.__path__):
        module = importlib.import_module(f"app.schemas.{info.name}")
        for obj in vars(module).values():
            if isinstance(obj, type) and issubclass(obj, BaseModel) and obj.__module__ == module.__name__:
                found.append(obj)
    return found


def test_exactly_these_fields_use_the_one_line_cleaners():
    users = {
        (model.__name__, name)
        for model in all_models()
        for name, field in model.model_fields.items()
        if _uses(field, ONE_LINE_CLEANERS)
    }
    assert users == {
        ("BusinessRegistrationCreateRequest", "representative_name"),
        ("BusinessRegistrationCreateRequest", "representative_email"),
        ("BusinessRegistrationCreateRequest", "clan_name"),
        ("BusinessRegistrationCreateRequest", "origin_place"),
        ("OwnerProvisionRequest", "email"),
        ("OwnerProvisionRequest", "display_name"),
        ("PasswordResetRequest", "email"),
    }


def test_exactly_these_fields_use_the_search_cleaner():
    users = {
        (model.__name__, name)
        for model in all_models()
        for name, field in model.model_fields.items()
        if _uses(field, SEARCH_CLEANERS)
    }
    assert users == {
        ("BusinessRegistrationListQuery", "q"),
        ("AdminUserListQuery", "q"),
    }


def test_the_search_cleaner_is_not_used_by_any_stored_field():
    """A search text is a filter: it must never be the type of a field that is written."""
    for model in all_models():
        for name, field in model.model_fields.items():
            if _uses(field, SEARCH_CLEANERS):
                assert model.__name__.endswith("ListQuery"), (model.__name__, name)


def test_no_secret_field_anywhere_uses_a_cleaner_or_is_a_plain_string():
    secret_like = ("password", "token", "oob_code", "tracking_code", "secret")
    checked = 0
    for model in all_models():
        for name, field in model.model_fields.items():
            if any(word in name for word in secret_like) and model.__name__.endswith("Request"):
                checked += 1
                assert not _uses_cleaner(field), (model.__name__, name)
                assert field.annotation is SecretStr, (model.__name__, name)  # a secret is a SecretStr
    assert checked >= 6  # the scan really looked at the secret fields


def test_the_secret_request_fields_are_secretstr_so_they_are_never_echoed_either():
    for model, name in (
        (SessionCreateRequest, "id_token"),
        (BusinessRegistrationTrackRequest, "tracking_code"),
        (PasswordResetConfirmRequest, "oob_code"),
        (PasswordResetConfirmRequest, "new_password"),
        (ChangePasswordRequest, "new_password"),
        (ChangePasswordRequest, "recent_id_token"),
    ):
        assert model.model_fields[name].annotation is SecretStr, (model.__name__, name)
        assert "SecretStr" in repr(getattr(model.model_construct(**{name: SecretStr("s3cr3t")}), name))
        assert "s3cr3t" not in repr(model.model_construct(**{name: SecretStr("s3cr3t")}))


def test_the_registration_request_cleans_the_applicant_fields_only():
    model = BusinessRegistrationCreateRequest(
        representative_name="  Tran   Thi  ", representative_email=" A@B.co ", clan_name=" Ho  Tran ",
        requested_plan_id="3f2b4e5c-0000-4000-8000-000000000000", origin_place=" Hà   Nội ",
    )
    assert (model.representative_name, model.representative_email, model.clan_name, model.origin_place) == (
        "Tran Thi", "A@B.co", "Ho Tran", "Hà Nội")
    with pytest.raises(ValidationError):
        BusinessRegistrationCreateRequest(
            representative_name="a" + NUL, representative_email="a@b.co", clan_name="x",
            requested_plan_id="3f2b4e5c-0000-4000-8000-000000000000")
    assert OwnerProvisionRequest(display_name=" A   B ").display_name == "A B"
    assert PasswordResetRequest(email=" X@Y.co ").email == "X@Y.co"
