class KinshipService:
    """
    Service for Kinship Naming.
    Rule-based algorithm mapping from Raw Descriptors to Vietnamese titles.
    Deterministic and consistent with the defined kinship rules.
    """

    # Dictionary Map mapping (Pattern, Gender) -> Kinship Name
    KINSHIP_RULES = {
        ("ANCESTOR", "M"): "Cha/Ông/Cụ (Tổ tiên Nam)",
        ("ANCESTOR", "F"): "Mẹ/Bà/Cụ (Tổ tiên Nữ)",
        
        ("DESCENDANT", "M"): "Con/Cháu/Chắt (Hậu duệ Nam)",
        ("DESCENDANT", "F"): "Con/Cháu/Chắt (Hậu duệ Nữ)",
        
        ("SIBLING", "M"): "Anh/Em trai",
        ("SIBLING", "F"): "Chị/Em gái",
        
        ("UNCLE_AUNT", "M"): "Bác/Chú/Cậu",
        ("UNCLE_AUNT", "F"): "Bác/Cô/Dì",
        
        ("NIECE_NEPHEW", "M"): "Cháu trai (gọi bằng Chú/Bác)",
        ("NIECE_NEPHEW", "F"): "Cháu gái (gọi bằng Chú/Bác)",
        
        ("COUSIN", "M"): "Anh/Em họ (Nam)",
        ("COUSIN", "F"): "Chị/Em họ (Nữ)",
        
        ("SPOUSE", "M"): "Chồng",
        ("SPOUSE", "F"): "Vợ",
    }

    @staticmethod
    def determine_kinship_name(relation_pattern: str, target_gender: str, depth_target: int = 1) -> str:
        """
        Dịch pattern thành danh xưng.
        Có thể kết hợp thêm depth_target để phân giải chi tiết hơn (VD: depth=1 -> Cha, depth=2 -> Ông).
        """
        # Logic phân giải chi tiết cho ANCESTOR / DESCENDANT dựa vào depth
        if relation_pattern == "ANCESTOR":
            if depth_target == 1: return "Cha" if target_gender == "M" else "Mẹ"
            if depth_target == 2: return "Ông" if target_gender == "M" else "Bà"
            if depth_target == 3: return "Cụ Ông" if target_gender == "M" else "Cụ Bà"
            
        if relation_pattern == "DESCENDANT":
            if depth_target == 1: return "Con Trai" if target_gender == "M" else "Con Gái"
            if depth_target == 2: return "Cháu Trai" if target_gender == "M" else "Cháu Gái"

        # Lookup cơ bản từ Map cho các Pattern còn lại
        return KinshipService.KINSHIP_RULES.get((relation_pattern, target_gender), "Họ Hàng Xa")
