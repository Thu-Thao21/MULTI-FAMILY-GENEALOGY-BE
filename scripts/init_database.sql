-- ============================================================================
-- SCRIPT KHỞI TẠO TOÀN BỘ CƠ SỞ DỮ LIỆU GIA PHẢ LIÊN HỌ (31 BẢNG & 3 VIEWS)
-- Multi-Family Genealogy - Complete Database Initialization DDL
-- ============================================================================

-- 1. Xóa các View và Bảng nếu đã tồn tại để làm sạch
DROP VIEW IF EXISTS vw_admins CASCADE;
DROP VIEW IF EXISTS vw_family_heads CASCADE;
DROP VIEW IF EXISTS vw_members CASCADE;
DROP TABLE IF EXISTS role_requests CASCADE;
DROP TABLE IF EXISTS account_roles CASCADE;
DROP TABLE IF EXISTS accounts CASCADE;
DROP TABLE IF EXISTS users CASCADE;

-- 2. TẠO TOÀN BỘ CÁC BẢNG TRONG HỆ THỐNG

-- 2.0 Bảng Xác thực Tập trung & Phân quyền (accounts, account_roles, role_requests)
CREATE TABLE IF NOT EXISTS accounts (
    id VARCHAR(36) PRIMARY KEY,
    firebase_uid VARCHAR(128) NOT NULL UNIQUE,
    username VARCHAR(150) UNIQUE,
    email VARCHAR(255) UNIQUE,
    phone_e164 VARCHAR(30) UNIQUE,
    display_name VARCHAR(255),
    email_verified BOOLEAN DEFAULT FALSE NOT NULL,
    phone_verified BOOLEAN DEFAULT FALSE NOT NULL,
    status VARCHAR(32) DEFAULT 'active' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS account_roles (
    id VARCHAR(36) PRIMARY KEY,
    account_id VARCHAR(36) REFERENCES accounts(id) ON DELETE CASCADE NOT NULL,
    role VARCHAR(50) NOT NULL,
    family_id VARCHAR(36),
    status VARCHAR(32) DEFAULT 'active' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS role_requests (
    id VARCHAR(36) PRIMARY KEY,
    account_id VARCHAR(36) REFERENCES accounts(id) ON DELETE CASCADE NOT NULL,
    requested_role VARCHAR(50) NOT NULL,
    family_id VARCHAR(36),
    reason TEXT,
    status VARCHAR(32) DEFAULT 'pending' NOT NULL,
    reviewer_id VARCHAR(36),
    reviewer_notes TEXT,
    reviewed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 2.1 Bảng Quản trị viên (admins)
CREATE TABLE IF NOT EXISTS admins (
    id VARCHAR(36) PRIMARY KEY,
    username VARCHAR(150) NOT NULL UNIQUE,
    email VARCHAR(255) UNIQUE,
    phone VARCHAR(30) UNIQUE,
    full_name VARCHAR(255) NOT NULL,
    password_hash TEXT NOT NULL,
    admin_code VARCHAR(50) DEFAULT 'SUPER-ADMIN',
    permissions_level VARCHAR(50) NOT NULL DEFAULT 'super_admin',
    managed_scope VARCHAR(255) DEFAULT 'all_families',
    role VARCHAR(32) NOT NULL DEFAULT 'admin',
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 2.2 Bảng Dòng Họ (families)
CREATE TABLE IF NOT EXISTS families (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    founder_name VARCHAR(255),
    founder_member_id VARCHAR(36),
    family_head_id VARCHAR(36),
    origin_place TEXT,
    ancestral_house_address TEXT,
    history TEXT,
    description TEXT,
    branches JSONB DEFAULT '[]'::jsonb NOT NULL,
    status VARCHAR(32) DEFAULT 'active' NOT NULL,
    created_by VARCHAR(36),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 2.3 Bảng Trưởng Họ (family_heads)
CREATE TABLE IF NOT EXISTS family_heads (
    id VARCHAR(36) PRIMARY KEY,
    username VARCHAR(150) NOT NULL UNIQUE,
    email VARCHAR(255) UNIQUE,
    phone VARCHAR(30) UNIQUE,
    full_name VARCHAR(255) NOT NULL,
    password_hash TEXT NOT NULL,
    family_id VARCHAR(36) REFERENCES families(id) ON DELETE SET NULL,
    appointment_date DATE,
    term_title VARCHAR(100) NOT NULL DEFAULT 'Trưởng Họ',
    role VARCHAR(32) NOT NULL DEFAULT 'family_head',
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 2.4 Bảng Cây Gia Phả Dòng Họ (family_trees)
CREATE TABLE IF NOT EXISTS family_trees (
    id VARCHAR(36) PRIMARY KEY,
    family_id VARCHAR(36) REFERENCES families(id) ON DELETE CASCADE NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    root_member_id VARCHAR(36),
    status VARCHAR(32) DEFAULT 'active' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 2.5 Bảng Chi/Nhánh Dòng Họ (family_branches)
CREATE TABLE IF NOT EXISTS family_branches (
    id VARCHAR(36) PRIMARY KEY,
    family_id VARCHAR(36) REFERENCES families(id) ON DELETE CASCADE NOT NULL,
    tree_id VARCHAR(36) REFERENCES family_trees(id) ON DELETE SET NULL,
    name VARCHAR(255) NOT NULL,
    parent_branch_id VARCHAR(36),
    branch_order INT DEFAULT 0 NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 2.6 Bảng Thành Viên Gia Tộc (members)
CREATE TABLE IF NOT EXISTS members (
    id VARCHAR(36) PRIMARY KEY,
    family_id VARCHAR(36) REFERENCES families(id) ON DELETE CASCADE,
    username VARCHAR(150) UNIQUE,
    email VARCHAR(255) UNIQUE,
    phone VARCHAR(30) UNIQUE,
    full_name VARCHAR(255) NOT NULL,
    password_hash TEXT,
    other_name VARCHAR(255),
    gender VARCHAR(16) DEFAULT 'male' NOT NULL,
    birth_date DATE,
    death_date DATE,
    lunar_death_date VARCHAR(80),
    is_alive BOOLEAN DEFAULT TRUE NOT NULL,
    burial_place TEXT,
    burial_coordinates JSONB,
    father_id VARCHAR(36),
    mother_id VARCHAR(36),
    branch VARCHAR(120),
    sub_branch VARCHAR(120),
    display_order INT DEFAULT 0 NOT NULL,
    role VARCHAR(32) DEFAULT 'member' NOT NULL,
    status VARCHAR(32) DEFAULT 'active' NOT NULL,
    occupation VARCHAR(255),
    education VARCHAR(255),
    bio TEXT,
    avatar_url TEXT,
    gallery_photos JSONB DEFAULT '[]'::jsonb NOT NULL,
    career_history JSONB DEFAULT '[]'::jsonb NOT NULL,
    contact JSONB,
    privacy_settings JSONB,
    contribution JSONB,
    generation INT DEFAULT 1 NOT NULL,
    is_primary BOOLEAN DEFAULT FALSE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 2.7 Bảng Liên Kết Dòng Họ Thuộc Thuộc (member_family_affiliations)
CREATE TABLE IF NOT EXISTS member_family_affiliations (
    id VARCHAR(36) PRIMARY KEY,
    member_id VARCHAR(36) REFERENCES members(id) ON DELETE CASCADE NOT NULL,
    family_id VARCHAR(36) REFERENCES families(id) ON DELETE CASCADE NOT NULL,
    branch_id VARCHAR(36) REFERENCES family_branches(id) ON DELETE SET NULL,
    relationship_role VARCHAR(80),
    is_primary BOOLEAN DEFAULT FALSE NOT NULL,
    joined_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    status VARCHAR(32) DEFAULT 'active' NOT NULL
);

-- 2.8 Bảng Quan Hệ Cha Mẹ - Con (parent_child_relationships)
CREATE TABLE IF NOT EXISTS parent_child_relationships (
    id VARCHAR(36) PRIMARY KEY,
    parent_member_id VARCHAR(36) REFERENCES members(id) ON DELETE CASCADE NOT NULL,
    child_member_id VARCHAR(36) REFERENCES members(id) ON DELETE CASCADE NOT NULL,
    relation_type VARCHAR(32) DEFAULT 'biological' NOT NULL,
    verified BOOLEAN DEFAULT FALSE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 2.9 Bảng Hôn Nhân / Gia Đình (unions)
CREATE TABLE IF NOT EXISTS unions (
    id VARCHAR(36) PRIMARY KEY,
    family_id VARCHAR(36) REFERENCES families(id) ON DELETE SET NULL,
    marriage_date DATE,
    divorce_date DATE,
    status VARCHAR(32) DEFAULT 'married' NOT NULL,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 2.10 Bảng Thành Viên Vợ/Chồng Trong Hôn Nhân (union_members)
CREATE TABLE IF NOT EXISTS union_members (
    id VARCHAR(36) PRIMARY KEY,
    union_id VARCHAR(36) REFERENCES unions(id) ON DELETE CASCADE NOT NULL,
    member_id VARCHAR(36) REFERENCES members(id) ON DELETE CASCADE NOT NULL,
    spouse_role VARCHAR(32) DEFAULT 'husband' NOT NULL
);

-- 2.11 Bảng Quan Hệ Thân Tộc Khác (relationships)
CREATE TABLE IF NOT EXISTS relationships (
    id VARCHAR(36) PRIMARY KEY,
    from_member_id VARCHAR(36) REFERENCES members(id) ON DELETE CASCADE NOT NULL,
    to_member_id VARCHAR(36) REFERENCES members(id) ON DELETE CASCADE NOT NULL,
    relationship_type VARCHAR(60) NOT NULL,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 2.12 Bảng Liên Kết Giữa Các Dòng Họ (family_links)
CREATE TABLE IF NOT EXISTS family_links (
    id VARCHAR(36) PRIMARY KEY,
    source_family_id VARCHAR(36) REFERENCES families(id) ON DELETE CASCADE NOT NULL,
    target_family_id VARCHAR(36) REFERENCES families(id) ON DELETE CASCADE NOT NULL,
    link_type VARCHAR(60) NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 2.13 Bảng Thông Tin Liên Hệ Thành Viên (member_contacts)
CREATE TABLE IF NOT EXISTS member_contacts (
    id VARCHAR(36) PRIMARY KEY,
    member_id VARCHAR(36) REFERENCES members(id) ON DELETE CASCADE NOT NULL UNIQUE,
    phone VARCHAR(30),
    email VARCHAR(255),
    address TEXT,
    social_links JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 2.14 Bảng Quyền Quyền Riêng Tư (member_privacy_rules)
CREATE TABLE IF NOT EXISTS member_privacy_rules (
    id VARCHAR(36) PRIMARY KEY,
    member_id VARCHAR(36) REFERENCES members(id) ON DELETE CASCADE NOT NULL UNIQUE,
    phone_visible BOOLEAN DEFAULT TRUE NOT NULL,
    email_visible BOOLEAN DEFAULT TRUE NOT NULL,
    address_visible BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 2.15 Bảng Hình Ảnh & Media (member_media)
CREATE TABLE IF NOT EXISTS member_media (
    id VARCHAR(36) PRIMARY KEY,
    member_id VARCHAR(36) REFERENCES members(id) ON DELETE CASCADE NOT NULL,
    media_type VARCHAR(32) DEFAULT 'image' NOT NULL,
    url TEXT NOT NULL,
    caption TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 2.16 Bảng Sự Kiện Đời Người (member_life_events)
CREATE TABLE IF NOT EXISTS member_life_events (
    id VARCHAR(36) PRIMARY KEY,
    member_id VARCHAR(36) REFERENCES members(id) ON DELETE CASCADE NOT NULL,
    event_name VARCHAR(255) NOT NULL,
    event_date DATE,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 2.17 Bảng Kỹ Năng / Nghề Nghiệp (skills & member_skills)
CREATE TABLE IF NOT EXISTS skills (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(120) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS member_skills (
    id VARCHAR(36) PRIMARY KEY,
    member_id VARCHAR(36) REFERENCES members(id) ON DELETE CASCADE NOT NULL,
    skill_id VARCHAR(36) REFERENCES skills(id) ON DELETE CASCADE NOT NULL
);

-- 2.18 Bảng Nhắc Nhở Ngày Giỗ (death_anniversary_reminders)
CREATE TABLE IF NOT EXISTS death_anniversary_reminders (
    id VARCHAR(36) PRIMARY KEY,
    member_id VARCHAR(36) REFERENCES members(id) ON DELETE CASCADE NOT NULL,
    lunar_date VARCHAR(80) NOT NULL,
    solar_date DATE,
    reminder_days_before INT DEFAULT 3 NOT NULL,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 2.19 Bảng Yêu Cầu Thay Đổi Thông Tin (change_requests)
CREATE TABLE IF NOT EXISTS change_requests (
    id VARCHAR(36) PRIMARY KEY,
    requester_id VARCHAR(36) NOT NULL,
    request_type VARCHAR(80) NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR(32) DEFAULT 'pending' NOT NULL,
    reviewer_id VARCHAR(36),
    rejection_reason TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 2.20 Bảng Nhật Ký Hệ Thống (audit_logs)
CREATE TABLE IF NOT EXISTS audit_logs (
    id VARCHAR(36) PRIMARY KEY,
    actor_id VARCHAR(36) NOT NULL,
    action VARCHAR(120) NOT NULL,
    target_table VARCHAR(120) NOT NULL,
    target_id VARCHAR(36),
    details JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 2.21 Bảng Thông Báo (notifications)
CREATE TABLE IF NOT EXISTS notifications (
    id VARCHAR(36) PRIMARY KEY,
    recipient_id VARCHAR(36) NOT NULL,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    is_read BOOLEAN DEFAULT FALSE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 2.22 Bảng Yêu Cầu Liên Kết Dòng Họ (family_link_requests)
CREATE TABLE IF NOT EXISTS family_link_requests (
    id VARCHAR(36) PRIMARY KEY,
    requester_family_id VARCHAR(36) REFERENCES families(id) ON DELETE CASCADE NOT NULL,
    target_family_id VARCHAR(36) REFERENCES families(id) ON DELETE CASCADE NOT NULL,
    requester_user_id VARCHAR(36) NOT NULL,
    status VARCHAR(32) DEFAULT 'pending' NOT NULL,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 2.23 Bảng Nhập / Xuất File Dữ Liệu (import_jobs, export_jobs, backup_records)
CREATE TABLE IF NOT EXISTS import_jobs (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    status VARCHAR(32) DEFAULT 'processing' NOT NULL,
    imported_count INT DEFAULT 0 NOT NULL,
    error_log JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS export_jobs (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    export_format VARCHAR(32) DEFAULT 'excel' NOT NULL,
    status VARCHAR(32) DEFAULT 'processing' NOT NULL,
    download_url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS backup_records (
    id VARCHAR(36) PRIMARY KEY,
    file_name VARCHAR(255) NOT NULL,
    file_size_bytes INT DEFAULT 0 NOT NULL,
    created_by VARCHAR(36),
    status VARCHAR(32) DEFAULT 'completed' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 2.24 Bảng Phân Quyền Vai Trò (permissions, role_permissions)
CREATE TABLE IF NOT EXISTS permissions (
    id VARCHAR(36) PRIMARY KEY,
    code VARCHAR(120) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS role_permissions (
    id VARCHAR(36) PRIMARY KEY,
    role_name VARCHAR(80) NOT NULL,
    permission_id VARCHAR(36) REFERENCES permissions(id) ON DELETE CASCADE NOT NULL,
    granted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 2.25 Bảng Quên Mật Khẩu & Phiên Làm Việc (password_reset_tokens, user_sessions, family_memberships)
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    email_or_phone VARCHAR(255) NOT NULL,
    otp_code VARCHAR(20) NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    is_used BOOLEAN DEFAULT FALSE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS user_sessions (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    session_token VARCHAR(255) NOT NULL UNIQUE,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    revoked_at TIMESTAMP WITH TIME ZONE,
    ip_address VARCHAR(64),
    user_agent TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS family_memberships (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    family_id VARCHAR(36) REFERENCES families(id) ON DELETE CASCADE NOT NULL,
    membership_role VARCHAR(80) DEFAULT 'member' NOT NULL,
    status VARCHAR(32) DEFAULT 'active' NOT NULL,
    joined_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 3. KHỞI TẠO TÀI KHOẢN MẶC ĐỊNH (ADMIN & TRƯỞNG TỘC)

-- 3.1 Nạp tài khoản Admin vào bảng accounts & account_roles
INSERT INTO accounts (id, firebase_uid, username, email, display_name, password_hash, email_verified, status)
VALUES (
    'admin_default_001',
    'admin_default_001',
    'admin',
    'thuthaor120608@gmail.com',
    'Quản Trị Viên Hệ Thống',
    '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeg6Lruj3vjPGga31lW',
    TRUE,
    'active'
) ON CONFLICT (id) DO NOTHING;

INSERT INTO account_roles (id, account_id, role, status)
VALUES (
    'role_admin_default_001',
    'admin_default_001',
    'admin',
    'active'
) ON CONFLICT (id) DO NOTHING;

INSERT INTO admins (id, username, email, full_name, password_hash, admin_code, permissions_level, managed_scope, role, status)
VALUES (
    'admin_default_001',
    'admin',
    'thuthaor120608@gmail.com',
    'Quản Trị Viên Hệ Thống',
    '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeg6Lruj3vjPGga31lW',
    'ADM-001',
    'super_admin',
    'all_families',
    'admin',
    'active'
) ON CONFLICT (id) DO NOTHING;


-- 3.2 Nạp tài khoản Trưởng Tộc vào bảng accounts & account_roles & family_heads
INSERT INTO accounts (id, firebase_uid, username, email, display_name, password_hash, email_verified, status)
VALUES (
    'family_head_default_001',
    'family_head_default_001',
    'truongtoc',
    'truongtoc@gmail.com',
    'Trưởng Tộc Nguyễn Văn',
    '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeg6Lruj3vjPGga31lW',
    TRUE,
    'active'
) ON CONFLICT (id) DO NOTHING;

INSERT INTO account_roles (id, account_id, role, status)
VALUES (
    'role_fh_default_001',
    'family_head_default_001',
    'family_head',
    'active'
) ON CONFLICT (id) DO NOTHING;

INSERT INTO family_heads (id, username, email, full_name, password_hash, status)
VALUES (
    'family_head_default_001',
    'truongtoc',
    'truongtoc@gmail.com',
    'Trưởng Tộc Nguyễn Văn',
    '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeg6Lruj3vjPGga31lW',
    'active'
) ON CONFLICT (id) DO NOTHING;

-- 4. TẠO 3 VIEWS TRUY VẤN TRỰC QUAN TRONG PGADMIN 4
CREATE OR REPLACE VIEW vw_admins AS
SELECT id, username, full_name, email, phone, admin_code, permissions_level, managed_scope, status, created_at
FROM admins;

CREATE OR REPLACE VIEW vw_family_heads AS
SELECT fh.id, fh.username, fh.full_name, fh.email, fh.phone, fh.family_id, f.name AS family_name, fh.term_title, fh.status, fh.created_at
FROM family_heads fh
LEFT JOIN families f ON fh.family_id = f.id;

CREATE OR REPLACE VIEW vw_members AS
SELECT m.id, m.username, m.full_name, m.email, m.phone, m.gender, m.generation, m.branch, m.family_id, f.name AS family_name, m.is_alive, m.status, m.created_at
FROM members m
LEFT JOIN families f ON m.family_id = f.id;
