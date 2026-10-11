import pytest
from app.services.auth_service import calculate_primary_role
from app.models.postgres import AccountRole, Role


def role_assignment(code: str, revoked: bool = False) -> AccountRole:
    assignment = AccountRole(
        account_id="user",
        role_id=f"role-{code}",
        revoked_at=None,
    )
    assignment.role_record = Role(
        id=f"role-{code}",
        code=code,
        name=code.replace("_", " ").title(),
    )
    if revoked:
        from datetime import datetime, timezone

        assignment.revoked_at = datetime.now(timezone.utc)
    return assignment


def test_calculate_primary_role_admin():
    roles = [
        role_assignment("member"),
        role_assignment("admin"),
    ]
    assert calculate_primary_role(roles) == "admin"



def test_calculate_primary_role_default_member():
    roles = [
        role_assignment("member"),
    ]
    assert calculate_primary_role(roles) == "member"


def test_calculate_primary_role_family_head():
    roles = [
        role_assignment("member"),
        role_assignment("family_head"),
    ]
    assert calculate_primary_role(roles) == "family_head"


def test_calculate_primary_role_ignores_inactive_admin():
    roles = [
        role_assignment("member"),
        role_assignment("admin", revoked=True),
    ]
    assert calculate_primary_role(roles) == "member"
