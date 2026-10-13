from typing import List, Dict, Any, Set

class TreeService:
    """
    Service for building the genealogy tree.
    Uses DFS (Depth-First Search) to build the full nested tree structure.
    """

    @staticmethod
    def build_full_tree_dfs(root_id: str, persons: List[Dict[str, Any]], relationships: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Dựng cây gia phả đầy đủ (Nested JSON) từ dữ liệu phẳng bằng đệ quy (DFS).
        Có cơ chế chống vòng lặp (Cycle Detection) bằng set visited.
        """
        person_lookup = {p["id"]: p for p in persons}
        
        children_map: Dict[str, List[str]] = {}
        spouses_map: Dict[str, List[str]] = {}
        
        # Build adjacency list
        for rel in relationships:
            p1 = rel.get("person_1")
            p2 = rel.get("person_2")
            rel_type = rel.get("type")
            
            if rel_type == "PARENT_CHILD":
                if p1 not in children_map: children_map[p1] = []
                children_map[p1].append(p2)
            elif rel_type == "SPOUSE":
                if p1 not in spouses_map: spouses_map[p1] = []
                if p2 not in spouses_map: spouses_map[p2] = []
                spouses_map[p1].append(p2)
                spouses_map[p2].append(p1)

        visited: Set[str] = set()

        def dfs_build_node(current_id: str, generation: int) -> Any:
            # Chống vòng lặp vô tận (Cycle detection)
            if current_id in visited:
                return None
            visited.add(current_id)

            node_data = person_lookup.get(current_id, {"id": current_id, "name": "Unknown"})
            
            node_result = {
                "id": current_id,
                "name": node_data.get("name"),
                "generation": generation,
                "attributes": node_data,
                "spouses": [],
                "children": []
            }
            
            for spouse_id in spouses_map.get(current_id, []):
                spouse_data = person_lookup.get(spouse_id, {"id": spouse_id, "name": "Unknown"})
                spouse_data["generation"] = generation
                node_result["spouses"].append(spouse_data)
                
            for child_id in children_map.get(current_id, []):
                child_node = dfs_build_node(child_id, generation + 1)
                if child_node is not None:
                    node_result["children"].append(child_node)
                
            return node_result

        # Thủy Tổ luôn bắt đầu từ Đời 1 (Generation = 1)
        return dfs_build_node(root_id, generation=1)
