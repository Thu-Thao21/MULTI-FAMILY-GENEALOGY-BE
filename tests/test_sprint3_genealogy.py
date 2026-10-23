"""Tests for Sprint 3: ERGO-CENTRIC Visualization & Search.

Covers:
- Focus View (Ego-centric BFS subgraph)
- Relationship Path (BFS Shortest Path with Lineage Preference)
- Vietnamese Kinship Naming (Comprehensive Rules)
- Tree Filtering by Branch and Generation
- Privacy Scoping (Public tree view)
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.services.genealogy.focus_view_service import FocusViewService
from app.services.genealogy.kinship_service import KinshipService
from app.services.genealogy.relationship_path_service import RelationshipPathService


def test_focus_view_bfs_depth_1():
    """Focus view 3-tier ego-centric rules:
    - Level -1: Parents of Ego
    - Level  0: Ego & Spouse
    - Level +1: Children of Ego
    """
    ego_id = "p_ego"
    relationships = [
        {"id": "r1", "from_member_id": "p_parent", "to_member_id": ego_id, "relationship_type": "PARENT_CHILD"},
        {"id": "r2", "from_member_id": ego_id, "to_member_id": "p_child", "relationship_type": "PARENT_CHILD"},
        {"id": "r3", "from_member_id": ego_id, "to_member_id": "p_spouse", "relationship_type": "SPOUSE"},
        # Grandchild (child of child) - should NOT be included
        {"id": "r4", "from_member_id": "p_child", "to_member_id": "p_grandchild", "relationship_type": "PARENT_CHILD"},
    ]

    res = FocusViewService.extract_focus_subgraph(ego_id, relationships, max_depth=1)
    node_depths = res["node_depths"]
    node_roles = res.get("node_roles", {})
    edges = res["edges"]

    assert ego_id in node_depths
    assert node_depths[ego_id] == 0
    assert node_roles[ego_id] == "ego"

    assert node_depths["p_parent"] == -1
    assert node_roles["p_parent"] == "parent"

    assert node_depths["p_spouse"] == 0
    assert node_roles["p_spouse"] == "spouse"

    assert node_depths["p_child"] == 1
    assert node_roles["p_child"] == "child"

    assert "p_grandchild" not in node_depths  # Grandchild must NOT be included

    edge_ids = {e["id"] for e in edges}
    assert edge_ids == {"r1", "r2", "r3"}


def test_focus_view_strict_3_tier_no_spillover():
    """Strictly prevents expanding to grandparents, siblings, or parents of spouse."""
    ego_id = "p_ego"
    relationships = [
        # Parents
        {"id": "r_father", "from_member_id": "p_father", "to_member_id": ego_id, "relationship_type": "PARENT_CHILD"},
        {"id": "r_mother", "from_member_id": "p_mother", "to_member_id": ego_id, "relationship_type": "PARENT_CHILD"},
        {"id": "r_parents_spouse", "from_member_id": "p_father", "to_member_id": "p_mother", "relationship_type": "SPOUSE"},

        # Grandparent (Father's father) - MUST BE EXCLUDED
        {"id": "r_gp", "from_member_id": "p_grandparent", "to_member_id": "p_father", "relationship_type": "PARENT_CHILD"},

        # Sibling (Child of father) - MUST BE EXCLUDED
        {"id": "r_sib", "from_member_id": "p_father", "to_member_id": "p_sibling", "relationship_type": "PARENT_CHILD"},

        # Spouse
        {"id": "r_sp", "from_member_id": ego_id, "to_member_id": "p_spouse", "relationship_type": "SPOUSE"},

        # Spouse's parent - MUST BE EXCLUDED
        {"id": "r_sp_parent", "from_member_id": "p_spouse_father", "to_member_id": "p_spouse", "relationship_type": "PARENT_CHILD"},

        # Children
        {"id": "r_ch", "from_member_id": ego_id, "to_member_id": "p_child", "relationship_type": "PARENT_CHILD"},
        {"id": "r_ch_sp", "from_member_id": "p_spouse", "to_member_id": "p_child", "relationship_type": "PARENT_CHILD"},

        # Grandchild - MUST BE EXCLUDED
        {"id": "r_gc", "from_member_id": "p_child", "to_member_id": "p_grandchild", "relationship_type": "PARENT_CHILD"},
    ]

    res = FocusViewService.extract_focus_subgraph(ego_id, relationships)
    node_depths = res["node_depths"]
    edges = res["edges"]

    # Allowed 3-tier members
    assert node_depths[ego_id] == 0
    assert node_depths["p_father"] == -1
    assert node_depths["p_mother"] == -1
    assert node_depths["p_spouse"] == 0
    assert node_depths["p_child"] == 1

    # FORBIDDEN members: MUST NOT BE IN SUBGRAPH
    assert "p_grandparent" not in node_depths
    assert "p_sibling" not in node_depths
    assert "p_spouse_father" not in node_depths
    assert "p_grandchild" not in node_depths

    edge_ids = {e["id"] for e in edges}
    assert edge_ids == {"r_father", "r_mother", "r_parents_spouse", "r_sp", "r_ch", "r_ch_sp"}


def test_relationship_path_direct_parent_child():
    """Finds path between parent and child."""
    relationships = [
        SimpleNamespace(id="r1", from_member_id="p1", to_member_id="p2", relationship_type="PARENT_CHILD"),
        SimpleNamespace(id="r2", from_member_id="p2", to_member_id="p3", relationship_type="PARENT_CHILD"),
    ]

    path_nodes, path_edges = RelationshipPathService.find_path("p1", "p3", relationships)
    assert path_nodes == ["p1", "p2", "p3"]
    assert len(path_edges) == 2


def test_relationship_path_same_person():
    """Path between the same person returns single node and 0 edges."""
    path_nodes, path_edges = RelationshipPathService.find_path("p1", "p1", [])
    assert path_nodes == ["p1"]
    assert path_edges == []


def test_relationship_path_not_found():
    """Returns None when no path exists in disconnected graph."""
    relationships = [
        SimpleNamespace(id="r1", from_member_id="p1", to_member_id="p2", relationship_type="PARENT_CHILD"),
        SimpleNamespace(id="r2", from_member_id="p3", to_member_id="p4", relationship_type="PARENT_CHILD"),
    ]

    res = RelationshipPathService.find_path("p1", "p4", relationships)
    assert res is None


def test_kinship_naming_spouse():
    """Tests Vietnamese kinship naming for spouses."""
    husband = SimpleNamespace(id="p1", gender="male", generation=2)
    wife = SimpleNamespace(id="p2", gender="female", generation=2)
    edges = [SimpleNamespace(relationship_type="SPOUSE", from_member_id="p1", to_member_id="p2")]

    # Husband views Wife
    res_wife = KinshipService.calculate_kinship(from_person=husband, to_person=wife, path=[husband, wife], edges=edges)
    assert res_wife["kinship_name"] == "Vợ"

    # Wife views Husband
    res_husb = KinshipService.calculate_kinship(from_person=wife, to_person=husband, path=[wife, husband], edges=edges)
    assert res_husb["kinship_name"] == "Chồng"


def test_kinship_naming_parent_child():
    """Tests direct ancestor/descendant naming."""
    father = SimpleNamespace(id="p1", gender="male", generation=1)
    son = SimpleNamespace(id="p2", gender="male", generation=2)
    edges = [SimpleNamespace(relationship_type="PARENT_CHILD", from_member_id="p1", to_member_id="p2")]

    # Son views Father
    res_father = KinshipService.calculate_kinship(from_person=son, to_person=father, path=[son, father], edges=edges)
    assert res_father["kinship_name"] == "Cha"

    # Father views Son
    res_son = KinshipService.calculate_kinship(from_person=father, to_person=son, path=[father, son], edges=edges)
    assert res_son["kinship_name"] == "Con trai"


def test_kinship_naming_grandparent_grandchild():
    """Tests 2-generation direct ancestor/descendant."""
    grandfather = SimpleNamespace(id="p1", gender="male", generation=1)
    father = SimpleNamespace(id="p2", gender="male", generation=2)
    granddaughter = SimpleNamespace(id="p3", gender="female", generation=3)

    edges = [
        SimpleNamespace(relationship_type="PARENT_CHILD", from_member_id="p1", to_member_id="p2"),
        SimpleNamespace(relationship_type="PARENT_CHILD", from_member_id="p2", to_member_id="p3"),
    ]

    # Granddaughter views Grandfather
    res_gf = KinshipService.calculate_kinship(
        from_person=granddaughter, to_person=grandfather, path=[granddaughter, father, grandfather], edges=edges
    )
    assert res_gf["kinship_name"] == "Ông"

    # Grandfather views Granddaughter
    res_gd = KinshipService.calculate_kinship(
        from_person=grandfather, to_person=granddaughter, path=[grandfather, father, granddaughter], edges=edges
    )
    assert res_gd["kinship_name"] == "Cháu gái"


def test_kinship_naming_siblings():
    """Tests sibling naming."""
    older_bro = SimpleNamespace(id="p1", gender="male", generation=2, birth_date="1990-01-01")
    younger_sis = SimpleNamespace(id="p2", gender="female", generation=2, birth_date="1995-05-05")
    parent = SimpleNamespace(id="p0", gender="male", generation=1)

    edges = [
        SimpleNamespace(relationship_type="PARENT_CHILD", from_member_id="p0", to_member_id="p1"),
        SimpleNamespace(relationship_type="PARENT_CHILD", from_member_id="p0", to_member_id="p2"),
    ]

    # Sister views Brother
    res = KinshipService.calculate_kinship(
        from_person=younger_sis, to_person=older_bro, path=[younger_sis, parent, older_bro], edges=edges
    )
    assert res["kinship_name"] == "Anh ruột"

    # Brother views Sister
    res2 = KinshipService.calculate_kinship(
        from_person=older_bro, to_person=younger_sis, path=[older_bro, parent, younger_sis], edges=edges
    )
    assert res2["kinship_name"] == "Em gái ruột"
    assert res2["reciprocal_kinship"] == "Anh ruột"


def test_kinship_naming_paternal_uncle_and_reciprocal():
    """Tests paternal uncle naming and 2-way reciprocal address."""
    father = SimpleNamespace(id="p_father", gender="male", generation=1, birth_date="1960-01-01")
    uncle = SimpleNamespace(id="p_uncle", gender="male", generation=1, birth_date="1965-01-01")
    nephew = SimpleNamespace(id="p_nephew", gender="male", generation=2, birth_date="1992-01-01")

    edges = [
        SimpleNamespace(relationship_type="PARENT_CHILD", from_member_id="p_father", to_member_id="p_nephew"),
        SimpleNamespace(relationship_type="PARENT_CHILD", from_member_id="p_gp", to_member_id="p_father"),
        SimpleNamespace(relationship_type="PARENT_CHILD", from_member_id="p_gp", to_member_id="p_uncle"),
    ]

    res = KinshipService.calculate_kinship(
        from_person=nephew,
        to_person=uncle,
        path=[nephew, father, uncle],
        edges=edges,
    )
    assert res["kinship_name"] == "Chú"
    assert "Chú" in res["address_title"]
    assert res["reciprocal_kinship"] == "Cháu trai"


def test_kinship_cousin_naming():
    """Tests cousin naming based on age difference."""
    older_cousin = SimpleNamespace(id="c1", gender="female", generation=2, birth_date="1988-01-01")
    younger_cousin = SimpleNamespace(id="c2", gender="male", generation=2, birth_date="1995-01-01")

    # Younger cousin calls Older female cousin
    res = KinshipService.calculate_kinship(
        from_person=younger_cousin,
        to_person=older_cousin,
        path=[younger_cousin, SimpleNamespace(id="p1"), SimpleNamespace(id="gp"), SimpleNamespace(id="p2"), older_cousin],
        edges=[SimpleNamespace(relationship_type="PARENT_CHILD")] * 4,
    )
    assert res["kinship_name"] == "Chị họ"
    assert "Chị họ" in res["address_title"]
    assert res["reciprocal_kinship"] == "Em họ"


# =========================================================================
# COMPREHENSIVE 12 TEST CASES (FV-01 -> FV-12) AS SPECIFIED IN USER REVIEW
# =========================================================================

def test_fv_01_two_parents_two_children():
    """FV-01: Ego có cha, mẹ và hai con -> Hiển thị đúng ba tầng (-1, 0, +1)."""
    ego_id = "ego_1"
    relationships = [
        {"id": "r_dad", "from_member_id": "dad", "to_member_id": ego_id, "relationship_type": "PARENT_CHILD"},
        {"id": "r_mom", "from_member_id": "mom", "to_member_id": ego_id, "relationship_type": "PARENT_CHILD"},
        {"id": "r_parents_sp", "from_member_id": "dad", "to_member_id": "mom", "relationship_type": "SPOUSE"},
        {"id": "r_sp", "from_member_id": ego_id, "to_member_id": "wife", "relationship_type": "SPOUSE"},
        {"id": "r_c1", "from_member_id": ego_id, "to_member_id": "child_1", "relationship_type": "PARENT_CHILD"},
        {"id": "r_c2", "from_member_id": ego_id, "to_member_id": "child_2", "relationship_type": "PARENT_CHILD"},
        {"id": "r_w_c1", "from_member_id": "wife", "to_member_id": "child_1", "relationship_type": "PARENT_CHILD"},
        {"id": "r_w_c2", "from_member_id": "wife", "to_member_id": "child_2", "relationship_type": "PARENT_CHILD"},
    ]

    res = FocusViewService.extract_focus_subgraph(ego_id, relationships)
    depths = res["node_depths"]
    roles = res["node_roles"]

    assert depths[ego_id] == 0 and roles[ego_id] == "ego"
    assert depths["dad"] == -1 and roles["dad"] == "parent"
    assert depths["mom"] == -1 and roles["mom"] == "parent"
    assert depths["wife"] == 0 and roles["wife"] == "spouse"
    assert depths["child_1"] == 1 and roles["child_1"] == "child"
    assert depths["child_2"] == 1 and roles["child_2"] == "child"
    assert len(depths) == 6


def test_fv_02_only_mother_known():
    """FV-02: Ego chỉ biết mẹ -> Hiển thị mẹ, Ego và con; không tạo cha giả."""
    ego_id = "ego_2"
    relationships = [
        {"id": "r_mom", "from_member_id": "mom_single", "to_member_id": ego_id, "relationship_type": "PARENT_CHILD"},
        {"id": "r_c1", "from_member_id": ego_id, "to_member_id": "child_1", "relationship_type": "PARENT_CHILD"},
    ]

    res = FocusViewService.extract_focus_subgraph(ego_id, relationships)
    depths = res["node_depths"]

    assert depths["mom_single"] == -1
    assert depths[ego_id] == 0
    assert depths["child_1"] == 1
    # Ensure no phantom father node or spouse edges
    assert len(depths) == 3
    assert not any(getattr(e, "relationship_type", "") == "SPOUSE" for e in res["edges"])


def test_fv_03_no_children():
    """FV-03: Ego không có con -> Không xuất hiện tầng con giả, chỉ có tầng -1 và 0."""
    ego_id = "ego_3"
    relationships = [
        {"id": "r_dad", "from_member_id": "dad", "to_member_id": ego_id, "relationship_type": "PARENT_CHILD"},
        {"id": "r_sp", "from_member_id": ego_id, "to_member_id": "wife", "relationship_type": "SPOUSE"},
    ]

    res = FocusViewService.extract_focus_subgraph(ego_id, relationships)
    depths = res["node_depths"]

    assert depths[ego_id] == 0
    assert depths["dad"] == -1
    assert depths["wife"] == 0
    # No node at level +1
    assert not any(d == 1 for d in depths.values())


def test_fv_04_multiple_spouses():
    """FV-04: Ego có nhiều vợ/chồng ở các thời kỳ -> Cả hai hiển thị ở tầng 0 với role spouse."""
    ego_id = "ego_4"
    relationships = [
        {"id": "r_sp1", "from_member_id": ego_id, "to_member_id": "wife_1", "relationship_type": "SPOUSE"},
        {"id": "r_sp2", "from_member_id": ego_id, "to_member_id": "wife_2", "relationship_type": "SPOUSE"},
    ]

    res = FocusViewService.extract_focus_subgraph(ego_id, relationships)
    depths = res["node_depths"]
    roles = res["node_roles"]

    assert depths["wife_1"] == 0 and roles["wife_1"] == "spouse"
    assert depths["wife_2"] == 0 and roles["wife_2"] == "spouse"
    # Ensure no spurious edge between the two wives
    edge_pairs = {
        (e.get("from_member_id") if isinstance(e, dict) else e.from_member_id,
         e.get("to_member_id") if isinstance(e, dict) else e.to_member_id)
        for e in res["edges"]
    }
    assert ("wife_1", "wife_2") not in edge_pairs
    assert ("wife_2", "wife_1") not in edge_pairs


def test_fv_05_stepchildren_and_separate_mothers():
    """FV-05: Ego có con riêng với vợ cũ -> Không nối nhầm con riêng với vợ mới."""
    ego_id = "ego_5"
    relationships = [
        # Wife 1 and child 1
        {"id": "r_w1", "from_member_id": ego_id, "to_member_id": "wife_1", "relationship_type": "SPOUSE"},
        {"id": "r_c1_dad", "from_member_id": ego_id, "to_member_id": "child_w1", "relationship_type": "PARENT_CHILD"},
        {"id": "r_c1_mom", "from_member_id": "wife_1", "to_member_id": "child_w1", "relationship_type": "PARENT_CHILD"},

        # Wife 2 and child 2
        {"id": "r_w2", "from_member_id": ego_id, "to_member_id": "wife_2", "relationship_type": "SPOUSE"},
        {"id": "r_c2_dad", "from_member_id": ego_id, "to_member_id": "child_w2", "relationship_type": "PARENT_CHILD"},
        {"id": "r_c2_mom", "from_member_id": "wife_2", "to_member_id": "child_w2", "relationship_type": "PARENT_CHILD"},
    ]

    res = FocusViewService.extract_focus_subgraph(ego_id, relationships)
    edges = res["edges"]

    edge_ids = {e["id"] for e in edges}
    # All 6 verified edges exist
    assert edge_ids == {"r_w1", "r_c1_dad", "r_c1_mom", "r_w2", "r_c2_dad", "r_c2_mom"}

    # CRITICAL: Verify wife_2 is NEVER linked to child_w1, and wife_1 is NEVER linked to child_w2
    for e in edges:
        from_id = e["from_member_id"]
        to_id = e["to_member_id"]
        assert not (from_id == "wife_2" and to_id == "child_w1")
        assert not (from_id == "wife_1" and to_id == "child_w2")


def test_fv_06_adopted_child():
    """FV-06: Ego có con nuôi (ADOPTED_CHILD) -> Hiển thị đúng tầng +1."""
    ego_id = "ego_6"
    relationships = [
        {"id": "r_adopt", "from_member_id": ego_id, "to_member_id": "adopted_kid", "relationship_type": "ADOPTED_CHILD"},
    ]

    res = FocusViewService.extract_focus_subgraph(ego_id, relationships)
    depths = res["node_depths"]
    roles = res["node_roles"]

    assert depths["adopted_kid"] == 1
    assert roles["adopted_kid"] == "child"
    assert len(res["edges"]) == 1
    assert res["edges"][0]["id"] == "r_adopt"


def test_fv_07_siblings_strictly_excluded():
    """FV-07: Ego có anh/chị/em ruột -> Tuyệt đối không hiển thị trong Focus View."""
    ego_id = "ego_7"
    relationships = [
        {"id": "r_dad", "from_member_id": "dad", "to_member_id": ego_id, "relationship_type": "PARENT_CHILD"},
        {"id": "r_dad_sib", "from_member_id": "dad", "to_member_id": "brother", "relationship_type": "PARENT_CHILD"},
    ]

    res = FocusViewService.extract_focus_subgraph(ego_id, relationships)
    assert "brother" not in res["node_depths"]
    assert not any(e["id"] == "r_dad_sib" for e in res["edges"])


def test_fv_08_grandparents_and_grandchildren_excluded():
    """FV-08: Ego có ông bà (-2) và cháu (+2) -> Không lấy tầng -2 hoặc +2."""
    ego_id = "ego_8"
    relationships = [
        {"id": "r_gp", "from_member_id": "grandpa", "to_member_id": "dad", "relationship_type": "PARENT_CHILD"},
        {"id": "r_dad", "from_member_id": "dad", "to_member_id": ego_id, "relationship_type": "PARENT_CHILD"},
        {"id": "r_child", "from_member_id": ego_id, "to_member_id": "my_child", "relationship_type": "PARENT_CHILD"},
        {"id": "r_gc", "from_member_id": "my_child", "to_member_id": "my_grandchild", "relationship_type": "PARENT_CHILD"},
    ]

    res = FocusViewService.extract_focus_subgraph(ego_id, relationships)
    depths = res["node_depths"]

    assert "grandpa" not in depths
    assert "my_grandchild" not in depths
    assert set(depths.keys()) == {ego_id, "dad", "my_child"}


def test_fv_09_spouse_parents_excluded():
    """FV-09: Ego có cha mẹ vợ -> Không đưa cha mẹ phối ngẫu vào Focus View."""
    ego_id = "ego_9"
    relationships = [
        {"id": "r_sp", "from_member_id": ego_id, "to_member_id": "wife", "relationship_type": "SPOUSE"},
        {"id": "r_inlaw", "from_member_id": "father_in_law", "to_member_id": "wife", "relationship_type": "PARENT_CHILD"},
    ]

    res = FocusViewService.extract_focus_subgraph(ego_id, relationships)
    assert "father_in_law" not in res["node_depths"]
    assert len(res["edges"]) == 1
    assert res["edges"][0]["id"] == "r_sp"


def test_fv_10_unmarried_parents_no_spouse_edge():
    """FV-10: Cha mẹ Ego không có quan hệ SPOUSE trong DB -> Không tự tạo cạnh vợ/chồng giả."""
    ego_id = "ego_10"
    relationships = [
        {"id": "r_dad", "from_member_id": "unmarried_dad", "to_member_id": ego_id, "relationship_type": "PARENT_CHILD"},
        {"id": "r_mom", "from_member_id": "unmarried_mom", "to_member_id": ego_id, "relationship_type": "PARENT_CHILD"},
        # No SPOUSE edge between unmarried_dad and unmarried_mom
    ]

    res = FocusViewService.extract_focus_subgraph(ego_id, relationships)
    depths = res["node_depths"]

    assert depths["unmarried_dad"] == -1
    assert depths["unmarried_mom"] == -1
    assert len(res["edges"]) == 2
    edge_types = {e["relationship_type"] for e in res["edges"]}
    assert "SPOUSE" not in edge_types  # CRITICAL: NO SPOUSE EDGE INFERRED


def test_fv_11_half_sibling_classification():
    """FV-11: Phân loại 3 nhóm anh chị em: ruột, cùng cha khác mẹ, cùng mẹ khác cha."""
    p_ego = SimpleNamespace(id="p_ego", gender="male", generation=2, birth_date="1995-01-01")
    older_bro = SimpleNamespace(id="p_bro", gender="male", generation=2, birth_date="1990-01-01")
    parent = SimpleNamespace(id="p_dad", gender="male", generation=1)

    # 1. Full sibling
    res_full = KinshipService.calculate_kinship(
        from_person=p_ego,
        to_person=older_bro,
        path=[p_ego, parent, older_bro],
        edges=[SimpleNamespace(relationship_type="PARENT_CHILD")] * 2,
        sibling_type="FULL",
    )
    assert res_full["kinship_name"] == "Anh ruột"

    # 2. Half-paternal sibling (cùng cha khác mẹ)
    res_half_dad = KinshipService.calculate_kinship(
        from_person=p_ego,
        to_person=older_bro,
        path=[p_ego, parent, older_bro],
        edges=[SimpleNamespace(relationship_type="PARENT_CHILD", notes="CUNG_CHA_KHAC_ME")] * 2,
    )
    assert res_half_dad["kinship_name"] == "Anh cùng cha khác mẹ"
    assert "cùng cha khác mẹ" in res_half_dad["description"]

    # 3. Half-maternal sibling (cùng mẹ khác cha)
    res_half_mom = KinshipService.calculate_kinship(
        from_person=p_ego,
        to_person=older_bro,
        path=[p_ego, parent, older_bro],
        edges=[SimpleNamespace(relationship_type="PARENT_CHILD", notes="CUNG_ME_KHAC_CHA")] * 2,
    )
    assert res_half_mom["kinship_name"] == "Anh cùng mẹ khác cha"


def test_fv_12_safe_birth_date_and_order_comparison():
    """FV-12: An toàn tuổi tác: cùng ngày sinh hoặc thiếu ngày sinh không được suy đoán sai lệch."""
    # Same date (twins)
    twin1 = SimpleNamespace(id="t1", gender="male", generation=2, birth_date="1995-05-20", birth_order=1)
    twin2 = SimpleNamespace(id="t2", gender="female", generation=2, birth_date="1995-05-20", birth_order=2)
    parent = SimpleNamespace(id="p", gender="male", generation=1)

    # twin2 views twin1: twin1 has earlier birth_order -> older
    res_twin = KinshipService.calculate_kinship(
        from_person=twin2, to_person=twin1, path=[twin2, parent, twin1], edges=[SimpleNamespace(relationship_type="PARENT_CHILD")] * 2
    )
    assert res_twin["kinship_name"] == "Anh ruột"

    # Indeterminate: no birth date and no birth order
    unknown1 = SimpleNamespace(id="u1", gender="male", generation=2)
    unknown2 = SimpleNamespace(id="u2", gender="male", generation=2)
    res_indet = KinshipService.calculate_kinship(
        from_person=unknown1, to_person=unknown2, path=[unknown1, parent, unknown2], edges=[SimpleNamespace(relationship_type="PARENT_CHILD")] * 2
    )
    # Neutral title, never assume seniority
    assert res_indet["kinship_name"] == "Anh/Em trai (ruột)"


