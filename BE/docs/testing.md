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

## 5. Số liệu chạy mới nhất (Mốc G, 06/10/2026)

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
| T28–30 Migration | DB trống; DB baseline; rollback/forward-fix | **Chưa** | Chưa có revision Alembic; baseline do trưởng nhóm chốt |
| T31–33 Tích hợp | CORS FE; luồng Guest đến Owner; log có request_id không secret | Một phần | CORS: `test_cors.py`; log request_id/không secret: `test_auth_api.py`, `test_security_checks.py`. Luồng Guest đến Owner: Mốc E. Thử với FE thật: chưa |

Ngoài mục 11 của kế hoạch, có thêm: đồng thời "SA cuối" và deadlock (`integration/test_user_admin_concurrency.py`, `test_last_sa_concurrency.py`), khóa dòng `FOR NO KEY UPDATE`, đối chiếu OpenAPI với hợp đồng, kiểm tra khởi động và lỗi cấu hình không lộ giá trị.

