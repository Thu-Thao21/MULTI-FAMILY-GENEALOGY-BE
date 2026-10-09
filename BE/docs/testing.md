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
- Kết nối tới Neon chậm (vài giây mỗi lần mở, ~0,3 giây mỗi truy vấn): mỗi test chạm DB mất khoảng 25 đến 45 giây, nên **cả bộ (456 test) mất khoảng 4 đến 5 giờ** (lượt 09/10/2026: 4 giờ 47 phút; số liệu ở mục 5). Chạy từng file để kiểm nhanh.
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

## 5. Số liệu chạy theo từng mốc

Bắt đầu bằng lượt chạy integration cả bộ ngày 09/10/2026 và các bước của Mốc E (mới nhất ở trên cùng: E8), rồi tới Mốc F2.

### Chạy integration cả bộ (09/10/2026)

Lệnh: `ALLOW_DB_TESTS=1 pytest -m integration -q`, chạy từ `BE` trên nhánh dev (alembic `0003_provisioning_idempotency`), một lần duy nhất, không sửa mã trong lúc chạy. Không lệnh nào gọi Firebase thật (provider giả).

| Lệnh | Kết quả |
| --- | --- |
| `ALLOW_DB_TESTS=1 pytest -m integration -q` (cả bộ, một lần) | **455 passed, 1 failed**, 5 warnings (cảnh báo `on_event` đã biết), **4 giờ 47 phút 22 giây** |
| Test lỗi: `test_a_suspended_member_can_still_be_revoked_and_non_fas_are_404` (`tests/integration/test_family_admin_lifecycle_db.py`) | `psycopg.OperationalError: server closed the connection unexpectedly`, phát sinh **trong phần dựng dữ liệu của chính test** (`world.business_owner()` chạy `INSERT INTO clans`), sau khi các khẳng định trước đó của test đã đạt |
| Chạy lại riêng test đó | **1 passed** (37 giây) |
| Chạy lại cả file `test_family_admin_lifecycle_db.py` | **12 passed**, hai lần (273 giây và 277 giây) |

**Kết luận:** kết nối bị đứt giữa một lượt chạy rất dài, không phải lỗi mã; cả 456 test integration đều pass (455 trong lượt cả bộ và 1 khi chạy lại riêng). Chưa có một lượt liền mạch 0 failed; nguyên nhân phía Neon chưa xác định (KI-23, KI-37). `pool_pre_ping` đã bật cho engine của test (qua `make_engine`) nhưng chỉ thay kết nối đã chết lúc lấy ra khỏi pool, không cứu được kết nối đứt khi đang dùng.

**Thời gian thực tế:** mỗi test chạm DB mất khoảng 25 đến 45 giây (kết nối Neon chậm, nhiều truy vấn tuần tự), nên cả bộ 456 test mất **khoảng 4 đến 5 giờ**, không phải vài chục phút. Muốn kiểm nhanh thì chạy từng file (xem mục 2).

### Mốc E, bước E8: smoke test với Firebase thật trên project dev (09/10/2026)

Chạy khoảng 02:00 đến 02:27 (UTC+7) trên project Firebase **dev** và nhánh Neon **dev** (`0003_provisioning_idempotency`). Đây là lần duy nhất của Mốc E có lời gọi Firebase thật; `pytest -q` vẫn không gọi Firebase thật. Không có test nào của repo đổi trong bước này (chỉ ghi tài liệu).

**Cách chạy.** Một script riêng **nằm ngoài repo** (KI-33), do người phụ trách chạy tay, qua một launcher hỏi các giá trị cần (id project, e-mail thử, Web API key, mật khẩu của System Admin) và chỉ đặt chúng trong biến môi trường của tiến trình đó; không giá trị nào vào file, log hay repo. App chạy ngay trong process (ASGI) với adapter Firebase thật (`FirebaseIdentityProvider`) được bọc bộ đo thời gian. Các giai đoạn:

| Giai đoạn | Làm gì |
| --- | --- |
| `--selftest` | Chỉ đồ giả, không mạng, không DB, gồm cả phép thử ngược: phá từng lớp bảo vệ thì selftest phải thất bại |
| `--preflight` | Chỉ đọc: cấu hình, project nằm trong danh sách cho phép và được gõ lại để xác nhận, project của service account, không có emulator, nhánh DB đúng và phiên bản alembic `0003`, khóa ngoại so với thứ tự dọn, chạy thử 9 câu `DELETE` rồi hoàn tác, đọc Admin API, thử Web API key; ghi số hàng gốc (baseline) |
| `--run --stage probe` | Tạo rồi xóa ngay các user Firebase thử (uid `own-<uuid>` và e-mail `@example.test` ngẫu nhiên), **không đụng DB**: đo độ trễ và dò chính sách mật khẩu |
| `--run --stage main` | Luồng Business thật qua app (ghi DB dev và Firebase dev) |
| `--verify` | Chỉ đọc: so **mọi** bảng dữ liệu với baseline và xác nhận mọi uid đã ghi nhận đều không còn ở Firebase |
| `--cleanup` | Xóa đúng những gì lượt chạy đã tạo: user Firebase theo uid đã ghi nhận (không bao giờ theo e-mail, không liệt kê), dòng DB theo id (đã ghi nhận, hoặc tìm ra từ các e-mail thử của lượt chạy), trong một giao dịch |

Giữa probe và main, người chạy quyết định `OWNER_TEMP_PASSWORD_REQUIRE_SYMBOL` theo kết quả probe. Uid được ghi vào file trạng thái (chỉ id, không bí mật, `fsync`) **trước** mỗi lần tạo user; mọi dòng in ra đi qua bộ lọc che key, mật khẩu, token, e-mail và uid.

**Điều kiện để chạy lại:**

- Project Firebase dev đã bật nhà cung cấp **Email/Password**.
- Một user System Admin phải được **tạo tay trước** trong Firebase Console. Script không bao giờ tạo hay xóa tài khoản Firebase này; nó chỉ thêm 2 dòng DB cho tài khoản (nếu chưa có) và chỉ xóa 2 dòng đó khi chính nó đã thêm.
- Chạy từ thư mục `BE` (để tìm thấy `.env`). Trên Windows script đặt chính sách vòng lặp sự kiện kiểu selector **trước** `asyncio.run`, vì `psycopg` ở chế độ async không chạy được trên vòng lặp mặc định của Windows (lần đầu quên bước này, preflight dừng ở `InterfaceError`).
- Nhánh DB dev: các e-mail thử chưa có trong `users` và `business_registrations`, không có user `firebase_uid` dạng `own-%`, các bảng giữ nguyên đúng số hàng (3 gói, 6 giới hạn tính năng, `roles`/`permissions`/`role_permissions` = 4/18/0) và có ít nhất một gói `ACTIVE`; preflight dừng nếu một điều kiện không đúng.

**Kết quả:**

| Giai đoạn | Kết quả |
| --- | --- |
| `--preflight` | Đạt. Web API key được Google chấp nhận **không cần referer** (gửi qua header). Ba bảng của sprint sau (`person_merge_history`, `restore_jobs`, `violation_reports`) có khóa ngoại mà thứ tự dọn không phủ nhưng **rỗng**, nên được bỏ qua có theo dõi (KI-34) |
| `--run --stage probe` | Chính sách mật khẩu của project: **chấp nhận mật khẩu 16 ký tự gồm chữ hoa, chữ thường, chữ số, không ký hiệu; độ dài tối thiểu 6**. Vậy `OWNER_TEMP_PASSWORD_REQUIRE_SYMBOL=false` là đủ, không cần đổi cấu hình. Độ trễ: lời gọi đơn **chậm nhất 2,5 giây**; ba lời gọi liên tiếp ở mức chậm nhất đó là **7,5 giây**, so với lease 90 giây và timeout 15 giây mỗi lời gọi (KI-28) |
| `--run --stage main` | **14 kiểm tra đạt** (danh sách dưới đây) |
| `--cleanup`, `--verify` | **CLEAN**: mọi bảng dữ liệu về đúng baseline, mọi user Firebase của lượt chạy không còn; `roles`/`permissions`/`role_permissions` vẫn 4/18/0, ba gói `DEV-` và 6 giới hạn tính năng còn nguyên, alembic `0003` |

Mười bốn kiểm tra của giai đoạn main:

1. System Admin đăng nhập bằng tài khoản Firebase thật, nhận ID token thật; phiên được tạo.
2. Guest xem được danh sách gói.
3. Business A: đăng ký, tra mã theo dõi, duyệt, tạo Business.
4. Cấp Owner A: user Firebase thật được tạo (`201`), mật khẩu tạm nhận trong bộ nhớ.
5. Owner A đăng nhập bằng mật khẩu tạm: phiên bị giới hạn (`requires_password_change`).
6. Owner A đổi mật khẩu (`set_password` thật: cập nhật và thu hồi refresh token).
7. ID token cũ bị từ chối (`401`): việc thu hồi token là thật.
8. Owner A đăng nhập lại: phiên đầy đủ, clan còn `PENDING`, chưa có quyền nào, các hành động của clan bị `403`.
9. Kích hoạt clan A: Owner A có quyền ngay trong cùng phiên; `GET /admin/clans/{id}` khớp.
10. Business B: đăng ký, tra mã, duyệt, tạo Business.
11. Cấp Owner B rồi cấp lại mật khẩu tạm (`set_owner_password` thật).
12. Owner B: mật khẩu tạm cũ bị Firebase từ chối, mật khẩu mới cho phiên bị giới hạn.
13. Business C: đăng ký, tra mã, duyệt, tạo Business.
14. Job C: sau khi "mất câu trả lời" (cố ý), user Firebase thật đã tồn tại; `abandon` xóa nó theo uid `own-<job_id>` và xác nhận đã mất.

Không ghi ở đây: e-mail, uid, khóa, mật khẩu, mã theo dõi hay fingerprint của DB.

### Mốc F2: vòng đời Family Admin (06/10/2026)

Chạy từ `BE`, Python 3.13.7, `.venv` của dự án, sau `seed_dev.py --cleanup` (DB không còn dữ liệu seed, nên mọi test "SA cuối" chạy chứ không skip).

| Lệnh | Kết quả |
| --- | --- |
| `pytest -q` | **320 passed, 137 deselected** (nhóm `integration`), 0 failed |
| `ALLOW_DB_TESTS=1 pytest -m integration -q` | **136 passed, 1 xfailed** (KI-03, đúng dự kiến), 0 skipped, 0 failed, 23 phút 11 giây |
| `python -c "import app.main"` | MAIN OK |
| `scripts/check_orm_vs_db.py` | 0 errors, 0 INFO |

Tổng cộng 457 test. Sau lần chạy, DB không còn dòng rác: 0 user, 0 clan, 0 audit_logs, 0 phiên; `roles`/`permissions`/`role_permissions` giữ nguyên (4/18/0). Mốc F2 thêm: nhóm test vòng đời Family Admin (đơn vị, DB thật, đồng thời) và test dev seed vẫn nhất quán. Test cũ của Mốc F `test_every_code_in_the_permissions_table_is_accepted` (ủy quyền mọi mã, kể cả `ADMIN_MANAGE`) đã đổi thành `test_every_delegable_code_in_the_permissions_table_is_accepted` theo quyết định Q1: mọi mã trừ `ADMIN_MANAGE` được nhận, thêm `ADMIN_MANAGE` thì `403`.

### Mốc E, bước E7: kích hoạt clan, đọc clan, tài liệu bàn giao cho FE (08/10/2026)

Chạy trên nhánh dev (`0003_provisioning_idempotency`, fingerprint 3ff0cec7), không migrate, không seed; ba gói `DEV-` giữ nguyên. **Không lệnh nào gọi Firebase thật** (provider giả). Chỉ chạy `pytest -q` và hai file integration mới; **không** chạy cả bộ integration.

| Lệnh | Kết quả |
| --- | --- |
| `pytest -q` | **1462 passed**, 456 deselected (nhóm `integration`), 0 failed, 80 giây. Thêm 81 test so với E6b (1381): 43 của `test_clan_activation_api.py`, 6 SQL, 19 quét tài liệu bàn giao (`test_handoff_examples.py`), phần còn lại là hợp đồng OpenAPI, quyền, bảo mật |
| `ALLOW_DB_TESTS=1 pytest -m integration` hai file mới (`test_clan_activation_db.py` 26 test, `test_clan_activation_concurrency.py` 6 test) | Lần đầu **20 passed, 2 failed** trên 22 test. Cả hai là lỗi của **test**: mỗi test gom nhiều tình huống trong một hàm, nên sau `409` đầu tiên use case rollback và các đối tượng ORM của factory (vai trò đã nạp) bị hết hạn, tình huống thứ hai bị `MissingGreenlet`. Tách thành 12 test, mỗi test một tình huống (DB thật: 14 + 12 = 26): chạy riêng 12 test đó **12 passed**. Tổng **32 passed** (13 phút 33 giây + 2 phút 13 giây) |
| `python -c "import app.main"` | MAIN OK |

Trạng thái DB dev sau các lần chạy và sau mọi lượt đột biến: các bảng dữ liệu (`users`, `clans`, `clan_subscriptions`, `provisioning_jobs`, `idempotency_keys`, `audit_logs`, ...) đều **0 dòng**; `subscription_plans` 3 (`DEV-*`, không còn gói `ITESTOP-PLAN-*`), `plan_feature_limits` 6; `roles`/`permissions`/`role_permissions` = 4/18/0; alembic `0003_provisioning_idempotency`. Test đồng thời dùng chung tiền tố `itest-conc-op-` với E6 và tự xóa các gói `ITESTOP-PLAN-*` của riêng nó (gói không có `ON DELETE CASCADE` từ clan).

### Mốc E, bước E6b: thử lại, bỏ, liệt kê job và cấp lại mật khẩu tạm của Owner (08/10/2026)

Chạy trên nhánh dev (`0003_provisioning_idempotency`, fingerprint 3ff0cec7), không migrate, không seed; ba gói `DEV-` giữ nguyên. **Không lệnh nào gọi Firebase thật** (provider giả có tiêm lỗi và điểm dừng; `tests/conftest.py` vẫn chặn các hàm Admin của SDK). Chỉ chạy `pytest -q` và hai file integration mới; **không** chạy cả bộ integration.

| Lệnh | Kết quả |
| --- | --- |
| `pytest -q` | **1381 passed**, 424 deselected (nhóm `integration`), 0 failed, 77 giây. Thêm 119 test so với E6a (1262): 57 của `test_owner_recovery_api.py`, phần còn lại là test adapter (`set_owner_password`, quét mã nguồn), SQL của repository, máy trạng thái (abandon), hợp đồng OpenAPI và bảo mật |
| `ALLOW_DB_TESTS=1 pytest -m integration` hai file mới (`test_owner_recovery_db.py` 22 test, `test_owner_recovery_concurrency.py` 13 test) | Lần đầu **33 passed, 2 failed** (26 phút 47 giây). Cả hai là lỗi của **test**, không phải của mã: (1) test seed một hàng key với `request_hash` giả nên phát lại key bị `IDEMPOTENCY_KEY_CONFLICT`; sửa bằng hash thật. (2) test "retry đua với abandon" kỳ vọng retry luôn `409` khi abandon thắng, nhưng retry đến lúc job còn nợ dọn thì đúng là chỉ dọn và trả `200` (không Owner, không mật khẩu); nới kỳ vọng cho cả hai kết quả hợp lệ. Chạy riêng hai test đó: **2 passed**. Tổng **35 passed** |
| `python -c "import app.main"` | MAIN OK |

Trạng thái DB dev sau các lần chạy và sau mọi lượt đột biến: `users`, `clans`, `user_roles`, `user_sessions`, `audit_logs`, `clan_memberships`, `family_admin_assignments`, `business_registrations`, `registration_status_history`, `clan_subscriptions`, `clan_ownership_history`, `provisioning_jobs`, `idempotency_keys` đều **0 dòng**; `subscription_plans` 3 (`DEV-*`), `plan_feature_limits` 6; `roles`/`permissions`/`role_permissions` = 4/18/0; alembic `0003_provisioning_idempotency`. Test đồng thời dùng tiền tố `itest-conc-op-`, dọn không phân biệt hoa/thường (kể cả `user_sessions`, vì bảng đó không có `ON DELETE CASCADE`) và kiểm tra cuối phiên không còn user hay phiên mồ côi.

### Mốc E, bước E6a: cấp Owner qua Firebase (08/10/2026)

Chạy trên nhánh dev (`0003_provisioning_idempotency`, fingerprint 3ff0cec7), không migrate, không seed; ba gói `DEV-` giữ nguyên. **Không lệnh nào gọi Firebase thật**: provider là bản giả có tiêm lỗi, và `tests/conftest.py` làm các hàm Admin của SDK fail test nếu có gì gọi tới.

| Lệnh | Kết quả |
| --- | --- |
| `pytest -q` | **1261 passed**, 387 deselected (nhóm `integration`), 0 failed, 71 giây. Thêm 209 test so với E5 (1052) |
| Hai file integration mới (`test_owner_provisioning_db.py`, `test_owner_provisioning_concurrency.py`) | Lần đầu **32 passed, 3 failed**: cả ba là lỗi của test (đọc thuộc tính ORM đã hết hạn sau khi request rollback: `MissingGreenlet`); sửa test thành **35 passed**. Sau đó thêm một test (lượt chạy bị thay thế ngay trước T4) nên file có **36 test** |
| `ALLOW_DB_TESTS=1 pytest -m integration -q` (cả bộ, một lần duy nhất) | **213 passed, 1 failed, 173 errors**, 44 phút 15 giây. Nguyên nhân: **mất mạng giữa lần chạy** (`failed to resolve host ... getaddrinfo failed`, sqlstate: không có, lỗi hạ tầng như phần B báo); test đầu tiên gặp lỗi fail, các test sau lỗi ở bước dựng fixture. Chạy riêng đúng 174 test đó: **174 passed** (32 phút 49 giây). Không chạy lại cả bộ |
| `python -c "import app.main"` | MAIN OK |
| **Sau bản sửa `UID_MISMATCH`** (không xóa user lạ, job `FAILED` với `needs_cleanup = false`): `pytest -q` | **1262 passed**, 389 deselected, 0 failed |
| Sau bản sửa: hai file integration E6a | **38 passed** (thêm `test_a_uid_mismatch_is_failed_never_deleted_and_blocks_nothing` và `test_after_a_failure_the_password_is_in_no_column_and_not_in_the_error`), 17 phút 36 giây. Không chạy lại cả bộ |

Tổng cộng 1651 test (1262 + 389).

**Dữ liệu bị bỏ lại và đã dọn:** sau lần chạy cả bộ, DB còn **2 user chủ họ** (`ITEST-CONC-OP-OWNER-...@EXAMPLE.TEST`). Đó là lỗi dọn dẹp trong test đồng thời của chính tôi: hàm `purge` so khớp tiền tố email phân biệt hoa/thường, trong khi một test cố ý gửi email viết hoa. Đã sửa (so khớp `lower(email)`), thêm kiểm tra cuối phiên ("không còn user nào mang tiền tố, ở bất kỳ kiểu chữ nào"), chạy lại hai test liên quan: hàm dọn xóa luôn hai dòng cũ. DB đã về đúng trạng thái dưới đây.

Sau các lần chạy, DB dev: 0 user, 0 clan, 0 hồ sơ đăng ký, 0 lịch sử trạng thái, 0 audit_logs, 0 provisioning_jobs, 0 idempotency_keys, 0 clan_subscriptions, 0 phiên, 0 vai trò người dùng, 0 credential_metadata; `subscription_plans` đúng **3** với 6 dòng `plan_feature_limits`; `roles`/`permissions`/`role_permissions` giữ nguyên (4/18/0); `alembic_version` = `0003_provisioning_idempotency`. Một truy vấn chỉ đọc mở 8 giao dịch đồng thời (8 backend khác nhau) cho `lock_timeout = 0` ở cả 8: pooler không bị nhiễm trạng thái session (bài học của E5).

### Mốc E, bước E4b và E5: kết nối bền hơn, idempotency, tạo Business (08/10/2026)

Chạy trên nhánh dev (`0003_provisioning_idempotency`, fingerprint 3ff0cec7), không migrate, không seed thêm; ba gói `DEV-` giữ nguyên.

| Lệnh | Kết quả |
| --- | --- |
| `pytest -q` | **1052 passed**, 351 deselected (nhóm `integration`), 0 failed, 64 giây. Thêm 218 test so với E4 (834): 23 của E4b (cấu hình engine, chẩn đoán lỗi), 195 của E5 và CORS |
| `ALLOW_DB_TESTS=1 pytest -m integration` hai file mới (`test_business_create_db.py`, `test_business_create_concurrency.py`) | **44 passed** ngay lần đầu, 14 phút 28 giây |
| `ALLOW_DB_TESTS=1 pytest -m integration -q` (cả bộ, một lần duy nhất) | **349 passed, 2 failed**, 53 phút 24 giây. Hai lỗi đều có nguyên nhân giải thích được (xem dưới); chạy riêng lại hai test đó: **2 passed**. Không chạy lại cả bộ |
| `python -c "import app.main"` | MAIN OK |

Tổng cộng 1403 test (1052 + 351). Số lỗi hạ tầng "server closed the connection" của E4 **không lặp lại** trong lần chạy này (sau khi engine dùng `pool_pre_ping`, `pool_recycle` và `connect_timeout`; chưa đủ một lần chạy để kết luận nguyên nhân phía Neon, KI-23).

**Hai lỗi của lần chạy cả bộ: do chính đột biến của tôi làm nhiễm pooler.**
- `test_business_create_db.py::test_set_lock_timeout_is_local_to_the_transaction` thấy `SHOW lock_timeout` vẫn là `10s` sau commit, và `test_family_admin_concurrency.py::test_put_then_delete_race_leaves_no_permissions_on_the_revoked_assignment` bị `55P03 canceling statement due to lock timeout` (sqlstate hiện rõ nhờ phần B của E4b).
- Nguyên nhân: đột biến DB "lock timeout theo session" (`set_config(..., false)`) chạy ngay trước lần chạy cả bộ đã đặt `lock_timeout = 10s` ở **cấp session** trên một kết nối server của pooler Neon. PgBouncer chế độ transaction **không reset trạng thái session**, nên kết nối đó được giao cho client khác, và test khác chạm 10 giây chờ khóa. Mã thật dùng `is_local = true` (chỉ trong giao dịch) nên không có rủi ro này; đúng là điều test đầu tiên bảo vệ.
- Kiểm chứng: sau lần chạy, một truy vấn chỉ đọc mở 12 giao dịch đồng thời (12 backend khác nhau) cho `lock_timeout = 0` ở cả 12; hai test chạy riêng đều pass. Đây là suy luận từ các dấu hiệu khớp nhau, không phải bằng chứng trực tiếp.
- **Bài học cho đột biến:** không bao giờ chạy đột biến thay đổi trạng thái session (SET, `set_config(..., false)`) trên DB đi qua pooler; chỉ dùng đột biến mức đơn vị cho loại đó (đột biến này vẫn bị bắt ở mức đơn vị bởi `test_business_create_repository_sql.py::test_the_lock_timeout_is_local_to_the_transaction_and_a_bound_parameter`). Đã ghi vào KI-23.

Sau các lần chạy, DB dev: 0 user, 0 clan, 0 hồ sơ đăng ký, 0 lịch sử trạng thái, 0 audit_logs, 0 provisioning_jobs, 0 idempotency_keys, 0 clan_subscriptions, 0 phiên, 0 vai trò người dùng; `subscription_plans` đúng **3** với 6 dòng `plan_feature_limits`; `roles`/`permissions`/`role_permissions` giữ nguyên (4/18/0); `alembic_version` = `0003_provisioning_idempotency`.

**Lỗi của test mới ở E5 (đã sửa trong test, không phải trong mã ứng dụng):** `LockedThenWait` và các helper đồng thời chạy đúng ngay lần đầu; các sửa là ở test đơn vị (kỳ vọng `commit` trước `rollback` khi commit hỏng, quy tắc `text()` của test bảo mật buộc dùng `set_config` có tham số thay cho `SET LOCAL` dạng f-string, so sánh `calls` thay vì tìm chữ trong docstring).

### Mốc E, bước E4: SA xem và duyệt hồ sơ (07/10/2026)

Chạy trên nhánh dev (`0003_provisioning_idempotency`, fingerprint 3ff0cec7), không migrate, không seed thêm; ba gói `DEV-` giữ nguyên.

| Lệnh | Kết quả |
| --- | --- |
| `pytest -q` | **834 passed**, 307 deselected (nhóm `integration`), 0 failed, 61 giây. Thêm 163 test so với E3 (671) |
| `ALLOW_DB_TESTS=1 pytest -m integration` hai file mới (`test_registration_admin_db.py`, `test_registration_review_concurrency.py`) | Lần đầu 33 passed, 4 failed, đều là lỗi của test (xem dưới); sau khi sửa: **37 passed** |
| `ALLOW_DB_TESTS=1 pytest -m integration -q` (cả bộ, một lần duy nhất) | **302 passed, 5 failed**, 43 phút 33 giây. 4 lỗi là `server closed the connection unexpectedly` (Neon cắt kết nối trong lần chạy dài) ở test cũ của E3; chạy riêng lại 4 test đó: **4 passed**. Lỗi thứ năm là test mới `test_different_registrations_are_reviewed_in_parallel_...` (xem dưới); sau khi sửa file đó chạy riêng: **8 passed**. Không chạy lại cả bộ |
| `python -c "import app.main"` | MAIN OK |

Tổng cộng 1141 test (834 + 307). Số lần chạy cả bộ không đạt 0 failed trong một lượt: 5 lỗi trên đều có nguyên nhân đã giải thích (4 lỗi hạ tầng, 1 lỗi của test mới), nhưng chưa có một lượt cả bộ nào xanh hoàn toàn sau khi sửa.

**Lỗi của test mới (đã sửa trong test, không phải trong mã ứng dụng):** `INSERT`/`begin()` sai trên session đã autobegin; kỳ vọng tìm kiếm sai (`clan <tag>` không khớp `Clan Beta <tag>`); các test "có bị chặn không" dùng thời gian giữ 1,5 giây trong khi chi tiết hồ sơ cần bốn lượt gọi Neon (~1,4 giây), nên không phân biệt được chậm với bị chặn: nay giữ 6 giây và so với 3,6 giây; test song song so sánh với một lần duyệt đơn nhưng tính cả thời gian mở kết nối: nay tính từ lúc rào chắn được thả.

Sau các lần chạy, DB dev: 0 user, 0 clan, 0 hồ sơ đăng ký, 0 lịch sử trạng thái, 0 audit_logs, 0 provisioning_jobs, 0 idempotency_keys, 0 clan_subscriptions, 0 phiên, 0 vai trò người dùng; `subscription_plans` đúng **3** với 6 dòng `plan_feature_limits`; `roles`/`permissions`/`role_permissions` giữ nguyên (4/18/0); `alembic_version` = `0003_provisioning_idempotency`.

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

## 10. Kiểm chứng test bằng đột biến (Mốc E, bước E4)

Cách làm như mục 8 và 9: áp từng đột biến lên mã thật, chạy các test liên quan, khôi phục, so sha256 với bản trước khi đột biến. Tổng cộng **73 lần đột biến, đều bị bắt, 0 sống sót**: 67 đột biến khác nhau chạy test không cần DB, 6 đột biến chạy trên DB dev (kèm 5 lần chạy lại cho các đột biến ban đầu chỉ bị bắt do lỗi phụ).

| Nhóm | Đột biến | Test bắt được |
| --- | --- | --- |
| Khóa | đọc hồ sơ không khóa; `FOR UPDATE` thay `FOR NO KEY UPDATE`; bỏ mệnh đề khóa; bỏ `populate_existing` | `test_registration_admin_repository_sql.py::test_the_review_lock_is_for_no_key_update_and_rereads_the_row`, `test_registration_admin_api.py::test_the_registration_is_locked_first_the_users_row_never_and_the_repository_never_commits` |
| Máy trạng thái | bỏ kiểm tra `PENDING`; cho duyệt lại hồ sơ `APPROVED` hoặc `REJECTED` | `test_registration_admin_api.py::test_only_a_pending_registration_can_be_reviewed_and_the_409_names_the_status`, `::test_both_decisions_are_final_a_second_review_in_any_direction_is_409` |
| Ghi dữ liệu | bỏ lịch sử; bỏ audit; commit hai lần hoặc không commit; thiếu `reviewed_by`, `reviewed_at`, `from_status`, `changed_by`, `actor_id`, `old_data` | `::test_approving_updates_the_registration_writes_one_history_row_and_one_audit_row` |
| Lý do | không bắt buộc khi `REJECTED`; chuỗi thường nhận NUL; ghi chú duyệt vào `rejection_reason`; `reason_visible_to_applicant` luôn đúng hoặc luôn sai | `::test_a_rejection_without_a_valid_reason_is_422_and_changes_nothing`, `::test_an_approval_note_is_internal_only_it_never_reaches_rejection_reason_or_the_audit`, `::test_rejecting_needs_a_reason_and_makes_it_visible_to_the_applicant` |
| Audit và log | audit chứa nội dung lý do, email, tên, tên họ; `audit_logs.reason` có giá trị; log chứa lý do | `::test_the_audit_row_holds_no_personal_data_no_clan_name_and_never_the_reason_text`, `::test_the_reason_the_applicant_and_the_request_never_reach_a_log` |
| Thông điệp `409` và gói | thông điệp không nêu trạng thái; bỏ kiểm tra gói khi duyệt; chỉ kiểm tra gói thiếu; kiểm tra gói cả khi từ chối | `::test_approving_needs_a_plan_that_is_still_active`, `::test_rejecting_does_not_look_at_the_plan[INACTIVE]` |
| Danh sách | lộ email; bỏ lọc trạng thái; bỏ tìm kiếm (use case và SQL); sắp xếp tăng dần hoặc thiếu khóa phụ; `LIKE` phân biệt hoa/thường; không thoát ký tự đại diện; tìm cả điện thoại; mốc ngày lệch một đơn vị (hai phía); tổng bằng độ dài trang hoặc bỏ bộ lọc; bỏ kiểm tra thứ tự ngày; `page_size` trên 100; chọn cột email | `test_registration_admin_repository_sql.py` (SQL thật), `test_registration_admin_api.py::test_the_list_shows_exactly_the_planned_fields_and_none_of_the_personal_contact_data`, `::test_paging_and_the_total_follow_the_filters`, `::test_bad_paging_is_422_and_the_largest_page_is_accepted` |
| Chi tiết | lộ `storage_key`, `tracking_code_hash`; đảo thứ tự lịch sử; không hiện `clan_id`; mã lạ không trả `404` (chi tiết và review) | `::test_the_detail_history_is_oldest_first_and_attachments_never_show_the_storage_key`, `::test_the_detail_never_shows_the_tracking_hash`, `::test_an_unknown_registration_is_404_and_a_bad_id_is_422` |
| Router | bỏ phân quyền của danh sách hoặc chi tiết; review chỉ cần đăng nhập; gắn bộ giới hạn tần suất; bỏ `no-store`; bỏ IP thật của client | `::test_an_anonymous_caller_is_401_on_every_endpoint`, `::test_everyone_who_is_not_a_system_admin_gets_403_and_nothing_changes`, `::test_the_admin_endpoints_are_not_rate_limited_on_the_real_app`, `::test_the_admin_router_source_never_mentions_the_rate_limiter`, `::test_the_audit_row_records_the_connecting_address_not_a_forwarded_one` |
| Kiểu văn bản | `SearchText` nhận ký tự điều khiển; `q` của `/admin/users` hoặc của hồ sơ về chuỗi thường | `test_text_types.py::test_search_text_rejects_every_control_character_including_nul`, `::test_exactly_these_fields_use_the_search_cleaner` |
| Kê khai | đổi tên một phương thức repository toàn cục | `test_security_checks.py::test_family_repository_methods_without_clan_id_are_all_accounted_for` |
| **Trên DB thật (6)** | bỏ khóa dòng (hai SA cùng thắng); bỏ kiểm tra `PENDING`; bỏ kiểm tra gói; `q` của `/admin/users` về chuỗi thường (**tái hiện lỗi `500` cũ**: `DataError` không xử lý); không thoát ký tự đại diện; audit chứa nội dung lý do | `integration/test_registration_review_concurrency.py::test_two_reviewers_approve_at_the_same_instant_exactly_one_wins`, `integration/test_registration_admin_db.py::test_both_decisions_are_final_on_the_real_database`, `::test_approving_needs_an_active_plan_but_rejecting_does_not`, `::test_a_control_character_in_the_search_is_422_never_a_500`, `::test_wildcards_and_backslash_in_the_search_are_ordinary_characters`, `::test_rejecting_stores_the_public_reason_and_the_audit_never_holds_it` |

Lần chạy đầu có 1 đột biến "không tìm thấy" (mẫu văn bản của chính script đột biến sai, không phải test yếu) và 5 đột biến chỉ bị bắt do lỗi phụ (ngoại lệ không xử lý) chứ không do khẳng định định sẵn; đã chạy lại từng đột biến với đúng test dự kiến và cả sáu đều fail đúng chỗ. Các đột biến mức DB chạy trên nhánh dev: mọi test tích hợp đều rollback, test đồng thời tự dọn dữ liệu `itest-conc-rv-` và không đụng gói `DEV-`. Sau đó DB vẫn đúng trạng thái ở mục 5.

## 11. Kiểm chứng test bằng đột biến (Mốc E, bước E4b và E5)

Cách làm như mục 8 đến 10: áp từng đột biến lên mã thật, chạy các test liên quan, khôi phục, so sha256 với bản trước khi đột biến. Test chỉ đáng tin khi nó **fail**. Không có đột biến nào còn sống.

**E4b (17 đột biến, đều bị bắt).** Bỏ hoặc đổi `pool_pre_ping`, `pool_recycle`, `connect_timeout`; ghi đè làm mất bộ tùy chọn; sửa cả dict dùng chung; dựng engine ngoài `make_engine` (ứng dụng và fixture); helper chẩn đoán không đọc sqlstate, không lọc URL, host, `host=`/`password=`, không cắt 60 ký tự, không gom một dòng, nhận nhầm lỗi hạ tầng, thêm hàm thử lại. Test bắt: `test_db_engine_config.py`, `test_integration_diagnostics.py`.

**E5: 90 đột biến mức đơn vị + 12 mức DB thật, đều bị bắt.**

| Nhóm | Đột biến | Test bắt được |
| --- | --- | --- |
| Hash | bỏ phương thức, endpoint, tham số đường dẫn hoặc body khỏi hash; không sắp xếp khóa; sha1; UUID không chuẩn tắc; use case bỏ tham số đường dẫn, không chuẩn hóa body, sai hằng endpoint | `test_idempotency_core.py::test_anything_that_makes_the_request_different_changes_the_hash`, `::test_the_hash_is_64_hex_characters_and_stable`, `test_business_create_api.py::test_the_key_row_is_completed_in_the_same_transaction_with_the_response_that_was_sent` |
| Header | độ dài tối thiểu 4, tối đa 256; cho khoảng trắng; header tùy chọn; router không nhận header | `test_idempotency_core.py::test_the_key_is_8_to_128_printable_ascii_characters_without_spaces`, `::test_the_header_is_required` |
| Claim | không đặt `lock_timeout` hoặc 60 giây; TTL 1 ngày; không so hash; bỏ kiểm tra hết hạn hoặc lệch biên; phát lại hàng đang chạy; không thử lại hàng biến mất, thử vô hạn | `test_idempotency_core.py::test_a_second_claim_of_a_completed_key_with_the_same_hash_is_a_replay`, `::test_the_same_key_with_another_hash_is_a_conflict_whatever_its_status`, `::test_the_expiry_boundary_counts_as_expired_and_one_second_before_does_not`, `::test_two_vanishing_rows_in_a_row_is_a_bug_not_a_race` |
| Complete và `run_idempotent` | cho phép bí mật hoặc body không phải JSON; commit hai lần hoặc không commit; phát lại có commit; không rollback khi lỗi; không đổi `55P03` thành `409`; thiếu `Retry-After`; hàng `IN_PROGRESS` chạy lại việc; bỏ `complete` | `::test_a_stored_response_may_never_hold_a_secret`, `::test_a_success_runs_the_work_inside_the_claim_stores_the_response_and_commits_once`, `::test_an_error_in_the_work_rolls_back_and_the_key_is_not_stored`, `::test_a_lock_wait_timeout_is_409_with_retry_after_not_a_503` |
| SQL | bỏ endpoint khỏi đích xung đột; hàng mới `COMPLETED`; khóa bỏ qua người gọi; `FOR UPDATE`; không đọc lại; `lock_timeout` theo session; `reset` giữ phản hồi cũ; repository commit; clan ngoài SAVEPOINT; clan `ACTIVE`; gói tự gia hạn; mất nơi gốc | `test_business_create_repository_sql.py` (SQL thật) |
| Use case | bỏ kiểm tra `APPROVED`, "đã có clan", gói `ACTIVE`; gói không lấy từ hồ sơ; đọc hồ sơ không khóa; không kiểm trước mã SA nhập; không sinh lại mã, 10 lần thay vì 3, thử lại mọi `IntegrityError`, không ánh xạ chỉ mục hồ sơ, nuốt `IntegrityError` lạ; thiếu profile; subscription hay clan `ACTIVE`; ngày kết thúc bằng ngày bắt đầu; thiếu `created_by`, sai tên, không gắn hồ sơ; không audit, audit thiếu `clan_id` hoặc chứa email, tên họ, mã clan; log chứa mã clan | `test_business_create_api.py` (nhiều test, xem mục 11 của `security_review.md`) |
| Router và CORS | không phân quyền; cho phép cache; không gửi header phát lại; gắn giới hạn tần suất; trạng thái 200; không expose `Idempotency-Replayed` | `::test_everyone_who_is_not_a_system_admin_gets_403_before_any_validation_or_lookup`, `::test_the_endpoint_is_not_rate_limited_and_a_browser_can_read_the_replay_marker`, `test_cors.py::test_a_cross_origin_page_may_read_the_replay_marker`, `test_openapi_contract.py` |
| Ngày và mã clan | không cắt ngày cuối tháng, lệch tháng, không sang năm, cho tháng âm; bảng chữ có ký tự nhập nhằng, 6 ký tự, tiền tố khác, dùng `random` | `test_core_helpers_e5.py` |
| **Trên DB thật (12)** | `INSERT` trơn không `ON CONFLICT`; key commit riêng ngay sau claim; clan không SAVEPOINT; đọc hồ sơ không khóa; bỏ kiểm tra gói, trạng thái; `lock_timeout` theo session; key không bao giờ hoàn tất; audit chứa email; không ánh xạ chỉ mục hồ sơ; không so hash; bỏ kiểm tra hết hạn | `integration/test_business_create_concurrency.py::test_the_same_key_at_the_same_instant_creates_one_business_and_both_get_the_same_answer`, `::test_a_request_that_dies_half_way_leaves_nothing_and_a_waiter_with_the_same_key_creates_it`, `::test_the_business_waits_for_a_review_that_approves_and_then_succeeds`, `integration/test_business_create_db.py` (các test tương ứng ở mục 11 của `security_review.md`) |

Lần chạy đầu có **1 đột biến sống sót** (thử lại vô hạn khi hàng key biến mất, `range(50)` thay vì `range(2)`): test chỉ kiểm kết quả `INTERNAL_ERROR`, vốn giống nhau. Đã siết test (đếm đúng số lần chèn và đọc: 3 và 2) và đột biến bị bắt. Sáu đột biến ban đầu chỉ bị bắt do lỗi phụ (ngoại lệ không xử lý, dòng log lỗi) đã được chạy lại với đúng test dự kiến và đều fail đúng chỗ.

**Cảnh báo về đột biến trên DB thật qua pooler:** đột biến `lock_timeout` theo session làm nhiễm kết nối server của pooler và gây hai lỗi ở lần chạy cả bộ liền sau (xem mục 5, E5). Từ nay đột biến kiểu đổi trạng thái session chỉ chạy ở mức đơn vị. Các đột biến mức DB khác chạy trên nhánh dev: mọi test tích hợp đều rollback, test đồng thời tự dọn dữ liệu `itest-conc-bc-` và không đụng gói `DEV-`.

## 12. Kiểm chứng test bằng đột biến (Mốc E, bước E6a)

Cách làm như mục 8 đến 11: áp từng đột biến lên mã thật, chạy các test liên quan, khôi phục, so sha256 với bản trước khi đột biến. Test chỉ đáng tin khi nó **fail**. Hai điểm khác: (1) các file E6a được **stage** (`git add`, chưa commit) trước khi đột biến, và sau **mỗi** đột biến `git diff` của các file bị chạm phải **trống** (script dừng nếu không); (2) **không dùng đột biến đặt trạng thái session qua pooler** (bài học ở mục 5, E5).

**Kết quả cuối (runner đã sửa, chạy lại toàn bộ trên mã sau bản sửa `UID_MISMATCH`): 124 đột biến mức đơn vị + 14 mức DB thật = 138, cả 138 đều `CAUGHT` theo mã thoát 1, 0 sống sót, 0 không xác định, không có lượt nào bị bắt mà 0 test chạy.**

**Runner đột biến (đã sửa):** kết luận chỉ dựa vào **mã thoát của pytest**: `1` = bị bắt (có test chạy và fail); `0` = sống sót; `2`, `3`, `4`, `5` (ngắt, lỗi nội bộ, lỗi cách dùng hoặc thu thập, **không có test nào chạy**) = **không xác định, tính là chưa bắt**. Mỗi dòng kết quả in mã thoát và số test đã chạy; tên test fail chỉ lấy từ dòng tóm tắt `FAILED tests…`/`ERROR tests…`/`ERROR collecting`, không lấy từ dòng log bị bắt giữ.

**Xử lý lại các lượt cũ:** log cũ không ghi mã thoát, nên tôi không lọc lại được mà **chạy lại toàn bộ** cả hai bộ bằng runner mới (kết quả ở trên). Đếm lại log cũ: thực tế là **138 lượt chứ không phải 137** như đã báo (118 + 6 chạy lại mức đơn vị, 12 + 2 chạy lại mức DB; báo cáo trước đếm thiếu một). Trong số đó 8 lượt "bị bắt" không có dòng `FAILED tests…` (chỉ có dòng log hoặc `deselected`), tức là không chứng minh được; một lượt trong đó là kết quả giả mã 5 nêu dưới đây. Lần chạy lại cho thấy mọi đột biến tương ứng đều bị bắt bằng mã 1 với đúng test dự kiến.

**Đột biến mới cho `UID_MISMATCH` (đều bị bắt):** mức đơn vị: user lạ bị xóa (bù trừ); dựng cờ dọn mà không xóa; coi là lỗi tạm; audit ghi `needs_cleanup = true`; tái dùng user lạ; `finish_failed` dựng cờ dọn. Bắt bởi `test_owner_provisioning_api.py::test_an_unexpected_user_under_our_uid_is_a_final_failure_and_is_never_deleted` và `test_provisioning_repository_sql.py`. Mức DB: user lạ bị xóa (bắt bởi `integration/test_owner_provisioning_db.py::test_a_uid_mismatch_is_failed_never_deleted_and_blocks_nothing`); mật khẩu lọt vào thông điệp lỗi (bắt bởi `::test_after_a_failure_the_password_is_in_no_column_and_not_in_the_error`).

| Nhóm | Đột biến | Test bắt được |
| --- | --- | --- |
| Máy trạng thái và fencing | job mới bị coi là kẹt; bỏ giới hạn lần thử; tiếp quản khi lease còn hiệu lực; job `SUCCEEDED` claim được; fencing không so `attempt_count`, không so `status`, hoặc lệ thuộc đồng hồ lease; lần thử cuối không thành cuối cùng | `test_provisioning_state.py`, `test_owner_provisioning_api.py::test_fencing_looks_at_the_attempt_not_at_the_lease_clock` |
| Repository job | uid không phải `own-<job_id>`; khóa job `FOR UPDATE` hoặc không đọc lại; so sánh email phân biệt hoa/thường; job `FAILED` cũng chặn; số lần thử không tăng; lỗi cuối không dựng cờ dọn hoặc cờ "đã tạo"; dọn xong không hạ cờ; repository commit; khóa clan `FOR UPDATE`; membership sinh ra đã thu hồi; ownership sinh ra đã kết thúc | `test_provisioning_repository_sql.py` |
| Adapter Firebase | chấp nhận uid không có tiền tố `own-` hoặc không đúng dạng UUID; `delete_user`/`create_user` không kiểm uid trước SDK; email đánh dấu đã xác minh; tạo user ở trạng thái vô hiệu; bỏ timeout; không chạy trong thread; gọi SDK ngoài helper; bỏ `httpTimeout`; "không tìm thấy" khi xóa trả sai; phân loại lỗi mật khẩu thành lỗi dữ liệu; email trùng đọc nhầm thành uid trùng | `test_firebase_admin_adapter.py` |
| Cấu hình | kiểm tra lease đổi `>=` thành `>`; mặc định timeout 20, lease 100, 3 lần thử, mật khẩu sống 24 giờ, ký hiệu bắt buộc; cho phép giá trị 0 | `test_firebase_admin_adapter.py`, `test_owner_provisioning_api.py` |
| Mật khẩu và sender | 12 ký tự; không trộn; ký tự dễ nhầm; không đảm bảo chữ số; tùy chọn ký hiệu vô tác dụng; dùng `random`; sender Noop có thể giữ trạng thái | `test_passwords_and_email_sender.py` |
| Nhận yêu cầu (T1) | không kiểm admin API; clan không nằm trong hash; replay mang mật khẩu; key đang chạy bắt đầu job mới, thiếu `job_id` hoặc `Retry-After`; key không ghi tài nguyên; bỏ từng kiểm tra (trạng thái clan, đã có Owner, cleanup còn nợ, job còn sống, email đã là tài khoản); bỏ nguồn thông tin từ hồ sơ (email, tên, điện thoại); body không ghi đè được | `test_owner_provisioning_api.py` |
| Chạy và ghi (T2 đến T4) | lease 1 giây; không tìm user có sẵn; tái dùng user có email khác; user cũ giữ mật khẩu cũ; không nhận ra tạo song song; lỗi chính sách mật khẩu thành lỗi mạng; lỗi vĩnh viễn thành tạm thời và ngược lại; bỏ fencing ở T3, T4 và khi ghi lỗi; lỗi DB không được ghi thành lỗi của job; bỏ kiểm tra clan đổi; Owner không phải đổi mật khẩu, không hạn, hoạt động ngay, sai vai trò, membership chỉ mời, thiếu ownership; phản hồi lưu có mật khẩu; key không hoàn tất; gửi email lỗi làm hỏng request; ẩn mật khẩu khỏi response; ghi mật khẩu hoặc email vào log | `test_owner_provisioning_api.py` (xem mục 12 của `security_review.md`) |
| Lỗi và bù trừ | lần thử cuối không cuối cùng; không bù trừ; lỗi cuối ghi như lỗi tạm; key không giải phóng; xóa theo email; xóa lỗi vẫn tính là xong; cờ hạ khi xóa lỗi; cờ không bao giờ hạ; lượt bị thay thế báo như lỗi nhà cung cấp | `test_owner_provisioning_api.py` |
| Audit | uid Firebase trong audit; đổi tên sự kiện; audit không có `clan_id` | `test_owner_provisioning_api.py::test_one_audit_row_per_job_state_change_and_nothing_personal_in_any_of_them` |
| Router, quyền | thay phân quyền bằng chỉ cần đăng nhập; đọc job không phân quyền; cho phép cache (cả hai endpoint); không gửi header phát lại; gắn giới hạn tần suất; trạng thái 200; header không bắt buộc; không ghi địa chỉ kết nối; action mới thiếu dòng trong `ACTION_RULES` | `test_owner_provisioning_api.py`, `test_openapi_contract.py`, `test_permissions.py` |
| **Trên DB thật (14)** | `UID_MISMATCH` bị xóa; mật khẩu vào thông điệp lỗi; cờ hạ khi xóa lỗi; lỗi cuối ghi như lỗi tạm; xóa theo email; bỏ fencing ở T4; bỏ kiểm tra tài khoản đã có, cleanup còn nợ; tra email phân biệt hoa/thường; key không ghi job; key không giải phóng; job claim không lease (CHECK `provisioning_jobs_running_lease_check` của DB tự bắt); không ghi membership; mật khẩu vào audit | `integration/test_owner_provisioning_db.py`, `integration/test_owner_provisioning_concurrency.py` |

**Sáu đột biến sống sót lần đầu (đều do thiếu khẳng định, không phải do mã), đã bổ sung test và bị bắt:** lease chỉ 1 giây (thêm khẳng định `lease == FROZEN + 90s`); tái dùng user có sẵn không đặt mật khẩu mới (test `test_a_firebase_user_left_by_an_earlier_attempt_is_reused_with_a_new_password`); không nhận ra tạo song song (test `..._a_parallel_creation_of_the_same_job_is_recognised...`); bỏ fencing ở T3 (khẳng định job của lượt mới không bị ghi: `firebase_user_created` và lease); bỏ fencing ở T4 (test `..._a_run_replaced_between_the_last_two_transactions_writes_no_owner`); ghi lỗi không kiểm fencing (test `..._a_replaced_run_that_then_fails_does_not_overwrite_the_newer_attempts_job`).

**Một kết quả "bị bắt" giả đã phát hiện và sửa:** đột biến "bỏ fencing ở T4" trên DB thật ban đầu báo bị bắt chỉ vì bộ lọc `-k` không khớp test nào (`8 deselected`, pytest thoát mã 5). Chạy lại với bộ lọc đúng thì **sống sót** (test đồng thời chỉ thay thế lượt chạy trước T3). Đã thêm `test_a_run_replaced_just_before_the_rows_are_written_writes_no_owner` (thay thế ngay trước T4 trên DB thật), và đột biến bị bắt đúng test đó. Lỗi này là lý do runner được sửa để chỉ tin mã thoát (xem trên).

**Điều kiện J:** sau mỗi đột biến `git diff` của file bị chạm trống (lần chạy cuối: 124 + 14 lần kiểm tra, không lần nào lệch), và sha256 các file sau mọi lượt khớp bản gốc. Sau các lượt trên DB, dev DB vẫn đúng trạng thái: bảng dữ liệu 0 dòng, 3 gói `DEV-`, 6 dòng tính năng, `roles`/`permissions`/`role_permissions` = 4/18/0, alembic `0003`.

## 13. Kiểm chứng test bằng đột biến (Mốc E, bước E6b)

Cách làm như mục 8 đến 12 và **runner đã sửa ở mục 12** (chỉ mã thoát `1` của pytest là "bị bắt"; `0` sống sót; mã khác không xác định, tính là chưa bắt; mỗi dòng in mã thoát và số test đã chạy). Các file E6b được **stage** (`git add`, chưa commit) trước khi đột biến, sau **mỗi** đột biến `git diff` của file bị chạm phải **trống** (script dừng nếu không), sha256 sau khôi phục khớp bản trước. **Không có đột biến nào đặt trạng thái session qua pooler.**

**Kết quả: 96 đột biến mới (83 mức đơn vị + 13 trên DB thật), cả 96 `CAUGHT` bằng mã thoát 1; 0 sống sót, 0 không xác định, 0 lượt bị bắt mà không có test nào chạy.** Hồi quy: vì E6b đổi mã dùng chung với E6a (`set_owner_password`, tìm key theo job, `_cleanup`), cả hai bộ E6a được chạy lại trên mã mới: **124 mức đơn vị + 14 trên DB thật, cả 138 bị bắt, 0 sống sót, 0 không xác định**. Trước đó 10 đột biến E6a phải dời điểm neo vì mã đã đổi (ví dụ `set_password` thành `set_owner_password`); script dò (`--dry`) báo 0 điểm neo không tìm thấy trước khi chạy.

| Nhóm | Đột biến | Test bắt được |
| --- | --- | --- |
| Adapter `set_owner_password` | **bỏ kiểm tra uid**; không thu hồi refresh token; gọi SDK ngoài thread; user không có báo thành lỗi chung; mật khẩu bị từ chối báo thành lỗi chung; `is_own_uid` nhận mọi chuỗi sau `own-`; ba chỗ luồng Owner (dùng lại user, tạo song song, đặt lại) chuyển sang `set_password` chung | `test_firebase_admin_adapter.py` (kể cả quét cây cú pháp: retry và reset không gọi `set_password` chung, chỉ luồng đổi mật khẩu gọi nó) |
| Máy trạng thái (abandon) | nhận `RUNNING` còn lease; nhận `SUCCEEDED`; nhận `FAILED`; nhận `PENDING` vừa tạo; từ chối `FAILED_RETRYABLE` | `test_provisioning_state.py` |
| Retry | không kiểm admin API; **nhận mọi trạng thái (retry nhận `SUCCEEDED`)**; bỏ kiểm tra clan còn `PENDING`, đã có Owner, email đã thành tài khoản; job chỉ nợ dọn bị chạy lại như job thường; dọn chưa xác nhận mà báo xong; trả `201` thay vì `200`; khóa job trước clan; không khóa clan; đổi tên sự kiện audit; **không tìm key gốc theo job**; `409` không nêu trạng thái; bỏ `Retry-After`; thiếu commit của bước nhận; **mật khẩu vào log, vào thông báo lỗi, vào audit, vào bản lưu idempotency** | `test_owner_recovery_api.py`, `test_owner_provisioning_api.py` |
| Abandon | không dọn khi lượt đã từng chạy; dọn cả khi chưa từng chạy; không dựng cờ trước khi xóa; không giải phóng key; không khóa hàng key; **commit cờ sau khi xóa**; đổi tên sự kiện audit; mã lỗi khác `ABANDONED` | `test_owner_recovery_api.py` |
| Danh sách | tổng bằng độ dài trang; bỏ bộ lọc clan, bộ lọc trạng thái, offset; đảo thứ tự; đếm không lọc; **thêm email vào schema** | `test_provisioning_repository_sql.py`, `test_owner_recovery_api.py` |
| Đặt lại mật khẩu | không kiểm admin API; clan không Owner được nhận; Owner không do job tạo được nhận; **bỏ kiểm tra `PENDING`** (ACTIVE, LOCKED, DISABLED); bỏ kiểm tra `must_change_password`; **không kết thúc giao dịch kiểm tra trước Firebase**; kiểm tra khóa clan; **ghi DB trước Firebase**; **không thu hồi phiên**; bỏ so sánh phiên bản credential; bỏ kiểm tra lại Owner của clan và trạng thái sau Firebase; không khóa credential hay clan; khóa cả `users`; hạn 24 giờ; không đặt `must_change_password`; không cập nhật `issued_at`; đổi tên action audit; **email vào audit, mật khẩu vào log và vào thông báo lỗi**; nuốt lỗi Firebase; nuốt "user không có"; không gọi sender | `test_owner_recovery_api.py` |
| Router, phân quyền | ba route (`retry`, `abandon`, đặt lại) chỉ cần phiên; danh sách không phân quyền; đổi action của đặt lại; cho phép cache cả bốn response | `test_owner_recovery_api.py` (kể cả `test_every_owner_route_is_guarded_by_exactly_the_planned_action`, đọc action từ closure của dependency) |
| **Trên DB thật (13)** | đặt lại giữ giao dịch và khóa clan qua lời gọi Firebase; retry giữ giao dịch của bước nhận qua lời gọi Firebase; abandon commit cờ sau khi xóa; không tìm key gốc theo job; đặt lại không thu hồi phiên; đặt lại bỏ so sánh phiên bản credential (hai đặt lại cùng lúc); đặt lại không kiểm tra lại trạng thái sau Firebase; abandon không giải phóng key; job chỉ nợ dọn bị chạy lại; abandon nhận `RUNNING` còn lease; retry nhận mọi trạng thái; danh sách bỏ bộ lọc trạng thái; tiếp quản không tăng `attempt_count` | `integration/test_owner_recovery_db.py`, `integration/test_owner_recovery_concurrency.py` |

**Đối chiếu danh sách đột biến bắt buộc:** bỏ kiểm tra uid ở `set_owner_password` (bị bắt), reset không thu hồi session (mức đơn vị và DB thật), DB trước Firebase (bị bắt), giữ khóa qua lời gọi Firebase (đặt lại và retry, trên DB thật bằng `FOR UPDATE NOWAIT` từ trong lời gọi Firebase), abandon cho `RUNNING` còn lease (mức đơn vị: máy trạng thái; DB thật), retry nhận `SUCCEEDED` (bị bắt), bỏ kiểm tra Owner `PENDING` (bị bắt), mật khẩu vào audit, log, lỗi (bị bắt). Cả tám loại đều có và đều `CAUGHT`.

**Lưu ý trung thực:** vài đột biến mức đơn vị bị bắt bởi bước dựng ban đầu của test chứ không bởi khẳng định chuyên biệt (ví dụ "không tìm key gốc theo job" làm hỏng chính khẳng định `idem.rows == []` ở hàm dựng `retryable()`, vì ghi lỗi dựa vào cùng cách tìm key). Chúng vẫn bị bắt (mã thoát 1, có test chạy), và khẳng định chuyên biệt của chúng cũng có (xem bảng mục 13 của `security_review.md`); đột biến tương ứng trên DB thật bị bắt bởi chính test chuyên biệt (`-k completes_the_original_key`). Đột biến "đặt lại dùng action khác" về hành vi là tương đương (cả hai action đều chỉ cho SA), nên chỉ một test đọc action của từng route mới bắt được nó; test đó đã có và đột biến bị bắt.

**Điều kiện:** sau mỗi đột biến `git diff` trống (83 + 13 lượt E6b, 124 + 14 lượt E6a), sha256 các file sau mọi lượt khớp bản gốc, DB dev sau mọi lượt về đúng trạng thái ở mục 5.

## 14. Kiểm chứng test bằng đột biến (Mốc E, bước E7)

Cách làm như mục 8 đến 13 và **runner đã sửa ở mục 12** (chỉ mã thoát `1` của pytest là "bị bắt"; `0` sống sót; mã khác không xác định, tính là chưa bắt; mỗi dòng in mã thoát và số test đã chạy). Các file E7 được **stage** (`git add`, chưa commit) trước khi đột biến, sau **mỗi** đột biến `git diff` của file bị chạm phải **trống** (script dừng nếu không), sha256 sau khôi phục khớp bản trước. **Không có đột biến nào đặt trạng thái session qua pooler** (kể cả đột biến bỏ lock timeout chỉ là bỏ một lời gọi `set_config(..., true)`, không đặt gì ở cấp session).

**Kết quả: 74 đột biến (60 mức đơn vị + 14 trên DB thật), cả 74 `CAUGHT` bằng mã thoát 1; 0 sống sót, 0 không xác định, 0 lượt bị bắt mà không có test nào chạy.** E7 không đổi mã dùng chung với E6, nên không chạy lại bộ E6 (các file E6 không bị chạm; `tests/fakes.py`, `fakes_owner.py` chỉ được thêm phương thức và pytest -q vẫn xanh).

| Nhóm | Đột biến | Test bắt được |
| --- | --- | --- |
| Điều kiện kích hoạt | clan không cần `PENDING`; clan không có mà không `404`; `409` của clan `ACTIVE` không nêu lúc kích hoạt; không cần Owner; không kiểm thành viên, thu hồi; không kiểm vai trò, hoặc kiểm vai trò ở phạm vi hệ thống; Owner `LOCKED`/`DISABLED`/`SUSPENDED` hay trạng thái lạ được nhận; bắt Owner phải `ACTIVE` (đảo quyết định Q1); gói `ACTIVE` sẵn không chặn; không có `PENDING` không bị từ chối; hai `PENDING` không bị từ chối; gói không còn `ACTIVE` được nhận | `test_clan_activation_api.py` |
| Hiệu lực | `starts_at` giữ ngày tạm; `ends_at` tính từ ngày tạm; sai một tháng; clan hoặc gói không được kích hoạt; thiếu commit; commit clan trước gói (không nguyên tử) | `test_clan_activation_api.py`; DB thật `test_clan_activation_db.py::test_a_failure_half_way_rolls_both_tables_back` |
| Repository | không ghi `activated_at`, `status`, `updated_at` của clan; không ghi trạng thái hay ngày của gói; khóa gói bằng `FOR UPDATE`, không có thứ tự cố định, không đọc lại hàng, không lọc theo clan; job gần nhất ở cuối, không lọc theo clan | `test_clan_activation_repository_sql.py` |
| Khóa | khóa gói trước clan; không khóa gói; không khóa clan; khóa `users`; bỏ lock timeout | `test_clan_activation_api.py` (thứ tự lời gọi); DB thật `test_clan_activation_concurrency.py` |
| Audit | đổi tên action; email, tên vào audit; thiếu id Owner; thiếu trạng thái cũ; người thực hiện sai | `test_clan_activation_api.py::test_the_audit_row_holds_ids_statuses_and_dates_and_nothing_personal` |
| Đọc clan | bỏ gói ACTIVE khi chọn; thiếu id Owner, job gần nhất, mã gói; clan không có mà không `404`; **thêm email vào schema**; response kích hoạt mất ngày | `test_clan_activation_api.py`, `test_openapi_contract.py`, `test_security_checks.py` |
| Router, quyền | cho phép cache cả hai response; kích hoạt chỉ cần phiên; đọc không phân quyền; đổi action của hai route; **kích hoạt đòi `Idempotency-Key`**; `clan.read` và `clan.activate` mở cho Owner | `test_clan_activation_api.py`, `test_permissions.py` |
| **Trên DB thật (14)** | không kích hoạt gói; `ends_at` từ ngày tạm; clan không cần `PENDING`; không kiểm vai trò; Owner `LOCKED` được nhận; gói không còn `ACTIVE` được nhận; hai `PENDING` không bị từ chối; không nguyên tử; không kích hoạt clan (đường đi của Owner thật); đọc có email; job gần nhất là cũ nhất; kích hoạt lần hai không bị chặn bởi gì; **không khóa clan và gói khi hai kích hoạt cùng lúc**; bỏ lock timeout (khóa bị giữ làm request treo) | `integration/test_clan_activation_db.py`, `integration/test_clan_activation_concurrency.py` |

**Lưu ý trung thực:** nhiều đột biến mức đơn vị bị bắt bởi test thành công đầu tiên chứ không bởi test chuyên biệt của chúng (ví dụ "gói không được kích hoạt" làm hỏng khẳng định ngày của `test_an_activation_makes_the_clan_and_its_subscription_active_from_now`); đó vẫn là mã thoát 1 với test chạy, và test chuyên biệt tương ứng có trong bảng ở `security_review.md` mục 14. Đột biến "đổi action" của hai route về hành vi là tương đương (mọi action ở đây đều chỉ cho SA) nên chỉ test đọc action của từng route mới bắt được; test đó đã có.

**Điều kiện:** sau mỗi đột biến `git diff` trống (60 + 14 lượt), sha256 các file sau mọi lượt khớp bản gốc, DB dev sau mọi lượt về đúng trạng thái ở mục 5.
