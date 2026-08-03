import pytest
from app.services.auth_service import calculate_primary_role
from app.models.postgres import AccountRole


def test_calculate_primary_role_admin():
    roles = [
        AccountRole(role="member", status="active"),
        AccountRole(role="admin", status="active"),
    ]
    assert calculate_primary_role(roles) == "admin"


def test_calculate_primary_role_family_head():
    roles = [
        AccountRole(role="member", status="active"),
        AccountRole(role="family_head", status="active"),
    ]
    assert calculate_primary_role(roles) == "family_head"


def test_calculate_primary_role_default_member():
    roles = [
        AccountRole(role="member", status="active"),
    ]
    assert calculate_primary_role(roles) == "member"
