-- =============================================================================
-- KỊCH BẢN DỮ LIỆU MẪU THỰC TẾ CHO NEON POSTGRESQL (MFGMS - HỆ THỐNG GIA PHẢ LIÊN HỌ)
-- Ngày tạo: 2026-10-23
-- 4 Email thật của người dùng được phân quyền:
--   1. thangvo250904@gmail.com   -> Võ Trí Thắng (System Admin & Trưởng Tộc Dòng Họ Võ)
--   2. maiphuchau144@gmail.com   -> Mai Phúc Hậu (Trưởng Tộc Dòng Họ Mai)
--   3. huy13052005@gmail.com     -> Nguyễn Gia Huy (Family Admin Chi 1 Dòng Họ Võ)
--   4. quankophaiwibu@gmail.com  -> Trần Minh Quân (Thành viên Dòng họ & Cầu nối liên họ)
--
-- Đặc điểm:
--   - Dùng cú pháp chuẩn PostgreSQL (idempotent: ON CONFLICT DO NOTHING / UPDATE).
--   - Tích hợp 2 Dòng họ thực tế (Họ Võ Đại Tộc & Họ Mai Thế Tộc), 4 thế hệ, thông gia liên họ.
--   - Đầy đủ Thủy tổ, Chi, Nhánh, Vợ/Chồng, Con cái, Closure Table, Liên kết tài khoản.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- 1. ĐẢM BẢO ROLES HỆ THỐNG ĐÃ TỒN TẠI
-- -----------------------------------------------------------------------------
INSERT INTO roles (role_id, code, name, is_system_role)
VALUES 
  ('11111111-0000-0000-0000-000000000001', 'SYSTEM_ADMIN', 'Quản trị hệ thống (System Admin)', true),
  ('11111111-0000-0000-0000-000000000002', 'BUSINESS_OWNER', 'Trưởng tộc / Chủ quản dòng họ (Business Owner)', true),
  ('11111111-0000-0000-0000-000000000003', 'FAMILY_ADMIN', 'Quản trị viên gia tộc (Family Admin)', true),
  ('11111111-0000-0000-0000-000000000004', 'FAMILY_MEMBER', 'Thành viên dòng họ (Member)', true)
ON CONFLICT (code) DO NOTHING;

-- -----------------------------------------------------------------------------
-- 2. TẠO 4 TÀI KHOẢN NGƯỜI DÙNG THẬT (USERS & CREDENTIAL METADATA)
-- -----------------------------------------------------------------------------
-- User 1: thangvo250904@gmail.com (Võ Trí Thắng - System Admin & Trưởng tộc Họ Võ)
INSERT INTO users (
  user_id, firebase_uid, username, email, phone, display_name, status, email_verified, phone_verified, first_login_required, created_at, updated_at
) VALUES (
  'a0000000-0000-0000-0000-000000000001',
  'usr_thangvo250904',
  'thangvo',
  'thangvo250904@gmail.com',
  '0905123456',
  'Võ Trí Thắng',
  'ACTIVE',
  true,
  true,
  false,
  CURRENT_TIMESTAMP,
  CURRENT_TIMESTAMP
) ON CONFLICT (email) DO UPDATE SET 
  display_name = EXCLUDED.display_name,
  status = 'ACTIVE',
  email_verified = true;

-- User 2: maiphuchau144@gmail.com (Mai Phúc Hậu - Trưởng tộc Họ Mai)
INSERT INTO users (
  user_id, firebase_uid, username, email, phone, display_name, status, email_verified, phone_verified, first_login_required, created_at, updated_at
) VALUES (
  'a0000000-0000-0000-0000-000000000002',
  'usr_maiphuchau144',
  'phuchau',
  'maiphuchau144@gmail.com',
  '0914234567',
  'Mai Phúc Hậu',
  'ACTIVE',
  true,
  true,
  false,
  CURRENT_TIMESTAMP,
  CURRENT_TIMESTAMP
) ON CONFLICT (email) DO UPDATE SET 
  display_name = EXCLUDED.display_name,
  status = 'ACTIVE',
  email_verified = true;

-- User 3: huy13052005@gmail.com (Nguyễn Gia Huy - Family Admin Chi 1 Họ Võ)
INSERT INTO users (
  user_id, firebase_uid, username, email, phone, display_name, status, email_verified, phone_verified, first_login_required, created_at, updated_at
) VALUES (
  'a0000000-0000-0000-0000-000000000003',
  'usr_huy13052005',
  'giahuy',
  'huy13052005@gmail.com',
  '0935345678',
  'Nguyễn Gia Huy',
  'ACTIVE',
  true,
  true,
  false,
  CURRENT_TIMESTAMP,
  CURRENT_TIMESTAMP
) ON CONFLICT (email) DO UPDATE SET 
  display_name = EXCLUDED.display_name,
  status = 'ACTIVE',
  email_verified = true;

-- User 4: quankophaiwibu@gmail.com (Trần Minh Quân - Thành viên / Rể kết nối liên họ)
INSERT INTO users (
  user_id, firebase_uid, username, email, phone, display_name, status, email_verified, phone_verified, first_login_required, created_at, updated_at
) VALUES (
  'a0000000-0000-0000-0000-000000000004',
  'usr_quankophaiwibu',
  'minhquan',
  'quankophaiwibu@gmail.com',
  '0978456789',
  'Trần Minh Quân',
  'ACTIVE',
  true,
  true,
  false,
  CURRENT_TIMESTAMP,
  CURRENT_TIMESTAMP
) ON CONFLICT (email) DO UPDATE SET 
  display_name = EXCLUDED.display_name,
  status = 'ACTIVE',
  email_verified = true;

-- Tạo credential_metadata cho 4 tài khoản
INSERT INTO credential_metadata (user_id, auth_provider, must_change_password, failed_login_count, updated_at)
SELECT u.user_id, 'FIREBASE', false, 0, CURRENT_TIMESTAMP
FROM users u
WHERE u.email IN ('thangvo250904@gmail.com', 'maiphuchau144@gmail.com', 'huy13052005@gmail.com', 'quankophaiwibu@gmail.com')
ON CONFLICT (user_id) DO NOTHING;

-- -----------------------------------------------------------------------------
-- 3. TẠO 2 DÒNG HỌ THỰC TẾ (HỌ VÕ ĐẠI TỘC & HỌ MAI THẾ TỘC)
-- -----------------------------------------------------------------------------
-- Clan 1: Họ Võ Đại Tộc (Quảng Nam)
INSERT INTO clans (clan_id, clan_code, name, status, created_by, activated_at, created_at, updated_at)
VALUES (
  'c0000000-0000-0000-0000-000000000001',
  'CLAN-VO-01',
  'Võ Đại Tộc (Gò Nổi - Quảng Nam)',
  'ACTIVE',
  (SELECT user_id FROM users WHERE email = 'thangvo250904@gmail.com'),
  CURRENT_TIMESTAMP,
  CURRENT_TIMESTAMP,
  CURRENT_TIMESTAMP
) ON CONFLICT (clan_code) DO NOTHING;

INSERT INTO clan_profiles (clan_id, origin_place, history, ancestral_house_address, public_description, updated_at)
VALUES (
  'c0000000-0000-0000-0000-000000000001',
  'Gò Nổi, Huyện Điện Bàn, Tỉnh Quảng Nam',
  'Dòng họ Võ Đại Tộc khai canh từ thế kỷ 18, có truyền thống khoa bảng, hiếu học và đoàn kết.',
  'Số 12 Đường Hùng Vương, TX Điện Bàn, Quảng Nam',
  'Gia phả chính thống Họ Võ Đại Tộc - kết nối các chi nhánh trong và ngoài nước.',
  CURRENT_TIMESTAMP
) ON CONFLICT (clan_id) DO NOTHING;

-- Clan 2: Họ Mai Thế Tộc (Huế)
INSERT INTO clans (clan_id, clan_code, name, status, created_by, activated_at, created_at, updated_at)
VALUES (
  'c0000000-0000-0000-0000-000000000002',
  'CLAN-MAI-02',
  'Mai Thế Tộc (Phong Điền - Thừa Thiên Huế)',
  'ACTIVE',
  (SELECT user_id FROM users WHERE email = 'maiphuchau144@gmail.com'),
  CURRENT_TIMESTAMP,
  CURRENT_TIMESTAMP,
  CURRENT_TIMESTAMP
) ON CONFLICT (clan_code) DO NOTHING;

INSERT INTO clan_profiles (clan_id, origin_place, history, ancestral_house_address, public_description, updated_at)
VALUES (
  'c0000000-0000-0000-0000-000000000002',
  'Phong Điền, Tỉnh Thừa Thiên Huế',
  'Mai Thế Tộc gốc Cố đô Huế, gìn giữ gia phong và nề nếp gia giáo qua nhiều thế hệ.',
  'Làng Cổ Phước Tích, Huyện Phong Điền, Thừa Thiên Huế',
  'Gia phả Họ Mai Thế Tộc - Nơi lưu giữ nguồn cội và kết nối anh em dòng tộc.',
  CURRENT_TIMESTAMP
) ON CONFLICT (clan_id) DO NOTHING;

-- -----------------------------------------------------------------------------
-- 4. PHÂN QUYỀN VAI TRÒ (USER ROLES & CLAN MEMBERSHIPS)
-- -----------------------------------------------------------------------------
-- Võ Trí Thắng: System Admin toàn hệ thống
INSERT INTO user_roles (user_role_id, user_id, role_id, clan_id, granted_by)
SELECT 
  gen_random_uuid(),
  u.user_id,
  r.role_id,
  NULL,
  u.user_id
FROM users u, roles r
WHERE u.email = 'thangvo250904@gmail.com' AND r.code = 'SYSTEM_ADMIN'
ON CONFLICT DO NOTHING;

-- Võ Trí Thắng: Trưởng Tộc Họ Võ
INSERT INTO user_roles (user_role_id, user_id, role_id, clan_id, granted_by)
SELECT 
  gen_random_uuid(),
  u.user_id,
  r.role_id,
  'c0000000-0000-0000-0000-000000000001',
  u.user_id
FROM users u, roles r
WHERE u.email = 'thangvo250904@gmail.com' AND r.code = 'BUSINESS_OWNER'
ON CONFLICT DO NOTHING;

-- Mai Phúc Hậu: Trưởng Tộc Họ Mai
INSERT INTO user_roles (user_role_id, user_id, role_id, clan_id, granted_by)
SELECT 
  gen_random_uuid(),
  u.user_id,
  r.role_id,
  'c0000000-0000-0000-0000-000000000002',
  (SELECT user_id FROM users WHERE email = 'thangvo250904@gmail.com')
FROM users u, roles r
WHERE u.email = 'maiphuchau144@gmail.com' AND r.code = 'BUSINESS_OWNER'
ON CONFLICT DO NOTHING;

-- Nguyễn Gia Huy: Family Admin Họ Võ
INSERT INTO user_roles (user_role_id, user_id, role_id, clan_id, granted_by)
SELECT 
  gen_random_uuid(),
  u.user_id,
  r.role_id,
  'c0000000-0000-0000-0000-000000000001',
  (SELECT user_id FROM users WHERE email = 'thangvo250904@gmail.com')
FROM users u, roles r
WHERE u.email = 'huy13052005@gmail.com' AND r.code = 'FAMILY_ADMIN'
ON CONFLICT DO NOTHING;

-- Trần Minh Quân: Thành viên (Member) Họ Võ
INSERT INTO user_roles (user_role_id, user_id, role_id, clan_id, granted_by)
SELECT 
  gen_random_uuid(),
  u.user_id,
  r.role_id,
  'c0000000-0000-0000-0000-000000000001',
  (SELECT user_id FROM users WHERE email = 'thangvo250904@gmail.com')
FROM users u, roles r
WHERE u.email = 'quankophaiwibu@gmail.com' AND r.code = 'FAMILY_MEMBER'
ON CONFLICT DO NOTHING;

-- Chủ quyền dòng họ (Clan Ownership History)
INSERT INTO clan_ownership_history (ownership_id, clan_id, user_id, started_at)
VALUES 
  ('e0000000-0000-0000-0000-000000000001', 'c0000000-0000-0000-0000-000000000001', (SELECT user_id FROM users WHERE email = 'thangvo250904@gmail.com'), CURRENT_TIMESTAMP),
  ('e0000000-0000-0000-0000-000000000002', 'c0000000-0000-0000-0000-000000000002', (SELECT user_id FROM users WHERE email = 'maiphuchau144@gmail.com'), CURRENT_TIMESTAMP)
ON CONFLICT DO NOTHING;

-- Thành viên gia nhập dòng họ (Clan Memberships)
INSERT INTO clan_memberships (membership_id, clan_id, user_id, status, joined_at)
VALUES 
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000001', (SELECT user_id FROM users WHERE email = 'thangvo250904@gmail.com'), 'ACTIVE', CURRENT_TIMESTAMP),
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000001', (SELECT user_id FROM users WHERE email = 'huy13052005@gmail.com'), 'ACTIVE', CURRENT_TIMESTAMP),
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000001', (SELECT user_id FROM users WHERE email = 'quankophaiwibu@gmail.com'), 'ACTIVE', CURRENT_TIMESTAMP),
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000002', (SELECT user_id FROM users WHERE email = 'maiphuchau144@gmail.com'), 'ACTIVE', CURRENT_TIMESTAMP)
ON CONFLICT DO NOTHING;

-- -----------------------------------------------------------------------------
-- 5. TẠO CÁC CHI / NHÁNH (BRANCHES)
-- -----------------------------------------------------------------------------
-- Họ Võ: Chi 1 (Trưởng) & Chi 2
INSERT INTO branches (branch_id, clan_id, parent_branch_id, name, status, branch_order)
VALUES 
  ('b0000000-0000-0000-0000-000000000001', 'c0000000-0000-0000-0000-000000000001', NULL, 'Chi 1 (Chi Trưởng - Phụng thờ Từ Đường)', 'ACTIVE', 1),
  ('b0000000-0000-0000-0000-000000000002', 'c0000000-0000-0000-0000-000000000001', NULL, 'Chi 2 (Chi Thứ - Phát triển phương xa)', 'ACTIVE', 2)
ON CONFLICT (branch_id) DO NOTHING;

-- Phân quyền quản trị Chi 1 cho Nguyễn Gia Huy (Family Admin)
INSERT INTO family_admin_assignments (assignment_id, user_id, clan_id, branch_id, assigned_by)
VALUES (
  'f0000000-0000-0000-0000-000000000001',
  (SELECT user_id FROM users WHERE email = 'huy13052005@gmail.com'),
  'c0000000-0000-0000-0000-000000000001',
  'b0000000-0000-0000-0000-000000000001',
  (SELECT user_id FROM users WHERE email = 'thangvo250904@gmail.com')
) ON CONFLICT DO NOTHING;

-- Họ Mai: Chi Trưởng
INSERT INTO branches (branch_id, clan_id, parent_branch_id, name, status, branch_order)
VALUES 
  ('b0000000-0000-0000-0000-000000000003', 'c0000000-0000-0000-0000-000000000002', NULL, 'Chi Trưởng Họ Mai (Cố Đô)', 'ACTIVE', 1)
ON CONFLICT (branch_id) DO NOTHING;

-- -----------------------------------------------------------------------------
-- 6. TẠO CÁC THÀNH VIÊN GIA PHẢ (PERSONS - 4 ĐỜI)
-- (UUID hợp lệ với tiền tố fa000000...)
-- -----------------------------------------------------------------------------
-- === DÒNG HỌ VÕ ===
-- Đời 1 (Thủy tổ):
INSERT INTO persons (person_id, clan_id, branch_id, full_name, gender, birth_date, death_date, is_living, generation_no, biography, status)
VALUES 
  ('fa000000-0000-0000-0000-000000000001', 'c0000000-0000-0000-0000-000000000001', 'b0000000-0000-0000-0000-000000000001', 'Cụ Võ Văn Tiên', 'MALE', '1910-02-15', '1985-08-20', false, 1, 'Thủy tổ dòng họ Võ Đại Tộc tại Gò Nổi, có công khai hoang lập nghiệp.', 'ACTIVE'),
  ('fa000000-0000-0000-0000-000000000002', 'c0000000-0000-0000-0000-000000000001', 'b0000000-0000-0000-0000-000000000001', 'Cụ Bà Lê Thị Lành', 'FEMALE', '1915-05-10', '1990-11-04', false, 1, 'Chính thất Thủy tổ, hiền thục mẫu mực, giàu đức hy sinh.', 'ACTIVE')
ON CONFLICT (person_id) DO NOTHING;

-- Đời 2 (Con của Cụ Tiên):
INSERT INTO persons (person_id, clan_id, branch_id, full_name, gender, birth_date, death_date, is_living, generation_no, biography, status)
VALUES 
  ('fa000000-0000-0000-0000-000000000003', 'c0000000-0000-0000-0000-000000000001', 'b0000000-0000-0000-0000-000000000001', 'Võ Văn Trung', 'MALE', '1940-03-20', '2018-04-12', false, 2, 'Trưởng nam Đời 2, từng giữ chức vụ trong hội đồng hương xã.', 'ACTIVE'),
  ('fa000000-0000-0000-0000-000000000004', 'c0000000-0000-0000-0000-000000000001', 'b0000000-0000-0000-0000-000000000001', 'Trần Thị Huệ', 'FEMALE', '1945-07-15', NULL, true, 2, 'Dâu trưởng đời 2, đang sinh sống an hưởng tuổi già tại quê nhà.', 'ACTIVE'),
  ('fa000000-0000-0000-0000-000000000005', 'c0000000-0000-0000-0000-000000000001', 'b0000000-0000-0000-0000-000000000002', 'Võ Văn Dũng', 'MALE', '1948-09-08', NULL, true, 2, 'Chi trưởng Chi 2, cựu giáo viên toán trường huyện.', 'ACTIVE'),
  ('fa000000-0000-0000-0000-000000000006', 'c0000000-0000-0000-0000-000000000001', 'b0000000-0000-0000-0000-000000000002', 'Phạm Thị Loan', 'FEMALE', '1952-12-01', NULL, true, 2, 'Vợ ông Võ Văn Dũng, giáo viên tiểu học về hưu.', 'ACTIVE'),
  ('fa000000-0000-0000-0000-000000000007', 'c0000000-0000-0000-0000-000000000001', 'b0000000-0000-0000-0000-000000000001', 'Võ Thị Mai', 'FEMALE', '1955-06-18', NULL, true, 2, 'Con gái cụ Tiên, định cư tại Đà Nẵng.', 'ACTIVE')
ON CONFLICT (person_id) DO NOTHING;

-- Đời 3 (Con của ông Trung và ông Dũng):
INSERT INTO persons (person_id, clan_id, branch_id, full_name, gender, birth_date, death_date, is_living, generation_no, biography, status)
VALUES 
  -- Con ông Trung:
  ('fa000000-0000-0000-0000-000000000008', 'c0000000-0000-0000-0000-000000000001', 'b0000000-0000-0000-0000-000000000001', 'Võ Trí Thắng', 'MALE', '1975-09-25', NULL, true, 3, 'Trưởng tộc đời 3, Kỹ sư xây dựng, đảm trách quản lý số hóa gia phả.', 'ACTIVE'),
  ('fa000000-0000-0000-0000-000000000009', 'c0000000-0000-0000-0000-000000000001', 'b0000000-0000-0000-0000-000000000001', 'Mai Thị Ngọc Lan', 'FEMALE', '1978-10-14', NULL, true, 3, 'Vợ Võ Trí Thắng (con gái Họ Mai Thế Tộc), Bác sĩ đa khoa.', 'ACTIVE'),
  ('fa000000-0000-0000-0000-000000000010', 'c0000000-0000-0000-0000-000000000001', 'b0000000-0000-0000-0000-000000000001', 'Võ Bích Ngọc', 'FEMALE', '1980-04-12', NULL, true, 3, 'Em gái ông Thắng, Giảng viên đại học.', 'ACTIVE'),
  -- Con ông Dũng:
  ('fa000000-0000-0000-0000-000000000011', 'c0000000-0000-0000-0000-000000000002', 'b0000000-0000-0000-0000-000000000002', 'Võ Trí Thành', 'MALE', '1978-01-30', NULL, true, 3, 'Con trưởng Chi 2, Doanh nhân tại TP.HCM.', 'ACTIVE'),
  ('fa000000-0000-0000-0000-000000000012', 'c0000000-0000-0000-0000-000000000002', 'b0000000-0000-0000-0000-000000000002', 'Nguyễn Thị Thu', 'FEMALE', '1982-08-19', NULL, true, 3, 'Vợ ông Võ Trí Thành.', 'ACTIVE'),
  ('fa000000-0000-0000-0000-000000000013', 'c0000000-0000-0000-0000-000000000001', 'b0000000-0000-0000-0000-000000000001', 'Nguyễn Gia Huy', 'MALE', '1985-05-13', NULL, true, 3, 'Quản trị viên Chi 1, Cử nhân Công nghệ thông tin.', 'ACTIVE')
ON CONFLICT (person_id) DO NOTHING;

-- Đời 4 (Hậu duệ):
INSERT INTO persons (person_id, clan_id, branch_id, full_name, gender, birth_date, death_date, is_living, generation_no, biography, status)
VALUES 
  -- Con của Võ Trí Thắng & Mai Thị Ngọc Lan:
  ('fa000000-0000-0000-0000-000000000014', 'c0000000-0000-0000-0000-000000000001', 'b0000000-0000-0000-0000-000000000001', 'Võ Minh Khôi', 'MALE', '2004-09-25', NULL, true, 4, 'Đích tôn đời 4, sinh viên Đại học Bách Khoa.', 'ACTIVE'),
  ('fa000000-0000-0000-0000-000000000015', 'c0000000-0000-0000-0000-000000000001', 'b0000000-0000-0000-0000-000000000001', 'Võ Tuệ An', 'FEMALE', '2008-11-15', NULL, true, 4, 'Ái nữ đời 4, học sinh phổ thông chuyên.', 'ACTIVE'),
  -- Con gái ông Thành & Rể Trần Minh Quân:
  ('fa000000-0000-0000-0000-000000000016', 'c0000000-0000-0000-0000-000000000002', 'b0000000-0000-0000-0000-000000000002', 'Võ Bích Hạnh', 'FEMALE', '2003-03-10', NULL, true, 4, 'Con gái ông Võ Trí Thành, kết hôn cùng Trần Minh Quân.', 'ACTIVE'),
  ('fa000000-0000-0000-0000-000000000017', 'c0000000-0000-0000-0000-000000000002', 'b0000000-0000-0000-0000-000000000002', 'Trần Minh Quân', 'MALE', '2002-06-20', NULL, true, 4, 'Con rể dòng họ Võ, thành viên tích cực hỗ trợ truyền thông gia tộc.', 'ACTIVE')
ON CONFLICT (person_id) DO NOTHING;

-- === DÒNG HỌ MAI ===
-- Đời 1 (Thủy tổ):
INSERT INTO persons (person_id, clan_id, branch_id, full_name, gender, birth_date, death_date, is_living, generation_no, biography, status)
VALUES 
  ('fa000000-0000-0000-0000-000000000020', 'c0000000-0000-0000-0000-000000000002', 'b0000000-0000-0000-0000-000000000003', 'Cụ Mai Thế Hùng', 'MALE', '1912-04-10', '1980-09-12', false, 1, 'Thủy tổ dòng họ Mai Thế Tộc tại Thừa Thiên Huế.', 'ACTIVE'),
  ('fa000000-0000-0000-0000-000000000021', 'c0000000-0000-0000-0000-000000000002', 'b0000000-0000-0000-0000-000000000003', 'Cụ Bà Hoàng Thị Nhàn', 'FEMALE', '1918-07-22', '1995-03-05', false, 1, 'Chính thất cụ Mai Thế Hùng, công dung ngôn hạnh.', 'ACTIVE')
ON CONFLICT (person_id) DO NOTHING;

-- Đời 2:
INSERT INTO persons (person_id, clan_id, branch_id, full_name, gender, birth_date, death_date, is_living, generation_no, biography, status)
VALUES 
  ('fa000000-0000-0000-0000-000000000022', 'c0000000-0000-0000-0000-000000000002', 'b0000000-0000-0000-0000-000000000003', 'Mai Thế Đức', 'MALE', '1942-08-14', NULL, true, 2, 'Nguyên Trưởng tộc đời 2 họ Mai, uy tín đức độ.', 'ACTIVE'),
  ('fa000000-0000-0000-0000-000000000023', 'c0000000-0000-0000-0000-000000000002', 'b0000000-0000-0000-0000-000000000003', 'Đặng Thị Cúc', 'FEMALE', '1946-02-28', NULL, true, 2, 'Vợ ông Mai Thế Đức.', 'ACTIVE')
ON CONFLICT (person_id) DO NOTHING;

-- Đời 3:
INSERT INTO persons (person_id, clan_id, branch_id, full_name, gender, birth_date, death_date, is_living, generation_no, biography, status)
VALUES 
  ('fa000000-0000-0000-0000-000000000024', 'c0000000-0000-0000-0000-000000000002', 'b0000000-0000-0000-0000-000000000003', 'Mai Phúc Hậu', 'MALE', '1976-06-15', NULL, true, 3, 'Trưởng tộc đời 3 Họ Mai, Giám đốc doanh nghiệp dược phẩm.', 'ACTIVE'),
  ('fa000000-0000-0000-0000-000000000025', 'c0000000-0000-0000-0000-000000000002', 'b0000000-0000-0000-0000-000000000003', 'Lê Hoàng Yến', 'FEMALE', '1980-03-21', NULL, true, 3, 'Vợ ông Mai Phúc Hậu, Thạc sĩ Tài chính.', 'ACTIVE'),
  ('fa000000-0000-0000-0000-000000000026', 'c0000000-0000-0000-0000-000000000002', 'b0000000-0000-0000-0000-000000000003', 'Mai Thế Khang', 'MALE', '1984-11-09', NULL, true, 3, 'Em trai ông Hậu, Kỹ sư phần mềm.', 'ACTIVE')
ON CONFLICT (person_id) DO NOTHING;

-- Đời 4:
INSERT INTO persons (person_id, clan_id, branch_id, full_name, gender, birth_date, death_date, is_living, generation_no, biography, status)
VALUES 
  ('fa000000-0000-0000-0000-000000000027', 'c0000000-0000-0000-0000-000000000002', 'b0000000-0000-0000-0000-000000000003', 'Mai Phúc Lâm', 'MALE', '2005-01-18', NULL, true, 4, 'Đích tôn đời 4 Họ Mai, sinh viên.', 'ACTIVE'),
  ('fa000000-0000-0000-0000-000000000028', 'c0000000-0000-0000-0000-000000000002', 'b0000000-0000-0000-0000-000000000003', 'Mai Bảo Trâm', 'FEMALE', '2009-08-30', NULL, true, 4, 'Con gái ông Mai Phúc Hậu.', 'ACTIVE')
ON CONFLICT (person_id) DO NOTHING;

-- Cập nhật Thủy tổ sáng lập cho 2 dòng họ
UPDATE clan_profiles SET founder_person_id = 'fa000000-0000-0000-0000-000000000001' WHERE clan_id = 'c0000000-0000-0000-0000-000000000001';
UPDATE clan_profiles SET founder_person_id = 'fa000000-0000-0000-0000-000000000020' WHERE clan_id = 'c0000000-0000-0000-0000-000000000002';

-- -----------------------------------------------------------------------------
-- 7. THIẾT LẬP MỐI QUAN HỆ GIA PHẢ (RELATIONSHIPS)
-- (UUID hợp lệ với tiền tố fb000000...)
-- -----------------------------------------------------------------------------
-- === QUAN HỆ HỌ VÕ ===
-- 1. Hôn nhân cụ Tiên - cụ Lành
INSERT INTO relationships (relationship_id, clan_id, from_person_id, to_person_id, relationship_type, status, created_by)
VALUES 
  ('fb000000-0000-0000-0000-000000000001', 'c0000000-0000-0000-0000-000000000001', 'fa000000-0000-0000-0000-000000000001', 'fa000000-0000-0000-0000-000000000002', 'SPOUSE', 'ACTIVE', (SELECT user_id FROM users WHERE email = 'thangvo250904@gmail.com'))
ON CONFLICT (relationship_id) DO NOTHING;

-- 2. Cha mẹ - Con (Cụ Tiên & Cụ Lành -> Võ Văn Trung, Võ Văn Dũng, Võ Thị Mai)
INSERT INTO relationships (relationship_id, clan_id, from_person_id, to_person_id, relationship_type, parent_type, child_order, status, created_by)
VALUES 
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000001', 'fa000000-0000-0000-0000-000000000001', 'fa000000-0000-0000-0000-000000000003', 'PARENT_CHILD', 'BIOLOGICAL', 1, 'ACTIVE', (SELECT user_id FROM users WHERE email = 'thangvo250904@gmail.com')),
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000001', 'fa000000-0000-0000-0000-000000000002', 'fa000000-0000-0000-0000-000000000003', 'PARENT_CHILD', 'BIOLOGICAL', 1, 'ACTIVE', (SELECT user_id FROM users WHERE email = 'thangvo250904@gmail.com')),
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000001', 'fa000000-0000-0000-0000-000000000001', 'fa000000-0000-0000-0000-000000000005', 'PARENT_CHILD', 'BIOLOGICAL', 2, 'ACTIVE', (SELECT user_id FROM users WHERE email = 'thangvo250904@gmail.com')),
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000001', 'fa000000-0000-0000-0000-000000000002', 'fa000000-0000-0000-0000-000000000005', 'PARENT_CHILD', 'BIOLOGICAL', 2, 'ACTIVE', (SELECT user_id FROM users WHERE email = 'thangvo250904@gmail.com')),
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000001', 'fa000000-0000-0000-0000-000000000001', 'fa000000-0000-0000-0000-000000000007', 'PARENT_CHILD', 'BIOLOGICAL', 3, 'ACTIVE', (SELECT user_id FROM users WHERE email = 'thangvo250904@gmail.com')),
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000001', 'fa000000-0000-0000-0000-000000000002', 'fa000000-0000-0000-0000-000000000007', 'PARENT_CHILD', 'BIOLOGICAL', 3, 'ACTIVE', (SELECT user_id FROM users WHERE email = 'thangvo250904@gmail.com'))
ON CONFLICT DO NOTHING;

-- 3. Hôn nhân Võ Văn Trung - Trần Thị Huệ
INSERT INTO relationships (relationship_id, clan_id, from_person_id, to_person_id, relationship_type, status, created_by)
VALUES 
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000001', 'fa000000-0000-0000-0000-000000000003', 'fa000000-0000-0000-0000-000000000004', 'SPOUSE', 'ACTIVE', (SELECT user_id FROM users WHERE email = 'thangvo250904@gmail.com'))
ON CONFLICT (relationship_id) DO NOTHING;

-- 4. Cha mẹ - Con (Võ Văn Trung & Trần Thị Huệ -> Võ Trí Thắng, Võ Bích Ngọc)
INSERT INTO relationships (relationship_id, clan_id, from_person_id, to_person_id, relationship_type, parent_type, child_order, status, created_by)
VALUES 
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000001', 'fa000000-0000-0000-0000-000000000003', 'fa000000-0000-0000-0000-000000000008', 'PARENT_CHILD', 'BIOLOGICAL', 1, 'ACTIVE', (SELECT user_id FROM users WHERE email = 'thangvo250904@gmail.com')),
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000001', 'fa000000-0000-0000-0000-000000000004', 'fa000000-0000-0000-0000-000000000008', 'PARENT_CHILD', 'BIOLOGICAL', 1, 'ACTIVE', (SELECT user_id FROM users WHERE email = 'thangvo250904@gmail.com')),
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000001', 'fa000000-0000-0000-0000-000000000003', 'fa000000-0000-0000-0000-000000000010', 'PARENT_CHILD', 'BIOLOGICAL', 2, 'ACTIVE', (SELECT user_id FROM users WHERE email = 'thangvo250904@gmail.com')),
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000001', 'fa000000-0000-0000-0000-000000000004', 'fa000000-0000-0000-0000-000000000010', 'PARENT_CHILD', 'BIOLOGICAL', 2, 'ACTIVE', (SELECT user_id FROM users WHERE email = 'thangvo250904@gmail.com'))
ON CONFLICT DO NOTHING;

-- 5. Hôn nhân Võ Trí Thắng - Mai Thị Ngọc Lan (Thông gia liên họ)
INSERT INTO relationships (relationship_id, clan_id, from_person_id, to_person_id, relationship_type, status, created_by)
VALUES 
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000001', 'fa000000-0000-0000-0000-000000000008', 'fa000000-0000-0000-0000-000000000009', 'SPOUSE', 'ACTIVE', (SELECT user_id FROM users WHERE email = 'thangvo250904@gmail.com'))
ON CONFLICT (relationship_id) DO NOTHING;

-- 6. Cha mẹ - Con (Võ Trí Thắng & Mai Thị Ngọc Lan -> Võ Minh Khôi, Võ Tuệ An)
INSERT INTO relationships (relationship_id, clan_id, from_person_id, to_person_id, relationship_type, parent_type, child_order, status, created_by)
VALUES 
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000001', 'fa000000-0000-0000-0000-000000000008', 'fa000000-0000-0000-0000-000000000014', 'PARENT_CHILD', 'BIOLOGICAL', 1, 'ACTIVE', (SELECT user_id FROM users WHERE email = 'thangvo250904@gmail.com')),
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000001', 'fa000000-0000-0000-0000-000000000009', 'fa000000-0000-0000-0000-000000000014', 'PARENT_CHILD', 'BIOLOGICAL', 1, 'ACTIVE', (SELECT user_id FROM users WHERE email = 'thangvo250904@gmail.com')),
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000001', 'fa000000-0000-0000-0000-000000000008', 'fa000000-0000-0000-0000-000000000015', 'PARENT_CHILD', 'BIOLOGICAL', 2, 'ACTIVE', (SELECT user_id FROM users WHERE email = 'thangvo250904@gmail.com')),
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000001', 'fa000000-0000-0000-0000-000000000009', 'fa000000-0000-0000-0000-000000000015', 'PARENT_CHILD', 'BIOLOGICAL', 2, 'ACTIVE', (SELECT user_id FROM users WHERE email = 'thangvo250904@gmail.com'))
ON CONFLICT DO NOTHING;

-- 7. Hôn nhân Võ Bích Hạnh - Trần Minh Quân (Rể Đời 4)
INSERT INTO relationships (relationship_id, clan_id, from_person_id, to_person_id, relationship_type, status, created_by)
VALUES 
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000001', 'fa000000-0000-0000-0000-000000000016', 'fa000000-0000-0000-0000-000000000017', 'SPOUSE', 'ACTIVE', (SELECT user_id FROM users WHERE email = 'thangvo250904@gmail.com'))
ON CONFLICT (relationship_id) DO NOTHING;

-- === QUAN HỆ HỌ MAI ===
-- 1. Hôn nhân Cụ Mai Thế Hùng - Cụ Hoàng Thị Nhàn
INSERT INTO relationships (relationship_id, clan_id, from_person_id, to_person_id, relationship_type, status, created_by)
VALUES 
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000002', 'fa000000-0000-0000-0000-000000000020', 'fa000000-0000-0000-0000-000000000021', 'SPOUSE', 'ACTIVE', (SELECT user_id FROM users WHERE email = 'maiphuchau144@gmail.com'))
ON CONFLICT (relationship_id) DO NOTHING;

-- 2. Cha mẹ - Con (Cụ Hùng -> Mai Thế Đức)
INSERT INTO relationships (relationship_id, clan_id, from_person_id, to_person_id, relationship_type, parent_type, child_order, status, created_by)
VALUES 
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000002', 'fa000000-0000-0000-0000-000000000020', 'fa000000-0000-0000-0000-000000000022', 'PARENT_CHILD', 'BIOLOGICAL', 1, 'ACTIVE', (SELECT user_id FROM users WHERE email = 'maiphuchau144@gmail.com')),
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000002', 'fa000000-0000-0000-0000-000000000021', 'fa000000-0000-0000-0000-000000000022', 'PARENT_CHILD', 'BIOLOGICAL', 1, 'ACTIVE', (SELECT user_id FROM users WHERE email = 'maiphuchau144@gmail.com'))
ON CONFLICT DO NOTHING;

-- 3. Hôn nhân Mai Thế Đức - Đặng Thị Cúc
INSERT INTO relationships (relationship_id, clan_id, from_person_id, to_person_id, relationship_type, status, created_by)
VALUES 
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000002', 'fa000000-0000-0000-0000-000000000022', 'fa000000-0000-0000-0000-000000000023', 'SPOUSE', 'ACTIVE', (SELECT user_id FROM users WHERE email = 'maiphuchau144@gmail.com'))
ON CONFLICT (relationship_id) DO NOTHING;

-- 4. Cha mẹ - Con (Mai Thế Đức & Đặng Thị Cúc -> Mai Phúc Hậu, Mai Thế Khang)
INSERT INTO relationships (relationship_id, clan_id, from_person_id, to_person_id, relationship_type, parent_type, child_order, status, created_by)
VALUES 
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000002', 'fa000000-0000-0000-0000-000000000022', 'fa000000-0000-0000-0000-000000000024', 'PARENT_CHILD', 'BIOLOGICAL', 1, 'ACTIVE', (SELECT user_id FROM users WHERE email = 'maiphuchau144@gmail.com')),
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000002', 'fa000000-0000-0000-0000-000000000023', 'fa000000-0000-0000-0000-000000000024', 'PARENT_CHILD', 'BIOLOGICAL', 1, 'ACTIVE', (SELECT user_id FROM users WHERE email = 'maiphuchau144@gmail.com')),
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000002', 'fa000000-0000-0000-0000-000000000022', 'fa000000-0000-0000-0000-000000000026', 'PARENT_CHILD', 'BIOLOGICAL', 2, 'ACTIVE', (SELECT user_id FROM users WHERE email = 'maiphuchau144@gmail.com')),
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000002', 'fa000000-0000-0000-0000-000000000023', 'fa000000-0000-0000-0000-000000000026', 'PARENT_CHILD', 'BIOLOGICAL', 2, 'ACTIVE', (SELECT user_id FROM users WHERE email = 'maiphuchau144@gmail.com'))
ON CONFLICT DO NOTHING;

-- 5. Hôn nhân Mai Phúc Hậu - Lê Hoàng Yến
INSERT INTO relationships (relationship_id, clan_id, from_person_id, to_person_id, relationship_type, status, created_by)
VALUES 
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000002', 'fa000000-0000-0000-0000-000000000024', 'fa000000-0000-0000-0000-000000000025', 'SPOUSE', 'ACTIVE', (SELECT user_id FROM users WHERE email = 'maiphuchau144@gmail.com'))
ON CONFLICT (relationship_id) DO NOTHING;

-- 6. Cha mẹ - Con (Mai Phúc Hậu & Lê Hoàng Yến -> Mai Phúc Lâm, Mai Bảo Trâm)
INSERT INTO relationships (relationship_id, clan_id, from_person_id, to_person_id, relationship_type, parent_type, child_order, status, created_by)
VALUES 
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000002', 'fa000000-0000-0000-0000-000000000024', 'fa000000-0000-0000-0000-000000000027', 'PARENT_CHILD', 'BIOLOGICAL', 1, 'ACTIVE', (SELECT user_id FROM users WHERE email = 'maiphuchau144@gmail.com')),
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000002', 'fa000000-0000-0000-0000-000000000025', 'fa000000-0000-0000-0000-000000000027', 'PARENT_CHILD', 'BIOLOGICAL', 1, 'ACTIVE', (SELECT user_id FROM users WHERE email = 'maiphuchau144@gmail.com')),
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000002', 'fa000000-0000-0000-0000-000000000024', 'fa000000-0000-0000-0000-000000000028', 'PARENT_CHILD', 'BIOLOGICAL', 2, 'ACTIVE', (SELECT user_id FROM users WHERE email = 'maiphuchau144@gmail.com')),
  (gen_random_uuid(), 'c0000000-0000-0000-0000-000000000002', 'fa000000-0000-0000-0000-000000000025', 'fa000000-0000-0000-0000-000000000028', 'PARENT_CHILD', 'BIOLOGICAL', 2, 'ACTIVE', (SELECT user_id FROM users WHERE email = 'maiphuchau144@gmail.com'))
ON CONFLICT DO NOTHING;

-- -----------------------------------------------------------------------------
-- 8. GẮN TÀI KHOẢN VỚI THÀNH VIÊN GIA PHẢ (PERSON_ACCOUNT_LINKS)
-- -----------------------------------------------------------------------------
INSERT INTO person_account_links (link_id, person_id, user_id, clan_id, status, linked_at)
VALUES 
  -- Võ Trí Thắng gắn với Person Võ Trí Thắng
  (gen_random_uuid(), 'fa000000-0000-0000-0000-000000000008', (SELECT user_id FROM users WHERE email = 'thangvo250904@gmail.com'), 'c0000000-0000-0000-0000-000000000001', 'ACTIVE', CURRENT_TIMESTAMP),
  -- Mai Phúc Hậu gắn với Person Mai Phúc Hậu
  (gen_random_uuid(), 'fa000000-0000-0000-0000-000000000024', (SELECT user_id FROM users WHERE email = 'maiphuchau144@gmail.com'), 'c0000000-0000-0000-0000-000000000002', 'ACTIVE', CURRENT_TIMESTAMP),
  -- Nguyễn Gia Huy gắn với Person Nguyễn Gia Huy
  (gen_random_uuid(), 'fa000000-0000-0000-0000-000000000013', (SELECT user_id FROM users WHERE email = 'huy13052005@gmail.com'), 'c0000000-0000-0000-0000-000000000001', 'ACTIVE', CURRENT_TIMESTAMP),
  -- Trần Minh Quân gắn với Person Trần Minh Quân
  (gen_random_uuid(), 'fa000000-0000-0000-0000-000000000017', (SELECT user_id FROM users WHERE email = 'quankophaiwibu@gmail.com'), 'c0000000-0000-0000-0000-000000000001', 'ACTIVE', CURRENT_TIMESTAMP)
ON CONFLICT (person_id, clan_id) DO NOTHING;

-- -----------------------------------------------------------------------------
-- 9. THIẾT LẬP LIÊN HỌ (INTER-CLAN LINKS & POLICIES GIỮA HỌ VÕ VÀ HỌ MAI)
-- -----------------------------------------------------------------------------
-- Yêu cầu liên họ đã được duyệt (Mai Thị Ngọc Lan họ Mai kết duyên với Võ Trí Thắng họ Võ)
INSERT INTO inter_clan_requests (inter_request_id, source_clan_id, target_clan_id, requester_id, source_person_id, target_person_id, status, reviewed_by)
VALUES (
  'd0000000-0000-0000-0000-000000000001',
  'c0000000-0000-0000-0000-000000000001',
  'c0000000-0000-0000-0000-000000000002',
  (SELECT user_id FROM users WHERE email = 'thangvo250904@gmail.com'),
  'fa000000-0000-0000-0000-000000000008',
  'fa000000-0000-0000-0000-000000000009',
  'APPROVED',
  (SELECT user_id FROM users WHERE email = 'maiphuchau144@gmail.com')
) ON CONFLICT (inter_request_id) DO NOTHING;

-- Liên kết liên họ (Inter Clan Link)
INSERT INTO inter_clan_links (link_id, request_id, clan_a_id, clan_b_id, status, linked_at)
VALUES (
  'd0000000-0000-0000-0000-000000000002',
  'd0000000-0000-0000-0000-000000000001',
  'c0000000-0000-0000-0000-000000000001',
  'c0000000-0000-0000-0000-000000000002',
  'ACTIVE',
  CURRENT_TIMESTAMP
) ON CONFLICT (link_id) DO NOTHING;

-- Chính sách chia sẻ dữ liệu liên họ
INSERT INTO inter_clan_shared_policies (policy_id, link_id, owner_clan_id, data_scope, allowed_fields, visibility, can_export)
VALUES 
  ('d0000000-0000-0000-0000-000000000003', 'd0000000-0000-0000-0000-000000000002', 'c0000000-0000-0000-0000-000000000001', 'ALL', '["full_name", "gender", "birth_date", "biography"]'::jsonb, 'INTER_FAMILY', true),
  ('d0000000-0000-0000-0000-000000000004', 'd0000000-0000-0000-0000-000000000002', 'c0000000-0000-0000-0000-000000000002', 'ALL', '["full_name", "gender", "birth_date", "biography"]'::jsonb, 'INTER_FAMILY', true)
ON CONFLICT (policy_id) DO NOTHING;

-- -----------------------------------------------------------------------------
-- 10. TÍNH TOÁN CLOSURE TABLE (PERSON_CLOSURE) CHO TRUY VẤN CÂY
-- -----------------------------------------------------------------------------
-- Độ sâu 0 (Bản thân)
INSERT INTO person_closure (ancestor_id, descendant_id, depth)
SELECT person_id, person_id, 0 FROM persons
ON CONFLICT (ancestor_id, descendant_id) DO NOTHING;

-- Độ sâu 1 (Cha mẹ trực tiếp)
INSERT INTO person_closure (ancestor_id, descendant_id, depth)
SELECT from_person_id, to_person_id, 1 
FROM relationships 
WHERE relationship_type = 'PARENT_CHILD'
ON CONFLICT (ancestor_id, descendant_id) DO NOTHING;

-- Độ sâu 2 (Ông bà -> Cháu)
INSERT INTO person_closure (ancestor_id, descendant_id, depth)
SELECT p1.from_person_id, p2.to_person_id, 2
FROM relationships p1
JOIN relationships p2 ON p1.to_person_id = p2.from_person_id
WHERE p1.relationship_type = 'PARENT_CHILD' AND p2.relationship_type = 'PARENT_CHILD'
ON CONFLICT (ancestor_id, descendant_id) DO NOTHING;

-- Độ sâu 3 (Cụ -> Chắt)
INSERT INTO person_closure (ancestor_id, descendant_id, depth)
SELECT p1.from_person_id, p3.to_person_id, 3
FROM relationships p1
JOIN relationships p2 ON p1.to_person_id = p2.from_person_id
JOIN relationships p3 ON p2.to_person_id = p3.from_person_id
WHERE p1.relationship_type = 'PARENT_CHILD' AND p2.relationship_type = 'PARENT_CHILD' AND p3.relationship_type = 'PARENT_CHILD'
ON CONFLICT (ancestor_id, descendant_id) DO NOTHING;

COMMIT;

-- =============================================================================
-- HOÀN TẤT IMPORT DỮ LIỆU THỰC TẾ
-- Kiểm tra:
--   SELECT email, display_name, status FROM users;
--   SELECT clan_code, name, status FROM clans;
--   SELECT count(*) AS total_persons FROM persons;
-- =============================================================================
