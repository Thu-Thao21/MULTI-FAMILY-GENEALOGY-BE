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

## KI-03 uq_active_user_role_scope không chặn gán trùng role cấp hệ thống (clan_id NULL) — Đã áp dụng lên dev_minhquan, production chưa

> **Trạng thái:** revision `0002_integrity_constraints` **đã áp dụng lên dev_minhquan ngày 06/10/2026**, **production chưa**. Mục "Hiện trạng" bên dưới mô tả database **chưa** có migration (như production hiện nay). Xem [`migrations.md`](migrations.md).

- **Bảng/index:** `user_roles`, `uq_active_user_role_scope` = `UNIQUE (user_id, role_id, clan_id) WHERE revoked_at IS NULL`.
- **Hiện trạng:** PostgreSQL coi hai giá trị NULL là khác nhau, nên với `clan_id IS NULL` (role cấp hệ thống, tức mọi dòng `SYSTEM_ADMIN`) index không bao giờ báo trùng. Một user có thể có nhiều dòng `SYSTEM_ADMIN` còn hiệu lực. Trong clan (`clan_id` không NULL) index chặn đúng.
- **Bằng chứng (trước migration):** `tests/integration/test_user_roles_unique_index.py` từng có `test_db_accepts_duplicate_system_admin_grant_current_behaviour` (ghi lại hành vi) và `test_db_should_reject_duplicate_system_admin_grant` (`xfail(strict=True)`, hành vi mong muốn). Cả hai đã được thay bằng `test_db_rejects_duplicate_system_admin_grant`.
- **Ảnh hưởng hiện tại:** Không làm sai quyền: `has_active_role` chỉ hỏi "có ít nhất một dòng", và `count_active_system_admins` dùng `COUNT(DISTINCT user_id)` nên guard "SA cuối cùng" không bị đếm dôi (có test). Rủi ro còn lại là dữ liệu rác và việc thu hồi chỉ một dòng không làm mất quyền SA.
- **Việc cần làm trong code:** Khi cấp SA, kiểm tra `has_active_role(user, 'SYSTEM_ADMIN', clan_id=None)` trước khi INSERT, trong cùng transaction; khi thu hồi, đặt `revoked_at` cho mọi dòng còn hiệu lực của user.
- **Quyết định của trưởng nhóm:** thay index cùng tên bằng `UNIQUE NULLS NOT DISTINCT (user_id, role_id, clan_id) WHERE revoked_at IS NULL` (PostgreSQL 15+). Migration kiểm tra dòng trùng trước và dừng với thông báo rõ nếu có (không đổi gì).
- **Đã làm (đã áp dụng lên dev_minhquan, 155 test tích hợp pass):** migration `0002`, ORM khai báo `postgresql_nulls_not_distinct=True`. Index trên dev: `UNIQUE (user_id, role_id, clan_id) NULLS NOT DISTINCT WHERE revoked_at IS NULL`. Test `test_user_roles_unique_index.py`: bỏ test `current_behaviour`, bỏ `xfail` của test SA trùng (nay `test_db_rejects_duplicate_system_admin_grant`, pass thật), thêm test cấp lại sau khi thu hồi và SA ở hai user. **Các test này cần migration đã áp dụng lên DB chúng chạy.** Code kiểm `has_active_role` trước khi INSERT vẫn nên giữ.

## KI-04 user_sessions.token_jti_hash không có unique index — Đã áp dụng lên dev_minhquan, production chưa

> **Trạng thái:** revision `0002_integrity_constraints` **đã áp dụng lên dev_minhquan ngày 06/10/2026**, **production chưa**. Mục "Hiện trạng" bên dưới mô tả database chưa có migration. Xem [`migrations.md`](migrations.md).

- **Bảng/index:** `user_sessions` chỉ có `user_sessions_pkey`, `idx_user_sessions_user`, `idx_user_sessions_active`. Kế hoạch mục 4 yêu cầu kiểm tra unique token hash; DB hiện chưa có.
- **Hiện trạng:** DB nhận hai phiên cùng `token_jti_hash`; khi đó `get_session_by_token_hash` ném `MultipleResultsFound` (lỗi 500 thay vì `SESSION_INVALID`). Token 256-bit ngẫu nhiên nên va chạm thực tế không đáng kể, nhưng DB không bảo đảm.
- **Bằng chứng (trước migration):** test cũ `test_db_does_not_enforce_unique_token_hash_known_issue` trong `tests/integration/test_sessions_db.py`; nay đã đổi thành `test_db_rejects_a_duplicate_token_hash` (cần migration đã áp dụng).
- **Quyết định của trưởng nhóm:** `CREATE UNIQUE INDEX uq_user_sessions_token_jti_hash ON user_sessions (token_jti_hash)` (cột vẫn nullable; nhiều NULL vẫn được). Test mới: `tests/integration/test_db_constraints.py`.

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

## KI-08 DB không chặn hai assignment FA còn hiệu lực cho cùng (clan, user) — Đã áp dụng lên dev_minhquan, production chưa

> **Trạng thái:** revision `0002_integrity_constraints` **đã áp dụng lên dev_minhquan ngày 06/10/2026**, **production chưa**. Tầng DB **vẫn còn mở ở production**; mục "Bảng" và "Hiện trạng" bên dưới mô tả database chưa có migration. Xem [`migrations.md`](migrations.md).

- **Bảng:** `family_admin_assignments` chỉ có khóa chính; không có unique trên `(clan_id, user_id)` (kể cả `WHERE revoked_at IS NULL`; `branch_id` NULL cũng không bị unique).
- **Code bảo vệ (Mốc F2), không phải DB:** mọi đề bạt xếp hàng trên dòng `clan_memberships (clan, user)` bằng `FOR NO KEY UPDATE`; request thứ hai thấy assignment của request đầu và trả `409`. `PUT` và `DELETE` khóa các dòng assignment của user (`FOR NO KEY UPDATE`, `ORDER BY assignment_id`). Dữ liệu trùng chỉ có thể xuất hiện nếu ghi thẳng vào DB (SQL, import, hoặc code tương lai bỏ qua các hàm này). `uq_active_user_role_scope` là lớp bảo vệ thứ hai ở DB, nhưng chỉ cho dòng `user_roles`, không cho assignment.
- **Hiện trạng với dữ liệu trùng đã có:** `PUT .../permissions` trả `409 STATE_CONFLICT` khi user có nhiều hơn một assignment toàn clan còn hiệu lực; `authorize()` hợp (union) quyền của mọi assignment còn hiệu lực; `DELETE` thu hồi tất cả. Test (tên hiện tại): `test_branch_limited_assignment_is_invisible_to_put_and_a_second_clan_wide_one_is_rejected`, `test_revoke_takes_every_active_assignment_and_leaves_other_users_alone`; dữ liệu trùng chỉ còn được dựng bằng fake (`test_branch_limited_assignment_alone_is_404_and_two_clan_wide_is_409`, `test_revoke_takes_every_active_assignment_including_branch_limited_and_duplicates`).
- **Test đồng thời** (`tests/integration/test_family_admin_concurrency.py`): hai đề bạt cùng lúc chỉ một thắng; test đối chứng (bỏ khóa membership) cho thấy hai assignment trùng xuất hiện trên DB **chưa migrate**, tức là chỉ có khóa trong code đứng giữa. Sau migration test đó đổi thành "chỉ một request thắng".
- **Quyết định của trưởng nhóm:** `CREATE UNIQUE INDEX uq_family_admin_active_assignment ON family_admin_assignments (clan_id, user_id, branch_id) NULLS NOT DISTINCT WHERE revoked_at IS NULL` (PostgreSQL 15+). Khóa trong code vẫn giữ: khóa biến cuộc đua thành `409` sạch, index là lớp cuối (request lọt qua khóa sẽ nhận `IntegrityError`, đã được ánh xạ thành `409`).
- **Đã làm (đã áp dụng lên dev_minhquan, 155 test tích hợp pass):** migration `0002`, ORM khai báo index, test mới `tests/integration/test_db_constraints.py` và `test_lost_race_on_the_assignment_index_is_409_and_rolled_back` (đơn vị). Ba test tích hợp từng dựa vào "DB cho phép assignment trùng" đã đổi: `test_branch_limited_assignment_is_invisible_to_put_and_a_second_clan_wide_one_is_rejected`, test thu hồi mọi assignment (dùng chi/ngành thứ hai thay cho dòng trùng), và test đối chứng của `test_family_admin_concurrency.py` (nay: bỏ khóa membership thì index vẫn để đúng một request thắng). **Các test này cần migration đã áp dụng.**
- **Hệ quả sau khi áp dụng:** nhánh `409` của `PUT .../permissions` khi có nhiều assignment toàn clan không còn đạt được trên DB đã migrate; code giữ lại cho DB chưa migrate và test bằng fake.

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

> Bộ giới hạn tần suất của Mốc E (KI-17) có cờ `TRUST_PROXY_HEADERS` riêng. `ClientInfo` (audit, `login_history`) **không** dùng cờ đó và vẫn chỉ lấy IP kết nối trực tiếp: khi bật cờ, IP trong audit và IP bị giới hạn có thể khác nhau.

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
- **Alembic:** image chứa `alembic/` (nay có `versions/` với hai revision) và `alembic.ini`, nhưng không đặt `ALLOW_MIGRATE` và `MIGRATE_EXPECT_FINGERPRINT`, nên container không tự chạy migration. Chưa thử `alembic` bên trong container thật.

## KI-15 Email không phân biệt hoa/thường: DB chặn, nhưng `get_user_by_email` so khớp chính xác

- **Quyết định (gói migration):** `uq_users_email_lower` (UNIQUE `lower(email)`) nằm trong migration `0002` (**đã áp dụng lên dev_minhquan ngày 06/10/2026, production chưa**, xem `migrations.md`). `users_email_key` (so khớp chính xác) vẫn giữ. Email vẫn lưu đúng chữ hoa/thường người dùng nhập (quyết định 24); `get_user_by_email` cố ý **không** đổi, vẫn so khớp chính xác.
- **Hệ quả:** `get_user_by_email("A@x.com")` không tìm thấy dòng `a@x.com`, nhưng INSERT `A@x.com` khi đã có `a@x.com` sẽ bị DB từ chối bằng `IntegrityError` (constraint `uq_users_email_lower`).
- **Việc bắt buộc cho Mốc E:** mọi code tạo `users` (đăng ký, cấp Owner, tạo tài khoản) phải bắt `IntegrityError` của `uq_users_email_lower` (và `users_email_key`) rồi rollback và trả `409`, không để thành `500`. Cần test thật trên DB.
- **Ngoài phạm vi:** chưa thêm unique cho `account_invitations.email`, `business_registrations.representative_email`, `email_delivery_logs.recipient_email`, `person_contacts.email`: một địa chỉ được phép lặp ở các bảng đó.

## KI-16 `database/initial_schema.sql` đã lỗi thời, không dùng để dựng database mới

- **Hiện trạng:** file là bản export cũ. So với schema thật của nhánh dev (`docs/schema_user_access.txt`, `docs/schema_family.txt`) nó **thiếu 6 bảng**: `credential_metadata`, `user_sessions`, `login_history`, `clan_memberships`, `clan_ownership_history`, `family_admin_permissions`. Nó cũng thiếu cột `users.username` và các index như `uq_active_user_role_scope`, `idx_user_sessions_user`, `idx_user_sessions_active`.
- **Hệ quả:** **không dùng file này để dựng database mới.** Một database dựng từ nó không có schema mà ORM và migration `0002` cần; `0002` sẽ dừng với thông báo thiếu bảng (kiểm tra tiền điều kiện) và không đổi gì. Baseline `0001_baseline` rỗng nghĩa là "schema của dev đã có sẵn", không phải "file này đã chạy".
- **Quyết định của trưởng nhóm:** chưa làm bây giờ. Việc dựng database mới (xuất `pg_dump --schema-only` từ nhánh dev làm file baseline, hoặc đưa DDL đầy đủ vào `0001`) làm **sau Mốc E**. Cho đến lúc đó, migration chỉ áp dụng được lên database đã có schema của dev. File đã có dòng cảnh báo ở đầu.
- **Liên quan:** `docs/migrations.md` mục 3.


## KI-17 Bộ giới hạn tần suất (Mốc E) đếm theo từng process, không dùng chung — Đã cài (bước E3)

> **Trạng thái:** bộ giới hạn đã cài ở bước E3 (`app/core/rate_limit.py`, `app/core/client_ip.py`), có test với đồng hồ giả. Các hạn chế dưới đây là hạn chế **của bản đã cài**, không phải kế hoạch.

- **Quyết định (kế hoạch Mốc E, bước E3):** các endpoint công khai ghi vào DB hoặc dò mã (`POST /business-registrations`, `POST /business-registrations/track`) có bộ giới hạn tần suất đặt trong bộ nhớ của process, trả `429 RATE_LIMITED` kèm `Retry-After`. **Chưa cài**: ghi ở đây trước để không ai nhầm nó là bảo vệ chống tấn công phân tán.
- **Hệ quả:**
  - Bộ đếm sống trong **từng process**. Chạy N worker hoặc N container thì mức cho phép thực tế là N lần mức cấu hình, và các instance không biết nhau.
  - Khởi động lại process thì bộ đếm về 0.
  - Không chống được kẻ tấn công đổi IP. Nó chỉ làm chậm spam đơn giản và dò mã từ một nguồn.
- **Bật/tắt và cấu hình:** `RATE_LIMIT_ENABLED` (mặc định bật); `RATE_LIMIT_REGISTRATION_MAX` (5) và `RATE_LIMIT_REGISTRATION_WINDOW_SECONDS` (3600); `RATE_LIMIT_TRACK_MAX` (20) và `RATE_LIMIT_TRACK_WINDOW_SECONDS` (600); `RATE_LIMIT_MAX_KEYS` (10000). Giá trị không dương làm app dừng khi khởi động.
- **Mạng dùng chung IP (mạng trường, quán cà phê, NAT của nhà mạng) có thể chặn cả nhóm khi demo.** Ngưỡng 5 đăng ký mỗi giờ tính theo IP, nên một lớp học hay một nhóm demo cùng nối chung một mạng sẽ dùng chung một bộ đếm: người thứ sáu trong giờ đó nhận `429`, dù mỗi người chỉ đăng ký một lần. **Cho ngày demo, đặt `RATE_LIMIT_REGISTRATION_MAX` cao hơn bằng biến môi trường** (ví dụ 50) rồi khởi động lại process; đặt lại mặc định sau buổi demo. Không cần sửa code. `RATE_LIMIT_ENABLED=false` tắt hẳn nhưng chỉ nên dùng trên máy dev.
- **Body không phải JSON hợp lệ** bị từ chối trước khi bộ giới hạn chạy, nên không bị đếm (chỉ tốn một lần phân tích, không chạm DB).
- **IP của người gọi:** **không tin `X-Forwarded-For`** trừ khi bật cờ `TRUST_PROXY_HEADERS` (khi đó dùng `TRUSTED_PROXY_COUNT`, mặc định 1, và đọc header từ bên phải). Nếu header đến mà cờ đang tắt, process ghi **một** WARNING (không kèm IP) để người vận hành biết đang đứng sau proxy mà chưa bật cờ. Mặc định dùng IP của kết nối trực tiếp, nên **sau reverse proxy mọi người dùng chung một IP và bị giới hạn chung** (liên quan KI-11). Chỉ bật `TRUST_PROXY_HEADERS` khi proxy là đường vào duy nhất và đã đặt danh sách proxy tin cậy; bật sai cho phép kẻ gọi giả IP để né giới hạn.
- **Việc cần lead quyết định khi triển khai nhiều instance:** bộ đếm dùng chung (Redis hoặc bảng DB) hoặc đặt giới hạn ở reverse proxy. Tới lúc đó, coi bộ đếm này là lớp giảm nhẹ chứ không phải biện pháp đủ.
- **Liên quan:** KI-06 (`POST /auth/session` cũng chưa có giới hạn).

## KI-18 `provisioning_jobs.clan_id` là `ON DELETE CASCADE`

- `provisioning_jobs.clan_id` khai báo `ON DELETE CASCADE` (migration 0003, đã áp dụng lên dev_minhquan ngày 06/10/2026, production chưa): nếu sau này có chức năng xóa clan thì job `needs_cleanup` cũng bị xóa theo, mất dấu vết duy nhất của user Firebase còn phải dọn. **Hiện chưa có chức năng xóa clan**; chức năng đó khi làm phải chặn xóa clan còn job `needs_cleanup` (hoặc đổi khóa ngoại sang `RESTRICT` bằng migration).

## KI-19 Gói dịch vụ production chưa có: nhóm quyết định rồi nhập qua kênh riêng

- **Hiện trạng:** `GET /service-plans` và `POST /business-registrations` (Mốc E, bước E3) chạy trên bảng `subscription_plans`. Trên nhánh dev chỉ có ba gói do `scripts/seed_dev.py` tạo (`DEV-TRIAL`, `DEV-STANDARD`, `DEV-LEGACY` không còn bán, kèm `plan_feature_limits`). Đó là **dữ liệu dev**, tên và giá do dev đặt, không phải gói thật.
- **Quyết định:** gói production (mã, tên, giá, thời hạn, giới hạn thành viên, Family Admin, dung lượng, tính năng) **do nhóm quyết định**, rồi **nhập qua một kênh riêng có kiểm soát**. **Không đưa dữ liệu gói vào migration** và không dùng `seed_dev.py` cho production: seed có cờ `ALLOW_DEV_SEED`, chỉ tạo mã tiền tố `DEV-`, và `--cleanup` chỉ xóa gói `DEV-` không được hồ sơ hay gói đăng ký của clan tham chiếu.
- **Hệ quả:** trên production, cho đến khi nhập gói, `GET /service-plans` trả danh sách rỗng và không ai đăng ký được (mọi `requested_plan_id` đều `422`). Cần có gói trước khi mở đăng ký công khai.
- **Ngoài phạm vi Sprint 1:** thanh toán và hoàn thiện gói dịch vụ (đổi gói, hết hạn, gia hạn, thanh toán thật) thuộc **Sprint 6, task 3.6.8.6** trong project plan. Sprint 1 chỉ chọn gói lúc đăng ký và để SA kích hoạt thủ công (D03).
- **Liên quan:** KI-17 (giới hạn tần suất của endpoint đăng ký), `docs/api_contract.md` quyết định 36.

## KI-20 Audit của `PATCH /admin/users/{id}/status` còn chứa nội dung lý do, khác với audit duyệt hồ sơ

- **Hiện trạng:** `PATCH /admin/users/{user_id}/status` (Mốc F, quyết định 21) ghi `reason` do SA nhập thẳng vào cột `audit_logs.reason`. Audit của `POST /admin/business-registrations/{id}/review` (Mốc E, bước E4, quyết định 47) thì **không**: chỉ ghi độ dài lý do (`new_data.reason_length`), còn `audit_logs.reason` luôn `NULL`.
- **Vì sao đáng ghi:** hai audit không cùng một quy tắc. Lý do khóa tài khoản là văn bản tự do của SA và có thể chứa dữ liệu cá nhân (tên, email, số điện thoại của người bị khóa), trong khi `audit_logs` là bảng không có quyền xóa theo từng người. Quy tắc 3.5 của `docs/security_review.md` (audit không chứa email) hiện chỉ được kiểm chứng cho các trường cố định, không cho văn bản tự do.
- **Quyết định cho Sprint 1:** giữ nguyên hành vi của `PATCH .../status` (không đổi endpoint cũ trong E4), nên lý do khóa tài khoản vẫn nằm trong `audit_logs.reason`. **Nhóm quyết định sau** giữa: (a) giữ nguyên và coi lý do khóa tài khoản là nội dung quản trị hợp lệ của audit, (b) chuyển sang kiểu "chỉ ghi độ dài" như review và lưu lý do ở bảng riêng có kiểm soát truy cập, (c) bỏ cột lý do khỏi audit.
- **Liên quan:** `docs/api_contract.md` quyết định 21 và 47; `docs/security_review.md` mục 3.5 và mục 10.

## KI-21 Bảng `idempotency_keys` phình dần: chưa có tác vụ dọn

- **Hiện trạng:** mỗi lần `POST /admin/business-registrations/{id}/business` thành công (và sau này `POST /admin/clans/{id}/owner`) để lại một dòng `idempotency_keys` hết hạn sau 7 ngày. **Không có tác vụ nào xóa dòng hết hạn.** Hết hạn chỉ được xét khi đọc: một dòng quá hạn bị ghi đè tại chỗ khi cùng key được dùng lại, còn dòng không ai dùng lại thì nằm mãi trong bảng.
- **Vì sao chấp nhận trong Sprint 1:** chỉ SA gọi, vài chục request mỗi ngày; không có hiệu ứng phụ nào ngoài kích thước bảng. Chỉ mục duy nhất `uq_idempotency_actor_endpoint_key` giữ tra cứu nhanh.
- **Việc cần làm sau:** một tác vụ định kỳ `DELETE FROM idempotency_keys WHERE expires_at < now() - interval '1 day'` (kèm giới hạn số dòng mỗi lần), hoặc dọn theo lô khi khởi động. Chưa có chỗ chạy tác vụ nền (cùng lý do với KI-17), nên để nhóm quyết định cùng lúc.
- **Liên quan:** `docs/api_contract.md` quyết định về idempotency; migration 0003.

## KI-22 `clan_subscriptions` không chụp giá và điều khoản của gói

- **Hiện trạng:** `clan_subscriptions` chỉ lưu `plan_id`, ngày bắt đầu, ngày kết thúc, trạng thái và `auto_renew`. Không có giá, chu kỳ hay giới hạn tại thời điểm đăng ký, và không có liên kết tới hồ sơ đăng ký.
- **Hệ quả:** nếu sau này gói đổi giá, đổi giới hạn hoặc ngừng bán thì không còn dấu vết điều khoản mà clan đã được cấp. Thanh toán thật và đổi gói thuộc Sprint 6 (task 3.6.8.6), nên đây là việc của Sprint đó: cần cột chụp (giá, chu kỳ, giới hạn) hoặc bảng phiên bản gói, qua migration riêng.
- **Hiện tại:** ngày của gói đăng ký lúc tạo Business chỉ là tạm thời (bắt đầu lúc tạo, kết thúc sau `billing_period_months` tháng); E7 đặt lại lúc kích hoạt clan.

## KI-23 Neon cắt kết nối trong lần chạy integration dài: nguyên nhân chưa xác định

- **Hiện tượng:** trong lần chạy integration 43 phút của E4 có 4 lỗi `server closed the connection unexpectedly` ở các test cũ của E3. Chạy riêng lại thì cả 4 pass.
- **Cái đã biết:** `DATABASE_URL` trỏ vào pooler của Neon (PgBouncer chế độ transaction). Ba lỗi nằm ở các test đầu tiên dùng fixture `session` sau một file đồng thời dài (pool của fixture có đúng 2 kết nối nhàn rỗi), khớp với việc kết nối nhàn rỗi bị cắt. Lỗi thứ tư là hai racer bị rớt giữa giao dịch trên kết nối mới (`NullPool`); lúc đó helper chỉ ghi tên loại lỗi nên không biết sqlstate.
- **Nguyên nhân phía Neon: CHƯA XÁC ĐỊNH.** Các giả thuyết: ngưỡng nhàn rỗi của pooler, **tự tạm dừng (autosuspend) của compute** (mặc định khoảng 5 phút không hoạt động trên nhiều gói), bảo trì. Việc cần làm của người có quyền Neon Console: xem cấu hình autosuspend của branch dev_minhquan và log kết nối quanh thời điểm lỗi; nếu autosuspend tắt được trên branch dev thì ghi lại.
- **Đã làm (E4b):** engine dùng `pool_pre_ping=True`, `pool_recycle=1800`, `connect_timeout=15` (`ENGINE_OPTIONS` trong `app/db/postgres.py`, dùng chung với test qua `make_engine`). Test tích hợp báo lỗi hạ tầng dưới dạng `ERROR:<loại>:<sqlstate hoặc no-sqlstate>:<60 ký tự đầu thông điệp đã lọc>`: không có sqlstate nghĩa là kết nối bị đứt; `40P01`, `23xxx`, `55P03` là lỗi thật của mã. **Không thử lại ở đâu cả.**
- **Giới hạn:** `pool_pre_ping` chỉ thay kết nối chết lúc lấy ra khỏi pool. Kết nối đứt giữa giao dịch vẫn là lỗi (ở ứng dụng là `503 DATABASE_UNAVAILABLE`) và pre-ping tốn thêm một vòng gọi mỗi lần lấy kết nối.
- **Bài học liên quan (E5):** pooler chế độ transaction **không reset trạng thái cấp session**. Một đột biến đặt `lock_timeout = 10s` ở cấp session đã làm nhiễm một kết nối server và gây hai lỗi ở lần chạy cả bộ liền sau (một test thấy `SHOW lock_timeout` là `10s` sau commit, một test đồng thời bị `55P03`). Mã thật chỉ dùng `set_config(..., true)` (trong giao dịch) nên không dính; quy tắc: **không bao giờ đặt `SET` hay `set_config(..., false)` trên DB đi qua pooler**, và đột biến loại này chỉ chạy ở mức đơn vị.
- **Liên quan:** `docs/testing.md` mục 5 (E4b và E5).
