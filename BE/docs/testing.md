# Chạy seed và test

Chạy từ thư mục `BE`, dùng `.venv\Scripts\python.exe`. Biến môi trường PowerShell chỉ có hiệu lực trong cửa sổ hiện tại. `DATABASE_URL` lấy từ `BE/.env`; không in và không commit.

## 0. Cấu hình Firebase (Mốc D) — máy dev có `.env` cũ cần sửa

- `FIREBASE_CREDENTIALS_PATH` **đã đổi tên** thành `FIREBASE_SERVICE_ACCOUNT_PATH`. Tên cũ bị bỏ qua im lặng, nên `.env` cũ sẽ chạy như không có service account (đổi mật khẩu trả `503`).
- `FIREBASE_PROJECT_ID` **không còn giá trị mặc định**. Thiếu thì app vẫn khởi động, nhưng `POST /auth/session` trả `503 PROVIDER_UNAVAILABLE` (fail closed).
- `FIREBASE_SERVICE_ACCOUNT_PATH` chỉ cần cho Admin API (đổi mật khẩu, kiểm tra token bị thu hồi). File không commit; `.gitignore` đã chặn `*service-account*.json` và `*firebase-adminsdk*.json`.
- Không đặt `FIREBASE_AUTH_EMULATOR_HOST`: ở chế độ emulator, SDK nhận token không chữ ký, nên backend từ chối toàn bộ (`503`).
- Test **không** đọc các biến Firebase từ `.env`: `tests/conftest.py` tự đặt `FIREBASE_PROJECT_ID=test-project`, `FIREBASE_SERVICE_ACCOUNT_PATH=` (rỗng) và xóa biến emulator. Không test nào gọi Firebase thật; luồng đăng nhập dùng `FakeIdentityProvider` trong `tests/fakes.py`.

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
