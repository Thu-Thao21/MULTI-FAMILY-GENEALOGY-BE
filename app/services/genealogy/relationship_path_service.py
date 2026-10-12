from collections import deque
from typing import List, Dict, Any, Optional

class RelationshipPathService:
    """
    Service for finding Relationship Paths.
    Uses BFS shortest path on the relationship graph.
    Memory optimized using parent_map instead of copying path arrays.
    """

    @staticmethod
    def find_shortest_path(start_id: str, target_id: str, relationships: List[Dict[str, Any]]) -> Optional[List[str]]:
        """
        Tìm đường đi ngắn nhất giữa 2 người trên đồ thị.
        
        Args:
            start_id: Điểm bắt đầu (Ego)
            target_id: Điểm cần tìm
            relationships: Danh sách cạnh (có thể query động từ DB sau này)
        """
        if start_id == target_id:
            return [start_id]
            
        # 1. Build adjacency list
        adj_list: Dict[str, List[str]] = {}
        for rel in relationships:
            p1, p2 = rel["person_1"], rel["person_2"]
            if p1 not in adj_list: adj_list[p1] = []
            if p2 not in adj_list: adj_list[p2] = []
            adj_list[p1].append(p2)
            adj_list[p2].append(p1)

        if start_id not in adj_list or target_id not in adj_list:
            return None

        # 2. BFS with parent_map for path reconstruction
        queue = deque([start_id])
        visited = {start_id}
        
        # parent_map[node] = parent_node_that_discovered_it
        parent_map: Dict[str, str] = {start_id: None}
        
        found = False
        while queue:
            current = queue.popleft()
            
            if current == target_id:
                found = True
                break
                
            for neighbor in adj_list.get(current, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    parent_map[neighbor] = current
                    queue.append(neighbor)
                    
        # 3. Reconstruct path by backtracking parent_map
        if not found:
            return None
            
        path = []
        curr = target_id
        while curr is not None:
            path.append(curr)
            curr = parent_map[curr]
            
        # Đảo ngược lại để có thứ tự từ start -> target
        path.reverse()
        return path
