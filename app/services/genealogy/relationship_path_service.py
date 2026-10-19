"""Service for finding Relationship Paths.
Uses BFS shortest path on the relationship graph with edge tracking.
Optimized to prioritize direct lineage (Parent-Child) when path lengths are equal.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Dict, List, Optional, Tuple


class RelationshipPathService:
    @staticmethod
    def find_path(
        start_id: str,
        target_id: str,
        relationships: List[Any],
    ) -> Optional[Tuple[List[str], List[Any]]]:
        """Finds the shortest relationship path between two person IDs.

        Returns (path_person_ids, path_relationships) or None if no path exists.
        """
        start_id = str(start_id)
        target_id = str(target_id)

        if start_id == target_id:
            return ([start_id], [])

        # Build adjacency list: node_id -> list of (neighbor_id, relationship_obj)
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

        if start_id not in adj_list or target_id not in adj_list:
            return None

        # Sort neighbors so PARENT_CHILD edges are explored before SPOUSE
        for node in adj_list:
            adj_list[node].sort(
                key=lambda item: 0 if getattr(item[1], "relationship_type", "").upper() == "PARENT_CHILD" else 1
            )

        # BFS queue storing (current_node, [nodes_in_path], [edges_in_path])
        queue: deque[Tuple[str, List[str], List[Any]]] = deque([(start_id, [start_id], [])])
        visited = {start_id}

        while queue:
            curr_id, path_nodes, path_edges = queue.popleft()

            if curr_id == target_id:
                return (path_nodes, path_edges)

            for neighbor_id, rel in adj_list.get(curr_id, []):
                if neighbor_id not in visited:
                    visited.add(neighbor_id)
                    queue.append((
                        neighbor_id,
                        path_nodes + [neighbor_id],
                        path_edges + [rel],
                    ))

        return None
