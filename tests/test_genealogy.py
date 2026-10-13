import pytest
from httpx import AsyncClient
from app.models.postgres import Family, Person

@pytest.mark.asyncio
async def test_genealogy_flow(client: AsyncClient, db_session):
    # Setup Family
    family = Family(id="fam1", name="Test Family", status="active")
    db_session.add(family)

    # Setup Persons
    a = Person(id="personA", family_id="fam1", full_name="A", gender="male", generation=1)
    b = Person(id="personB", family_id="fam1", full_name="B", gender="male", generation=1)
    c = Person(id="personC", family_id="fam1", full_name="C", gender="male", generation=1)

    db_session.add_all([a, b, c])
    await db_session.commit()

    # 1. A parent B
    res1 = await client.post("/api/v1/families/fam1/relationships", json={
        "fromMemberId": "personA",
        "toMemberId": "personB",
        "relationshipType": "PARENT"
    })
    assert res1.status_code == 201

    # Check Generation of B is 2
    res_b = await client.get("/api/v1/families/fam1/persons/personB")
    assert res_b.status_code == 200
    assert res_b.json()["generation"] == 2

    # 2. B parent C
    res2 = await client.post("/api/v1/families/fam1/relationships", json={
        "fromMemberId": "personB",
        "toMemberId": "personC",
        "relationshipType": "PARENT"
    })
    assert res2.status_code == 201

    # Check Generation of C is 3
    res_c = await client.get("/api/v1/families/fam1/persons/personC")
    assert res_c.json()["generation"] == 3

    # Check Ancestors of C (should contain A and B)
    res_anc = await client.get("/api/v1/families/fam1/persons/personC/ancestors")
    assert res_anc.status_code == 200
    anc_ids = [item["person"]["id"] for item in res_anc.json()]
    assert "personA" in anc_ids
    assert "personB" in anc_ids

    # Check depth of A from C should be 2
    a_anc = next((item for item in res_anc.json() if item["person"]["id"] == "personA"), None)
    assert a_anc is not None
    assert a_anc["depth"] == 2

    # Check Descendants of A (should contain B and C)
    res_desc = await client.get("/api/v1/families/fam1/persons/personA/descendants")
    assert res_desc.status_code == 200
    desc_ids = [item["person"]["id"] for item in res_desc.json()]
    assert "personB" in desc_ids
    assert "personC" in desc_ids

    # 3. Cycle rejected
    res_cycle = await client.post("/api/v1/families/fam1/relationships", json={
        "fromMemberId": "personC",
        "toMemberId": "personA",
        "relationshipType": "PARENT"
    })
    assert res_cycle.status_code == 400
    assert "cycle" in res_cycle.json()["detail"].lower()

    # 4. Duplicate rejected
    res_dup = await client.post("/api/v1/families/fam1/relationships", json={
        "fromMemberId": "personA",
        "toMemberId": "personB",
        "relationshipType": "PARENT"
    })
    assert res_dup.status_code == 400
    assert "already exists" in res_dup.json()["detail"].lower()

    # 5. Get Tree Data
    res_tree = await client.get("/api/v1/families/fam1/tree-data")
    assert res_tree.status_code == 200
    tree_data = res_tree.json()
    assert len(tree_data["nodes"]) == 3
    assert len(tree_data["edges"]) == 2

    # 6. Re-parent C from B to A directly
    rel_bc_id = res2.json()["id"]
    res_del = await client.delete(f"/api/v1/families/fam1/relationships/{rel_bc_id}")
    assert res_del.status_code == 204

    # Check C generation is now 1 (because B->C is removed, max depth from C is 0, 0+1=1)
    res_c2 = await client.get("/api/v1/families/fam1/persons/personC")
    assert res_c2.json()["generation"] == 1

    # Check Ancestors of C (should be empty now)
    res_anc2 = await client.get("/api/v1/families/fam1/persons/personC/ancestors")
    assert len(res_anc2.json()) == 0

    # Now D parent C
    d = Person(id="personD", family_id="fam1", full_name="D", gender="male", generation=1)
    db_session.add(d)
    await db_session.commit()

    res_d_c = await client.post("/api/v1/families/fam1/relationships", json={
        "fromMemberId": "personD",
        "toMemberId": "personC",
        "relationshipType": "PARENT"
    })
    assert res_d_c.status_code == 201

    # C generation should now be 2
    res_c3 = await client.get("/api/v1/families/fam1/persons/personC")
    assert res_c3.json()["generation"] == 2

    # Ancestors of C should be D only
    res_anc3 = await client.get("/api/v1/families/fam1/persons/personC/ancestors")
    assert len(res_anc3.json()) == 1
    assert res_anc3.json()[0]["person"]["id"] == "personD"

    # Test permissions for cross family
    fam2 = Family(id="fam2", name="Fam 2", status="active")
    db_session.add(fam2)
    await db_session.commit()

    # Try to access personA from fam2 scope
    res_cross = await client.get("/api/v1/families/fam2/persons/personA")
    assert res_cross.status_code == 403
