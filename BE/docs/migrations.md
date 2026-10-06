# Migration (Alembic)

> **Cảnh báo.** Hai revision dưới đây đã áp dụng lên nhánh **dev_minhquan** (06/10/2026, nhật ký ở mục 11). **Chưa chạy production.** Chỉ chạy production sau khi nhóm đồng ý (mục 5): dev đã diễn tập thành công.

## 1. Trạng thái

| Revision | Nội dung | Trạng thái |
| --- | --- | --- |
| `0001_baseline` | Rỗng. Ghi nhận "các bảng đã có sẵn" | Đã áp dụng lên dev_minhquan; production chưa |
| `0002_integrity_constraints` | KI-03, KI-04, KI-08 và unique `lower(email)` (mục 6) | Đã áp dụng lên dev_minhquan; production chưa |

Lịch sử là một đường thẳng: `0001_baseline` rồi `0002_integrity_constraints` (đầu duy nhất, có test).

## 2. Yêu cầu

- **PostgreSQL 15 trở lên.** `NULLS NOT DISTINCT` chỉ có từ bản 15. Revision 0002 tự kiểm phiên bản và dừng với thông báo rõ nếu thấp hơn. Nhánh dev hiện tại là PostgreSQL 18.6.
- Chạy bằng `.venv\Scripts\python.exe -m alembic ...` từ thư mục `BE`, với `DATABASE_URL` trong `.env` hoặc biến môi trường.
- Database đích đã có sẵn schema của dev (mục 3).

## 3. Baseline `0001` rỗng nghĩa là "các bảng đã có sẵn"

Revision `0001_baseline` không chứa lệnh nào. Nó chỉ tạo bảng `alembic_version` và ghi vào đó id `0001_baseline`. **`alembic upgrade` không tạo bảng nghiệp vụ**: một database mới tinh chạy `upgrade head` sẽ không có bảng nào, và 0002 sẽ dừng với thông báo thiếu bảng.

**`database/initial_schema.sql` không đủ để dựng schema hiện tại.** Đó là bản export cũ: nó thiếu các bảng như `user_sessions`, `credential_metadata`, `login_history`, `clan_memberships`, `clan_ownership_history`, `family_admin_permissions`, thiếu cột `users.username` và các index như `uq_active_user_role_scope`. Schema thật của nhánh dev được mô tả trong `docs/schema_user_access.txt` và `docs/schema_family.txt`, và `scripts/check_orm_vs_db.py` đối chiếu ORM với nó.

**Không dùng `initial_schema.sql` để dựng database mới** (file có dòng cảnh báo ở đầu; `docs/known_issues.md` KI-16). Hiện chưa có cách chuẩn để dựng một database mới giống dev. **Quyết định của trưởng nhóm:** làm sau Mốc E, bằng một trong hai cách: xuất `pg_dump --schema-only` từ nhánh dev làm file baseline, hoặc đưa DDL đầy đủ vào `0001`. Cho đến lúc đó, migration chỉ áp dụng được lên database đã có schema của dev.

## 4. Cơ chế an toàn

`alembic/env.py` chỉ cho chạy các lệnh **có kết nối database** (`upgrade`, `downgrade`, `stamp`, `current`) khi có đủ hai biến:

| Biến | Giá trị |
| --- | --- |
| `ALLOW_MIGRATE` | Đúng `1` |
| `MIGRATE_EXPECT_FINGERPRINT` | Fingerprint của database mà `DATABASE_URL` đang trỏ tới |

Thiếu biến hoặc sai fingerprint thì lệnh in fingerprint hiện tại rồi dừng **trước khi mở kết nối**; không đổi gì trong database. Thông báo chỉ có tên database và fingerprint, không bao giờ có host, user hay mật khẩu.

**Fingerprint** là 8 ký tự đầu của sha256 trên chuỗi `<host>/<tên database>`. Các nhánh Neon (dev, production) thường dùng cùng tên database nhưng khác host, nên fingerprint khác nhau: tên database một mình không đủ để biết đang ở nhánh nào.

Lấy fingerprint của `.env` hiện tại (chỉ-đọc, không kết nối database):

```powershell
.venv\Scripts\python.exe -m app.db.fingerprint
# database=<tên> fingerprint=<8 ký tự>
```

Chạy migration (PowerShell), sau khi đã xác nhận fingerprint đúng là của nhánh định chạy:

```powershell
$env:ALLOW_MIGRATE = "1"
$env:MIGRATE_EXPECT_FINGERPRINT = "<fingerprint đã xác nhận>"
.venv\Scripts\python.exe -m alembic upgrade head
Remove-Item Env:ALLOW_MIGRATE, Env:MIGRATE_EXPECT_FINGERPRINT
```

**Xem trước SQL** không kết nối database nên không cần hai biến trên (chỉ in tên database và fingerprint ra stderr):

```powershell
.venv\Scripts\python.exe -m alembic upgrade base:head --sql
.venv\Scripts\python.exe -m alembic upgrade 0001_baseline:0002_integrity_constraints --sql
.venv\Scripts\python.exe -m alembic downgrade 0002_integrity_constraints:0001_baseline --sql
```

Image Docker có chứa thư mục `alembic/` nhưng không đặt hai biến, nên container không tự chạy migration.

## 5. Quy trình: dev trước, production sau khi nhóm đồng ý

1. Đọc SQL xem trước (mục 4).
2. Lấy fingerprint, xác nhận đúng là nhánh dev.
3. Chạy `upgrade head` trên dev. Sau đó `scripts/check_orm_vs_db.py` (0 errors) và `pytest -m integration`.
4. Diễn tập hoàn tác trên dev: `downgrade -1` rồi `upgrade head`.
5. Cập nhật `docs/known_issues.md` (KI-03, KI-04, KI-08 chuyển thành "đã áp dụng lên dev, production chưa").
6. **Production chỉ sau khi nhóm đồng ý.** Trước đó: tạo snapshot hoặc nhánh sao lưu, chạy các truy vấn kiểm tra trùng ở mục 7 bằng tay, lấy fingerprint của production và xác nhận với người phụ trách. Không dùng chung fingerprint của dev.

## 6. Revision `0002_integrity_constraints` làm gì

| Việc | SQL | Ghi chú |
| --- | --- | --- |
| KI-03 | `DROP INDEX uq_active_user_role_scope` rồi `CREATE UNIQUE INDEX uq_active_user_role_scope ON user_roles (user_id, role_id, clan_id) NULLS NOT DISTINCT WHERE revoked_at IS NULL` | Cùng tên, nên ORM và `check_orm_vs_db.py` không đổi tên. Từ nay một user không thể có hai dòng `SYSTEM_ADMIN` còn hiệu lực |
| KI-04 | `CREATE UNIQUE INDEX uq_user_sessions_token_jti_hash ON user_sessions (token_jti_hash)` | Cột vẫn cho NULL; nhiều phiên không có hash không xung đột |
| KI-08 | `CREATE UNIQUE INDEX uq_family_admin_active_assignment ON family_admin_assignments (clan_id, user_id, branch_id) NULLS NOT DISTINCT WHERE revoked_at IS NULL` | `branch_id` NULL (toàn clan) tính là một giá trị. Khóa dòng membership trong code vẫn giữ |
| Email | `CREATE UNIQUE INDEX uq_users_email_lower ON users (lower(email))` | `users_email_key` (so khớp chính xác) vẫn còn. Chỉ `users.email` có unique; các cột email khác (`account_invitations.email`, `business_registrations.representative_email`, `email_delivery_logs.recipient_email`, `person_contacts.email`) cố ý không có, vì một địa chỉ được phép lặp |

Thứ tự trong một lần chạy online, trước mọi DDL: (1) phiên bản PostgreSQL, (2) schema baseline có đủ bảng và index cũ, (3) không có dòng trùng. Rồi `SET LOCAL lock_timeout = '5s'` và các lệnh trên. Mỗi revision chạy trong một transaction riêng (`transaction_per_migration`): nếu 0002 dừng thì baseline vẫn được ghi nhận và 0002 không đổi gì.

`CREATE INDEX` **không** dùng `CONCURRENTLY`, nên khi xây index bảng bị chặn ghi. Với dữ liệu Sprint 1 thì không đáng kể. Nếu bảng production lớn, cần viết lại thành `CONCURRENTLY` ngoài transaction (`autocommit_block`) trước khi chạy.

## 7. Khi migration dừng vì dữ liệu trùng

Migration in nhóm trùng của KI-03 và KI-08 (chỉ UUID) và chỉ in **số nhóm** cho KI-04 và email (không in token hash hay địa chỉ email). Không có gì bị đổi. Cách xử lý, luôn bằng tay và có người xem lại:

- **Không xóa dòng.** Giữ dòng cũ nhất, đặt `revoked_at` cho các dòng thừa của `user_roles` và `family_admin_assignments`. Với assignment, thu hồi kèm xóa các dòng `family_admin_permissions` của nó, đúng như `DELETE /clans/{id}/admins/{user_id}`.
- Phiên trùng hash: thu hồi một trong các phiên (`revoked_at`).
- Email trùng không phân biệt hoa/thường: hai tài khoản thật khác nhau cần người quyết định, không có cách tự động đúng.

Truy vấn chỉ-đọc để xem (đúng như migration dùng):

```sql
-- KI-03
SELECT user_id, role_id, clan_id, count(*) FROM user_roles WHERE revoked_at IS NULL
GROUP BY user_id, role_id, clan_id HAVING count(*) > 1;
-- KI-04
SELECT count(*) FROM user_sessions WHERE token_jti_hash IS NOT NULL
GROUP BY token_jti_hash HAVING count(*) > 1;
-- KI-08
SELECT clan_id, user_id, branch_id, count(*) FROM family_admin_assignments WHERE revoked_at IS NULL
GROUP BY clan_id, user_id, branch_id HAVING count(*) > 1;
-- email (kết quả chứa email: dữ liệu cá nhân, đừng dán vào chat hay ticket)
SELECT lower(email), count(*) FROM users GROUP BY lower(email) HAVING count(*) > 1;
```

## 8. Hoàn tác

`alembic downgrade 0001_baseline` bỏ bốn index mới và dựng lại `uq_active_user_role_scope` đúng như trước (NULL khác nhau). Hoàn tác chỉ nới ràng buộc nên không bao giờ lỗi vì dữ liệu. `downgrade base` chỉ xóa dòng trong `alembic_version`; bảng `alembic_version` vẫn còn.

## 9. Việc cho các mốc sau

- **Mốc E (đăng ký, tạo user):** khi tạo `users`, phải bắt `IntegrityError` của `uq_users_email_lower` (và `users_email_key`) và trả `409`. `get_user_by_email` cố ý vẫn so khớp **chính xác** (quyết định 24: email không bị lowercase), nên nó không tìm thấy `A@x.com` khi đã có `a@x.com`; chỉ DB chặn được trường hợp đó. Xem `docs/known_issues.md` KI-15.
- Code tạo assignment FA vẫn giữ khóa dòng membership: khóa biến cuộc đua thành `409` sạch, còn unique index là lớp cuối. Nhánh `409` của `PUT .../permissions` khi có nhiều assignment toàn clan không còn đạt được trên DB đã migrate, nhưng giữ lại cho DB chưa migrate.

## 10. Test liên quan

| Test | Nội dung |
| --- | --- |
| `tests/test_migration_guard.py` (không cần DB) | Fingerprint, guard (hàm và qua `python -m alembic` thật với host không tồn tại), SQL xem trước, lịch sử revision, kiểm tra tiền điều kiện của 0002, không có câu lệnh chỉ chứa chú thích |
| `tests/integration/test_db_constraints.py` | KI-04, KI-08, email, định nghĩa thật của bốn index trong `pg_indexes`, truy vấn kiểm tra trùng chạy trên dữ liệu thật |
| `tests/integration/test_user_roles_unique_index.py` | KI-03 (hết `xfail`) |

Các test tích hợp mới **cần migration đã áp dụng** lên database chúng chạy; trên database chưa migrate chúng fail, và đó là cách phát hiện thiếu migration.

## 11. Nhật ký đã áp dụng

### 06/10/2026: dev_minhquan

Đích: `database=mfgms_ai`, fingerprint `3ff0cec7` (trưởng nhóm xác nhận đây là nhánh dev_minhquan). `ALLOW_MIGRATE=1` và `MIGRATE_EXPECT_FINGERPRINT=3ff0cec7` chỉ đặt trong lệnh chạy, **không ghi vào `.env`**. Trước khi chạy: PostgreSQL 18.6, 0 dòng trong `users`, `user_sessions`, `user_roles`, `family_admin_assignments`, 0 dòng trùng, chưa có `alembic_version`.

| Bước | Lệnh | Kết quả |
| --- | --- | --- |
| 1 | `alembic upgrade head` | Chạy `0001_baseline` rồi `0002_integrity_constraints`, thoát 0. `alembic current` ra `0002_integrity_constraints (head)` |
| 2 | Truy vấn `pg_indexes` (chỉ đọc) | Bốn index đúng định nghĩa, bên dưới. `NULLS NOT DISTINCT` có ở hai index cần có; `users_email_key` vẫn còn |
| 3 | `scripts/check_orm_vs_db.py` | 0 errors, 0 INFO |
| 4 | `alembic downgrade -1` | `uq_active_user_role_scope` dựng lại đúng như cũ (không `NULLS NOT DISTINCT`), ba index mới biến mất, `alembic_version` = `0001_baseline` |
| 4 | `alembic upgrade head` lần hai | Thoát 0; `alembic current` ra `0002_integrity_constraints (head)`; định nghĩa bốn index giống bước 2 |
| 5 | `pytest -q` | 363 passed, 155 deselected |
| 6 | `ALLOW_DB_TESTS=1 pytest -m integration` (một lần) | 155 passed, 0 failed, 0 xfailed, 21 phút 31 giây. DB sau đó: 0 user, 0 clan, 0 audit_logs, 0 phiên; `roles`/`permissions`/`role_permissions` = 4/18/0 |

Định nghĩa bốn index trên dev sau khi áp dụng:

```
uq_active_user_role_scope         CREATE UNIQUE INDEX uq_active_user_role_scope ON public.user_roles USING btree (user_id, role_id, clan_id) NULLS NOT DISTINCT WHERE (revoked_at IS NULL)
uq_user_sessions_token_jti_hash   CREATE UNIQUE INDEX uq_user_sessions_token_jti_hash ON public.user_sessions USING btree (token_jti_hash)
uq_family_admin_active_assignment CREATE UNIQUE INDEX uq_family_admin_active_assignment ON public.family_admin_assignments USING btree (clan_id, user_id, branch_id) NULLS NOT DISTINCT WHERE (revoked_at IS NULL)
uq_users_email_lower              CREATE UNIQUE INDEX uq_users_email_lower ON public.users USING btree (lower((email)::text))
```

Production: **chưa chạy**. Cần nhóm đồng ý, snapshot hoặc nhánh sao lưu, truy vấn kiểm tra trùng ở mục 7, và fingerprint riêng của production (mục 5).
