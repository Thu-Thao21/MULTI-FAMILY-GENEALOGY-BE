# Chạy seed và test

Chạy từ thư mục `BE`, dùng `.venv\Scripts\python.exe`. Biến môi trường PowerShell chỉ có hiệu lực trong cửa sổ hiện tại. `DATABASE_URL` lấy từ `BE/.env`; không in và không commit.

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
- Route trong test (`/auth/me`, `/admin/users`, `/clans/{id}/users`...) là app mini ở `tests/integration/factory.py` gắn dependency thật; chưa có endpoint thật trong `main`.

## 3. Seed dữ liệu dev

```powershell
$env:ALLOW_DEV_SEED = "1"
.venv\Scripts\python.exe scripts\seed_dev.py            # tạo / bổ sung (chạy lại an toàn)
.venv\Scripts\python.exe scripts\seed_dev.py --cleanup  # xóa chỉ dữ liệu DEV-*
```

Thiếu `ALLOW_DEV_SEED=1` script thoát ngay. Seed chạy trong một transaction, in số bản ghi "tạo mới" và "đã có", không in bí mật. Không có password, không có phiên/token.

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

`--cleanup` xóa dòng họ `DEV-*` (membership, ownership, assignment xóa theo cascade) rồi user `dev-*`. Nếu user dev đã được tham chiếu bởi bảng khác không cascade thì xóa lỗi và rollback toàn bộ.
