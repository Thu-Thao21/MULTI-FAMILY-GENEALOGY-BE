from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.postgres import get_db
from app.dependencies.auth import get_current_account
from app.main import app
from app.models.postgres import (
    Account,
    AccountRole,
    Family,
    FamilyBranch,
    FamilyMembership,
    Permission,
    Person,
    PersonClosure,
    Role,
    RolePermission,
)
from app.services.access_service import (
    MANAGE_PERMISSIONS,
    VIEW_PERMISSIONS,
    get_default_permission_codes,
)

from conftest import TestingSessionLocal


@asynccontextmanager
async def client_for_account(account_id: str):
    async def override_account():
        async with TestingSessionLocal() as session:
            result = await session.execute(select(Account).where(Account.id == account_id))
            return result.scalar_one()

    app.dependency_overrides[get_current_account] = override_account
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as scoped_client:
            yield scoped_client
    finally:
        app.dependency_overrides.pop(get_current_account, None)


async def add_account(
    db_session,
    account_id: str,
    family_id: str,
    role: str,
    membership_status: str = "ACTIVE",
):
    db_session.add(
        Account(
            id=account_id,
            firebase_uid=account_id,
            username=account_id,
            email=f"{account_id}@example.test",
            display_name=account_id,
            status="ACTIVE",
        )
    )
    role_id = f"role-{role}"
    existing_role = await db_session.get(Role, role_id)
    if not existing_role:
        db_session.add(
            Role(
                id=role_id,
                code=role,
                name=role.replace("_", " ").title(),
            )
        )
        await db_session.flush()
    permission_codes = (
        MANAGE_PERMISSIONS if role in {"manager", "owner", "family_admin"}
        else VIEW_PERMISSIONS
    )
    for code in permission_codes:
        result = await db_session.execute(select(Permission).where(Permission.code == code))
        permission = result.scalar_one_or_none()
        if permission is None:
            permission = Permission(
                id=f"permission-{code}",
                code=code,
                module=code.split(".", maxsplit=1)[0],
            )
            db_session.add(permission)
            await db_session.flush()
        existing_grant = await db_session.get(
            RolePermission, (role_id, permission.id)
        )
        if existing_grant is None:
            db_session.add(
                RolePermission(role_id=role_id, permission_id=permission.id)
            )
    db_session.add(
        AccountRole(account_id=account_id, role_id=role_id, family_id=family_id)
    )
    db_session.add(
        FamilyMembership(
            user_id=account_id,
            family_id=family_id,
            status=membership_status,
        )
    )
    await db_session.commit()


async def add_account_with_builtin_role(
    db_session,
    account_id: str,
    role_code: str,
    role_family_id: str | None,
    membership_family_id: str | None = None,
):
    db_session.add(
        Account(
            id=account_id,
            firebase_uid=account_id,
            username=account_id,
            email=f"{account_id}@example.test",
            display_name=account_id,
            status="ACTIVE",
        )
    )
    role_id = f"role-{role_code.lower()}"
    db_session.add(
        Role(
            id=role_id,
            code=role_code,
            name=role_code.replace("_", " ").title(),
        )
    )
    db_session.add(
        AccountRole(
            account_id=account_id,
            role_id=role_id,
            family_id=role_family_id,
        )
    )
    if membership_family_id is not None:
        db_session.add(
            FamilyMembership(
                user_id=account_id,
                family_id=membership_family_id,
                status="ACTIVE",
            )
        )
    await db_session.commit()


@pytest.mark.asyncio
async def test_sprint2_requires_real_auth_for_reads_and_mutations(db_session):
    db_session.add(Family(id="fam1", name="Family 1", status="active"))
    await db_session.commit()

    app.dependency_overrides.pop(get_current_account, None)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as unauthenticated:
        no_token = await unauthenticated.get("/api/v1/families/fam1")
        invalid_token = await unauthenticated.post(
            "/api/v1/families/fam1/branches",
            headers={"Authorization": "Bearer invalid-token"},
            json={"name": "Unauthorized"},
        )

    assert no_token.status_code == 401
    assert invalid_token.status_code == 401


@pytest.mark.asyncio
async def test_permission_and_active_family_membership(db_session):
    db_session.add(Family(id="fam1", name="Family 1", status="active"))
    await db_session.commit()
    await add_account(db_session, "manager", "fam1", "manager")
    await add_account(db_session, "viewer", "fam1", "member")
    await add_account(
        db_session,
        "inactive-manager",
        "fam1",
        "manager",
        membership_status="inactive",
    )

    async with client_for_account("manager") as manager_client:
        allowed = await manager_client.get("/api/v1/families/fam1")
    async with client_for_account("viewer") as viewer_client:
        forbidden = await viewer_client.post(
            "/api/v1/families/fam1/persons", json={"fullName": "New Person"}
        )
    async with client_for_account("inactive-manager") as inactive_client:
        inactive = await inactive_client.get("/api/v1/families/fam1")

    assert allowed.status_code == 200
    assert forbidden.status_code == 403
    assert inactive.status_code == 403


@pytest.mark.asyncio
async def test_family_admin_builtin_permissions_and_family_scope(db_session):
    db_session.add_all(
        [
            Family(id="fam1", name="Family 1", status="active"),
            Family(id="fam2", name="Family 2", status="active"),
        ]
    )
    await db_session.commit()
    await add_account_with_builtin_role(
        db_session,
        account_id="family-admin",
        role_code="FAMILY_ADMIN",
        role_family_id="fam1",
        membership_family_id="fam1",
    )

    async with client_for_account("family-admin") as family_admin:
        own_family = await family_admin.get("/api/v1/families/fam1")
        update_family = await family_admin.patch(
            "/api/v1/families/fam1", json={"name": "Updated Family 1"}
        )
        branch = await family_admin.post(
            "/api/v1/families/fam1/branches", json={"name": "Main Branch"}
        )
        branches = await family_admin.get("/api/v1/families/fam1/branches")
        first_person = await family_admin.post(
            "/api/v1/families/fam1/persons", json={"fullName": "First Person"}
        )
        second_person = await family_admin.post(
            "/api/v1/families/fam1/persons", json={"fullName": "Second Person"}
        )
        update_person = await family_admin.patch(
            f"/api/v1/families/fam1/persons/{first_person.json()['id']}",
            json={"fullName": "Updated First Person"},
        )
        persons = await family_admin.get("/api/v1/families/fam1/persons")
        relationship = await family_admin.post(
            "/api/v1/families/fam1/relationships",
            json={
                "fromMemberId": first_person.json()["id"],
                "toMemberId": second_person.json()["id"],
                "relationshipType": "PARENT",
            },
        )
        ancestors = await family_admin.get(
            f"/api/v1/families/fam1/persons/{second_person.json()['id']}/ancestors"
        )
        tree = await family_admin.get("/api/v1/families/fam1/tree-data")
        other_family = await family_admin.get("/api/v1/families/fam2")

    assert own_family.status_code == 200
    assert update_family.status_code == 200
    assert branch.status_code == 201
    assert branches.status_code == 200
    assert first_person.status_code == 201
    assert second_person.status_code == 201
    assert update_person.status_code == 200
    assert persons.status_code == 200
    assert relationship.status_code == 201
    assert ancestors.status_code == 200
    assert tree.status_code == 200
    assert other_family.status_code == 403
    assert get_default_permission_codes({"FAMILY_ADMIN"}) == MANAGE_PERMISSIONS


@pytest.mark.asyncio
async def test_role_without_required_permission_is_forbidden(db_session):
    db_session.add(Family(id="fam1", name="Family 1", status="active"))
    await db_session.commit()
    await add_account_with_builtin_role(
        db_session,
        account_id="unprivileged-user",
        role_code="UNPRIVILEGED",
        role_family_id="fam1",
        membership_family_id="fam1",
    )

    async with client_for_account("unprivileged-user") as unprivileged:
        response = await unprivileged.get("/api/v1/families/fam1")

    assert response.status_code == 403
    assert response.json()["detail"] == "Missing required permission: family.view"


@pytest.mark.asyncio
async def test_system_admin_global_access_does_not_require_family_membership(db_session):
    db_session.add_all(
        [
            Family(id="fam1", name="Family 1", status="active"),
            Family(id="fam2", name="Family 2", status="active"),
        ]
    )
    await db_session.commit()
    await add_account_with_builtin_role(
        db_session,
        account_id="system-admin",
        role_code="SYSTEM_ADMIN",
        role_family_id=None,
    )

    async with client_for_account("system-admin") as system_admin:
        first_family = await system_admin.get("/api/v1/families/fam1")
        second_family = await system_admin.get("/api/v1/families/fam2")

    assert first_family.status_code == 200
    assert second_family.status_code == 200


@pytest.mark.asyncio
async def test_person_create_update_scope_branch_and_generation(client, db_session):
    db_session.add_all(
        [
            Family(id="fam1", name="Family 1", status="active"),
            Family(id="fam2", name="Family 2", status="active"),
            FamilyBranch(id="branch1", family_id="fam1", name="Branch 1"),
            FamilyBranch(id="branch2", family_id="fam2", name="Branch 2"),
            Person(id="foreign-person", family_id="fam2", full_name="Foreign"),
        ]
    )
    await db_session.commit()

    controlled_generation = await client.post(
        "/api/v1/families/fam1/persons",
        json={"fullName": "Invalid", "generation": 99},
    )
    wrong_branch = await client.post(
        "/api/v1/families/fam1/persons",
        json={"fullName": "Invalid Branch", "branchId": "branch2"},
    )
    created = await client.post(
        "/api/v1/families/fam1/persons",
        json={
            "fullName": "Created Person",
            "branchId": "branch1",
            "gender": "female",
            "isLiving": True,
        },
    )
    person_id = created.json()["id"]
    patched = await client.patch(
        f"/api/v1/families/fam1/persons/{person_id}",
        json={"fullName": "Updated Person"},
    )
    patch_generation = await client.patch(
        f"/api/v1/families/fam1/persons/{person_id}", json={"generation": 7}
    )
    cross_family = await client.patch(
        "/api/v1/families/fam1/persons/foreign-person",
        json={"fullName": "Forbidden"},
    )
    missing = await client.patch(
        "/api/v1/families/fam1/persons/missing", json={"fullName": "Missing"}
    )

    closure = await db_session.execute(
        select(PersonClosure).where(
            PersonClosure.ancestor_id == person_id,
            PersonClosure.descendant_id == person_id,
        )
    )
    self_row = closure.scalar_one_or_none()

    assert controlled_generation.status_code == 422
    assert wrong_branch.status_code == 400
    assert created.status_code == 201
    assert created.json()["generation"] == 1
    assert created.json()["branchId"] == "branch1"
    assert patched.status_code == 200
    assert patched.json()["fullName"] == "Updated Person"
    assert patched.json()["generation"] == 1
    assert patch_generation.status_code == 422
    assert cross_family.status_code == 403
    assert missing.status_code == 404
    assert self_row is not None and self_row.depth == 0


@pytest.mark.asyncio
async def test_spouse_duplicate_and_tree_logical_edge(client, db_session):
    db_session.add(Family(id="fam1", name="Family 1", status="active"))
    db_session.add_all(
        [
            Person(id="A", family_id="fam1", full_name="A"),
            Person(id="B", family_id="fam1", full_name="B"),
        ]
    )
    await db_session.commit()

    created = await client.post(
        "/api/v1/families/fam1/relationships",
        json={"fromMemberId": "A", "toMemberId": "B", "relationshipType": "SPOUSE"},
    )
    duplicate = await client.post(
        "/api/v1/families/fam1/relationships",
        json={"fromMemberId": "A", "toMemberId": "B", "relationshipType": "SPOUSE"},
    )
    reverse = await client.post(
        "/api/v1/families/fam1/relationships",
        json={"fromMemberId": "B", "toMemberId": "A", "relationshipType": "SPOUSE"},
    )
    tree = await client.get("/api/v1/families/fam1/tree-data")
    spouse_edges = [
        edge for edge in tree.json()["edges"] if edge["relationshipType"] == "SPOUSE"
    ]

    assert created.status_code == 201
    assert duplicate.status_code == 400
    assert reverse.status_code == 400
    assert len(spouse_edges) == 1
    assert {spouse_edges[0]["fromMemberId"], spouse_edges[0]["toMemberId"]} == {
        "A",
        "B",
    }


@pytest.mark.asyncio
async def test_tree_requires_membership_and_correct_family(db_session):
    db_session.add_all(
        [
            Family(id="fam1", name="Family 1", status="active"),
            Family(id="fam2", name="Family 2", status="active"),
            Person(id="A", family_id="fam1", full_name="A"),
            Person(id="B", family_id="fam2", full_name="B"),
        ]
    )
    await db_session.commit()
    await add_account(db_session, "family1-user", "fam1", "member")

    async with client_for_account("family1-user") as scoped_client:
        own_tree = await scoped_client.get("/api/v1/families/fam1/tree-data")
        foreign_tree = await scoped_client.get("/api/v1/families/fam2/tree-data")

    assert own_tree.status_code == 200
    assert foreign_tree.status_code == 403


def test_user_service_imports_successfully():
    import app.services.user_service as user_service

    assert user_service.Account.__name__ == "Account"
