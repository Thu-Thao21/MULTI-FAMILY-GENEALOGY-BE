"""Service for Kinship Naming.
Determines deterministic Vietnamese kinship terms and forms of address
between two persons in the genealogy tree.
"""

from __future__ import annotations

from typing import Any, List, Optional


class KinshipService:
    @staticmethod
    def _compare_age_and_order(p1: Any, p2: Any) -> Optional[int]:
        """Safely compares age between p1 and p2 using verified birth dates or birth orders.

        Returns:
            -1 if p1 is older (born earlier) than p2 (i.e. p2 is younger)
            +1 if p1 is younger (born later) than p2 (i.e. p2 is older)
             0 if strictly the same date and no order differentiation
            None if indeterminate (missing date, invalid date format, or no verified order)
        """
        bo1 = getattr(p1, "birth_order", None)
        bo2 = getattr(p2, "birth_order", None)

        b1_raw = getattr(p1, "birth_date", None)
        b2_raw = getattr(p2, "birth_date", None)

        if b1_raw and b2_raw:
            try:
                s1 = str(b1_raw).strip()[:10]
                s2 = str(b2_raw).strip()[:10]
                # Validate date string format (YYYY or YYYY-MM-DD)
                if len(s1) >= 4 and len(s2) >= 4 and s1[:4].isdigit() and s2[:4].isdigit():
                    if s1 < s2:
                        return -1  # p1 born earlier (older)
                    elif s1 > s2:
                        return 1   # p1 born later (younger)
                    else:
                        # Identical date: check birth_order if available
                        if bo1 is not None and bo2 is not None and bo1 != bo2:
                            return -1 if bo1 < bo2 else 1
                        return 0  # strictly same date
            except Exception:
                pass

        if bo1 is not None and bo2 is not None and bo1 != bo2:
            return -1 if bo1 < bo2 else 1

        return None

    @classmethod
    def calculate_kinship(
        cls,
        from_person: Any,
        to_person: Any,
        path: List[Any],
        edges: List[Any],
        sibling_type: Optional[str] = None,
    ) -> dict[str, Any]:
        """Calculates kinship name, address title, and description between two persons.

        from_person: The person viewing / calling.
        to_person: The person being referred to.
        path: List of persons from start to target.
        edges: List of relationships linking the path.
        sibling_type: Optional 'FULL', 'HALF_PATERNAL', 'HALF_MATERNAL' override.
        """
        if str(from_person.id) == str(to_person.id):
            return {
                "kinship_name": "Chính mình",
                "address_title": "Tôi",
                "description": "Hai đối tượng được chọn là cùng một người.",
            }

        target_gender = (getattr(to_person, "gender", None) or "unknown").lower()
        is_male = target_gender in ("male", "nam", "m")
        is_female = target_gender in ("female", "nu", "nữ", "f")

        gen_from = getattr(from_person, "generation", 1) or 1
        gen_to = getattr(to_person, "generation", 1) or 1
        delta_gen = gen_to - gen_from  # positive if to_person is lower generation (child/grandchild)

        # 1. Direct spouse check
        if len(path) == 2 and any(getattr(e, "relationship_type", "").upper() == "SPOUSE" for e in edges):
            if is_male:
                return {
                    "kinship_name": "Chồng",
                    "address_title": "Chồng (Mình xưng Vợ)",
                    "description": "Quan hệ vợ chồng hôn phối trực tiếp.",
                }
            return {
                "kinship_name": "Vợ",
                "address_title": "Vợ (Mình xưng Chồng)",
                "description": "Quan hệ vợ chồng hôn phối trực tiếp.",
            }

        # Check if direct ancestor or descendant
        # All edges must be PARENT_CHILD
        all_parent_child = all(
            getattr(e, "relationship_type", "").upper() == "PARENT_CHILD" for e in edges
        )

        if all_parent_child:
            # Check direction: from_person is ancestor of to_person
            is_descendant = True
            for i in range(len(path) - 1):
                p1, p2 = str(path[i].id), str(path[i + 1].id)
                # p1 should be parent of p2
                if not any(
                    str(getattr(e, "from_member_id", "")) == p1
                    and str(getattr(e, "to_member_id", "")) == p2
                    for e in edges
                ):
                    is_descendant = False
                    break

            if is_descendant:
                depth = len(path) - 1
                if depth == 1:
                    title = "Con trai" if is_male else ("Con gái" if is_female else "Con")
                    address = f"{title} (Tôi xưng Cha/Mẹ)"
                elif depth == 2:
                    title = "Cháu trai" if is_male else ("Cháu gái" if is_female else "Cháu")
                    address = f"{title} (Tôi xưng Ông/Bà)"
                elif depth == 3:
                    title = "Chắt trai" if is_male else ("Chắt gái" if is_female else "Chắt")
                    address = f"{title} (Tôi xưng Cụ)"
                elif depth == 4:
                    title = "Chút"
                    address = "Chút (Tôi xưng Kỵ)"
                else:
                    title = f"Hậu duệ đời thứ {depth}"
                    address = f"Hậu duệ (Tôi xưng Tổ tiên)"
                return {
                    "kinship_name": title,
                    "address_title": address,
                    "description": f"Quan hệ trực hệ hậu duệ cách {depth} thế hệ.",
                }

            # Check direction: to_person is ancestor of from_person
            is_ancestor = True
            for i in range(len(path) - 1):
                p1, p2 = str(path[i].id), str(path[i + 1].id)
                # p2 should be parent of p1 (going backwards up)
                if not any(
                    str(getattr(e, "from_member_id", "")) == p2
                    and str(getattr(e, "to_member_id", "")) == p1
                    for e in edges
                ):
                    is_ancestor = False
                    break

            if is_ancestor:
                depth = len(path) - 1
                if depth == 1:
                    title = "Cha" if is_male else ("Mẹ" if is_female else "Cha/Mẹ")
                    address = f"{title} (Tôi xưng Con)"
                elif depth == 2:
                    title = "Ông" if is_male else ("Bà" if is_female else "Ông/Bà")
                    address = f"{title} (Tôi xưng Cháu)"
                elif depth == 3:
                    title = "Cụ Ông" if is_male else ("Cụ Bà" if is_female else "Cụ")
                    address = f"{title} (Tôi xưng Chắt)"
                elif depth == 4:
                    title = "Kỵ Ông" if is_male else ("Kỵ Bà" if is_female else "Kỵ")
                    address = f"{title} (Tôi xưng Chút)"
                else:
                    title = f"Tổ tiên ({depth} đời trước)"
                    address = f"Tổ tiên (Tôi xưng Con cháu)"
                return {
                    "kinship_name": title,
                    "address_title": address,
                    "description": f"Quan hệ trực hệ tổ tiên cách {depth} thế hệ.",
                }

        # Sibling check: Path length 3 (Child -> Parent -> Sibling)
        if len(path) == 3 and delta_gen == 0:
            from_gender = (getattr(from_person, "gender", None) or "").lower()
            from_is_male = from_gender in ("male", "nam", "m")

            # Determine sibling relation category:
            # 1. Full sibling: 'ruột (cùng cha cùng mẹ)'
            # 2. Half-paternal: 'cùng cha khác mẹ'
            # 3. Half-maternal: 'cùng mẹ khác cha'
            stype = (sibling_type or "").upper()
            if not stype:
                notes = [str(getattr(e, "notes", "") or "") for e in edges]
                combined_notes = " ".join(notes).upper()
                if "KHAC_ME" in combined_notes or "CUNG_CHA_KHAC_ME" in combined_notes or "HALF_PATERNAL" in combined_notes:
                    stype = "HALF_PATERNAL"
                elif "KHAC_CHA" in combined_notes or "CUNG_ME_KHAC_CHA" in combined_notes or "HALF_MATERNAL" in combined_notes:
                    stype = "HALF_MATERNAL"
                else:
                    stype = "FULL"

            if stype == "HALF_PATERNAL":
                label_suffix = "cùng cha khác mẹ"
                desc = "Quan hệ anh chị em cùng cha khác mẹ."
            elif stype == "HALF_MATERNAL":
                label_suffix = "cùng mẹ khác cha"
                desc = "Quan hệ anh chị em cùng mẹ khác cha."
            else:
                label_suffix = "ruột"
                desc = "Quan hệ anh chị em ruột cùng cha mẹ."

            age_cmp = cls._compare_age_and_order(from_person, to_person)

            if age_cmp == 1:
                # to_person is older than from_person
                title = f"Anh {label_suffix}" if is_male else (f"Chị {label_suffix}" if is_female else f"Anh/Chị {label_suffix}")
                address = f"{title} (Tôi xưng Em)"
                reciprocal_kinship = f"Em trai {label_suffix}" if from_is_male else f"Em gái {label_suffix}"
                reciprocal_address = f"{reciprocal_kinship} (Tôi xưng {'Anh' if is_male else 'Chị'})"
            elif age_cmp == -1:
                # to_person is younger than from_person
                title = f"Em trai {label_suffix}" if is_male else (f"Em gái {label_suffix}" if is_female else f"Em {label_suffix}")
                address = f"{title} (Tôi xưng {'Anh' if from_is_male else 'Chị'})"
                reciprocal_kinship = f"Anh {label_suffix}" if from_is_male else f"Chị {label_suffix}"
                reciprocal_address = f"{reciprocal_kinship} (Tôi xưng Em)"
            else:
                # Same date or indeterminate: neutral title, never assume seniority
                if is_male:
                    title = f"Anh/Em trai ({label_suffix})"
                    address = f"Anh/Em trai ({label_suffix})"
                elif is_female:
                    title = f"Chị/Em gái ({label_suffix})"
                    address = f"Chị/Em gái ({label_suffix})"
                else:
                    title = f"Anh/Chị/Em ({label_suffix})"
                    address = f"Anh/Chị/Em ({label_suffix})"
                reciprocal_kinship = title
                reciprocal_address = address
                if age_cmp == 0:
                    desc += " (Cùng ngày sinh/sinh đôi, thứ bậc ngang hàng)."

            return {
                "kinship_name": title,
                "address_title": address,
                "reciprocal_kinship": reciprocal_kinship,
                "reciprocal_address": reciprocal_address,
                "description": desc,
            }

        # Uncle / Aunt check: delta_gen == -1 (to_person is 1 generation older than from_person)
        if delta_gen == -1:
            # Check if through Father or Mother
            parent_in_path = path[1] if len(path) > 1 else None
            parent_gender = (getattr(parent_in_path, "gender", "") or "").lower() if parent_in_path else ""
            is_through_father = parent_gender in ("male", "nam", "m")
            is_through_mother = parent_gender in ("female", "nu", "nữ", "f")

            if is_through_father:
                parent_birth = getattr(parent_in_path, "birth_date", None)
                target_birth = getattr(to_person, "birth_date", None)
                if is_male:
                    if parent_birth and target_birth:
                        title = "Bác trai" if target_birth < parent_birth else "Chú"
                    else:
                        title = "Bác trai / Chú"
                    address = f"{title} (Tôi xưng Cháu)"
                elif is_female:
                    title = "Cô / Bác gái"
                    address = f"{title} (Tôi xưng Cháu)"
                else:
                    title = "Bác / Chú / Cô"
                    address = f"{title} (Tôi xưng Cháu)"
            elif is_through_mother:
                if is_male:
                    title = "Cậu / Bác trai"
                    address = f"{title} (Tôi xưng Cháu)"
                elif is_female:
                    title = "Dì / Bác gái"
                    address = f"{title} (Tôi xưng Cháu)"
                else:
                    title = "Cậu / Dì"
                    address = f"{title} (Tôi xưng Cháu)"
            else:
                if is_male:
                    title = "Bác / Chú / Cậu"
                    address = "Bác / Chú / Cậu (Tôi xưng Cháu)"
                elif is_female:
                    title = "Bác / Cô / Dì"
                    address = "Bác / Cô / Dì (Tôi xưng Cháu)"
                else:
                    title = "Bác / Chú / Cô / Cậu / Dì"
                    address = "Bác / Chú / Cô (Tôi xưng Cháu)"

            from_gender = (getattr(from_person, "gender", None) or "").lower()
            ch_title = "Cháu trai" if from_gender in ("male", "nam", "m") else "Cháu gái"
            return {
                "kinship_name": title,
                "address_title": address,
                "reciprocal_kinship": ch_title,
                "reciprocal_address": f"{ch_title} (Tôi xưng {title.split(' ')[0]})",
                "description": f"Quan hệ chú/bác/cô/dì/cậu bề trên ({len(path) - 1} bước kết nối).",
            }

        # Nephew / Niece check: delta_gen == 1 (to_person is 1 generation younger)
        if delta_gen == 1:
            title = "Cháu trai" if is_male else ("Cháu gái" if is_female else "Cháu")
            from_gender = (getattr(from_person, "gender", None) or "").lower()
            from_title = "Bác/Chú" if from_gender in ("male", "nam", "m") else "Cô/Dì/Bác"
            address = f"{title} (Tôi xưng {from_title})"
            return {
                "kinship_name": title,
                "address_title": address,
                "reciprocal_kinship": from_title,
                "reciprocal_address": f"{from_title} (Tôi xưng {title})",
                "description": f"Quan hệ cháu gọi bằng chú/bác/cô/dì/cậu ({len(path) - 1} bước kết nối).",
            }

        # Cousin check: delta_gen == 0
        if delta_gen == 0:
            from_gender = (getattr(from_person, "gender", None) or "").lower()
            from_is_male = from_gender in ("male", "nam", "m")

            age_cmp = cls._compare_age_and_order(from_person, to_person)

            if age_cmp == 1:
                title = "Anh họ" if is_male else ("Chị họ" if is_female else "Anh/Chị họ")
                address = f"{title} (Tôi xưng Em)"
                rec_k = "Em họ"
                rec_a = f"Em họ (Tôi xưng {'Anh' if is_male else 'Chị'})"
            elif age_cmp == -1:
                title = "Em trai họ" if is_male else ("Em gái họ" if is_female else "Em họ")
                address = f"{title} (Tôi xưng {'Anh' if from_is_male else 'Chị'})"
                rec_k = "Anh họ" if from_is_male else "Chị họ"
                rec_a = f"{rec_k} (Tôi xưng Em)"
            else:
                title = "Anh/Em họ" if is_male else ("Chị/Em họ" if is_female else "Anh/Chị/Em họ")
                address = f"{title} đồng thế hệ"
                rec_k = "Anh/Chị/Em họ"
                rec_a = "Anh/Chị/Em họ"

            return {
                "kinship_name": title,
                "address_title": address,
                "reciprocal_kinship": rec_k,
                "reciprocal_address": rec_a,
                "description": f"Quan hệ anh em họ cùng thế hệ ({len(path) - 1} bước kết nối).",
            }

        # Grand-uncle or Grand-aunt / Grand-nephew
        if delta_gen == -2:
            title = "Ông Bác / Ông Chú / Bà Cô" if is_male else "Bà Bác / Bà Dì / Bà Cô"
            return {
                "kinship_name": title,
                "address_title": f"{title} (Tôi xưng Cháu)",
                "reciprocal_kinship": "Cháu họ",
                "reciprocal_address": "Cháu họ (Tôi xưng Ông/Bà)",
                "description": f"Bề trên cách 2 thế hệ ({len(path) - 1} bước kết nối).",
            }

        if delta_gen == 2:
            title = "Cháu họ đời thứ hai"
            return {
                "kinship_name": title,
                "address_title": "Cháu họ (Tôi xưng Ông/Bà)",
                "reciprocal_kinship": "Ông/Bà họ",
                "reciprocal_address": "Ông/Bà họ (Tôi xưng Cháu)",
                "description": f"Hậu duệ cách 2 thế hệ ({len(path) - 1} bước kết nối).",
            }

        # General distant relative
        if delta_gen < 0:
            title = f"Bề trên (cách {abs(delta_gen)} thế hệ)"
            address = f"Cụ/Tổ tiên họ hàng (Tôi xưng Hậu duệ)"
            rec_k = f"Hậu duệ (cách {abs(delta_gen)} thế hệ)"
            rec_a = "Hậu duệ (Tôi xưng Bề trên)"
        else:
            title = f"Hậu duệ (cách {delta_gen} thế hệ)"
            address = f"Hậu duệ (Tôi xưng Bề trên)"
            rec_k = f"Bề trên (cách {delta_gen} thế hệ)"
            rec_a = "Cụ/Tổ tiên họ hàng (Tôi xưng Hậu duệ)"

        return {
            "kinship_name": title,
            "address_title": address,
            "reciprocal_kinship": rec_k,
            "reciprocal_address": rec_a,
            "description": f"Quan hệ họ hàng qua {len(path) - 1} bước trung gian.",
        }
