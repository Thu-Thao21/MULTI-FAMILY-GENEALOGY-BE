"""
Script Reset toàn bộ dữ liệu nghiệp vụ test trên Neon PostgreSQL DEV.
Đảm bảo:
- Xóa toàn bộ dữ liệu nghiệp vụ (Clan, Branch, Person, Relationship, Closure, Business Registrations, User test...)
- Giữ nguyên toàn bộ Schema: Tables, Columns, Constraints, Indexes, Foreign Keys, alembic_version.
- Giữ nguyên các bảng seed hệ thống bắt buộc: roles, permissions, role_permissions, subscription_plans, plan_feature_limits.
- Tạo đúng 1 tài khoản System Admin mặc định:
    Email: thuthaor120608@gmail.com
    Password: (Firebase: 12060805)
    Firebase UID: Kt23xmxKJ6Stne3GEOerJ5ParHE3
    Role: SYSTEM_ADMIN
    Status: ACTIVE
"""

import sys
import os
import uuid
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asyncio
from sqlalchemy import text
from app.db.postgres import async_session_maker

BUSINESS_TABLES_TO_RESET = [
    # Giao dịch, audit, session, notifications
    "user_sessions",
    "login_history",
    "audit_logs",
    "idempotency_keys",
    "user_notifications",
    "notification_preferences",
    "notifications",
    "email_delivery_attempts",
    "email_delivery_logs",
    "password_reset_tokens",
    "scheduled_reminders",
    "violation_reports",
    "support_access_grants",
    # AI & Imports / Exports / Backups
    "ai_messages",
    "ai_conversations",
    "ai_suggestion_reviews",
    "ai_suggestions",
    "ai_jobs",
    "ai_consents",
    "import_errors",
    "import_jobs",
    "export_jobs",
    "restore_jobs",
    "backup_jobs",
    # Phòng thờ số & Tư liệu số
    "virtual_incense",
    "memorial_messages",
    "media_360_items",
    "three_d_items",
    "worship_artifacts",
    "worship_persons",
    "worship_spaces",
    "relationship_evidence",
    "person_documents",
    "event_documents",
    "fund_transaction_documents",
    "document_access_policies",
    "documents",
    "document_categories",
    # Sự kiện & Quỹ
    "event_participants",
    "events",
    "contributions",
    "fund_transactions",
    "fund_categories",
    "funds",
    "death_anniversaries",
    "anniversary_follows",
    # Liên họ & Yêu cầu thay đổi
    "inter_clan_shared_policies",
    "inter_clan_links",
    "inter_clan_requests",
    "change_requests",
    "request_reviews",
    # Gia phả, quan hệ, nhân khẩu
    "duplicate_person_suggestions",
    "person_merge_history",
    "person_privacy_settings",
    "person_professional_profiles",
    "person_account_links",
    "person_aliases",
    "person_contacts",
    "account_invitations",
    "person_closure",
    "relationships",
    "persons",
    "branches",
    # Hồ sơ dòng họ & phân quyền
    "family_admin_permissions",
    "family_admin_assignments",
    "clan_memberships",
    "clan_ownership_history",
    "ownership_transfers",
    "clan_privacy_settings",
    "clan_profiles",
    "public_contents",
    "provisioning_jobs",
    "registration_attachments",
    "registration_status_history",
    "business_registrations",
    "clan_subscriptions",
    "invoices",
    "payments",
    "subscription_changes",
    "clans",
    # Phân quyền user & credential metadata
    "user_roles",
    "credential_metadata",
    "users",
]

ADMIN_USER_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
ADMIN_FIREBASE_UID = "Kt23xmxKJ6Stne3GEOerJ5ParHE3"
ADMIN_EMAIL = "thuthaor120608@gmail.com"
ADMIN_DISPLAY_NAME = "Thu Thảo (System Admin)"

async def reset_database():
    async with async_session_maker() as session:
        print("==================================================")
        print("BẮT ĐẦU RESET TOÀN BỘ DỮ LIỆU TEST TRÊN NEON DB...")
        print("==================================================")

        # 1. Truncate toàn bộ bảng nghiệp vụ
        table_list_sql = ", ".join(BUSINESS_TABLES_TO_RESET)
        print(f"1. Đang dọn sạch {len(BUSINESS_TABLES_TO_RESET)} bảng nghiệp vụ...")
        await session.execute(text(f"TRUNCATE TABLE {table_list_sql} CASCADE;"))
        print("   -> Đã xóa toàn bộ dữ liệu nghiệp vụ thành công. Schema được bảo toàn nguyên vẹn.")

        # 2. Kiểm tra các bảng seed hệ thống
        roles_cnt = await session.execute(text("SELECT count(*) FROM roles"))
        perms_cnt = await session.execute(text("SELECT count(*) FROM permissions"))
        plans_cnt = await session.execute(text("SELECT count(*) FROM subscription_plans"))
        print(f"2. Kiểm tra dữ liệu hệ thống:")
        print(f"   - Roles: {roles_cnt.scalar()} (Được bảo toàn)")
        print(f"   - Permissions: {perms_cnt.scalar()} (Được bảo toàn)")
        print(f"   - Subscription Plans: {plans_cnt.scalar()} (Được bảo toàn)")

        # 3. Tạo tài khoản System Admin mặc định
        print(f"3. Đang tạo tài khoản System Admin mặc định: {ADMIN_EMAIL}...")
        await session.execute(text("""
            INSERT INTO users (
                user_id, firebase_uid, email, display_name, status,
                email_verified, phone_verified, first_login_required,
                created_at, updated_at
            )
            VALUES (
                :uid, :fb_uid, :email, :name, 'ACTIVE',
                true, false, false,
                NOW(), NOW()
            )
        """), {
            "uid": ADMIN_USER_ID,
            "fb_uid": ADMIN_FIREBASE_UID,
            "email": ADMIN_EMAIL,
            "name": ADMIN_DISPLAY_NAME,
        })

        await session.execute(text("""
            INSERT INTO credential_metadata (
                user_id, must_change_password, temporary_password_issued_at,
                temporary_password_expires_at, password_changed_at
            )
            VALUES (
                :uid, false, NULL, NULL, NOW()
            )
        """), {"uid": ADMIN_USER_ID})

        # Gán quyền SYSTEM_ADMIN
        role_res = await session.execute(text("SELECT role_id FROM roles WHERE code = 'SYSTEM_ADMIN'"))
        sa_role_id = role_res.scalar()
        if not sa_role_id:
            raise RuntimeError("Không tìm thấy role SYSTEM_ADMIN trong bảng roles!")

        await session.execute(text("""
            INSERT INTO user_roles (
                user_role_id, user_id, role_id, clan_id, granted_by, granted_at, revoked_at
            )
            VALUES (
                gen_random_uuid(), :uid, :rid, NULL, :uid, NOW(), NULL
            )
        """), {
            "uid": ADMIN_USER_ID,
            "rid": sa_role_id,
        })
        print("   -> Đã gán quyền SYSTEM_ADMIN thành công.")

        await session.commit()

        # 4. Xác minh lại số lượng sau khi reset
        clans_c = (await session.execute(text("SELECT count(*) FROM clans"))).scalar()
        persons_c = (await session.execute(text("SELECT count(*) FROM persons"))).scalar()
        branches_c = (await session.execute(text("SELECT count(*) FROM branches"))).scalar()
        rels_c = (await session.execute(text("SELECT count(*) FROM relationships"))).scalar()
        users_c = (await session.execute(text("SELECT count(*) FROM users"))).scalar()

        print("\n==================================================")
        print("KẾT QUẢ SAU RESET:")
        print(f" - clans: {clans_c} (SẠCH)")
        print(f" - branches: {branches_c} (SẠCH)")
        print(f" - persons: {persons_c} (SẠCH)")
        print(f" - relationships: {rels_c} (SẠCH)")
        print(f" - users: {users_c} (Duy nhất 1 tài khoản System Admin mặc định: {ADMIN_EMAIL})")
        print("==================================================")

if __name__ == "__main__":
    asyncio.run(reset_database())
