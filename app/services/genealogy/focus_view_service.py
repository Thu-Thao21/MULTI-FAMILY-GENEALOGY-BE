from collections import deque
from typing import List, Dict, Any, Set

class FocusViewService:
    """
    Service for Ego-centric / Focus View.
    Uses BFS (Breadth-First Search) with a depth limit to get relatives around an Ego node.
    """

    @staticmethod
    def get_focus_view(ego_id: str, relationships: List[Dict[str, Any]], max_depth: int = 2) -> Dict[str, Any]:
        """
        Dựng góc nhìn tập trung quanh 1 người (Ego).
        
        Args:
            ego_id: ID của người làm tâm.
            relationships: Danh sách tất cả các mối quan hệ (Mock data).
                           Contract: 
                           {'person_1': parent_id, 'person_2': child_id, 'type': 'PARENT_CHILD'}
                           {'person_1': p1_id, 'person_2': p2_id, 'type': 'SPOUSE'}
                           
            max_depth: Độ sâu tối đa (dựa trên số lượng cạnh).
                       Depth 0: Ego
                       Depth 1: Parent, Spouse, Children
                       Depth 2: Grandparents, Grandchildren, Siblings
                       Depth 3: Uncle, Aunt, Nephew, Niece, Cousin depending on path
                       
        Returns:
            Dict chứa danh sách 'nodes' (các thành viên) và 'edges' (các mối quan hệ giữa họ).
        """
        
        # LƯU Ý KHI RÁP DATABASE (SPRINT 1-2 HOÀN THÀNH):
        # Không nên load toàn bộ data từ DB rồi for loop như cách Mock dưới đây.
        # Thay vào đó, thay đổi luồng BFS:
        # Ở mỗi vòng lặp `while queue:`, gọi Repository để lấy neighbors của `current_id` trực tiếp từ DB.
        # Ví dụ: relatives = repository.get_neighbors(current_id)
        
        # 1. Biểu diễn đồ thị bằng Adjacency List (Danh sách kề) vô hướng
        # adj_list[person_id] = [(related_person_id, relation_type)]
        adj_list: Dict[str, List[Dict[str, Any]]] = {}
        
        for rel in relationships:
            p1 = rel.get("person_1")
            p2 = rel.get("person_2")
            rel_type = rel.get("type")
            
            if p1 not in adj_list:
                adj_list[p1] = []
            if p2 not in adj_list:
                adj_list[p2] = []
                
            # Đồ thị vô hướng: A quan hệ với B thì B cũng quan hệ với A
            adj_list[p1].append({"related_id": p2, "type": rel_type, "direction": "forward"})
            adj_list[p2].append({"related_id": p1, "type": rel_type, "direction": "backward"})

        # Nếu Ego không tồn tại trong tập dữ liệu
        if ego_id not in adj_list and not any(r.get("person_1") == ego_id or r.get("person_2") == ego_id for r in relationships):
             return {"nodes": [{"id": ego_id, "depth": 0}], "edges": []}

        # 2. Thuật toán BFS giới hạn độ sâu (Depth-limited BFS)
        queue = deque([(ego_id, 0)]) # Lưu tuple (person_id, depth)
        visited_nodes: Set[str] = {ego_id}
        
        # Lưu kết quả
        result_nodes: List[Dict[str, Any]] = []
        result_edges: List[Dict[str, Any]] = []
        
        # Dùng set để tránh add trùng cạnh (edge) A-B và B-A
        added_edges = set()

        while queue:
            current_id, depth = queue.popleft()
            
            # Lưu node vào kết quả
            result_nodes.append({
                "id": current_id,
                "depth": depth
            })
            
            # Chỉ lan truyền tiếp nếu chưa đạt max_depth
            if depth < max_depth:
                # Lấy các họ hàng của current_id
                relatives = adj_list.get(current_id, [])
                
                for rel in relatives:
                    neighbor_id = rel["related_id"]
                    
                    # Ghi nhận Edge (Quan hệ)
                    # Sắp xếp id và kèm type để tạo signature duy nhất cho cạnh
                    edge_sig = (*sorted([current_id, neighbor_id]), rel["type"])
                    
                    if edge_sig not in added_edges:
                        added_edges.add(edge_sig)
                        result_edges.append({
                            "source": current_id if rel["direction"] == "forward" else neighbor_id,
                            "target": neighbor_id if rel["direction"] == "forward" else current_id,
                            "type": rel["type"]
                        })

                    # Nếu neighbor chưa được duyệt, đưa vào queue với depth + 1
                    if neighbor_id not in visited_nodes:
                        visited_nodes.add(neighbor_id)
                        queue.append((neighbor_id, depth + 1))

        return {
            "nodes": result_nodes,
            "edges": result_edges
        }

# --- TEST MOCK DATA ---
if __name__ == "__main__":
    # Hardcode Mock Data để test trực tiếp
    # Contract chuẩn: person_1 = Parent, person_2 = Child
    mock_relationships = [
        {"person_1": "Ông Nội", "person_2": "Cha", "type": "PARENT_CHILD"},
        {"person_1": "Bà Nội", "person_2": "Cha", "type": "PARENT_CHILD"},
        {"person_1": "Cha", "person_2": "Ego", "type": "PARENT_CHILD"},
        {"person_1": "Mẹ", "person_2": "Ego", "type": "PARENT_CHILD"},
        {"person_1": "Ego", "person_2": "Vợ", "type": "SPOUSE"},
        {"person_1": "Ego", "person_2": "Con Trai", "type": "PARENT_CHILD"},
        {"person_1": "Ông Nội", "person_2": "Chú", "type": "PARENT_CHILD"},
        {"person_1": "Cha", "person_2": "Anh Trai", "type": "PARENT_CHILD"}, # Anh ruột (Ego -> Cha -> Anh Trai = Depth 2)
    ]
    
    service = FocusViewService()
    
    print("--- TEST EGO-CENTRIC VIEW (DEPTH = 1) ---")
    result_d1 = service.get_focus_view("Ego", mock_relationships, max_depth=1)
    print(f"Nodes (Depth 1): {[n['id'] for n in result_d1['nodes']]}")
    # Kỳ vọng: Parent, Spouse, Children
    # Kết quả: Ego, Cha, Mẹ, Vợ, Con Trai
    
    print("\n--- TEST EGO-CENTRIC VIEW (DEPTH = 2) ---")
    result_d2 = service.get_focus_view("Ego", mock_relationships, max_depth=2)
    print(f"Nodes (Depth 2): {[n['id'] for n in result_d2['nodes']]}")
    # Kỳ vọng: Thêm Grandparents, Siblings
    # Kết quả: Thêm Ông Nội, Bà Nội (từ Cha), Anh Trai (từ Cha)
