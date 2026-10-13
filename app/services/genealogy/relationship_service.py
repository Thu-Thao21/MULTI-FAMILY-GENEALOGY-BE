from typing import List, Dict, Any, Optional

class RelationshipService:
    """
    Service for Relationship Calculation.
    Uses Lowest Common Ancestor (LCA) and closure table to output Raw Descriptors.
    """

    @staticmethod
    def calculate_lca_relationship(person_a_id: str, person_b_id: str, closure_table: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Tìm Tổ tiên chung gần nhất (LCA) và xác định Pattern quan hệ cơ bản.
        """
        a_ancestors = {row["ancestor_id"]: row["depth"] for row in closure_table if row["descendant_id"] == person_a_id}
        b_ancestors = {row["ancestor_id"]: row["depth"] for row in closure_table if row["descendant_id"] == person_b_id}
                
        common_ancestors = set(a_ancestors.keys()).intersection(set(b_ancestors.keys()))
        
        if not common_ancestors:
            return None
            
        best_lca = None
        min_total_depth = float('inf')
        
        for anc in common_ancestors:
            total_depth = a_ancestors[anc] + b_ancestors[anc]
            if total_depth < min_total_depth:
                min_total_depth = total_depth
                best_lca = anc
                
        depth_a = a_ancestors[best_lca]
        depth_b = b_ancestors[best_lca]
        
        # Determine Raw Descriptor Pattern
        pattern = "UNKNOWN"
        if depth_a == 0 and depth_b > 0:
            pattern = "DESCENDANT"
        elif depth_b == 0 and depth_a > 0:
            pattern = "ANCESTOR"
        elif depth_a == 1 and depth_b == 1:
            pattern = "SIBLING"
        elif depth_a == 1 and depth_b == 2:
            pattern = "NIECE_NEPHEW"
        elif depth_a == 2 and depth_b == 1:
            pattern = "UNCLE_AUNT"
        elif depth_a == 2 and depth_b == 2:
            pattern = "COUSIN"
                
        return {
            "common_ancestor": best_lca,
            "depth_from_a": depth_a,
            "depth_from_b": depth_b,
            "relation_pattern": pattern
        }
