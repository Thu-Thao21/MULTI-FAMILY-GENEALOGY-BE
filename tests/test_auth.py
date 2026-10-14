from types import SimpleNamespace
from app.services.auth_access.auth_service import calculate_primary_role


def test_calculate_primary_role_admin():
    roles = [
        SimpleNamespace(role="member", status="active"),
        SimpleNamespace(role="admin", status="active"),
    ]
    assert calculate_primary_role(roles) == "admin"



def test_calculate_primary_role_default_member():
    roles = [
        SimpleNamespace(role="member", status="active"),
    ]
    assert calculate_primary_role(roles) == "member"


def test_calculate_primary_role_family_head():
    roles = [
        SimpleNamespace(role="member", status="active"),
        SimpleNamespace(role="family_head", status="active"),
    ]
    assert calculate_primary_role(roles) == "family_head"


def test_calculate_primary_role_ignores_inactive_admin():
    roles = [
        SimpleNamespace(role="member", status="active"),
        SimpleNamespace(role="admin", status="locked"),
    ]
    assert calculate_primary_role(roles) == "member"
