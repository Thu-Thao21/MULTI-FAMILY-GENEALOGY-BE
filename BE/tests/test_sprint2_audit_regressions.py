import importlib
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core import firebase
from app.core.config import settings
from app.models.postgres import Family, Person, PersonClosure


BACKEND_ROOT = Path(__file__).resolve().parents[1]


async def add_parent(client, parent_id: str, child_id: str):
    return await client.post(
        "/api/v1/families/fam1/relationships",
        json={
            "fromMemberId": parent_id,
            "toMemberId": child_id,
            "relationshipType": "PARENT",
        },
    )


@pytest.mark.asyncio
async def test_required_multi_parent_closure_delete(client, db_session):
    db_session.add(Family(id="fam1", name="Family 1", status="active"))
    db_session.add_all(
        [
            Person(id=person_id, family_id="fam1", full_name=person_id)
            for person_id in ("A", "B", "C", "D")
        ]
    )
    await db_session.commit()

    ac = await add_parent(client, "A", "C")
    bc = await add_parent(client, "B", "C")
    cd = await add_parent(client, "C", "D")
    assert ac.status_code == bc.status_code == cd.status_code == 201

    before = set(
        (
            await db_session.execute(
                select(
                    PersonClosure.ancestor_id,
                    PersonClosure.descendant_id,
                    PersonClosure.depth,
                )
            )
        ).all()
    )
    assert {
        ("A", "A", 0),
        ("B", "B", 0),
        ("C", "C", 0),
        ("D", "D", 0),
        ("A", "C", 1),
        ("B", "C", 1),
        ("C", "D", 1),
        ("A", "D", 2),
        ("B", "D", 2),
    } <= before

    deleted = await client.delete(
        f"/api/v1/families/fam1/relationships/{ac.json()['id']}"
    )
    assert deleted.status_code == 204
    after = set(
        (
            await db_session.execute(
                select(
                    PersonClosure.ancestor_id,
                    PersonClosure.descendant_id,
                    PersonClosure.depth,
                )
            )
        ).all()
    )
    assert ("A", "C", 1) not in after
    assert ("A", "D", 2) not in after
    assert {("B", "C", 1), ("B", "D", 2), ("C", "D", 1)} <= after
    assert all(
        (person_id, person_id, 0) in after for person_id in ("A", "B", "C", "D")
    )


@pytest.mark.asyncio
async def test_required_reparent_preserves_new_parent_ancestry(client, db_session):
    db_session.add(Family(id="fam1", name="Family 1", status="active"))
    db_session.add_all(
        [
            Person(id=person_id, family_id="fam1", full_name=person_id)
            for person_id in ("A", "B", "C", "D", "E")
        ]
    )
    await db_session.commit()

    await add_parent(client, "A", "B")
    bc = await add_parent(client, "B", "C")
    await add_parent(client, "E", "D")
    assert (
        await client.delete(
            f"/api/v1/families/fam1/relationships/{bc.json()['id']}"
        )
    ).status_code == 204
    assert (await add_parent(client, "D", "C")).status_code == 201

    ancestors = await client.get("/api/v1/families/fam1/persons/C/ancestors")
    depths = {item["person"]["id"]: item["depth"] for item in ancestors.json()}
    assert depths == {"D": 1, "E": 2}


def test_sprint2_layering_and_all_app_modules_import():
    controller_paths = [
        BACKEND_ROOT / "app/controllers/family_controller.py",
        BACKEND_ROOT / "app/controllers/genealogy_controller.py",
    ]
    router_paths = [
        BACKEND_ROOT / "app/routers/family.py",
        BACKEND_ROOT / "app/routers/genealogy.py",
    ]
    for path in controller_paths:
        source = path.read_text(encoding="utf-8")
        assert "APIRouter" not in source
        assert "Depends(" not in source
        assert ".commit(" not in source
        assert ".rollback(" not in source
    for path in router_paths:
        source = path.read_text(encoding="utf-8")
        assert ".commit(" not in source
        assert "sqlalchemy import select" not in source

    failures = []
    for path in sorted((BACKEND_ROOT / "app").rglob("*.py")):
        module = ".".join(path.relative_to(BACKEND_ROOT).with_suffix("").parts)
        try:
            importlib.import_module(module)
        except Exception as exc:  # pragma: no cover - assertion reports exact failure
            failures.append((module, type(exc).__name__, str(exc)))
    assert failures == []


def test_firebase_default_never_uses_unsigned_fallback(monkeypatch):
    unsigned_decode_called = False

    def fail_official_verification():
        raise RuntimeError("official verification unavailable")

    def record_unsigned_decode(*args, **kwargs):
        nonlocal unsigned_decode_called
        unsigned_decode_called = True
        return {"uid": "unsafe"}

    monkeypatch.setattr(settings, "ALLOW_INSECURE_FIREBASE_DEV", False)
    monkeypatch.setattr(firebase, "get_firebase_app", fail_official_verification)
    monkeypatch.setattr(firebase.jwt, "decode", record_unsigned_decode)

    with pytest.raises(ValueError, match="Firebase token verification failed"):
        firebase.verify_firebase_token("secret-token-not-logged")
    assert unsigned_decode_called is False


def test_firebase_only_auth_and_environment_security_defaults():
    assert settings.ALLOW_INSECURE_FIREBASE_DEV is False

    db_source = (BACKEND_ROOT / "app/db/postgres.py").read_text(encoding="utf-8")
    assert "ALTER TABLE" not in db_source

    runtime_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((BACKEND_ROOT / "app").rglob("*.py"))
    )
    for forbidden in (
        "password_hash",
        "hash_password",
        "verify_password",
        "UserSession",
        "PasswordReset",
    ):
        assert forbidden not in runtime_source

    env_example = (BACKEND_ROOT / ".env.example").read_text(encoding="utf-8")
    assert (
        "DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST/DATABASE?ssl=require"
        in env_example
    )
    assert (
        "MIGRATION_DATABASE_URL=postgresql://USER:PASSWORD@DIRECT_HOST/DATABASE?sslmode=require"
        in env_example
    )
    assert "```" not in env_example


def test_stable_branch_contract_and_openapi_person_operations():
    from app.main import app
    from app.models.postgres import Person

    branch_column = Person.__table__.c.branch_id
    assert branch_column.nullable is True
    assert list(branch_column.foreign_keys)[0].target_fullname == "branches.branch_id"

    paths = app.openapi()["paths"]
    assert "post" in paths["/api/v1/families/{family_id}/persons"]
    assert "patch" in paths["/api/v1/families/{family_id}/persons/{person_id}"]


def test_neon_canonical_table_and_column_mapping():
    from sqlalchemy.dialects import postgresql
    from app.db.postgres import Base
    from app.models.postgres import (
        Account,
        AccountRole,
        Family,
        FamilyBranch,
        FamilyMembership,
        Permission,
        Person,
        PersonClosure,
        Relationship,
        Role,
        RolePermission,
    )

    assert Account.__table__.name == "users"
    assert Account.__table__.c.user_id.primary_key
    assert Account.__table__.c.phone.name == "phone"
    assert "password_hash" not in Account.__table__.c
    assert Family.__table__.name == "clans"
    assert Family.__table__.c.clan_id.primary_key
    assert FamilyMembership.__table__.name == "clan_memberships"
    assert FamilyMembership.__table__.c.membership_id.primary_key
    assert FamilyMembership.__table__.c.clan_id.name == "clan_id"
    assert FamilyBranch.__table__.name == "branches"
    assert FamilyBranch.__table__.c.branch_id.primary_key
    assert Person.__table__.name == "persons"
    assert Person.__table__.c.person_id.primary_key
    assert Person.__table__.c.generation_no.name == "generation_no"
    assert Person.__table__.c.avatar_storage_key.name == "avatar_storage_key"
    assert Relationship.__table__.name == "relationships"
    assert Relationship.__table__.c.relationship_id.primary_key
    assert Relationship.__table__.c.from_person_id.name == "from_person_id"
    assert Relationship.__table__.c.to_person_id.name == "to_person_id"
    assert Relationship.__table__.c.created_by.nullable is False
    assert set(PersonClosure.__table__.c.keys()) == {
        "ancestor_id",
        "descendant_id",
        "depth",
    }
    assert AccountRole.__table__.name == "user_roles"
    assert Role.__table__.name == "roles"
    assert Permission.__table__.name == "permissions"
    assert RolePermission.__table__.name == "role_permissions"

    assert set(Base.metadata.tables) == {
        "users",
        "clans",
        "clan_memberships",
        "branches",
        "persons",
        "relationships",
        "person_closure",
        "roles",
        "user_roles",
        "permissions",
        "role_permissions",
    }
    assert set(Account.__table__.c.keys()) == {
        "user_id",
        "firebase_uid",
        "username",
        "email",
        "phone",
        "display_name",
        "status",
        "email_verified",
        "phone_verified",
        "first_login_required",
        "last_login_at",
        "created_at",
        "updated_at",
    }

    forbidden = {
        "accounts",
        "families",
        "family_memberships",
        "family_branches",
        "members",
    }
    assert forbidden.isdisjoint(Base.metadata.tables)
    for column in (
        Account.__table__.c.user_id,
        Family.__table__.c.clan_id,
        FamilyMembership.__table__.c.membership_id,
        FamilyBranch.__table__.c.branch_id,
        Person.__table__.c.person_id,
        Relationship.__table__.c.relationship_id,
        PersonClosure.__table__.c.ancestor_id,
    ):
        assert str(column.type.dialect_impl(postgresql.dialect())) == "UUID"
