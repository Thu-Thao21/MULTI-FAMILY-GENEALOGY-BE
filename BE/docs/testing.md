# Chạy seed và test

Chạy từ thư mục `BE`, dùng `.venv\Scripts\python.exe`. Biến môi trường PowerShell chỉ có hiệu lực trong cửa sổ hiện tại. `DATABASE_URL` lấy từ `BE/.env`; không in và không commit.

## 0. Cấu hình Firebase (Mốc D) — máy dev có `.env` cũ cần sửa

- `FIREBASE_CREDENTIALS_PATH` **đã đổi tên** thành `FIREBASE_SERVICE_ACCOUNT_PATH`. Tên cũ bị bỏ qua im lặng, nên `.env` cũ sẽ chạy như không có service account (đổi mật khẩu trả `503`).
- `FIREBASE_PROJECT_ID` **không còn giá trị mặc định**. Thiếu thì app vẫn khởi động, nhưng `POST /auth/session` trả `503 PROVIDER_UNAVAILABLE` (fail closed).
- `FIREBASE_SERVICE_ACCOUNT_PATH` chỉ cần cho Admin API (đổi mật khẩu, kiểm tra token bị thu hồi). File không commit; `.gitignore` đã chặn `*service-account*.json` và `*firebase-adminsdk*.json`.
- Không đặt `FIREBASE_AUTH_EMULATOR_HOST`: ở chế độ emulator, SDK nhận token không chữ ký, nên backend từ chối toàn bộ (`503`).
- Test **không** đọc cấu hình Firebase/CORS từ `.env`: `tests/conftest.py` tự đặt `FIREBASE_PROJECT_ID=test-project`, `FIREBASE_SERVICE_ACCOUNT_PATH=` (rỗng), `FRONTEND_ORIGINS=http://localhost:5173,http://localhost:8080` và xóa biến emulator. (`DATABASE_URL` vẫn lấy từ `.env`: app cần nó để import; test thường không kết nối.)
- **Kiểm tra cấu hình khi khởi động** (Mốc G): thiếu `FIREBASE_PROJECT_ID`, có `FIREBASE_AUTH_EMULATOR_HOST`, `FIREBASE_SERVICE_ACCOUNT_PATH` trỏ file không tồn tại, hoặc `FRONTEND_ORIGINS` chứa `*` thì app **dừng ngay khi khởi động** (sự kiện startup, không phải lúc import). Thông báo chỉ nêu tên biến, không nêu giá trị. Không test nào gọi Firebase thật; luồng đăng nhập dùng `FakeIdentityProvider` trong `tests/fakes.py`.

## 1. Test thường (không cần database)

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Dùng fake trong `tests/fakes.py`. Nhóm `integration` bị loại mặc định (`addopts = -m "not integration"` trong `pytest.ini`), nên thấy dòng `N deselected`.

## 2. Test tích hợp trên PostgreSQL thật

```powershell
$env:ALLOW_DB_TESTS = "1"
.venv\Scripts\python.exe -m pytest -m integration -q
```

- Thiếu `ALLOW_DB_TESTS=1` thì toàn bộ nhóm này bị skip. Thiếu `-m integration` thì không chạy.
- Mỗi test chạy trong một transaction và ROLLBACK ở cuối; dữ liệu tự tạo, không phụ thuộc seed. Không DDL, không ghi `roles`, `permissions`, `role_permissions` (chỉ SELECT role theo code).
- Kết nối tới Neon chậm (vài giây mỗi lần mở, ~0,3 giây mỗi truy vấn), cả nhóm chạy vài phút.
- **Cần migration đã áp dụng (gói migration, `docs/migrations.md`; đã áp dụng lên dev_minhquan ngày 06/10/2026):** `test_db_constraints.py`, `test_db_provisioning.py` (migration 0003, áp dụng lên dev ngày 06/10/2026), `test_user_roles_unique_index.py` (KI-03), `test_db_rejects_a_duplicate_token_hash` (`test_sessions_db.py`), `test_duplicate_sa_grant_is_rejected_by_the_db_and_the_count_stays_one` (`test_system_admin_guard.py`) và vài test Family Admin đã đổi theo KI-08 (`test_user_admin_db.py`, `test_family_admin_lifecycle_db.py`, `test_family_admin_concurrency.py`) kỳ vọng DB đã có bốn index mới. Trên DB **chưa** migrate chúng fail, và đó là cách phát hiện thiếu migration. `tests/test_migration_guard.py` không cần DB.
- **Gói `DEV-` đã seed trên dev (Mốc E, E3):** các test tích hợp của hồ sơ đăng ký và seed gói (`test_registration_db.py`, `test_registration_concurrency.py`, `test_seed_plans.py`) **không bao giờ xóa hay sửa gói `DEV-`**. Mỗi test tự tạo gói riêng (`ITEST-...`, hoặc tiền tố `DEV-ITEST-<mã>-` cho test cleanup) và chỉ đếm hoặc liệt kê gói theo tiền tố của chính nó. Test cleanup luôn truyền tiền tố riêng; cleanup mặc định (tiền tố `DEV-`) không test nào gọi.
- Bỏ test đồng thời: `-m "integration and not concurrency"`. Chỉ chạy test đồng thời: `-m concurrency`.
- Test `concurrency` **commit thật**, dùng user `itest-conc-*` và xóa trong `finally`. Chúng cần DB không còn System Admin ACTIVE nào khác (guard đếm toàn bộ); nếu có (ví dụ SA của seed dev) thì tự skip và nêu lý do. Muốn chạy: `seed_dev.py --cleanup` trước, hoặc dùng nhánh DB riêng.
- **Trước khi chạy, dọn seed** (`seed_dev.py --cleanup`): khi DB còn System Admin ACTIVE khác (ví dụ `dev-sa`), 3 test "SA cuối" trong `test_last_sa_concurrency.py` tự skip.
- `test_user_admin_db.py` và `test_user_admin_concurrency.py` (Mốc F) dùng router thật `user_admin_router`. Test đồng thời **commit thật** (user `itest-conc-*` cùng các dòng audit_logs của chúng, xóa trong `finally`), cần DB không còn SA khác, và gồm một test đối chứng (`test_control_user_row_first_with_for_update_deadlocks`) phải thấy deadlock thật để chứng minh các test còn lại bắt được lỗi thứ tự khóa.
- `test_auth_flow_db.py` dùng router auth thật (`app/controllers/auth_access`) với DB thật và Firebase giả. Các route `/admin/users`, `/clans/{id}/users` trong `tests/integration/factory.py` vẫn là app mini để thử dependency phân quyền (chưa có endpoint nghiệp vụ thật).

## 3. Seed dữ liệu dev

```powershell
$env:ALLOW_DEV_SEED = "1"
.venv\Scripts\python.exe scripts\seed_dev.py            # tạo / bổ sung (chạy lại an toàn)
.venv\Scripts\python.exe scripts\seed_dev.py --cleanup  # xóa chỉ dữ liệu DEV-*
```

Thiếu `ALLOW_DEV_SEED=1` script thoát ngay.

**Đăng nhập thật bằng `dev-sa` (tùy chọn):** đặt UID của một tài khoản Firebase dev trong biến môi trường trước khi seed. Giá trị chỉ nằm trong biến môi trường của cửa sổ đó; **không ghi UID thật vào code, docs, test hay `.env.example`**. Seed không in giá trị này.

```powershell
$env:ALLOW_DEV_SEED = "1"
$env:DEV_SA_FIREBASE_UID = "<UID trong Firebase Console > Authentication>"
.venv\Scripts\python.exe scripts\seed_dev.py
Remove-Item Env:DEV_SA_FIREBASE_UID
```

Không đặt biến thì `dev-sa` mới dùng UID giả `dev-sa`; `dev-sa` đã gắn UID thật từ trước thì giữ nguyên. Nếu UID đã thuộc user khác, seed dừng. Các user dev khác luôn dùng UID giả nên không đăng nhập thật được. Seed chạy trong một transaction, in số bản ghi "tạo mới" và "đã có", không in bí mật. Không có password, không có phiên/token.

Dữ liệu nhận diện bằng tiền tố: dòng họ `DEV-*`, user `dev-*@example.test` với `firebase_uid` `dev-*`.

| User | Vai trò |
| --- | --- |
| dev-sa | SYSTEM_ADMIN (clan_id NULL) |
| dev-bo-a | BUSINESS_OWNER của DEV-CLAN-A (ACTIVE): role + ownership còn hiệu lực + membership ACTIVE |
| dev-bo-b | BUSINESS_OWNER của DEV-CLAN-B (PENDING, chưa ACTIVE): như trên |
| dev-fa-a | FAMILY_ADMIN của clan A: membership ACTIVE + assignment (cả clan) + `MEMBER_ACCOUNT_MANAGE` |
| dev-member-a | FAMILY_MEMBER của clan A |
| dev-member-b | FAMILY_MEMBER của clan B (kiểm tra cô lập clan) |
| dev-locked-a | Tài khoản `LOCKED`, thành viên clan A |

`--cleanup` xóa dòng họ `DEV-*` (membership, ownership, assignment xóa theo cascade) rồi user `dev-*@example.test` (kể cả `dev-sa` đã gắn UID thật; tài khoản Firebase không bị đụng tới). Nếu user dev đã được tham chiếu bởi bảng khác không cascade thì xóa lỗi và rollback toàn bộ.

## 4. Thử tay với token Firebase thật (không tự động hóa)

**Chưa có test tự động nào xác minh chữ ký trên token Firebase thật.** Test tự động chỉ chứng minh: SDK thật từ chối token giả mạo/không chữ ký mà không cần mạng, token RS256 hợp lệ về hình thức luôn được đưa tới bước kiểm chữ ký theo chứng chỉ `securetoken`, và cấu hình thiếu thì fail closed. Bước dưới đây là cách kiểm chứng phần còn lại bằng tay trên máy dev.

1. `.env` có `FIREBASE_PROJECT_ID` đúng project. Muốn thử đổi mật khẩu thì có thêm `FIREBASE_SERVICE_ACCOUNT_PATH`.
2. Seed `dev-sa` với `DEV_SA_FIREBASE_UID` của một tài khoản **dev** (mục 3).
3. Chạy app: `.venv\Scripts\python.exe -m uvicorn app.main:app --port 8001`.
4. Lấy ID token từ FE (sau khi đăng nhập bằng Firebase SDK: `await auth.currentUser.getIdToken()` trong console trình duyệt của FE dev). Token là bí mật: không dán vào chat, issue, log hay file trong repo.
5. Đổi token lấy phiên, rồi gọi `/auth/me`:

```powershell
$idToken = Read-Host "Firebase ID token" -AsSecureString
$plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($idToken))
$s = Invoke-RestMethod -Method Post -Uri http://localhost:8001/api/v1/auth/session -ContentType "application/json" -Body (@{ id_token = $plain } | ConvertTo-Json)
Invoke-RestMethod -Uri http://localhost:8001/api/v1/auth/me -Headers @{ Authorization = "Bearer $($s.access_token)" }
Invoke-RestMethod -Method Post -Uri http://localhost:8001/api/v1/auth/logout -Headers @{ Authorization = "Bearer $($s.access_token)" }
Remove-Variable plain, idToken, s
```

Kết quả mong đợi:

| Thử | Mong đợi |
| --- | --- |
| Token thật, UID đã seed | `201`, rồi `/auth/me` trả `200` với role SA |
| Sửa 1 ký tự trong phần chữ ký của token | `401 INVALID_ID_TOKEN` |
| Token của project Firebase khác | `401 INVALID_ID_TOKEN` |
| Token hết hạn (để quá 1 giờ) | `401 INVALID_ID_TOKEN` |
| Token thật nhưng UID chưa seed | `401 INVALID_ID_TOKEN`, không có dòng mới trong `users` |
| Gỡ `FIREBASE_PROJECT_ID` rồi khởi động lại | `503 PROVIDER_UNAVAILABLE` |
| Sau `logout`, gọi lại `/auth/me` | `401 SESSION_INVALID` |

## 5. Số liệu chạy mới nhất (Mốc F2, 06/10/2026)

Chạy từ `BE`, Python 3.13.7, `.venv` của dự án, sau `seed_dev.py --cleanup` (DB không còn dữ liệu seed, nên mọi test "SA cuối" chạy chứ không skip).

| Lệnh | Kết quả |
| --- | --- |
| `pytest -q` | **320 passed, 137 deselected** (nhóm `integration`), 0 failed |
| `ALLOW_DB_TESTS=1 pytest -m integration -q` | **136 passed, 1 xfailed** (KI-03, đúng dự kiến), 0 skipped, 0 failed, 23 phút 11 giây |
| `python -c "import app.main"` | MAIN OK |
| `scripts/check_orm_vs_db.py` | 0 errors, 0 INFO |

Tổng cộng 457 test. Sau lần chạy, DB không còn dòng rác: 0 user, 0 clan, 0 audit_logs, 0 phiên; `roles`/`permissions`/`role_permissions` giữ nguyên (4/18/0). Mốc F2 thêm: nhóm test vòng đời Family Admin (đơn vị, DB thật, đồng thời) và test dev seed vẫn nhất quán. Test cũ của Mốc F `test_every_code_in_the_permissions_table_is_accepted` (ủy quyền mọi mã, kể cả `ADMIN_MANAGE`) đã đổi thành `test_every_delegable_code_in_the_permissions_table_is_accepted` theo quyết định Q1: mọi mã trừ `ADMIN_MANAGE` được nhận, thêm `ADMIN_MANAGE` thì `403`.

### Mốc E, bước E3: Guest, bộ giới hạn tần suất, seed gói (07/10/2026)

Chạy trên nhánh dev (`0003_provisioning_idempotency`), sau khi seed ba gói `DEV-` (`seed_dev.py --plans-only`, chạy hai lần: lần một tạo 3 gói và 6 dòng tính năng, lần hai tạo 0 dòng).

| Lệnh | Kết quả |
| --- | --- |
| `pytest -q` | **671 passed**, 270 deselected (nhóm `integration`), 0 failed. Thêm 254 test so với E2 (417) |
| `ALLOW_DB_TESTS=1 pytest -m integration` ba file mới (`test_registration_db.py`, `test_registration_concurrency.py`, `test_seed_plans.py`) | Lần đầu 42 passed, 1 failed: lỗi của test (sau `rollback()` các đối tượng ORM hết hạn nên test đọc lại `plan.plan_id` bị `MissingGreenlet`; mã ứng dụng không dính vì use case lấy `plan_id` từ trước). Sửa test, chạy lại riêng test đó: pass. 43 test của ba file đều pass |
| `ALLOW_DB_TESTS=1 pytest -m integration -q` (cả bộ, một lần) | **270 passed**, 0 failed, 0 skipped, **0 xfailed**, 31 phút 57 giây. Thêm 48 test so với E2 (222): 25 đăng ký trên DB thật, 7 đồng thời, 11 seed, 5 trường lý do |
| `scripts/check_orm_vs_db.py` | 0 errors, 0 INFO |
| `python -c "import app.main"` | MAIN OK |

Tổng cộng 941 test (671 + 270). Sau lần chạy, DB dev: 0 user, 0 clan, 0 hồ sơ đăng ký, 0 lịch sử trạng thái, 0 audit_logs, 0 provisioning_jobs, 0 idempotency_keys, 0 clan_subscriptions; `subscription_plans` đúng **3** (`DEV-TRIAL`, `DEV-STANDARD`, `DEV-LEGACY`) với 6 dòng `plan_feature_limits`, giữ nguyên định nghĩa đã seed; `roles`/`permissions`/`role_permissions` = 4/18/0; `alembic_version` = `0003_provisioning_idempotency`.

### Mốc E, bước E2: migration 0003 đã áp dụng lên dev_minhquan (06/10/2026)

Chạy sau `alembic upgrade head` lên nhánh dev (`0003_provisioning_idempotency`), DB không còn dữ liệu seed.

| Lệnh | Kết quả |
| --- | --- |
| `pytest -q` | **417 passed**, 222 deselected (nhóm `integration`), 0 failed. Thêm 54 test so với gói migration 0002: `test_migration_0003.py` |
| `ALLOW_DB_TESTS=1 pytest -m integration tests/integration/test_db_provisioning.py` | Lần đầu 65 passed, 2 failed (lỗi của test: cột `varchar` từ chối chuỗi quá dài bằng lỗi kiểu dữ liệu trước khi CHECK được xét); sửa test, chạy lại **67 passed** |
| `ALLOW_DB_TESTS=1 pytest -m integration -q` (cả bộ, một lần) | **222 passed**, 0 failed, 0 skipped, **0 xfailed**, 24 phút 04 giây |
| `scripts/check_orm_vs_db.py` | 0 errors, 0 INFO |
| `python -c "import app.main"` | MAIN OK |

Tổng cộng 639 test (417 + 222). So với gói migration 0002: thêm 67 test tích hợp (`test_db_provisioning.py`) và 54 test không cần DB (`test_migration_0003.py`); `test_migration_guard.py` chỉ đổi một test (kiểm đầu chuỗi revision), không đổi số lượng. Sau lần chạy, DB không còn dòng rác: 0 user, 0 clan, 0 job, 0 khóa idempotency, 0 audit_logs, 0 hồ sơ đăng ký; `roles`/`permissions`/`role_permissions` giữ nguyên (4/18/0); `alembic_version` = `0003_provisioning_idempotency`. `subscription_plans` trên dev có 0 dòng: test tích hợp tự tạo gói trong giao dịch rollback; các bước E3 trở đi cần dữ liệu gói để chạy luồng thật.

Kiểm chứng test bằng đột biến (áp dụng, chạy test, khôi phục, kiểm sha256) cho `test_migration_0003.py`: 32 đột biến, đều bị bắt. Gồm bỏ hoặc nới `provisioning_jobs_firebase_uid_check` (A2), bỏ `needs_cleanup` khỏi hai index và khỏi CHECK (A5), bỏ từng bước kiểm tra tiền điều kiện, in email trong báo cáo trùng, thêm cột mật khẩu, câu lệnh chỉ chứa chú thích, `CONCURRENTLY`, ORM lệch migration, và năm đột biến cho việc downgrade từ chối khi còn job `needs_cleanup` (bỏ kiểm tra, kiểm tra sau cảnh báo, đếm mọi job, cho lọt một dòng, thông báo nêu uid).

### Gói migration, sau khi áp dụng lên dev_minhquan (06/10/2026, trước Mốc E)

Chạy sau `alembic upgrade head` lên nhánh dev (`0002_integrity_constraints`), DB không còn dữ liệu seed.

| Lệnh | Kết quả |
| --- | --- |
| `pytest -q` | **363 passed**, 155 deselected (nhóm `integration`), 0 failed. Thêm 43 test so với Mốc F2: 42 trong `test_migration_guard.py` và 1 test thua cuộc đua trên index assignment |
| `ALLOW_DB_TESTS=1 pytest -m integration -q` | **155 passed**, 0 failed, 0 skipped, **0 xfailed**, 21 phút 31 giây (một lần duy nhất) |
| `scripts/check_orm_vs_db.py` | 0 errors, 0 INFO (ba index mới đã có ở cả ORM và DB) |
| `python -c "import app.main"` | MAIN OK |

Tổng cộng 518 test (363 + 155). So với Mốc F2: `1 xfailed` của KI-03 biến mất (test SA trùng nay pass thật), thêm 16 test tích hợp mới trong `test_db_constraints.py` và 2 test ròng trong `test_user_roles_unique_index.py` (5 thành 7). Sau lần chạy, DB không còn dòng rác: 0 user, 0 clan, 0 audit_logs, 0 phiên; `roles`/`permissions`/`role_permissions` giữ nguyên (4/18/0); `alembic_version` = `0002_integrity_constraints`. Diễn tập `downgrade -1` rồi `upgrade head`: xem `docs/migrations.md` mục 11.

### Số liệu Mốc G (trước F2, giữ để so sánh)

Chạy từ `BE`, Python 3.13.7, `.venv` của dự án, sau `seed_dev.py --cleanup` (DB không còn dữ liệu seed, nên 3 test "SA cuối" chạy chứ không skip).

| Lệnh | Kết quả |
| --- | --- |
| `pytest -q` | **283 passed**, 117 deselected (nhóm `integration`), 0 failed, ~30 giây |
| `ALLOW_DB_TESTS=1 pytest -m integration -q` | **116 passed, 1 xfailed** (KI-03, đúng dự kiến), 0 skipped, 0 failed, 16 phút 9 giây |
| `python -c "import app.main"` | MAIN OK |
| `scripts/check_orm_vs_db.py` | 0 errors, 0 INFO |
| `docker build` (Python 3.13-slim, phiên bản ghim) | thành công; xem mục 6 |

Tổng cộng 400 test (283 + 116 + 1 xfail). Sau lần chạy, DB không còn dòng rác: 0 user, 0 clan, 0 audit_logs, 0 phiên, 0 login_history; `roles`/`permissions`/`role_permissions` giữ nguyên (4/18/0).

Nhóm test theo nội dung:

| Nhóm | File chính |
| --- | --- |
| Xác thực, phiên, đăng nhập Firebase (giả lập) | `test_auth_dependency.py`, `test_auth_api.py`, `test_firebase_provider.py`, `integration/test_sessions_db.py`, `integration/test_auth_flow_db.py` |
| Phân quyền, tenant, SA cuối | `test_permissions.py`, `integration/test_http_access.py`, `integration/test_system_admin_guard.py`, `integration/test_user_roles_unique_index.py`, `integration/test_last_sa_concurrency.py` |
| Quản trị người dùng, ủy quyền FA | `test_user_admin_api.py`, `integration/test_user_admin_db.py`, `integration/test_user_admin_concurrency.py` |
| Vòng đời Family Admin (đề bạt, thu hồi, tính nhất quán của dev seed) | `test_user_admin_api.py` (mục Mốc F2), `integration/test_family_admin_lifecycle_db.py`, `integration/test_family_admin_concurrency.py` |
| Guest: gói dịch vụ, đăng ký hồ sơ, theo dõi (Mốc E, E3) | `test_service_plans_api.py`, `test_registration_api.py`, `test_public_repository_sql.py`, `integration/test_registration_db.py`, `integration/test_registration_concurrency.py` |
| Bộ giới hạn tần suất và IP người gọi (Mốc E, E3) | `test_rate_limit.py`, `test_client_ip.py` |
| Kiểu văn bản: làm sạch một dòng, nhiều dòng, bí mật không bị chuẩn hóa | `test_text_types.py`, `test_user_admin_api.py` (trường lý do), `integration/test_user_admin_db.py` (trường lý do trên DB thật) |
| Seed gói dev (`seed_dev.py --plans-only`) | `test_seed_plans_definition.py`, `integration/test_seed_plans.py` |
| Migration: fingerprint, guard `ALLOW_MIGRATE`, SQL xem trước, kiểm tra tiền điều kiện của 0002 và 0003, từ chối downgrade khi còn việc dọn Firebase (không cần DB) | `test_migration_guard.py`, `test_migration_0003.py` |
| Ràng buộc toàn vẹn của migration 0003 (job Owner, idempotency, hồ sơ PENDING trùng; cần 0003 đã áp dụng) | `integration/test_db_provisioning.py` |
| Ràng buộc toàn vẹn của migration 0002 (KI-03, KI-04, KI-08, email; cần migration đã áp dụng) | `integration/test_db_constraints.py`, `integration/test_user_roles_unique_index.py` |
| Hợp đồng OpenAPI so với `api_contract.md` | `test_openapi_contract.py` |
| CORS (mọi loại response, kể cả 500) | `test_cors.py` |
| Cấu hình khởi động, lỗi `DATABASE_URL` không lộ chuỗi | `test_startup_checks.py`, `test_config_secrets.py` |
| Kiểm tra bảo mật cơ khí (xem `security_review.md`) | `test_security_checks.py`, `test_no_insecure_auth.py` |

## 6. Docker: build thử và kiểm tra image

Đã chạy ngày 06/10/2026 với Docker 23.0.5; **chỉ build, không chạy container, không push**.

```powershell
docker build -t mfgms-be:check .
docker image inspect mfgms-be:check --format "User={{.Config.User}} Exposed={{.Config.ExposedPorts}} Healthcheck={{.Config.Healthcheck.Test}}"
docker history mfgms-be:check --no-trunc
docker rmi mfgms-be:check
```

Kết quả: build thành công; `User=appuser`, cổng `8000`, có `HEALTHCHECK`; `/app` chỉ có `app/`, `alembic/`, `alembic.ini`, `requirements.txt` (không `.env`, file service account, `scripts/`, `tests/`, `docs/`, `.git`); phiên bản gói cài trong image trùng bộ đã test (fastapi 0.142.2, uvicorn 0.54.0, sqlalchemy 2.1.3, psycopg 3.3.6, firebase-admin 7.7.0, alembic 1.20.0, pydantic-settings 2.15.0).

Chưa làm: chạy container thật, quét CVE của image (KI-14). `alembic/versions/` chưa tồn tại nên `alembic upgrade` trong image chưa dùng được.

Kiểm tra phụ thuộc (cài `pip-audit` vào venv tạm **ngoài repo**, không thêm vào requirements):

```powershell
python -m venv D:\tmp\audit-venv
D:\tmp\audit-venv\Scripts\python.exe -m pip install pip-audit
D:\tmp\audit-venv\Scripts\pip-audit.exe --path "<BE>\.venv\Lib\site-packages"
```

Ngày 06/10/2026: **No known vulnerabilities found** (pip-audit 2.10.1). Chỉ phản ánh thời điểm chạy; nên chạy lại định kỳ.

## 7. Đối chiếu mục 11 của kế hoạch (T01–T33)

"Có" nghĩa là có test tự động; "Có (Firebase giả)" nghĩa là xác minh chữ ký trên token Firebase thật chưa được test tự động (mục 4).

| Nhóm | Tình huống | Trạng thái | Test hoặc lý do chưa có |
| --- | --- | --- | --- |
| T01–03 Auth | Token giả/hết hạn/đã revoke; UID lạ; account khóa | Có (Firebase giả) | `test_firebase_provider.py` (token giả mạo), `test_auth_api.py`, `integration/test_auth_flow_db.py`, `integration/test_sessions_db.py` |
| T04–06 Phiên | Logout; hết hạn; restart ứng dụng | Một phần | Logout và hết hạn: `test_auth_api.py`, `integration/test_sessions_db.py`. Restart: chưa có test riêng (phiên nằm hoàn toàn trong DB, không có trạng thái trong bộ nhớ; kết luận từ đọc mã) |
| T07–09 Mật khẩu | Mật khẩu tạm hết hạn; first-login gọi API nghiệp vụ; đổi mật khẩu thành công | Có (Firebase giả) | `test_auth_api.py`, `integration/test_http_access.py`, `integration/test_auth_flow_db.py` |
| T10–12 Reset | Email có/không tồn tại; code sai/hết hạn/dùng lại; spam | **Chưa** | Chưa có API reset (KI-05) |
| T13–15 Tenant | BO A gọi tài nguyên B; FA thiếu quyền; ME tự nâng role | Có | `integration/test_http_access.py`, `integration/test_user_admin_db.py`; không có API nâng vai trò nên "ME tự nâng role" chỉ kiểm được là member/FA bị `403` trên các API quản trị |
| T16–18 Quyền | Thu hồi membership/role; SA xem PRIVATE; sửa field nhạy cảm ngoài schema | Một phần | Thu hồi: `integration/test_http_access.py`; field ngoài schema: `422` do `extra=forbid`. **SA xem PRIVATE: chưa** (chưa có API dữ liệu gia phả, `support_access_grants` chưa dùng) |
| T19–21 Duyệt | Hồ sơ trùng; hai SA duyệt đồng thời; tạo clan khi chưa duyệt | **Chưa** | Mốc E |
| T22–24 Cấp Owner | Hai request đồng thời; retry cùng key; key cũ khác payload | **Chưa** | Mốc E (Idempotency-Key, job cấp tài khoản) |
| T25–27 Lỗi ngoài DB | Firebase timeout; email lỗi; Firebase thành công nhưng DB lỗi | Một phần | Firebase lỗi và "Firebase đổi mật khẩu xong nhưng DB lỗi": `test_auth_api.py`. Email lỗi: chưa (Mốc E) |
| T28–30 Migration | DB trống; DB baseline; rollback/forward-fix | Một phần | Có revision (`docs/migrations.md`) và test không cần DB: SQL `upgrade`/`downgrade` xem trước, guard, kiểm tra tiền điều kiện và dừng khi trùng dữ liệu (`test_migration_guard.py`). **Đã áp dụng thật lên dev_minhquan** (06/10/2026) và diễn tập `downgrade -1` rồi `upgrade head` (T29 baseline, T30 rollback: có, bằng lệnh tay, nhật ký ở `migrations.md` mục 11). **Chưa** chạy production. "DB trống" (T28) chưa làm được: chưa có cách dựng schema mới giống dev (`initial_schema.sql` đã cũ, KI-16, làm sau Mốc E) |
| T31–33 Tích hợp | CORS FE; luồng Guest đến Owner; log có request_id không secret | Một phần | CORS: `test_cors.py`; log request_id/không secret: `test_auth_api.py`, `test_security_checks.py`. Luồng Guest đến Owner: Mốc E. Thử với FE thật: chưa |

Ngoài mục 11 của kế hoạch, có thêm: đồng thời "SA cuối" và deadlock (`integration/test_user_admin_concurrency.py`, `test_last_sa_concurrency.py`), khóa dòng `FOR NO KEY UPDATE`, đối chiếu OpenAPI với hợp đồng, kiểm tra khởi động và lỗi cấu hình không lộ giá trị.

## 8. Kiểm chứng test bắt lỗi bằng đột biến (Mốc F2)

Mỗi đột biến được áp dụng tạm thời lên mã thật, chạy các test liên quan, rồi khôi phục; sau khi khôi phục băm sha256 của các file trùng với trước khi đột biến. Test chỉ đáng tin khi nó **fail** với đột biến.

| Đột biến | Kết quả | Test bắt được |
| --- | --- | --- |
| Bỏ khóa dòng membership khi đề bạt | Bị bắt **một phần** | `test_two_simultaneous_appointments_of_one_user_only_one_wins[role-row-already-active]` fail (hai assignment được tạo). Biến thể `[fresh-user]` vẫn qua vì chỉ mục `uq_active_user_role_scope` trên dòng vai trò `FAMILY_ADMIN` chặn request thứ hai (lớp bảo vệ thứ hai). Vì vậy có biến thể "đã có dòng vai trò" để khóa membership là thứ duy nhất đứng giữa |
| Bỏ khóa `FOR NO KEY UPDATE` trên các dòng assignment | Bị bắt (cả 4 test) | PUT với DELETE (quyền còn trên assignment đã thu hồi), DELETE rồi PUT (`ok` thay vì `404`), DELETE rồi đề bạt lại (`409` thay vì thành công), hai DELETE (`ok`, `ok` thay vì `ok`, `404`) |
| DELETE lấy khóa membership **sau** khóa assignment (ngược thứ tự với POST) | Bị bắt | `test_delete_and_appoint_started_at_the_same_instant_never_deadlock`: `ERROR:DeadlockDetected` |
| DELETE không xóa dòng permission | Bị bắt (cả 4 test đồng thời) | `revoked_with_permissions` khác 0 |
| DELETE không thu hồi dòng vai trò `FAMILY_ADMIN` | Bị bắt | `test_revoke_deletes_permissions_revokes_assignment_and_role_with_immediate_effect`, `test_reappoint_after_revoke_does_not_violate_the_unique_role_index` |
| Bỏ kiểm tra mã không được ủy quyền | Bị bắt | `test_non_delegable_code_is_403_and_nothing_is_created`, `test_put_rejects_admin_manage_with_403`, `test_put_keeping_an_existing_admin_manage_is_403_and_dropping_it_works` |

**Bài học về thời gian (đã sửa trong test):** mỗi session mới cần ~4 giây để mở kết nối Neon, trong khi một request chỉ giữ khóa vài trăm mili giây. Lần đầu, các test "so le" (request thứ hai chờ sự kiện rồi mới chạy) không thật sự đồng thời: request thứ hai kết nối xong thì request thứ nhất đã commit, nên đột biến "bỏ khóa assignment" **không bị bắt** (4 test vẫn qua). Đã sửa bằng cách mở sẵn kết nối trước khi chờ sự kiện/barrier (`await session.connection()`), giữ commit lâu hơn (1,5 giây, hoặc 3,5 giây khi request sau cần nhiều truy vấn trước khi tới khóa), dùng sự kiện thay cho `sleep` cố định, và cho test deadlock gửi danh sách mã rỗng để thứ tự khóa xác định. Sau đó đột biến mới bị bắt. Khi viết test đồng thời mới, hãy luôn chạy thử một đột biến.

## 9. Kiểm chứng test bằng đột biến (Mốc E, bước E3)

Cách làm như mục 8: áp từng đột biến lên mã thật, chạy các test liên quan, khôi phục, so sha256 với bản trước khi đột biến. Test chỉ đáng tin khi nó **fail**. Tổng cộng **79 đột biến, đều bị bắt**.

**Phần Guest và bộ giới hạn (60 đột biến, chỉ chạy test không cần DB).** Nhóm đã kiểm:

- **Hồ sơ trùng và mã theo dõi:** không bắt `IntegrityError`, bỏ kiểm tra trước, lưu mã thô, entropy yếu (8 byte), ghi mã vào log, bỏ thử lại khi va chạm mã.
- **Audit, lịch sử, dữ liệu:** audit chứa email, bỏ ghi audit hoặc lịch sử, gán người thực hiện, hạ chữ thường email khi lưu.
- **Gói:** chấp nhận gói không `ACTIVE`, đổi `422` thành `404`, truy vấn tính năng lặp theo từng gói.
- **Theo dõi:** lộ hash, lộ lý do khi không `REJECTED`, mã sai trả `403`, cắt khoảng trắng của mã, bỏ `no-store`.
- **Bộ giới hạn:** router không gắn bộ giới hạn, lệch một đơn vị, bỏ quét rác, bỏ trần số khóa, đẩy nhầm khóa vừa dùng, không ghi nhớ thứ tự dùng, ghi cả lần bị từ chối, `Retry-After` sai hoặc thiếu, không khóa luồng, không bỏ lượt hết hạn, bỏ gom IPv6, một bộ đếm chung, bộ giới hạn tắt vẫn đếm.
- **IP:** tin `X-Forwarded-For` mặc định, lấy phần tử bên trái, dùng giá trị rác, cảnh báo mọi lần, cảnh báo kèm giá trị header, cảnh báo cả khi tin proxy, bỏ qua header rỗng.
- **Kiểu văn bản:** bỏ từng luật làm sạch (ký tự điều khiển, NFC, gộp khoảng trắng), hạ chữ thường email, NUL lọt vào văn bản nhiều dòng, bí mật bị trim hoặc đi qua bộ làm sạch.
- **SQL thật của repository:** bỏ lọc `ACTIVE`, so sánh phân biệt hoa/thường, bỏ lọc `PENDING`, bỏ sắp xếp.

Lần chạy đầu có **2 đột biến sống sót**, do test yếu chứ không phải do mã: làm tròn xuống chưa được phân biệt với làm tròn lên (phần dư lớn hơn 1 giây), và việc thiếu khóa không lộ ra dù đã ép chuyển luồng liên tục. Đã thêm `test_retry_after_is_rounded_up_not_down` và `test_every_check_runs_under_the_limiters_own_lock`; cả hai đột biến sau đó bị bắt. Lần chạy đột biến đầu tiên cũng bị crash vì script giải mã sai đầu ra pytest (cp1252); nguồn nguyên vẹn (637 test vẫn pass), script đã sửa rồi chạy lại.

**Phần trường lý do, seed và vài đột biến trên DB thật (19 đột biến).**

| Nhóm | Đột biến | Test bắt được |
| --- | --- | --- |
| Trường lý do | `reason` của `PATCH .../status` hoặc của review về lại chuỗi thường; không đổi CRLF thành LF | `test_text_types.py::test_exactly_the_reason_fields_use_multiline_text`, `::test_multiline_text_turns_crlf_into_lf_and_trims` |
| Trường lý do trên DB thật | `reason` về chuỗi thường: **tái hiện lỗi cũ** (`DataError` không được xử lý, tức `500`) | `integration/test_user_admin_db.py::test_a_reason_with_nul_or_a_control_character_is_422_not_a_database_error` |
| Seed | ghi đè gói đã có; luôn tạo (bỏ tra cứu); thêm tính năng đã có; không bổ sung tính năng thiếu; bỏ qua trạng thái của spec | `integration/test_seed_plans.py::test_the_seed_never_overwrites_what_exists`, `::test_running_the_seed_again_creates_no_row_at_all`, `::test_the_seed_creates_the_plans_and_their_features_with_the_specified_values` |
| Định nghĩa seed | tiền tố `DEV-` bị xóa; một mã gói mất tiền tố; một tính năng lặp trong gói | `test_seed_plans_definition.py` |
| Cleanup | xóa cả gói đang được tham chiếu; bỏ qua tiền tố; coi tiền tố là mẫu `LIKE`; không bảo vệ gói có gói đăng ký của clan; đếm sai số gói giữ lại | `integration/test_seed_plans.py::test_cleanup_deletes_unreferenced_prefixed_plans_and_keeps_referenced_or_foreign_ones`, `::test_cleanup_matches_the_prefix_literally_not_as_a_like_pattern` |
| Đăng ký trên DB thật | không bắt `IntegrityError` (cuộc đua đồng thời lộ lỗi driver); danh sách gói liệt kê mọi trạng thái | `integration/test_registration_concurrency.py::test_identical_registrations_at_the_same_instant_exactly_one_wins_and_the_rest_get_409`, `integration/test_registration_db.py::test_only_active_plans_are_listed_cheapest_first_with_their_features` |

Các đột biến mức DB chạy trên nhánh dev: mọi test tích hợp đều rollback, test đồng thời tự dọn dữ liệu `itest-conc-` và không đụng gói `DEV-`. Sau đó DB vẫn đúng trạng thái ở mục 5.
