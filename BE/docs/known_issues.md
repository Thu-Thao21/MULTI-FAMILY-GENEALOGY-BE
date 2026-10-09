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
- **Ngoài phạm vi Sprint 1:** thanh toán và hoàn thiện gói dịch vụ (đổi gói, hết hạn, gia hạn, thanh toán thật) thuộc **Sprint 6, task 3.6.8.6** trong project plan. Sprint 1 chỉ chọn gói lúc đăng ký và để SA kích hoạt thủ công (D03, đã cài ở E7: kích hoạt là xác nhận thủ công, không kiểm thanh toán).
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
- **Hiện tại:** ngày của gói đăng ký lúc tạo Business chỉ là tạm thời (bắt đầu lúc tạo, kết thúc sau `billing_period_months` tháng); `POST /admin/clans/{id}/activate` (E7) đặt lại: bắt đầu lúc kích hoạt, kết thúc sau `billing_period_months` tháng lịch.

## KI-23 Neon cắt kết nối trong lần chạy integration dài: nguyên nhân chưa xác định

- **Hiện tượng:** trong lần chạy integration 43 phút của E4 có 4 lỗi `server closed the connection unexpectedly` ở các test cũ của E3. Chạy riêng lại thì cả 4 pass.
- **Cái đã biết:** `DATABASE_URL` trỏ vào pooler của Neon (PgBouncer chế độ transaction). Ba lỗi nằm ở các test đầu tiên dùng fixture `session` sau một file đồng thời dài (pool của fixture có đúng 2 kết nối nhàn rỗi), khớp với việc kết nối nhàn rỗi bị cắt. Lỗi thứ tư là hai racer bị rớt giữa giao dịch trên kết nối mới (`NullPool`); lúc đó helper chỉ ghi tên loại lỗi nên không biết sqlstate.
- **Nguyên nhân phía Neon: CHƯA XÁC ĐỊNH.** Các giả thuyết: ngưỡng nhàn rỗi của pooler, **tự tạm dừng (autosuspend) của compute** (mặc định khoảng 5 phút không hoạt động trên nhiều gói), bảo trì. Việc cần làm của người có quyền Neon Console: xem cấu hình autosuspend của branch dev_minhquan và log kết nối quanh thời điểm lỗi; nếu autosuspend tắt được trên branch dev thì ghi lại.
- **Đã làm (E4b):** engine dùng `pool_pre_ping=True`, `pool_recycle=1800`, `connect_timeout=15` (`ENGINE_OPTIONS` trong `app/db/postgres.py`, dùng chung với test qua `make_engine`). Test tích hợp báo lỗi hạ tầng dưới dạng `ERROR:<loại>:<sqlstate hoặc no-sqlstate>:<60 ký tự đầu thông điệp đã lọc>`: không có sqlstate nghĩa là kết nối bị đứt; `40P01`, `23xxx`, `55P03` là lỗi thật của mã. **Không thử lại ở đâu cả.**
- **Giới hạn:** `pool_pre_ping` chỉ thay kết nối chết lúc lấy ra khỏi pool. Kết nối đứt giữa giao dịch vẫn là lỗi (ở ứng dụng là `503 DATABASE_UNAVAILABLE`) và pre-ping tốn thêm một vòng gọi mỗi lần lấy kết nối.
- **Bài học liên quan (E5):** pooler chế độ transaction **không reset trạng thái cấp session**. Một đột biến đặt `lock_timeout = 10s` ở cấp session đã làm nhiễm một kết nối server và gây hai lỗi ở lần chạy cả bộ liền sau (một test thấy `SHOW lock_timeout` là `10s` sau commit, một test đồng thời bị `55P03`). Mã thật chỉ dùng `set_config(..., true)` (trong giao dịch) nên không dính; quy tắc: **không bao giờ đặt `SET` hay `set_config(..., false)` trên DB đi qua pooler**, và đột biến loại này chỉ chạy ở mức đơn vị.
- **Liên quan:** `docs/testing.md` mục 5 (E4b và E5).

## KI-24 Chưa có tác vụ đối soát user Firebase mồ côi (`own-<job_id>`)

- **Hiện trạng:** Firebase và PostgreSQL không chung giao dịch. Một user Firebase `own-<job_id>` có thể tồn tại mà DB không có dòng `users` tương ứng: tiến trình chết hoặc timeout **sau** `create_user` mà **trước** khi ghi `firebase_user_created`, hoặc lỗi DB sau khi Firebase đã tạo mà không ai thử lại. Job khi đó nằm ở `RUNNING` quá lease, `PENDING` kẹt hoặc `FAILED_RETRYABLE`, và **chặn clan** (chỉ mục `uq_provisioning_job_live_per_clan`).
- **Đã làm (E6a):** mỗi lần chạy bắt đầu bằng `get_user(own-<job_id>)` nên lần thử lại (E6b) tìm thấy user và dùng lại với mật khẩu mới; lỗi cuối cùng được bù trừ bằng `delete_user` đúng uid đó; xóa lỗi thì `needs_cleanup` giữ cờ và chặn clan, email.
- **Cố ý để lại (`UID_MISMATCH`):** nếu dưới `own-<job_id>` có một user Firebase mang email KHÁC email của job, app không xóa nó (không chắc đó là của mình). Job thành `FAILED` với `needs_cleanup = false` (không chặn clan, một job mới dùng uid mới). User đó nằm lại ở Firebase và **cần người kiểm tra bằng tay** (Firebase Console, tìm theo uid `own-<job_id>` lấy từ thông điệp `409` hoặc từ audit).
- **Chưa có:** không có tác vụ nền quét job quá hạn rồi thử lại hoặc dọn, không có công cụ liệt kê user Firebase `own-*` không có dòng DB. Nếu không ai thử lại, user mồ côi nằm lại ở Firebase (không đăng nhập được vào app vì không có `users`) và job vẫn hiện trong danh sách job ở trạng thái chưa xong.
- **Đã làm (E6b):** `GET /admin/provisioning-jobs` (lọc theo clan và trạng thái), `POST /admin/provisioning-jobs/{id}/retry` (chạy lại, hoặc chỉ dọn Firebase khi job còn nợ) và `POST /admin/provisioning-jobs/{id}/abandon` (bỏ job, vẫn thử `delete_user(own-<job_id>)`). SA tự xử lý job kẹt.
- **Việc cần làm sau:** một tác vụ đối soát định kỳ cần chỗ chạy nền (cùng lý do với KI-17, KI-21). Xem thêm KI-28 (lượt chạy vượt quá lease).

## KI-25 Đặt lại mật khẩu tạm của Owner: Firebase và DB không chung giao dịch, có khoảng hở

- **Hiện trạng (E6b, `POST /admin/clans/{id}/owner/temporary-password`):** không thể giữ giao dịch hay khóa DB xuyên qua lời gọi Firebase (cấm giữ giao dịch mở lúc chờ ngoài). Thứ tự cố định là kiểm tra (giao dịch chỉ đọc, kết thúc), `set_owner_password` trên Firebase, rồi một giao dịch DB khóa clan và `credential_metadata`, kiểm tra lại và ghi. Khoảng giữa lời gọi Firebase và giao dịch DB là khoảng hở, độ dài một lời gọi Firebase (tối đa 15 giây):
  1. **Owner tự đổi mật khẩu trong khoảng hở.** Giao dịch DB thấy tài khoản không còn `PENDING`, **không ghi đè DB** và trả `409`. Nhưng lời gọi Firebase đã đặt mật khẩu tạm **đè lên mật khẩu mới của Owner** trên Firebase (và thu hồi refresh token). Owner không đăng nhập được bằng mật khẩu họ vừa đặt; SA cũng không đặt lại được vì tài khoản đã `ACTIVE` (`409`). Cách xử lý hiện nay: Owner dùng chức năng "quên mật khẩu" của Firebase, hoặc xử lý ngoài luồng; endpoint quên mật khẩu của BE (`/auth/password-reset/*`) chưa có.
  2. **Hai SA đặt lại cùng lúc.** Hàng `credential_metadata` được so sánh với giá trị đã thấy lúc kiểm tra, nên chỉ một bên ghi DB; bên kia nhận `409` và không ghi gì. Nhưng Firebase giữ mật khẩu của lời gọi Firebase kết thúc **sau cùng**, có thể không phải của bên thắng ở DB: bên thắng có thể cầm mật khẩu đã vô hiệu. SA thấy mật khẩu không dùng được thì đặt lại một lần nữa.
  3. **DB lỗi sau khi Firebase đã đổi mật khẩu** (hoặc `update_user` xong mà thu hồi refresh token lỗi): trả `503`, DB không đổi (hạn và phiên giữ nguyên) nhưng mật khẩu Firebase đã khác. Gọi lại là sửa được.
- **Giảm nhẹ:** thao tác hiếm; mọi trường hợp đều có đường sửa là đặt lại thêm một lần, trừ trường hợp 1 (Owner đã `ACTIVE`). Có test với provider giả có điểm dừng cho cả ba (`test_owner_recovery_api.py`, `integration/test_owner_recovery_db.py`, `integration/test_owner_recovery_concurrency.py`).
- **Không sửa triệt để được** nếu không có cột khóa hay phiên bản mật khẩu ở DB (cần migration riêng) hoặc kiểm tra "mật khẩu Firebase hiện tại là của ai" (Firebase không cho đọc).

## KI-26 Chưa có `EmailSender` thật: SA chuyển mật khẩu tạm thủ công

- **Hiện trạng:** chỉ có bản `NoopEmailSender` (không gửi, không lưu, không log). `email_delivery_status` luôn `null`. Mật khẩu tạm chỉ hiện **một lần** trong response `201` của `POST /admin/clans/{id}/owner`; SA phải chuyển cho Owner qua kênh riêng. Mất response (đóng tab, lỗi mạng) thì mật khẩu mất theo và SA phải đặt lại bằng `POST /admin/clans/{id}/owner/temporary-password` (E6b); `retry` cũng chỉ hiện mật khẩu một lần. Chưa chọn nhà cung cấp email (D04), chưa có nơi lưu bản gửi (bảng `email_delivery_logs` không đủ cho việc gửi lại an toàn: nó không có cơ chế lưu payload mã hóa).
- **Việc cần làm sau:** chọn nhà cung cấp, cài `EmailSender` thật sau giao diện đã có; không bao giờ lưu mật khẩu rõ để gửi lại.

## KI-27 `provisioning_jobs` giữ email, tên và số điện thoại của Owner; chưa có chính sách xóa

- **Hiện trạng:** để thử lại một job, bảng `provisioning_jobs` lưu `email`, `display_name` và `phone` của người sẽ làm Owner (dữ liệu cá nhân), và các dòng này tồn tại mãi (kể cả job `SUCCEEDED`, `FAILED`). Không có tác vụ xóa hay ẩn danh hóa, không có thời hạn giữ. Các dữ liệu này đã nằm ở `users` sau khi thành công, nên bản trong job là thừa.
- **Giảm nhẹ:** `GET /admin/provisioning-jobs/{id}` không bao giờ trả email, điện thoại hay tên; audit không chứa chúng.
- **Việc cần làm sau:** nhóm quyết định chính sách (ví dụ xóa `email`, `phone`, `display_name` khi job `SUCCEEDED` hoặc `FAILED` đã dọn xong và sau N ngày). Cần đổi ràng buộc `NOT NULL` của `email` và `display_name` (migration riêng) nếu muốn xóa thay vì ẩn danh hóa.
- **Liên quan:** KI-21 (`idempotency_keys` cũng không có tác vụ dọn).

## KI-28 Lượt chạy vượt quá lease vẫn có thể gọi Firebase sau khi bị tiếp quản hoặc bị bỏ

- **Hiện trạng:** fencing (`attempt_count` và `status = RUNNING`) chặn mọi **ghi DB** của một lượt chạy đã bị thay thế, nhưng không chặn được một lời gọi Firebase **đang bay**. Mỗi lời gọi Firebase tối đa 15 giây và lease là 90 giây (kiểm tra `3 x timeout < lease` lúc khởi động), nên một lượt chạy chỉ vượt lease nếu một bước DB treo bất thường. Khi đó: (a) sau `abandon` đã xóa `own-<job_id>`, lượt cũ có thể tạo lại user đó, để lại một user mồ côi không có cờ nào (cùng loại với KI-24, cần kiểm tra bằng tay); (b) sau khi một retry tiếp quản, lượt cũ có thể `set_owner_password` đè lên mật khẩu mà retry vừa trả cho SA, và SA cầm mật khẩu vô hiệu (đặt lại bằng `POST /admin/clans/{id}/owner/temporary-password` là sửa được).
- **Không chặn được** nếu không kiểm tra fencing ngay trước từng lời gọi Firebase, mà việc đó cần giao dịch DB mở (cấm). Chấp nhận vì cần cả sự cố DB lẫn thời điểm trùng khít.
- **Giảm nhẹ:** `abandon` và `retry` từ chối `RUNNING` còn lease (`409` kèm `Retry-After`); lượt cũ không bao giờ ghi DB sau khi bị thay thế (test `integration/test_owner_recovery_concurrency.py::test_a_lease_that_ran_out_is_taken_over_the_old_run_writes_nothing_and_the_original_key_is_completed`).

## KI-29 Không có đường đưa clan ra khỏi `ACTIVE`, và không kích hoạt lại

- **Hiện trạng:** `POST /admin/clans/{id}/activate` chỉ đi một chiều `PENDING` -> `ACTIVE`. Các trạng thái `SUSPENDED`, `EXPIRED`, `LOCKED`, `INACTIVE` có trong CHECK của bảng `clans` nhưng **không có endpoint nào đưa clan tới đó**, và không có cách kích hoạt lại một clan đã rời `PENDING`. Subscription cũng không có endpoint đổi trạng thái (`SUSPENDED`, `EXPIRED`, `CANCELLED`).
- **Hệ quả:** nếu cần tạm ngưng hay đóng một dòng họ trong Sprint 1, người vận hành phải sửa DB trực tiếp (ghi audit bằng tay). Đã quyết định không làm suspend/deactivate trong Sprint 1.
- **Việc cần làm sau:** nhóm quyết định vòng đời clan sau kích hoạt (tạm ngưng, hết hạn, đóng, kích hoạt lại) cùng với vòng đời gói của Sprint 6 (task 3.6.8.6). Liên quan KI-30.

## KI-30 Hết hạn gói không được thực thi

- **Hiện trạng:** `clan_subscriptions.ends_at` chỉ được **ghi** khi kích hoạt. Không có tác vụ nền nào đổi subscription thành `EXPIRED` hay clan thành `EXPIRED`, và `authorize()` chỉ xét `clans.status = ACTIVE` (không xét subscription). Một clan `ACTIVE` vẫn dùng được **mãi mãi** dù gói đã hết hạn.
- **Giảm nhẹ:** `GET /admin/clans/{id}` cho SA thấy `subscription.ends_at` để tự theo dõi; Sprint 1 không có thanh toán nên không có doanh thu bị mất thật.
- **Việc cần làm sau:** một tác vụ nền (cùng lý do với KI-17, KI-21, KI-24 là chưa có chỗ chạy nền) hoặc kiểm tra `ends_at` ngay trong `authorize()`; thuộc Sprint 6. Liên quan KI-29.

## KI-31 Chưa có endpoint liệt kê clan

- **Hiện trạng:** SA đọc được **một** clan (`GET /admin/clans/{id}`) nhưng không liệt kê hay tìm clan. `clan_id` lấy từ chi tiết hồ sơ (`GET /admin/business-registrations/{id}`, trường `clan_id`) hoặc từ response tạo Business.
- **Việc cần làm sau:** `GET /admin/clans` có lọc theo trạng thái và phân trang khi cần màn quản lý clan; dùng `Page[...]` như các danh sách khác.

## KI-32 Chưa có endpoint đổi gói của một subscription: gói ngừng bán làm kẹt việc kích hoạt

- **Hiện trạng:** nếu gói của subscription `PENDING` bị chuyển `INACTIVE` (ngừng bán) giữa lúc tạo Business và lúc kích hoạt, `POST /admin/clans/{id}/activate` trả `409` ("The plan of the subscription is no longer available"). Sprint 1 không có API quản lý gói (đổi trạng thái gói, đổi gói của subscription), nên **SA không tự gỡ được qua giao diện**.
- **Cách gỡ kẹt (do người vận hành có quyền DB, trên nhánh Neon đúng, theo quy trình migration của KI-15; luôn trong một giao dịch, có người thứ hai xem lại, và ghi tay một dòng audit):**
  1. **Nếu việc ngừng bán là nhầm:** đặt lại gói về bán: `UPDATE subscription_plans SET status = 'ACTIVE', updated_at = now() WHERE plan_id = '<plan_id>';`
  2. **Nếu gói thật sự đã ngừng bán:** chọn gói đang bán `ACTIVE` cho khách (đã thỏa thuận với họ) rồi đổi gói của subscription còn `PENDING`: `UPDATE clan_subscriptions SET plan_id = '<plan_id_moi>' WHERE subscription_id = '<subscription_id>' AND status = 'PENDING';`
  Sau đó SA gọi lại `POST /admin/clans/{id}/activate` (nó đọc lại gói và tính `ends_at` theo gói mới lúc kích hoạt). Không đụng `clans.status` bằng tay: để endpoint kích hoạt làm.
- **Việc cần làm sau:** API quản lý gói và đổi gói thuộc Sprint 6 (task 3.6.8.6, liên kết KI-19, KI-22).

## KI-33 Script smoke test E8 nằm ngoài repo: không chạy lại được từ một bản checkout

- **Hiện trạng:** smoke test với Firebase thật (Mốc E, bước E8, kết quả ở `docs/testing.md` mục 5) chạy bằng một script và một launcher PowerShell **nằm ngoài repo**, do người phụ trách giữ. Repo chỉ có kết quả và các điều kiện chạy lại, không có chính script. Không có CI nào chạy nó (cố ý: nó ghi vào Firebase và DB dev thật).
- **Hệ quả:** người khác, hoặc chính nhóm sau này, muốn lặp lại bài kiểm tra (ví dụ sau khi đổi adapter Firebase hay luồng cấp Owner) phải xin script từ người giữ nó.
- **Việc cần làm sau:** nhóm quyết định có đưa script vào repo (ví dụ `scripts/`) hay không. Nếu đưa vào thì phải rà soát như mã chạm hệ thống thật: không giá trị bí mật nào trong file, launcher chỉ hỏi và đặt biến môi trường, và giữ phần selftest toàn đồ giả.

## KI-34 Ba bảng của sprint sau nằm ngoài thứ tự dọn của E8: đang rỗng, được theo dõi

- **Hiện trạng:** lúc preflight, khóa ngoại của `person_merge_history`, `restore_jobs` và `violation_reports` trỏ vào `users`, `clans` hoặc bảng đi theo clan mà **không** có `ON DELETE CASCADE` hay `SET NULL`, và thứ tự dọn của E8 (9 bảng, `users` cuối cùng) không xóa chúng. Cả ba **rỗng** và luồng E8 không ghi vào, nên preflight cho qua và ghi ba bảng vào danh sách theo dõi. Một bảng như vậy mà có dữ liệu thì preflight dừng.
- **Hệ quả:** khi một tính năng của sprint sau bắt đầu ghi vào các bảng này (hoặc vào bất kỳ bảng nào có khóa ngoại kiểu đó), một lượt E8 mới sẽ dừng ở preflight, hoặc dừng ở cuối giai đoạn main và đầu `--cleanup` nếu dữ liệu xuất hiện giữa chừng, và **không xóa gì** (kể cả user Firebase) cho tới khi có người quyết định.
- **Việc cần làm sau:** khi các tính năng đó vào, thêm các bảng tương ứng vào thứ tự dọn của script trước khi chạy lại E8. Liên quan KI-33.

## KI-35 E8 chạy với Web API key không bị hạn chế theo HTTP referrer

- **Hiện trạng:** bước kiểm tra key của preflight cho thấy Google chấp nhận Web API key **không kèm referer** (key gửi qua header), nghĩa là trong lần chạy E8 key không có hạn chế HTTP referrer nào có hiệu lực cho lời gọi đăng nhập. Chưa thử trường hợp key bị hạn chế theo referrer.
- **Hệ quả:** nếu nhóm sau này hạn chế key theo referrer, script E8 chỉ chạy được khi đặt `E8_HTTP_REFERER` thành một referer được phép (launcher có hỏi giá trị này). BE không dùng Web API key, nên không bị ảnh hưởng.
- **Việc cần làm sau:** không có việc nào của BE; ghi lại để người chạy lại E8 biết.

## KI-36 Windows: chạy `uvicorn` không có `--reload` thì kết nối DB lỗi (`psycopg` async trên `ProactorEventLoop`) — Đã xác nhận, có cách tránh

- **Triệu chứng (xác nhận ngày 09/10/2026, Windows, uvicorn 0.54.0, cùng máy và cùng `.env`):** `uvicorn app.main:app --port 8000` **không** có `--reload` ghi log "Database connectivity check failed at startup (InterfaceError)" và `GET /api/health/ready` trả `503`. Với `--reload` thì khởi động xong không có thông báo đó và `GET /api/health/ready` trả `200`.
- **Nguyên nhân:** `psycopg` ở chế độ async không chạy được trên `ProactorEventLoop`. `app/main.py` và `app/db/postgres.py` đặt `WindowsSelectorEventLoopPolicy` ngay khi import, nhưng uvicorn 0.54.0 tự truyền một *loop factory* cho `asyncio.run`: trên Windows nó là `ProactorEventLoop` khi không có `--reload` và `--workers` (`uvicorn/loops/asyncio.py`), nên chính sách đã đặt bị bỏ qua. Với `--reload` hoặc `--workers` uvicorn dùng vòng lặp selector. Cùng nguyên nhân với lỗi `InterfaceError` mà script E8 gặp ở lần preflight đầu (E8 đã tự đặt chính sách trước `asyncio.run`).
- **Cách tránh:** trên Windows luôn chạy `uvicorn app.main:app --reload` như README ghi. Docker và Linux **không** bị ảnh hưởng (vòng lặp selector là mặc định ở đó).
- **Chưa có sửa trong code.** Một hướng có thể làm sau (chưa quyết định): một runner dev nhỏ khởi động uvicorn với loop factory kiểu selector, để chạy được cả khi không có `--reload`.

## KI-37 Lượt integration cả bộ rất dài vẫn có thể mất một kết nối Neon và làm hỏng một test ngẫu nhiên (ưu tiên thấp)

- **Hiện tượng:** lượt chạy cả bộ ngày 09/10/2026 (`ALLOW_DB_TESTS=1 pytest -m integration -q`, 456 test, **4 giờ 47 phút 22 giây**) cho 455 passed, 1 failed. Test lỗi là `test_a_suspended_member_can_still_be_revoked_and_non_fas_are_404` (`tests/integration/test_family_admin_lifecycle_db.py`), với `psycopg.OperationalError: server closed the connection unexpectedly` ngay trong phần dựng dữ liệu của test (`INSERT INTO clans`), sau khi các khẳng định trước đó đã đạt. Chạy lại riêng test đó pass (37 giây); cả file pass hai lần (12 passed, 273 và 277 giây). Đây là sự cố hạ tầng, không phải lỗi mã.
- **Cái đã có:** engine của test đã dùng `pool_pre_ping=True`, `pool_recycle=1800`, `connect_timeout=15` (cùng `ENGINE_OPTIONS` với ứng dụng, qua `make_engine`; `tests/test_db_engine_config.py` canh việc này). `pool_pre_ping` chỉ thay kết nối **đã chết lúc lấy ra khỏi pool**; kết nối đứt **khi đang dùng** (giữa giao dịch hoặc ngay sau khi lấy) vẫn là lỗi, nên nó không cứu được trường hợp này.
- **Nguyên nhân phía Neon: CHƯA XÁC ĐỊNH**, như KI-23 (đây là thêm một mẫu quan sát cho KI-23, sau lượt 43 phút của E4).
- **Việc cần làm sau (không chọn bây giờ, hai hướng):** (a) điều tra phía Neon: cấu hình autosuspend và ngưỡng nhàn rỗi của pooler, log kết nối quanh thời điểm lỗi (người có quyền Neon Console); (b) một lần thử lại **chỉ ở test**, chỉ cho phần dựng dữ liệu và chỉ khi gặp `OperationalError` không có sqlstate (kết nối đứt), không bao giờ ở mã ứng dụng.
- **Giảm nhẹ:** chạy lại riêng test lỗi hoặc file của nó; tránh sửa mã trong lúc một lượt cả bộ đang chạy. Liên quan KI-23.

