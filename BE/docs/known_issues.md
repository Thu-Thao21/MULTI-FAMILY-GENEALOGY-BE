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

## KI-07 Chưa có API cấp Family Admin mới và thu hồi Family Admin hẳn — Đã xử lý (Mốc F2)

- **Đã xử lý:**
  - `POST /clans/{id}/admins` (BO đề bạt một thành viên `ACTIVE` thành FA toàn clan, kèm tập quyền ban đầu, có thể rỗng) và `DELETE /clans/{id}/admins/{user_id}` (thu hồi hẳn). `PUT .../permissions` của Mốc F sửa được assignment mới tạo.
  - Hai action mới `clan.fa.assign`, `clan.fa.revoke`, chỉ BO, clan phải `ACTIVE`.
  - Đề bạt ghi assignment, các dòng permission và một dòng `user_roles` `FAMILY_ADMIN` trong clan; thu hồi đặt `revoked_at` cho mọi assignment còn hiệu lực của user trong clan, **xóa các dòng permission** (lịch sử mã quyền nằm ở `audit_logs.old_data`) và đặt `revoked_at` cho dòng vai trò. Chi tiết: `api_contract.md` mục 6, quyết định 28 đến 34.
- **Còn lại:**
  - Phạm vi chi/ngành: `POST` luôn tạo assignment toàn clan (không nhận `branch_id`), `PUT` chỉ tác động lên assignment toàn clan; assignment theo chi/ngành chỉ có thể tạo bằng SQL hoặc dữ liệu seed, và chỉ `DELETE` mới thu hồi được. Bảng `branches` chưa có model. `authorize()` vẫn kiểm `branch_id` của tài nguyên.
  - Đề bạt qua lời mời (`FAMILY_ADMIN_INVITE`, D05) chưa làm.

## KI-08 DB không chặn hai assignment FA còn hiệu lực cho cùng (clan, user) — còn mở ở tầng DB

- **Bảng:** `family_admin_assignments` chỉ có khóa chính; không có unique trên `(clan_id, user_id)` (kể cả `WHERE revoked_at IS NULL`; `branch_id` NULL cũng không bị unique).
- **Code bảo vệ (Mốc F2), không phải DB:** mọi đề bạt xếp hàng trên dòng `clan_memberships (clan, user)` bằng `FOR NO KEY UPDATE`; request thứ hai thấy assignment của request đầu và trả `409`. `PUT` và `DELETE` khóa các dòng assignment của user (`FOR NO KEY UPDATE`, `ORDER BY assignment_id`). Dữ liệu trùng chỉ có thể xuất hiện nếu ghi thẳng vào DB (SQL, import, hoặc code tương lai bỏ qua các hàm này). `uq_active_user_role_scope` là lớp bảo vệ thứ hai ở DB, nhưng chỉ cho dòng `user_roles`, không cho assignment.
- **Hiện trạng với dữ liệu trùng đã có:** `PUT .../permissions` trả `409 STATE_CONFLICT` khi user có nhiều hơn một assignment toàn clan còn hiệu lực; `authorize()` hợp (union) quyền của mọi assignment còn hiệu lực; `DELETE` thu hồi tất cả. Test: `test_branch_limited_and_duplicate_assignments_on_db`, `test_revoke_takes_every_active_assignment_and_leaves_other_users_alone`.
- **Test đồng thời** (`tests/integration/test_family_admin_concurrency.py`): hai đề bạt cùng lúc chỉ một thắng; test đối chứng (bỏ khóa membership) cho thấy hai assignment trùng xuất hiện, tức là chỉ có khóa trong code đứng giữa.
- **Đề xuất cho lead (không tự áp dụng):** index unique trên `(clan_id, user_id, branch_id)` với `NULLS NOT DISTINCT` và `WHERE revoked_at IS NULL` (PostgreSQL 15+). Cần dọn dòng trùng trước khi tạo index. Đây là lớp bảo vệ ở tầng DB; khóa trong code vẫn nên giữ.

## KI-09 Danh sách quyền ủy quyền được: chỉ cấm `ADMIN_MANAGE`

- **Quyết định (Mốc F2):** mã phải có trong bảng `permissions` (lạ → `422`) và **không** nằm trong `NON_DELEGABLE_PERMISSION_CODES` (`app/dependencies/permissions.py`, hiện chỉ `ADMIN_MANAGE`; vi phạm → `403 FORBIDDEN`, theo dòng "cấp vượt quyền được ủy quyền" của hợp đồng gốc). Áp dụng cho `POST` và `PUT`. **Hệ quả:** `PUT` giữ nguyên `ADMIN_MANAGE` của một assignment cũ cũng bị `403`; muốn lưu phải bỏ mã đó (khi đó nó bị gỡ khỏi assignment).
- **Các mã nhạy cảm còn lại trong bảng `permissions` (kiểm bằng SELECT ngày 06/10/2026), vẫn được ủy quyền, để lead xem xét thêm vào danh sách cấm nếu cần:**
  - `MEMBER_ACCOUNT_MANAGE` ("Quản lý tài khoản thành viên"): mở danh sách tài khoản của clan (đang dùng bởi `clan.users.list`);
  - `AUDIT_VIEW` (xem nhật ký), `IMPORT_EXPORT` (nhập/xuất dữ liệu), `FUND_MANAGE` (quỹ), `INTER_FAMILY_MANAGE` (liên họ).
- **Hiện chỉ `MEMBER_ACCOUNT_MANAGE` có tác dụng** (không action nào khác dùng mã FA); mã khác được lưu và hiện trong `/auth/me` nhưng chưa mở quyền gì.

## KI-10 Khóa tài khoản chỉ chặn ở DB, không đụng Firebase

- **Quyết định (Mốc F):** `PATCH /admin/users/{id}/status` chỉ đổi `users.status` và thu hồi phiên ứng dụng. Không gọi Firebase Admin SDK (không `disabled=True`, không `revoke_refresh_tokens`).
- **Hệ quả:** người bị khóa vẫn đăng nhập được vào Firebase và ID token còn sống tối đa 1 giờ, nhưng không đổi được phiên: `POST /auth/session` trả `403 ACCOUNT_BLOCKED` và mọi request dùng phiên cũ trả `401 SESSION_INVALID`. Mở khóa không cần làm gì phía Firebase. Cần lead quyết định nếu muốn chặn cả đăng nhập phía Firebase (cần Admin API và service account).

## KI-11 Triển khai sau reverse proxy: `login_history` ghi IP của proxy

- **Hiện trạng:** `ClientInfo.from_request` chỉ dùng IP của kết nối trực tiếp (`request.client.host`) và cố ý **không** tin `X-Forwarded-For`. Sau reverse proxy (nginx, load balancer, Cloud Run...), mọi dòng `login_history`, `user_sessions` và `audit_logs` sẽ mang IP của proxy.
- **Việc cần làm khi triển khai:** chạy uvicorn với `--proxy-headers` kèm `--forwarded-allow-ips=<danh sách proxy tin cậy>` (không dùng `*` trừ khi proxy là đường vào duy nhất). Dockerfile hiện **chưa** bật các cờ này, theo quyết định của Mốc G.
- **Rủi ro nếu bật sai:** tin `X-Forwarded-For` từ nguồn không tin cậy cho phép giả mạo IP trong nhật ký đăng nhập.

## KI-12 CORS: lỗi 500 chưa xử lý không có header CORS — Đã xử lý (Mốc G)

- **Phát hiện:** Starlette chạy handler của `Exception` trong lớp ngoài cùng (`ServerErrorMiddleware`), nằm ngoài `CORSMiddleware`. Lỗi 500 vì thế tới trình duyệt không có `Access-Control-*`, FE chỉ thấy lỗi mạng và không đọc được `request_id`.
- **Đã xử lý:** `UnhandledErrorMiddleware` đặt ngay dưới `CORSMiddleware` (thứ tự: RequestId, CORS, UnhandledError), trả cùng envelope 500 và cùng log như trước (tên lớp lỗi và `request_id`, không có thông điệp lỗi). Thêm `expose_headers=["X-Request-ID", "Retry-After"]`. Test: `tests/test_cors.py`.

## KI-13 Lỗi `DATABASE_URL` sai định dạng in cả chuỗi kết nối (có mật khẩu) — Đã xử lý (Mốc G)

- **Phát hiện:** `ValidationError` của pydantic in `input_value='<giá trị>'`, nên một `DATABASE_URL` sai định dạng làm lộ mật khẩu trong traceback khởi động và log triển khai.
- **Đã xử lý:** `Settings` đặt `hide_input_in_errors=True`. Test (mật khẩu giả, subprocess, cả stdout, stderr và log DEBUG): `tests/test_config_secrets.py`.

## KI-14 Chưa chạy container thật và chưa quét CVE của image

- **Đã làm (Mốc G):** `docker build` thành công, kiểm tra nội dung `/app` của image (không có `.env`, service account, `scripts/`, `tests/`, `docs/`), cấu hình `USER`, `HEALTHCHECK`, `EXPOSE` và phiên bản gói cài khớp bộ đã test.
- **Chưa làm:** chạy container với database và Firebase thật, kiểm tra `HEALTHCHECK` ở trạng thái chạy, và quét lỗ hổng của lớp hệ điều hành (`python:3.13-slim`) bằng công cụ quét image.
- **Alembic:** image chứa `alembic/` và `alembic.ini` nhưng thư mục `alembic/versions/` chưa tồn tại (chờ baseline của trưởng nhóm), nên `alembic upgrade` trong image chưa dùng được.

