import pytest
from httpx import AsyncClient
from app.models.postgres import Family

@pytest.mark.asyncio
async def test_family_flow(client: AsyncClient, db_session):
    # Setup Family
    family = Family(id="fam1", name="Test Family", status="active")
    db_session.add(family)
    await db_session.commit()

    # 1. Get Family Detail
    res1 = await client.get("/api/v1/families/fam1")
    assert res1.status_code == 200
    assert res1.json()["name"] == "Test Family"

    # 2. Update Family
    res2 = await client.patch("/api/v1/families/fam1", json={"name": "Updated Family"})
    assert res2.status_code == 200
    assert res2.json()["name"] == "Updated Family"

    # 3. Create Branch
    res3 = await client.post("/api/v1/families/fam1/branches", json={"name": "Branch 1"})
    assert res3.status_code == 201
    branch_id = res3.json()["id"]

    # 4. Update Branch
    res4 = await client.patch(f"/api/v1/families/fam1/branches/{branch_id}", json={"name": "Updated Branch 1"})
    assert res4.status_code == 200
    assert res4.json()["name"] == "Updated Branch 1"

    # 5. Get Branches
    res5 = await client.get("/api/v1/families/fam1/branches")
    assert res5.status_code == 200
    assert len(res5.json()) == 1
