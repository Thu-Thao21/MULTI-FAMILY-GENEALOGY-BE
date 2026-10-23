"""Service for Ego-centric / Focus View.
Uses BFS (Breadth-First Search) with a depth limit to discover relatives and edges
around an Ego node in the genealogy graph.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Dict, List, Set, Tuple


class FocusViewService:
    @staticmethod
    def extract_focus_subgraph(
        ego_id: str,
        relationships: List[Any],
        max_depth: int = 2,
    ) -> Dict[str, Any]:
        """Extracts the subgraph of nodes and edges within `max_depth` edges of `ego_id`.

        Returns:
            {
                "node_depths": {person_id: depth_from_ego},
                "edges": list_of_included_relationships
            }
        """
        ego_id = str(ego_id)

        # 1. Build undirected adjacency list
        adj_list: Dict[str, List[Tuple[str, Any]]] = {}
        for rel in relationships:
            p1 = str(getattr(rel, "from_member_id", None) or rel.get("from_member_id") or rel.get("person_1"))
            p2 = str(getattr(rel, "to_member_id", None) or rel.get("to_member_id") or rel.get("person_2"))

            if not p1 or not p2:
                continue

            if p1 not in adj_list:
                adj_list[p1] = []
            if p2 not in adj_list:
                adj_list[p2] = []

            adj_list[p1].append((p2, rel))
            adj_list[p2].append((p1, rel))

        # 2. BFS from ego_id up to max_depth
        node_depths: Dict[str, int] = {ego_id: 0}
        queue: deque[Tuple[str, int]] = deque([(ego_id, 0)])

        while queue:
            curr_id, depth = queue.popleft()

            if depth < max_depth:
                for neighbor_id, rel in adj_list.get(curr_id, []):
                    if neighbor_id not in node_depths:
                        node_depths[neighbor_id] = depth + 1
                        queue.append((neighbor_id, depth + 1))

        # 3. Collect all edges between any two nodes in node_depths
        subgraph_nodes = set(node_depths.keys())
        included_edges: List[Any] = []
        seen_edge_ids: Set[str] = set()

        for rel in relationships:
            p1 = str(getattr(rel, "from_member_id", None) or rel.get("from_member_id") or rel.get("person_1"))
            p2 = str(getattr(rel, "to_member_id", None) or rel.get("to_member_id") or rel.get("person_2"))
            edge_id = str(getattr(rel, "id", None) or f"{p1}_{p2}")

            if p1 in subgraph_nodes and p2 in subgraph_nodes:
                if edge_id not in seen_edge_ids:
                    seen_edge_ids.add(edge_id)
                    included_edges.append(rel)

        return {
            "node_depths": node_depths,
            "edges": included_edges,
        }
