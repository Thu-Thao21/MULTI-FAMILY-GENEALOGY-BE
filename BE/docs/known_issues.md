# Vấn đề đã biết

Danh sách lỗi và rủi ro phát hiện trong lúc làm. Mục đã xử lý giữ lại để tra cứu, có ghi **Đã xử lý**.

## KI-01 Firebase ID token có thể được chấp nhận mà không kiểm chữ ký — Đã xử lý (Mốc D)

- **Đã xử lý:** `app/core/firebase.py` viết lại. Chỉ xác minh bằng `firebase_admin.auth.verify_id_token` (chữ ký RS256 theo chứng chỉ công khai của Google, issuer, audience = `FIREBASE_PROJECT_ID`, hạn dùng). Không còn nhánh giải mã không kiểm chữ ký. Thiếu `FIREBASE_PROJECT_ID`, đường dẫn service account sai, hoặc có `FIREBASE_AUTH_EMULATOR_HOST` (chế độ emulator của SDK nhận token không chữ ký) đều trả `503 PROVIDER_UNAVAILABLE`. Test: `tests/test_firebase_provider.py`, `tests/test_no_insecure_auth.py`.
- **Còn lại:** kiểm tra thu hồi token phía Firebase (`check_revoked`) chỉ bật khi có `FIREBASE_SERVICE_ACCOUNT_PATH`, vì đó là lời gọi Admin API. Không có service account thì token bị thu hồi phía Firebase vẫn dùng được tới khi hết hạn (tối đa 1 giờ).

Mô tả gốc:

- **File:** `app/core/firebase.py`, hàm `verify_firebase_token`
- **Hiện trạng:** Khi không có file service account, hoặc khi Admin SDK báo lỗi, hàm chuyển sang `jwt.decode(..., options={"verify_signature": False})`. Hàm chỉ kiểm `exp` và sự có mặt của UID.
- **Rủi ro:** Bất kỳ ai cũng có thể tự tạo JWT với UID tùy ý và được chấp nhận. Lỗi cấu hình trở thành lỗ hổng giả mạo danh tính, trái với mục 5 của kế hoạch ("cấu hình sai phải từ chối").
- **Ảnh hưởng hiện tại:** Chưa có route nào gọi hàm này. `app/dependencies/auth.py` mới không import nó.
- **Xử lý ở Mốc D:** Bỏ nhánh fallback. Chỉ dùng `firebase_admin.auth.verify_id_token(..., check_revoked=True)`. Thiếu cấu hình thì từ chối và trả `503 PROVIDER_UNAVAILABLE`. Không log nội dung exception vì có thể chứa token.

## KI-02 Băm mật khẩu bcrypt cục bộ cắt mật khẩu ở 72 byte — Đã xử lý (Mốc D)

- **Đã xử lý:** Xóa `app/core/security.py` và `passlib[bcrypt]` trong `requirements.txt`. Mật khẩu do Firebase quản lý; DB không lưu mật khẩu. Test canh chừng: `tests/test_no_insecure_auth.py`.

Mô tả gốc:

- **File:** `app/core/security.py`, hàm `hash_password` và `verify_password`
- **Hiện trạng:** Mật khẩu bị cắt `[:72]` byte trước khi băm và kiểm tra. Hai mật khẩu chung 72 byte đầu được coi là trùng.
- **Rủi ro:** Giảm độ mạnh mật khẩu dài một cách âm thầm. Ngoài ra đây là kho mật khẩu cục bộ song song, trái với mục 5 ("không thêm kho mật khẩu local song song").
- **Ảnh hưởng hiện tại:** Chưa có route nào gọi hai hàm này.
- **Xử lý ở Mốc D:** Nếu chốt D01 dùng Firebase cho mật khẩu thì xóa module này. Nếu cần mật khẩu cục bộ thì thiết kế lại theo mục 5, không cắt input âm thầm.

## KI-03 uq_active_user_role_scope không chặn gán trùng role cấp hệ thống (clan_id NULL)

- **Bảng/index:** `user_roles`, `uq_active_user_role_scope` = `UNIQUE (user_id, role_id, clan_id) WHERE revoked_at IS NULL`.
- **Hiện trạng:** PostgreSQL coi hai giá trị NULL là khác nhau, nên với `clan_id IS NULL` (role cấp hệ thống, tức mọi dòng `SYSTEM_ADMIN`) index không bao giờ báo trùng. Một user có thể có nhiều dòng `SYSTEM_ADMIN` còn hiệu lực. Trong clan (`clan_id` không NULL) index chặn đúng.
- **Bằng chứng:** `tests/integration/test_user_roles_unique_index.py`. `test_db_accepts_duplicate_system_admin_grant_current_behaviour` ghi lại hành vi hiện tại; `test_db_should_reject_duplicate_system_admin_grant` là `xfail(strict=True)` mô tả hành vi mong muốn.
- **Ảnh hưởng hiện tại:** Không làm sai quyền: `has_active_role` chỉ hỏi "có ít nhất một dòng", và `count_active_system_admins` dùng `COUNT(DISTINCT user_id)` nên guard "SA cuối cùng" không bị đếm dôi (có test). Rủi ro còn lại là dữ liệu rác và việc thu hồi chỉ một dòng không làm mất quyền SA.
- **Việc cần làm trong code:** Khi cấp SA, kiểm tra `has_active_role(user, 'SYSTEM_ADMIN', clan_id=None)` trước khi INSERT, trong cùng transaction; khi thu hồi, đặt `revoked_at` cho mọi dòng còn hiệu lực của user.
- **Đề xuất cho lead quyết định (không tự áp dụng):** migration thay index bằng `UNIQUE NULLS NOT DISTINCT (user_id, role_id, clan_id) WHERE revoked_at IS NULL` (PostgreSQL 15+), hoặc thêm index riêng `UNIQUE (user_id, role_id) WHERE clan_id IS NULL AND revoked_at IS NULL`. Cần dọn dòng trùng đã có trước khi tạo index. Khi migration được duyệt: xóa test "current_behaviour" và bỏ `xfail` ở test còn lại.

## KI-04 user_sessions.token_jti_hash không có unique index

- **Bảng/index:** `user_sessions` chỉ có `user_sessions_pkey`, `idx_user_sessions_user`, `idx_user_sessions_active`. Kế hoạch mục 4 yêu cầu kiểm tra unique token hash; DB hiện chưa có.
- **Hiện trạng:** DB nhận hai phiên cùng `token_jti_hash`; khi đó `get_session_by_token_hash` ném `MultipleResultsFound` (lỗi 500 thay vì `SESSION_INVALID`). Token 256-bit ngẫu nhiên nên va chạm thực tế không đáng kể, nhưng DB không bảo đảm.
- **Bằng chứng:** `test_db_does_not_enforce_unique_token_hash_known_issue` trong `tests/integration/test_sessions_db.py`.
- **Đề xuất cho lead:** migration `UNIQUE (token_jti_hash)` (cột đang nullable; unique cho phép nhiều NULL).

## KI-05 Chưa có API reset mật khẩu (`/auth/password-reset/request`, `/confirm`)

- **Quyết định (Mốc D):** để sang mốc sau. `confirm` cần REST Identity Toolkit (API key), `request` cần quyết định email (D04).
- **Tạm thời:** FE dùng `sendPasswordResetEmail` của Firebase SDK trực tiếp. Sau khi reset, `credential_metadata.password_changed_at` **không** được cập nhật (BE không biết), nên phiên ứng dụng cũ vẫn sống tới khi hết hạn (8 giờ) và ID token đăng nhập trước lúc reset vẫn đổi được phiên trong thời hạn của nó (trừ khi có service account: khi đó `check_revoked` của Firebase chặn token phát hành trước lúc reset). Trái với tiêu chí "reset phải làm phiên cũ mất hiệu lực" ở mục 6 của plan; cần xử lý khi làm endpoint reset.

## KI-06 `POST /auth/session` chưa có rate limit

- **Hiện trạng:** hợp đồng ghi `429 RATE_LIMITED` nhưng chưa có hạ tầng giới hạn. Token sai và UID lạ chỉ ghi log ứng dụng (không ghi DB), nên spam không làm phình `login_history`, nhưng mỗi request vẫn tốn một lần xác minh token.
- **Cần lead quyết định:** limiter trong bộ nhớ (một instance) hay dùng chung (Redis/DB), ngưỡng theo IP và theo UID, và vị trí đặt (app hay reverse proxy).
