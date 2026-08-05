-- ============================================================================
-- SCRIPT THÊM DỮ LIỆU MẪU GIA TỘC & THÀNH VIÊN (MOCK DATA)
-- ============================================================================

-- 1. Tạo 1 Tài khoản người dùng (Account) đóng vai trò là người đã tạo ra dòng họ
INSERT INTO accounts (id, firebase_uid, email, phone_e164, display_name, password_hash, status)
VALUES (
    '9b8c7d6e-5f4a-3b2c-1d0e-f1a2b3c4d5e6', 
    'mock_firebase_uid_123456', 
    'trung.nguyen@example.com', 
    '0912345678', 
    'Nguyễn Khắc Trung', 
    '$2b$12$fmoyqA0ljOzb5cE2QqcRsOSfe2MG8UQvU00tMJxnNGaZuwbx6HqLq', -- Mật khẩu tương ứng là 123456
    'active'
) ON CONFLICT (id) DO NOTHING;

-- 2. Tạo Gia tộc
INSERT INTO families (id, name, founder_name, origin_place, status)
VALUES (
    'a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d',
    'Dòng họ Nguyễn Khắc',
    'Nguyễn Khắc Cần',
    'Làng Vẽ, Cổ Nhuế, Từ Liêm, Hà Nội',
    'active'
) ON CONFLICT (id) DO NOTHING;

-- 3. Cấp quyền Trưởng tộc (admin) cho tài khoản đối với dòng họ này
INSERT INTO account_roles (id, account_id, role, family_id, status)
VALUES (
    '8c7d6e5f-4a3b-2c1d-0e9f-8a7b6c5d4e3f',
    '9b8c7d6e-5f4a-3b2c-1d0e-f1a2b3c4d5e6',
    'admin',
    'a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d',
    'active'
) ON CONFLICT (id) DO NOTHING;

-- 4. Tạo các thành viên trong gia tộc (Lưu ý Trung được liên kết với account)
INSERT INTO members (id, family_id, account_id, full_name, gender, birth_date, death_date, is_alive, generation, role, status, father_id, mother_id)
VALUES 
    ('b2c3d4e5-f6a7-8b9c-0d1e-2f3a4b5c6d7e', 'a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d', NULL, 'Nguyễn Khắc Đại', 'male', '1940-02-15', '2015-08-20', FALSE, 1, 'admin', 'active', NULL, NULL),
    ('c3d4e5f6-a7b8-9c0d-1e2f-3a4b5c6d7e8f', 'a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d', NULL, 'Trần Thị Thu Hạnh', 'female', '1945-10-10', NULL, TRUE, 1, 'member', 'active', NULL, NULL),
    ('d4e5f6a7-b8c9-0d1e-2f3a-4b5c6d7e8f9a', 'a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d', '9b8c7d6e-5f4a-3b2c-1d0e-f1a2b3c4d5e6', 'Nguyễn Khắc Trung', 'male', '1970-05-20', NULL, TRUE, 2, 'manager', 'active', 'b2c3d4e5-f6a7-8b9c-0d1e-2f3a4b5c6d7e', 'c3d4e5f6-a7b8-9c0d-1e2f-3a4b5c6d7e8f'),
    ('e5f6a7b8-c9d0-1e2f-3a4b-5c6d7e8f9a0b', 'a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d', NULL, 'Nguyễn Khắc Kiên', 'male', '1998-11-05', NULL, TRUE, 3, 'member', 'active', 'd4e5f6a7-b8c9-0d1e-2f3a-4b5c6d7e8f9a', NULL)
ON CONFLICT (id) DO NOTHING;

-- 5. Liên kết Vợ - Chồng
INSERT INTO unions (id, family_id, marriage_date, status)
VALUES ('f6a7b8c9-d0e1-2f3a-4b5c-6d7e8f9a0b1c', 'a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d', '1965-02-14', 'married')
ON CONFLICT (id) DO NOTHING;

INSERT INTO union_members (id, union_id, member_id, spouse_role)
VALUES 
    ('0a1b2c3d-4e5f-6a7b-8c9d-0e1f2a3b4c5d', 'f6a7b8c9-d0e1-2f3a-4b5c-6d7e8f9a0b1c', 'b2c3d4e5-f6a7-8b9c-0d1e-2f3a4b5c6d7e', 'husband'),
    ('1b2c3d4e-5f6a-7b8c-9d0e-1f2a3b4c5d6e', 'f6a7b8c9-d0e1-2f3a-4b5c-6d7e8f9a0b1c', 'c3d4e5f6-a7b8-9c0d-1e2f-3a4b5c6d7e8f', 'wife')
ON CONFLICT (id) DO NOTHING;

-- 6. Liên kết Cha Mẹ - Con cái
INSERT INTO parent_child_relationships (id, parent_member_id, child_member_id, relation_type)
VALUES 
    ('2c3d4e5f-6a7b-8c9d-0e1f-2a3b4c5d6e7f', 'b2c3d4e5-f6a7-8b9c-0d1e-2f3a4b5c6d7e', 'd4e5f6a7-b8c9-0d1e-2f3a-4b5c6d7e8f9a', 'biological'),
    ('3d4e5f6a-7b8c-9d0e-1f2a-3b4c5d6e7f8a', 'c3d4e5f6-a7b8-9c0d-1e2f-3a4b5c6d7e8f', 'd4e5f6a7-b8c9-0d1e-2f3a-4b5c6d7e8f9a', 'biological'),
    ('4e5f6a7b-8c9d-0e1f-2a3b-4c5d6e7f8a9b', 'd4e5f6a7-b8c9-0d1e-2f3a-4b5c6d7e8f9a', 'e5f6a7b8-c9d0-1e2f-3a4b-5c6d7e8f9a0b', 'biological')
ON CONFLICT (id) DO NOTHING;

-- 7. Cập nhật thêm thông tin JSON cho Trung (Tiểu sử, Học vấn, v.v.)
UPDATE members SET 
    occupation = 'Giám đốc Công nghệ (CTO)',
    education = 'Thạc sĩ Khoa học Máy tính',
    bio = 'Là người đam mê công nghệ, hiện đang làm việc tại một công ty công nghệ lớn. Luôn hướng về gia đình và nguồn cội.',
    career_history = '[{"company": "Google", "role": "Senior Software Engineer", "year": "2010-2015"}, {"company": "Tech Startup", "role": "CTO", "year": "2015-Nay"}]'::json,
    contribution = '{"financial": 50000000, "events": ["Tổ chức Giỗ tổ 2025", "Tài trợ tu sửa từ đường"]}'::json
WHERE id = 'd4e5f6a7-b8c9-0d1e-2f3a-4b5c6d7e8f9a';

-- 8. Thông tin liên hệ (member_contacts)
INSERT INTO member_contacts (id, member_id, contact_type, contact_value, is_primary, is_public, notes)
VALUES 
    ('c1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c61', 'd4e5f6a7-b8c9-0d1e-2f3a-4b5c6d7e8f9a', 'phone', '0912345678', TRUE, TRUE, 'Số điện thoại chính'),
    ('c1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c62', 'd4e5f6a7-b8c9-0d1e-2f3a-4b5c6d7e8f9a', 'email', 'trung.nguyen@example.com', TRUE, TRUE, 'Email công việc'),
    ('c1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c63', 'd4e5f6a7-b8c9-0d1e-2f3a-4b5c6d7e8f9a', 'address', 'Quận 1, TP. Hồ Chí Minh', FALSE, TRUE, 'Địa chỉ hiện tại')
ON CONFLICT (id) DO NOTHING;

-- 9. Hình ảnh cá nhân (member_media)
INSERT INTO member_media (id, member_id, media_type, media_url, caption, sort_order)
VALUES 
    ('m1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c61', 'd4e5f6a7-b8c9-0d1e-2f3a-4b5c6d7e8f9a', 'image', 'https://i.imgur.com/3YQ2cEw.jpeg', 'Ảnh chụp tại lễ hội mùa xuân', 1),
    ('m1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c62', 'd4e5f6a7-b8c9-0d1e-2f3a-4b5c6d7e8f9a', 'image', 'https://i.imgur.com/7YQ2cEw.jpeg', 'Tham dự hội thảo công nghệ', 2)
ON CONFLICT (id) DO NOTHING;

-- 10. Sự kiện đời người (member_life_events)
INSERT INTO member_life_events (id, member_id, event_type, title, event_date, description, location)
VALUES 
    ('e1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c61', 'd4e5f6a7-b8c9-0d1e-2f3a-4b5c6d7e8f9a', 'education', 'Tốt nghiệp Đại học Bách Khoa', '1992-07-15', 'Tốt nghiệp loại Giỏi ngành CNTT', 'Hà Nội'),
    ('e1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c62', 'd4e5f6a7-b8c9-0d1e-2f3a-4b5c6d7e8f9a', 'career', 'Trở thành CTO', '2015-05-01', 'Bắt đầu đảm nhận vị trí Giám đốc công nghệ tại công ty hiện tại', 'TP.HCM')
ON CONFLICT (id) DO NOTHING;

-- 11. Kỹ năng / Năng lực (skills & member_skills)
INSERT INTO skills (id, name, category) VALUES 
    ('s1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c61', 'Lập trình', 'Công nghệ'),
    ('s1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c62', 'Quản lý dự án', 'Kinh doanh')
ON CONFLICT (id) DO NOTHING;

INSERT INTO member_skills (id, member_id, skill_id, proficiency_level)
VALUES 
    ('msb2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c61', 'd4e5f6a7-b8c9-0d1e-2f3a-4b5c6d7e8f9a', 's1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c61', 'expert'),
    ('msb2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c62', 'd4e5f6a7-b8c9-0d1e-2f3a-4b5c6d7e8f9a', 's1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c62', 'advanced')
ON CONFLICT (id) DO NOTHING;
