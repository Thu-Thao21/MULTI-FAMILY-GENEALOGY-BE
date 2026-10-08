# Hợp đồng API Sprint 1 — MFGMS AI

Trạng thái: **đề xuất**. Schema Pydantic đã có trong `app/schemas/`. Đã cài trong `main`: Mốc D `POST /auth/session`, `GET /auth/me`, `POST /auth/logout`, `POST /auth/change-password`; Mốc F `GET /admin/users`, `GET /admin/users/{id}`, `PATCH /admin/users/{id}/status`, `GET /clans/{id}/users`, `PUT /clans/{id}/admins/{user_id}/permissions`; Mốc F2 `POST /clans/{id}/admins`, `DELETE /clans/{id}/admins/{user_id}`; Mốc E bước E3 (Guest) `GET /service-plans`, `POST /business-registrations`, `POST /business-registrations/track`; Mốc E bước E4 (System Admin) `GET /admin/business-registrations`, `GET /admin/business-registrations/{id}`, `POST /admin/business-registrations/{id}/review`; Mốc E bước E5 `POST /admin/business-registrations/{id}/business`; Mốc E bước E6a `POST /admin/clans/{id}/owner`, `GET /admin/provisioning-jobs/{id}`; Mốc E bước E6b `GET /admin/provisioning-jobs`, `POST /admin/provisioning-jobs/{id}/retry`, `POST /admin/provisioning-jobs/{id}/abandon`, `POST /admin/clans/{id}/owner/temporary-password`. Các API khác chưa có endpoint. Tài liệu này là căn cứ để FE nối màn hình và để BE viết controller ở Mốc D, E, F. Nguồn: mục 6, 7, 8, 9 của `BE_Sprint1_Coding_Plan.md.md`.

## Trạng thái cài đặt

Cập nhật 06/10/2026 (Mốc G). Chỉ ghi chú trạng thái; nội dung hợp đồng ở các mục sau không đổi. `tests/test_openapi_contract.py` khóa danh sách "đã cài" và đối chiếu từng endpoint với tài liệu này.

| Endpoint | Trạng thái | Ghi chú |
| --- | --- | --- |
| `POST /auth/session` | Đã cài (Mốc D) | Mã `429` trong hợp đồng chưa cài (chưa có rate limit, KI-06) |
| `GET /auth/me` | Đã cài (Mốc D) | `permissions[]` tạm thời, chờ lead (mục 6, quyết định 16) |
| `POST /auth/logout` | Đã cài (Mốc D) | |
| `POST /auth/change-password` | Đã cài (Mốc D) | Đổi xong phải đăng nhập lại |
| `POST /auth/password-reset/request`, `POST /auth/password-reset/confirm` | Chưa cài | KI-05; FE tạm dùng `sendPasswordResetEmail` của Firebase |
| `GET /admin/users`, `GET /admin/users/{user_id}` | Đã cài (Mốc F) | |
| `PATCH /admin/users/{user_id}/status` | Đã cài (Mốc F) | Bảng chuyển trạng thái tạm thời, chờ lead (quyết định 20) |
| `GET /clans/{clan_id}/users` | Đã cài (Mốc F) | |
| `PUT /clans/{clan_id}/admins/{user_id}/permissions` | Đã cài (Mốc F) | Sửa tập quyền; mã `ADMIN_MANAGE` bị `403` (quyết định 30) |
| `POST /clans/{clan_id}/admins`, `DELETE /clans/{clan_id}/admins/{user_id}` | Đã cài (Mốc F2) | Đề bạt và thu hồi Family Admin (KI-07 đã xử lý) |
| `GET /service-plans`, `POST /business-registrations`, `POST /business-registrations/track` | Đã cài (Mốc E, bước E3) | Guest, không cần xác thực. Có giới hạn tần suất trong bộ nhớ theo từng process (KI-17). Dữ liệu gói dev do `seed_dev.py` tạo (gói `DEV-`, viết sau E3); gói production do nhóm quyết định (KI-19) |
| `GET /admin/business-registrations`, `GET /admin/business-registrations/{id}`, `POST /admin/business-registrations/{id}/review` | Đã cài (Mốc E, bước E4) | Chỉ SA. Không giới hạn tần suất. Mọi response `Cache-Control: no-store`. **Có thay đổi hợp đồng ảnh hưởng FE**, xem mục "Thay đổi hợp đồng ở E4" cuối mục 4 |
| `POST /admin/business-registrations/{id}/business` | Đã cài (Mốc E, bước E5) | Chỉ SA. Header `Idempotency-Key` bắt buộc. Tạo clan `PENDING`, hồ sơ clan và gói đăng ký `PENDING` trong một giao dịch; chưa tạo Owner (E6). Ngày của gói đăng ký là tạm thời, E7 đặt lại khi kích hoạt. **Có thay đổi hợp đồng ảnh hưởng FE**, xem mục "Thay đổi hợp đồng ở E5" |
| `POST /admin/clans/{id}/owner`, `GET /admin/provisioning-jobs/{id}` | Đã cài (Mốc E, bước E6a) | Chỉ SA. Header `Idempotency-Key` bắt buộc cho `POST`. Cấp Owner qua Firebase bằng một **job** (nhiều giao dịch ngắn, Firebase nằm giữa). `201` trả **mật khẩu tạm một lần** kèm `Cache-Control: no-store`. Chưa có `EmailSender` thật: SA chuyển mật khẩu thủ công (KI-26). **Có thay đổi hợp đồng ảnh hưởng FE**, xem mục "Thay đổi hợp đồng ở E6a" |
| `GET /admin/provisioning-jobs`, `POST /admin/provisioning-jobs/{id}/retry`, `POST /admin/provisioning-jobs/{id}/abandon`, `POST /admin/clans/{id}/owner/temporary-password` | Đã cài (Mốc E, bước E6b) | Chỉ SA, `Cache-Control: no-store`. `retry` và `temporary-password` trả **mật khẩu tạm một lần**; danh sách và `abandon` không bao giờ có email, điện thoại hay mật khẩu. Không có `Idempotency-Key` (xem mục "Thay đổi hợp đồng ở E6b") |
| `POST /admin/clans/{id}/activate` | Chưa cài | Mốc E, bước E7 (D03) |

OpenAPI do FastAPI sinh ra (`/docs`, `/openapi.json`) khai báo mọi mã lỗi của từng endpoint đã cài bằng schema `ErrorResponse` (thay cho `HTTPValidationError` mặc định của FastAPI, vốn không phải body lỗi thật). Mã khai báo là các mã mà code có thể trả; có thể rộng hơn danh sách "Lỗi" của từng mục (ví dụ `503 DATABASE_UNAVAILABLE`, `403 TEMPORARY_PASSWORD_EXPIRED` áp dụng cho mọi API cần đăng nhập, theo mục 2).

## 1. Quy ước chung

| Mục | Quy ước |
| --- | --- |
| Prefix | `/api/v1` cho mọi API dưới đây |
| Xác thực | `Authorization: Bearer <access_token>` lấy từ `POST /auth/session`. API "Guest" không cần header này |
| Request ID | Gửi `X-Request-ID` (8–128 ký tự `A-Z a-z 0-9 . _ -`) nếu có; nếu thiếu hoặc không hợp lệ, server tự sinh UUID. Mọi response đều có header `X-Request-ID` |
| Idempotency | API có ghi "Idempotency-Key" bắt buộc gửi header `Idempotency-Key`: **8 đến 128 ký tự ASCII in được, không có khoảng trắng** (khuyến nghị UUID); thiếu hoặc sai độ dài hay ký tự thì `422` (giá trị không được in lại). Phạm vi của key là (người gọi, endpoint), sống **7 ngày**. Cùng key + cùng yêu cầu (đường dẫn, kể cả mã trong đường dẫn, và body đã chuẩn hóa; body vắng, `{}` và trường `null` là một) thì phát lại **đúng phản hồi thành công đã lưu**, kèm header `Idempotency-Replayed: true`; cùng key + yêu cầu khác trả `409 IDEMPOTENCY_KEY_CONFLICT`. **Chỉ phản hồi thành công được lưu**: lỗi không được lưu, nên gửi lại với cùng key sẽ kiểm tra điều kiện lại từ đầu. Hai request cùng key cùng lúc: request sau chờ request trước xong rồi nhận phát lại. Key và hàng làm việc nằm trong cùng một giao dịch, nên request chết giữa chừng không để lại key kẹt. Phản hồi đã lưu không bao giờ chứa bí mật |
| ID | UUID dạng chuỗi |
| Thời gian | ISO 8601 UTC có hậu tố `Z`, ví dụ `2026-10-05T08:00:00Z`. Input phải có múi giờ; datetime không múi giờ bị `422` |
| Tiền | `price`, `limit_value` là chuỗi thập phân, ví dụ `"199000.00"` |
| Email | Chỉ trim khoảng trắng hai đầu, **không** lowercase. Kiểm tra bằng regex đơn giản, tối đa 255 ký tự. Từ chối ký tự điều khiển, chuẩn hóa Unicode NFC |
| Văn bản một dòng | Tên, nơi gốc, tên họ (kiểu `Str255`): trim, gộp dãy khoảng trắng bên trong thành một dấu cách, chuẩn hóa NFC, tối đa 255 ký tự. **Ký tự điều khiển bị `422`**: NUL, tab, xuống dòng, DEL và nhóm C1 (một ký tự NUL làm driver DB ném lỗi nên không bao giờ được lọt xuống DB). Giá trị sai không được in lại trong lỗi |
| Văn bản nhiều dòng | Các trường **lý do** (`reason` của `PATCH /admin/users/{id}/status` và của `POST .../review`; kiểu `MultilineText`): trim, cho phép xuống dòng và tab, đổi CRLF thành LF, chuẩn hóa NFC, tối đa 2000 ký tự. **Ký tự NUL và mọi ký tự điều khiển khác bị `422`** (trước đây NUL lọt xuống driver DB và thành `500`). Giá trị sai không được in lại trong lỗi |
| Văn bản tìm kiếm | Ô tìm kiếm `q` (kiểu `SearchText`, E4): trim, gộp khoảng trắng, NFC; **ký tự điều khiển (kể cả NUL, tab, xuống dòng) bị `422`**; không đổi hoa/thường (so khớp không phân biệt hoa/thường do DB lo). Ký tự `%`, `_` và `\` được coi là ký tự thường. Giá trị `q` không được in lại trong lỗi và không ghi log. `GET /admin/business-registrations`: 2 đến 100 ký tự; `GET /admin/users`: 0 đến 255 ký tự như cũ (`q` rỗng vẫn là không lọc) |
| Bí mật | `id_token`, `recent_id_token`, `oob_code`, `tracking_code`, mật khẩu: không trim, không chuẩn hóa, không gộp khoảng trắng, không ghi log. Giá trị đến nguyên vẹn từng byte (có test); không bao giờ đi qua hai kiểu văn bản ở trên. Mật khẩu tối thiểu 6 ký tự theo Firebase |
| Giới hạn tần suất | Các API Guest ghi dữ liệu hoặc dò mã (`POST /business-registrations`, `POST /business-registrations/track`) bị giới hạn theo IP: quá ngưỡng trả `429 RATE_LIMITED` kèm header `Retry-After` (giây). Đếm trong bộ nhớ của từng process (KI-17). `X-Forwarded-For` bị bỏ qua trừ khi bật `TRUST_PROXY_HEADERS`. Các API quản trị (cần đăng nhập, kể cả của SA) **không** bị giới hạn tần suất |
| Field lạ | Request body có field không khai báo bị `422` |
| Phân trang | Query `page` (≥ 1, mặc định 1), `page_size` (1–100, mặc định 20). Response `{items, total, page, page_size}` (`Page[T]`) |
| Không bao giờ trả | Credential metadata nhạy cảm (failed_login_count, locked_until, mốc mật khẩu tạm, firebase_uid), `tracking_code_hash`, `storage_key`, mật khẩu, token đã lưu, ORM thô |

## 2. Envelope lỗi

```json
{"error": {"code": "ACCOUNT_BLOCKED", "message": "This account cannot be used.", "request_id": "6df2c3e1-27f4-43c4-b2e3-97fe67742e24"}}
```

FE rẽ nhánh theo `code`, không theo `message`. Lỗi `422` chỉ nêu vị trí field lỗi, không trả lại giá trị đã nhập.

| HTTP | Mã lỗi | Khi nào |
| --- | --- | --- |
| 400 | `BAD_REQUEST` | Request sai ngoài phạm vi validation schema |
| 400 | `RESET_CODE_INVALID` | `oob_code` reset mật khẩu sai |
| 400 | `RESET_CODE_EXPIRED` | `oob_code` reset mật khẩu hết hạn |
| 401 | `UNAUTHENTICATED` | Thiếu bearer token |
| 401 | `INVALID_ID_TOKEN` | Firebase ID token sai, hết hạn hoặc đã thu hồi |
| 401 | `SESSION_INVALID` | Phiên ứng dụng sai, hết hạn hoặc đã thu hồi |
| 401 | `RECENT_LOGIN_REQUIRED` | `recent_id_token` không đủ mới hoặc UID không khớp |
| 403 | `FORBIDDEN` | Thiếu quyền |
| 403 | `ACCOUNT_BLOCKED` | users.status là LOCKED, SUSPENDED hoặc DISABLED |
| 403 | `PASSWORD_CHANGE_REQUIRED` | Phiên hạn chế gọi API ngoài me, change-password, logout |
| 403 | `TEMPORARY_PASSWORD_EXPIRED` | Mật khẩu tạm đã hết hạn |
| 404 | `NOT_FOUND` | Tài nguyên không tồn tại hoặc không nhìn thấy với người gọi, kể cả tài nguyên của clan khác |
| 405 | `METHOD_NOT_ALLOWED` | Sai method |
| 409 | `STATE_CONFLICT` | Trạng thái đã đổi hoặc chuyển trạng thái không hợp lệ |
| 409 | `DUPLICATE_RESOURCE` | Vi phạm unique (clan_code, clan đã tạo cho hồ sơ, hồ sơ đăng ký `PENDING` trùng người nộp...) |
| 409 | `IDEMPOTENCY_KEY_CONFLICT` | Dùng lại Idempotency-Key với payload khác |
| 422 | `VALIDATION_ERROR` | Input sai schema, thiếu header bắt buộc |
| 429 | `RATE_LIMITED` | Quá giới hạn tần suất; luôn kèm header `Retry-After` (số giây nguyên, tối thiểu 1) và envelope chuẩn có `request_id`. Hiện chỉ ở hai `POST` Guest của hồ sơ đăng ký (`/auth/session` chưa có, KI-06) |
| 500 | `INTERNAL_ERROR` | Lỗi không lường trước. Server chỉ log tên lớp lỗi và request_id |
| 503 | `PROVIDER_UNAVAILABLE` | Firebase hoặc email provider lỗi |
| 503 | `DATABASE_UNAVAILABLE` | Database lỗi |

Mọi API có thể trả thêm `500 INTERNAL_ERROR` và `503 DATABASE_UNAVAILABLE`; bảng dưới không lặp lại hai mã này. Mọi API cần đăng nhập đều có thể trả `401 UNAUTHENTICATED`, `401 SESSION_INVALID`, `403 ACCOUNT_BLOCKED` và, nếu không nằm trong nhóm được phép, `403 PASSWORD_CHANGE_REQUIRED`.

Vai trò: **SA** System Admin, **BO** Business Owner, **FA** Family Admin, **ME** Member, **Guest** chưa đăng nhập.

## 3. API xác thực (mục 6)

Schema nằm trong `app/schemas/auth.py`.

### POST /auth/session
- **Quyền:** Guest (đổi Firebase ID token lấy phiên ứng dụng)
- **Body:** `SessionCreateRequest` `{id_token}`
- **Thành công:** `201` `SessionCreateResponse` `{access_token, token_type: "Bearer", expires_at, user: {user_id, display_name, email, status}, requires_password_change}`. `access_token` chỉ trả một lần
- **Lỗi:** `401 INVALID_ID_TOKEN`; `403 ACCOUNT_BLOCKED`, `403 TEMPORARY_PASSWORD_EXPIRED`; `422`; `429` (chưa cài, KI-06); `503 PROVIDER_UNAVAILABLE`
- **Mốc D:** `401 INVALID_ID_TOKEN` dùng chung cho token sai/hết hạn/thu hồi, UID chưa có trong `users`, và ID token có `auth_time` trước lần đổi mật khẩu gần nhất. Cùng thông điệp, không lộ UID có tồn tại hay không. Không bao giờ tự tạo user, không nối tài khoản theo email. `expires_at` = lúc tạo + `SESSION_TTL_HOURS` (8 giờ).

### GET /auth/me
- **Quyền:** phiên hợp lệ, kể cả phiên hạn chế
- **Thành công:** `200` `MeResponse` `{user_id, display_name, status, memberships[], permissions[], requires_password_change}`
  - `memberships[]`: `MembershipSummary` `{clan_id, clan_name, clan_status, membership_status, roles[], permissions[]}`; quyền trong từng clan
  - `permissions[]` cấp hệ thống: quyền từ role có `clan_id = NULL`
  - **Tạm thời, chờ lead chốt** (xem mục 6, Mốc D): giá trị trong `permissions` là mã action của policy cho SA/BO và mã trong `family_admin_permissions` cho FA
- **Lỗi:** chỉ các lỗi chung của API cần đăng nhập

### POST /auth/logout
- **Quyền:** phiên hiện tại, kể cả phiên hạn chế
- **Body:** không có
- **Thành công:** `204`. Thu hồi phiên hiện tại; FE xóa token và gọi `signOut` Firebase
- **Lỗi:** `401 SESSION_INVALID`

### POST /auth/password-reset/request

> **Chưa cài (Mốc D để sang mốc sau, KI-05).** FE tạm dùng `sendPasswordResetEmail` của Firebase SDK.

- **Quyền:** Guest; có rate limit
- **Body:** `PasswordResetRequest` `{email}`
- **Thành công:** `202` `PasswordResetRequestAccepted` `{message}`. Cùng một thông báo dù email có tồn tại hay không
- **Lỗi:** `422`; `429`; `503 PROVIDER_UNAVAILABLE`. Không bao giờ trả `404`

### POST /auth/password-reset/confirm
- **Quyền:** Guest; có rate limit
- **Body:** `PasswordResetConfirmRequest` `{oob_code, new_password}`
- **Thành công:** `204`. Mọi phiên ứng dụng cũ của user bị thu hồi
- **Lỗi:** `400 RESET_CODE_INVALID`, `400 RESET_CODE_EXPIRED`; `422`; `429`; `503 PROVIDER_UNAVAILABLE`

### POST /auth/change-password
- **Quyền:** phiên hợp lệ, kể cả phiên hạn chế
- **Body:** `ChangePasswordRequest` `{new_password, recent_id_token}`
- **Thành công:** `204`. Mọi phiên bị thu hồi; FE phải đăng nhập lại
- **Mốc D:** BE gọi Firebase Admin SDK (`update_user` rồi `revoke_refresh_tokens`), cần `FIREBASE_SERVICE_ACCOUNT_PATH`; thiếu thì `503 PROVIDER_UNAVAILABLE`. `recent_id_token` phải cùng UID với phiên và có `auth_time` trong vòng `RECENT_LOGIN_MAX_AGE_SECONDS` (300 giây), nếu không `401 RECENT_LOGIN_REQUIRED`. Sau khi đổi, **mọi ID token cũ (đăng nhập trước lúc đổi) bị `POST /auth/session` từ chối**, nên FE phải `signOut` rồi đăng nhập lại bằng mật khẩu mới để lấy ID token mới. Firebase từ chối mật khẩu theo chính sách của project thì `422 VALIDATION_ERROR`. Nếu Firebase đã đổi nhưng DB lỗi: `503 DATABASE_UNAVAILABLE` kèm `request_id`; cờ đổi mật khẩu vẫn còn nên tài khoản vẫn bị hạn chế, gọi lại là hoàn tất
- **Lỗi:** `401 RECENT_LOGIN_REQUIRED`; `403 TEMPORARY_PASSWORD_EXPIRED`; `422`; `503 PROVIDER_UNAVAILABLE`. Nếu Firebase đã đổi nhưng DB lỗi, trả `503` kèm `request_id` để theo dõi, không trả thành công

## 4. API Business và người dùng (mục 8)

Schema nằm trong `app/schemas/business.py` và `app/schemas/users.py`.

### GET /service-plans
- **Quyền:** Guest (không cần xác thực; header `Authorization` nếu có thì bị bỏ qua). Không giới hạn tần suất
- **Query:** `page`, `page_size`
- **Thành công:** `200` `Page[ServicePlanResponse]`; mỗi gói có `features[]` (`PlanFeaturePublic` `{feature_code, enabled, limit_value}`; tính năng tắt vẫn được liệt kê với `enabled: false`). Chỉ gói `ACTIVE`, sắp theo giá tăng dần rồi theo `code`. `price` và `limit_value` là chuỗi thập phân. Không lộ `status`, `metadata`, thời gian tạo
- **Lỗi:** `422`

### POST /business-registrations
- **Quyền:** Guest; giới hạn tần suất theo IP (mặc định 5 mỗi giờ). Header `Authorization` nếu có thì bị bỏ qua
- **Body:** `BusinessRegistrationCreateRequest` `{representative_name, representative_email, representative_phone?, clan_name, origin_place?, requested_plan_id}`. Quy tắc: tên, tên họ, nơi gốc 1 đến 255 ký tự sau khi trim và gộp khoảng trắng; email theo regex của mục 1, giữ nguyên chữ hoa/thường; `representative_phone` 6 đến 30 ký tự chỉ gồm chữ số, dấu cách, `+ ( ) -`, dấu `+` chỉ ở đầu; mọi chuỗi bị `422` nếu có ký tự điều khiển
- **Thành công:** `201` `BusinessRegistrationCreateResponse` `{registration_id, tracking_code, status, created_at}`, kèm `Cache-Control: no-store`. `tracking_code` là chuỗi ngẫu nhiên 256 bit (43 ký tự), chỉ trả **một lần**, server chỉ lưu SHA-256 và không ghi nó vào log hay audit. Hồ sơ vào trạng thái `PENDING`; mỗi hồ sơ mới ghi một dòng lịch sử trạng thái và một dòng audit (không có người thực hiện, vì Guest không có tài khoản)
- **Lỗi:** `409 DUPLICATE_RESOURCE` nếu đã có hồ sơ `PENDING` cùng email và cùng tên họ (không phân biệt hoa/thường, chuẩn hóa NFC); `422` (kể cả gói không tồn tại hoặc không được chọn: cùng một thông điệp cho cả hai trường hợp, để Guest không dò được gói nào có thật); `429` kèm `Retry-After`

### POST /business-registrations/track
- **Quyền:** Guest; giới hạn tần suất theo IP (mặc định 20 mỗi 10 phút)
- **Body:** `BusinessRegistrationTrackRequest` `{tracking_code}`. Mã không bị trim hay chuẩn hóa
- **Thành công:** `200` `BusinessRegistrationTrackResponse` `{clan_name, status, public_reason?, submitted_at, updated_at}`, kèm `Cache-Control: no-store`. `public_reason` là lý do từ chối **chỉ khi** `status` là `REJECTED` (người nộp hồ sơ sẽ thấy lý do SA nhập), các trường hợp khác là `null`. Không có hash, email, ID, gói hay người duyệt
- **Lỗi:** `404 NOT_FOUND` khi mã sai (mọi mã sai cho cùng một thông điệp); `422`; `429` kèm `Retry-After`. Không có API liệt kê hồ sơ cho Guest

### GET /admin/business-registrations
- **Quyền:** chỉ SA (phạm vi hệ thống). Người khác, kể cả BO, FA và tài khoản có vai trò SA gắn với một clan: `403`. Không giới hạn tần suất. `Cache-Control: no-store`
- **Query:** `BusinessRegistrationListQuery` `{page, page_size, status?, q?, created_from?, created_to?}`. `status` là một trong `DRAFT`, `PENDING`, `NEED_SUPPLEMENT`, `APPROVED`, `REJECTED`, `CANCELLED`. `q` là chuỗi con không phân biệt hoa/thường của tên họ, tên người đại diện hoặc email người đại diện (quy tắc ở mục 1, "Văn bản tìm kiếm"; 2 đến 100 ký tự). `created_from` **bao gồm** mốc, `created_to` **không bao gồm** mốc; cả hai bắt buộc có múi giờ; `created_from` sau `created_to` bị `422`. Các bộ lọc kết hợp bằng AND và `total` theo đúng các bộ lọc
- **Sắp xếp:** `created_at` giảm dần, rồi `registration_id` giảm dần (thứ tự ổn định khi trùng thời gian)
- **Thành công:** `200` `Page[BusinessRegistrationSummary]`; mỗi dòng **chỉ có** `registration_id, clan_name, representative_name, requested_plan_id, requested_plan_code, status, created_at, reviewed_at?`. **Không có** email, điện thoại, nơi gốc, lý do từ chối, người duyệt, lịch sử, tệp đính kèm, `clan_id`, hash; các trường đó chỉ có ở API chi tiết
- **Lỗi:** `401` (mục 2); `403 FORBIDDEN`; `422`

### GET /admin/business-registrations/{registration_id}
- **Quyền:** chỉ SA (người khác `403`, kể cả khi mã không tồn tại: không ai ngoài SA biết hồ sơ có thật hay không). `Cache-Control: no-store`
- **Thành công:** `200` `BusinessRegistrationDetail`: các trường của dòng danh sách + `representative_email`, `representative_phone?`, `origin_place?`, `reviewed_by?` (UUID của SA), `rejection_reason?`, `updated_at`, `clan_id?` (có khi Business đã được tạo), `status_history[]` (cũ trước, mới sau; `{from_status?, to_status, changed_by?, reason?, changed_at}`) và `attachments[]` (`{attachment_id, file_name, mime_type, uploaded_at}`; **không** có `storage_key`). SA được xem dữ liệu cá nhân của người nộp. Không bao giờ có `tracking_code_hash`. `reason` trong lịch sử có thể là ghi chú nội bộ khi duyệt
- **Lỗi:** `401` (mục 2); `403 FORBIDDEN`; `404 NOT_FOUND`; `422` (mã không phải UUID)

### POST /admin/business-registrations/{registration_id}/review
- **Quyền:** chỉ SA. Không giới hạn tần suất. `Cache-Control: no-store`
- **Body:** `RegistrationReviewRequest` `{decision: "APPROVED" | "REJECTED", reason?}`. `reason` là văn bản nhiều dòng, tối đa 2000 ký tự (mục 1: NUL và ký tự điều khiển khác bị `422`). **Bắt buộc khi `REJECTED`** và **người nộp hồ sơ sẽ thấy lý do này** (`public_reason` của `POST /business-registrations/track`). Khi `APPROVED`, `reason` là **ghi chú nội bộ**: chỉ nằm trong lịch sử trạng thái, người nộp không thấy. Field lạ (kể cả `reviewed_by`, `status`) bị `422`
- **Quy tắc:** chỉ hồ sơ `PENDING` được duyệt; `APPROVED` và `REJECTED` đều là kết quả cuối (không có duyệt lại, không idempotency: lần duyệt thứ hai là `409`). `APPROVED` còn đòi gói đã đăng ký **vẫn `ACTIVE`**; `REJECTED` không kiểm tra gói (E5 kiểm tra lại khi tạo Business). Hồ sơ, một dòng lịch sử trạng thái và một dòng audit nằm trong một giao dịch. `reviewed_by` luôn là SA đang đăng nhập, không nhận từ body
- **Thành công:** `200` `RegistrationReviewResponse` `{registration_id, status, reviewed_by, reviewed_at, reason_visible_to_applicant}`. `reason_visible_to_applicant` là `true` khi `REJECTED` (lý do hiển thị cho người nộp) và `false` khi `APPROVED`
- **Lỗi:** `401` (mục 2); `403 FORBIDDEN`; `404 NOT_FOUND`; `409 STATE_CONFLICT` khi hồ sơ không còn `PENDING` (thông điệp nêu trạng thái hiện tại, ví dụ "The registration is APPROVED; only a PENDING registration can be reviewed.") hoặc khi duyệt `APPROVED` mà gói đã đăng ký không còn `ACTIVE`; `422`

### POST /admin/business-registrations/{registration_id}/business
- **Quyền:** chỉ SA (phạm vi hệ thống; người khác `403` trước cả validation, kể cả khi mã hồ sơ không tồn tại). Không giới hạn tần suất. `Cache-Control: no-store`
- **Header:** `Idempotency-Key` bắt buộc (quy tắc ở mục 1)
- **Body:** `BusinessCreateRequest` `{clan_code?}`, tùy chọn (không gửi body, `{}` và `{"clan_code": null}` đều nghĩa là server tự sinh mã). `clan_code`: 3 đến 50 ký tự `A-Z 0-9 _ -`. Mã tự sinh có dạng `CLAN-` + 8 ký tự từ bảng chữ không nhập nhằng (`ABCDEFGHJKMNPQRSTUVWXYZ23456789`). **Gói không bao giờ lấy từ request**: server dùng gói đã đăng ký trong hồ sơ; field lạ (kể cả `plan_id`) bị `422`
- **Điều kiện:** hồ sơ `APPROVED`; hồ sơ chưa có clan; gói đã đăng ký **còn `ACTIVE`** (kiểm lại dù lúc duyệt đã kiểm). Chưa tạo Owner (E6); clan chỉ thành `ACTIVE` khi SA gọi `clan.activate` sau khi có Owner (E7)
- **Thành công:** `201` `BusinessCreateResponse` `{clan_id, clan_code, clan_status, subscription_id, plan_id, subscription_status, starts_at, ends_at}`. Một giao dịch tạo: clan `PENDING`, hồ sơ clan (kèm nơi gốc của hồ sơ), gói đăng ký `PENDING`, một dòng audit, dòng idempotency. **Ngày của gói đăng ký là tạm thời**: `starts_at` là lúc tạo, `ends_at` sau số tháng lịch của gói (31/01 cộng 1 tháng là 28/02, hoặc 29/02 năm nhuận); E7 đặt lại khi kích hoạt clan. Hồ sơ vẫn `APPROVED` và không có dòng lịch sử trạng thái mới. Phát lại: cùng `201`, cùng body, thêm header `Idempotency-Replayed: true`
- **Lỗi:** `401` (mục 2); `403 FORBIDDEN`; `404 NOT_FOUND`; `409 STATE_CONFLICT` khi hồ sơ chưa `APPROVED` (thông điệp nêu trạng thái), khi gói không còn `ACTIVE`, hoặc khi một request khác giữ khóa quá 10 giây (kèm `Retry-After: 1`); `409 DUPLICATE_RESOURCE` khi hồ sơ đã có clan hoặc `clan_code` do SA nhập đã tồn tại; `409 IDEMPOTENCY_KEY_CONFLICT` khi cùng key nhưng yêu cầu khác; `422` (header thiếu hoặc sai, body sai, mã không phải UUID)

### POST /admin/clans/{clan_id}/owner
- **Quyền:** chỉ SA (phạm vi hệ thống; người khác `403` trước mọi validation). Không giới hạn tần suất. `Cache-Control: no-store`
- **Header:** `Idempotency-Key` bắt buộc (quy tắc ở mục 1)
- **Body:** `OwnerProvisionRequest` `{email?, display_name?, phone?}`, tùy chọn (không gửi body, `{}` hay `null` đều hợp lệ). **Nguồn thông tin Owner:** mặc định lấy từ **người đại diện của hồ sơ đăng ký Business đã tạo clan** (`representative_email`, `representative_name`, `representative_phone`); body ghi đè từng trường riêng. Clan không có hồ sơ đăng ký thì **bắt buộc** `email` và `display_name` (thiếu thì `422`). Email giữ nguyên chữ hoa/thường như đã nhập
- **Điều kiện:** clan `PENDING`; chưa có Owner; chưa có job còn sống (`PENDING`, `RUNNING`, `FAILED_RETRYABLE`) của clan; email chưa thuộc tài khoản nào (không phân biệt hoa/thường) và chưa có job còn sống của clan khác; **không còn job `FAILED` đang chờ dọn Firebase (`needs_cleanup`) của clan hoặc của email đó**
- **Thành công:** `201` `OwnerProvisionResponse` `{job_id, status, clan_id, user_id, owner_email, owner_display_name, temporary_password, temporary_password_expires_at, email_delivery_status}`. `temporary_password` gồm 16 ký tự (chữ hoa, chữ thường, số; bỏ các ký tự dễ nhầm I, O, l, 0, 1), **chỉ hiện đúng một lần trong response này**, hết hạn sau 72 giờ; không bao giờ có trong DB, log, audit, key idempotency, job, thông báo lỗi hay tài liệu. Tài khoản Owner ở trạng thái `PENDING`, phải đổi mật khẩu ở lần đăng nhập đầu; clan vẫn `PENDING` (chỉ thành `ACTIVE` qua `clan.activate` ở E7). `email_delivery_status` là `null` khi chỉ có bản Noop: SA tự chuyển mật khẩu cho Owner
- **Phát lại:** cùng key + cùng yêu cầu trả `201` kèm `Idempotency-Replayed: true`, cùng `job_id`, `status`, `clan_id`, `user_id`; mọi trường còn lại (**kể cả `temporary_password`**) là `null`, vì mật khẩu không được lưu. Mất response thì dùng `POST /admin/clans/{id}/owner/temporary-password` (E6b). Key đang chạy (`IN_PROGRESS`): `409 STATE_CONFLICT` kèm `job_id` trong thông điệp và `Retry-After`, không tạo job mới
- **Lỗi:** `401` (mục 2); `403 FORBIDDEN`; `404 NOT_FOUND`; `409 STATE_CONFLICT` (clan không `PENDING`; đã có Owner; đã có job; còn job chờ dọn; key đang chạy; lượt chạy bị lượt mới thay thế; job lỗi sau 5 lần); `409 DUPLICATE_RESOURCE` (email đã là tài khoản hoặc đã thuộc tài khoản Firebase khác); `409 IDEMPOTENCY_KEY_CONFLICT`; `422` (header, body, hoặc thiếu email/tên khi clan không có hồ sơ); `503 PROVIDER_UNAVAILABLE` (Firebase không dùng được hoặc từ chối mật khẩu theo chính sách) và `503 DATABASE_UNAVAILABLE`. Khi lỗi sau khi job đã tạo, thông điệp nêu `job_id` và job ở `FAILED_RETRYABLE` (thử lại được, E6b) hoặc `FAILED`

### GET /admin/provisioning-jobs/{job_id}
- **Quyền:** chỉ SA. `Cache-Control: no-store`
- **Thành công:** `200` `ProvisioningJobResponse` `{job_id, job_type, clan_id, status, user_id?, email_delivery_status?, attempt_count, needs_cleanup, error_code?, created_at, updated_at}`. **Không bao giờ** có email, điện thoại, tên, Firebase uid hay mật khẩu. `status`: `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED_RETRYABLE`, `FAILED`. `error_code` là mã ngắn: `PROVIDER_UNAVAILABLE`, `PASSWORD_POLICY_REJECTED` (Firebase từ chối mật khẩu theo chính sách), `DATABASE_UNAVAILABLE`, `INTERNAL_ERROR`, `PROVIDER_EMAIL_TAKEN`, `PROVIDER_REJECTED_USER`, `UID_MISMATCH`, `OWNER_EMAIL_EXISTS`, `CLAN_STATE_CHANGED`. `needs_cleanup` là `true` khi job `FAILED` còn nợ việc xóa user Firebase của chính nó; job `FAILED` với `UID_MISMATCH` có `needs_cleanup = false` vì user lạ dưới uid của job không bao giờ bị xóa
- **Lỗi:** `401` (mục 2); `403 FORBIDDEN`; `404 NOT_FOUND`; `422` (mã không phải UUID)

### GET /admin/provisioning-jobs
- **Quyền:** chỉ SA (action `provisioning_job.read`). `Cache-Control: no-store`
- **Query:** `ProvisioningJobListQuery` `{page, page_size, clan_id?, status?}`. `page_size` tối đa **100** (mặc định 20); `status` là một trong `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED_RETRYABLE`, `FAILED`; các bộ lọc kết hợp bằng AND và `total` theo đúng bộ lọc
- **Sắp xếp:** `created_at` giảm dần, rồi `job_id` (thứ tự ổn định)
- **Thành công:** `200` `Page[ProvisioningJobResponse]`; mỗi dòng giống `GET /admin/provisioning-jobs/{id}`. **Không bao giờ** có email, điện thoại, tên, Firebase uid hay mật khẩu
- **Lỗi:** `401` (mục 2); `403 FORBIDDEN`; `422` (query sai, `page_size` quá 100, `clan_id` không phải UUID)

### POST /admin/provisioning-jobs/{job_id}/retry
- **Quyền:** chỉ SA (action `clan.owner.provision`). Không giới hạn tần suất. `Cache-Control: no-store`. Không có body, không có `Idempotency-Key`: hai request cùng lúc cho cùng job được khóa dòng job nối thứ tự, request đến sau thấy `RUNNING` còn lease và nhận `409`
- **Nhận:** `FAILED_RETRYABLE`; `PENDING` kẹt (không ai bắt đầu và đã quá lease 90 giây từ lúc tạo); `RUNNING` đã quá lease (tiếp quản, `attempt_count` tăng nên lượt cũ bị fencing chặn); `FAILED` còn `needs_cleanup` (**chỉ dọn Firebase**, không sinh mật khẩu). **Từ chối `409 STATE_CONFLICT`, thông điệp nêu trạng thái hiện tại:** `SUCCEEDED`; `FAILED` không cần dọn (kể cả `UID_MISMATCH` và job đã hết 5 lần); `RUNNING` còn lease (kèm `Retry-After`); `PENDING` vừa tạo (kèm `Retry-After`); job đã dùng đủ lần thử (nên `abandon`)
- **Điều kiện khi sẽ chạy lại:** clan còn `PENDING` và chưa có Owner (`409 STATE_CONFLICT`, nên `abandon`); email của job chưa thuộc tài khoản nào (`409 DUPLICATE_RESOURCE`). Dữ liệu Owner lấy từ chính job (email, tên, điện thoại đã lưu)
- **Thành công:** `200` `OwnerProvisionResponse` (cùng model với `201` của endpoint cấp Owner). Mỗi lần retry thành công **luôn sinh mật khẩu mới** (hạn 72 giờ), hiện **một lần** trong response này. Retry chỉ dọn thì `200` với `status: "FAILED"` và mọi trường sau `clan_id` là `null` (không có mật khẩu); dọn không xác nhận được thì `503 PROVIDER_UNAVAILABLE`, cờ giữ nguyên, gọi lại sau
- **`Idempotency-Key` gốc:** nếu job hoàn tất nhờ retry mà key của request cấp Owner đầu tiên còn `IN_PROGRESS` (tiến trình chết giữa chừng), key đó được **hoàn tất** (tìm theo `resource_id` là job, không theo chuỗi key), nên phát lại key gốc trả `201` với job và `temporary_password: null`. Retry lỗi thì key đó được giải phóng như mọi lỗi
- **Lỗi:** `401` (mục 2); `403 FORBIDDEN`; `404 NOT_FOUND`; `409 STATE_CONFLICT` (trạng thái không retry được; clan không còn `PENDING`; clan đã có Owner; lượt chạy bị lượt mới thay thế); `409 DUPLICATE_RESOURCE` (email đã là tài khoản hoặc thuộc tài khoản Firebase khác); `422` (mã không phải UUID); `503 PROVIDER_UNAVAILABLE` và `503 DATABASE_UNAVAILABLE`. Retry lỗi cũng ghi lại job như lần đầu (`FAILED_RETRYABLE`, hoặc `FAILED` sau lần thứ 5)

### POST /admin/provisioning-jobs/{job_id}/abandon
- **Quyền:** chỉ SA (action `clan.owner.provision`). `Cache-Control: no-store`. Không có body
- **Nhận:** `FAILED_RETRYABLE` (kể cả khi đã dùng đủ lần thử); `PENDING` kẹt; `RUNNING` đã quá lease. **Từ chối `409 STATE_CONFLICT` nêu trạng thái hiện tại:** `RUNNING` còn lease (kèm `Retry-After`: có thể một lượt đang ghi); `PENDING` vừa tạo; `SUCCEEDED`; `FAILED` (đã là kết quả cuối; job còn nợ dọn thì dùng `retry`)
- **Hiệu lực:** job thành `FAILED` với `error_code = ABANDONED`, có audit (`abandoned`). Khi một lượt chạy từng bắt đầu (`attempt_count > 0`) thì **luôn thử** `delete_user(own-<job_id>)` theo đúng thứ tự bù trừ: commit `FAILED` + `needs_cleanup` + `firebase_user_created` **trước**, rồi xóa, rồi hạ cờ. Xóa lỗi thì `firebase_user_created = true` và `needs_cleanup = true` giữ nguyên (chặn clan và email; `retry` sẽ dọn tiếp). `attempt_count = 0` thì không có gì ở Firebase: không gọi Firebase, không cờ. Key idempotency gốc còn `IN_PROGRESS` bị giải phóng. Clan không bị đổi
- **Thành công:** `200` `ProvisioningJobResponse` (sau khi dọn; `needs_cleanup` cho biết còn nợ hay không; **không** lỗi `503` nếu xóa thất bại)
- **Lỗi:** `401` (mục 2); `403 FORBIDDEN`; `404 NOT_FOUND`; `409 STATE_CONFLICT`; `422` (mã không phải UUID)

### POST /admin/clans/{clan_id}/owner/temporary-password
- **Quyền:** chỉ SA (action `clan.owner.temp_password.reset`). `Cache-Control: no-store`. Không có body, không có `Idempotency-Key`
- **Điều kiện:** clan có Owner hiện hành (`clan_ownership_history` đang mở); tài khoản Owner **`PENDING`** và còn phải đổi mật khẩu (`must_change_password`); tài khoản do job cấp (uid `own-<uuid>`). Mật khẩu tạm đã hết hạn vẫn đặt lại được (đó là mục đích). **`409 STATE_CONFLICT`** (thông điệp nêu trạng thái) khi Owner `ACTIVE` (đã tự đặt mật khẩu), `LOCKED`, `DISABLED`, không còn phải đổi mật khẩu, hoặc clan chưa có Owner
- **Thứ tự cố định:** (1) kiểm tra bằng giao dịch chỉ đọc và **kết thúc giao dịch**; (2) `set_owner_password(uid, mật khẩu mới)` trên Firebase (đặt mật khẩu và thu hồi refresh token), không giữ giao dịch hay khóa DB; (3) một giao dịch DB: khóa clan rồi `credential_metadata` (`FOR NO KEY UPDATE`), **kiểm tra lại** Owner và trạng thái, đặt `temporary_password_issued_at` = bây giờ, `expires_at` = +72 giờ, `must_change_password = true`, **thu hồi mọi phiên** của Owner, một dòng audit (`clan.owner.temp_password_reset`, chỉ id và số phiên bị thu hồi), commit; (4) `EmailSender` (Noop) sau commit
- **Khoảng hở (KI-25):** nếu ở bước 3 thấy Owner **đã đổi mật khẩu** (tài khoản không còn `PENDING`) thì **không ghi DB** và trả `409`, nhưng bước 2 đã đặt mật khẩu tạm đè lên mật khẩu mới của Owner trên Firebase; Owner dùng "quên mật khẩu" của Firebase hoặc SA xử lý ngoài luồng. Nếu bước 3 thấy hàng `credential_metadata` đã đổi so với lúc kiểm tra (reset khác thắng cuộc đua) thì cũng `409`, không ghi gì: gọi lại
- **Thành công:** `200` `OwnerPasswordResetResponse` `{clan_id, user_id, owner_email, owner_display_name, temporary_password, temporary_password_expires_at, email_delivery_status}`. Mật khẩu hiện **một lần**, 72 giờ; không bao giờ có trong DB, log, audit hay thông báo lỗi. Phiên cũ của Owner bị thu hồi; đăng nhập (`POST /auth/session`) lại chặn mật khẩu hết hạn như thường
- **Lỗi:** `401` (mục 2); `403 FORBIDDEN`; `404 NOT_FOUND` (clan không có); `409 STATE_CONFLICT`; `422` (mã không phải UUID); `503 PROVIDER_UNAVAILABLE` (Firebase lỗi hoặc từ chối mật khẩu: DB không đổi) và `503 DATABASE_UNAVAILABLE` (Firebase đã đổi mật khẩu nhưng DB không ghi: gọi lại)

### POST /admin/clans/{clan_id}/activate
- **Quyền:** SA; chờ chốt D03
- **Body:** không có
- **Thành công:** `200` `ClanActivateResponse` `{clan_id, status, activated_at?}`
- **Lỗi:** `403 FORBIDDEN`; `404 NOT_FOUND`; `409 STATE_CONFLICT` nếu chưa đủ điều kiện kích hoạt

### GET /admin/users
- **Quyền:** SA
- **Query:** `AdminUserListQuery` `{page, page_size, status?, q?}`; `q` theo quy tắc "Văn bản tìm kiếm" của mục 1: **ký tự điều khiển (kể cả NUL) bị `422`** (từ E4; trước đây NUL làm driver DB ném lỗi và trả `500`); `q` rỗng vẫn là không lọc
- **Thành công:** `200` `Page[AdminUserSummary]` `{user_id, email, display_name, status, last_login_at?, created_at}`
- **Lỗi:** `403 FORBIDDEN`; `422`

### GET /admin/users/{user_id}
- **Quyền:** SA
- **Thành công:** `200` `AdminUserDetail`: các field của summary + `username?, phone?, email_verified, phone_verified, requires_password_change, updated_at, memberships[]`
- **Lỗi:** `403 FORBIDDEN`; `404 NOT_FOUND`

### PATCH /admin/users/{user_id}/status
- **Quyền:** SA
- **Body:** `UserStatusUpdateRequest` `{status: "ACTIVE" | "LOCKED" | "SUSPENDED" | "DISABLED", reason}`. `reason` là văn bản nhiều dòng 1 đến 2000 ký tự (mục 1); chứa NUL hoặc ký tự điều khiển khác thì `422`, không ghi gì, không thu hồi phiên
- **Thành công:** `200` `UserStatusUpdateResponse` `{user_id, status, revoked_session_count, updated_at}`. LOCKED, SUSPENDED và DISABLED thu hồi mọi phiên
- **Lỗi:** `403 FORBIDDEN`; `404 NOT_FOUND`; `409 STATE_CONFLICT` nếu chuyển trạng thái không hợp lệ hoặc khóa SA cuối cùng; `422`

### GET /clans/{clan_id}/users
- **Quyền:** BO của clan, hoặc FA được ủy quyền trong clan đó
- **Query:** `ClanUserListQuery` `{page, page_size, membership_status?}`
- **Thành công:** `200` `Page[ClanUserItem]` `{user_id, display_name, email, user_status, membership_status, roles[], is_family_admin, joined_at?}`
- **Lỗi:** `403 FORBIDDEN`; `404 NOT_FOUND` khi clan không nhìn thấy với người gọi (không lộ clan khác); `422`

### PUT /clans/{clan_id}/admins/{user_id}/permissions
- **Quyền:** BO của clan
- **Body:** `FamilyAdminPermissionsUpdateRequest` `{permission_codes[]}`: thay toàn bộ, tối đa 100 mã, không trùng; danh sách rỗng xóa hết quyền
- **Thành công:** `200` `FamilyAdminPermissionsResponse` `{clan_id, user_id, assignment_id, permission_codes[], updated_at}`
- **Lỗi:** `403 FORBIDDEN` nếu cấp vượt quyền được ủy quyền (hiện là mã `ADMIN_MANAGE`); `404 NOT_FOUND` nếu user không phải FA đang hiệu lực trong clan; `422`

### POST /clans/{clan_id}/admins
- **Quyền:** BO của clan (clan phải `ACTIVE`)
- **Body:** `FamilyAdminAssignRequest` `{user_id, permission_codes[]}`: `permission_codes` tối đa 100 mã, không trùng, có thể rỗng; không có `branch_id` (luôn là phạm vi toàn clan)
- **Thành công:** `201` `FamilyAdminAssignResponse` `{clan_id, user_id, assignment_id, permission_codes[], created_at}`
- **Lỗi:** `403 FORBIDDEN` nếu thiếu quyền hoặc có mã không được ủy quyền; `404 NOT_FOUND` nếu clan không nhìn thấy, hoặc user không phải thành viên `ACTIVE` của clan; `409 STATE_CONFLICT` nếu user đã là FA còn hiệu lực, hoặc là chủ họ/người còn vai trò `BUSINESS_OWNER` trong clan; `422` (mã không có trong bảng `permissions`, trường lạ, `user_id` sai định dạng)

### DELETE /clans/{clan_id}/admins/{user_id}
- **Quyền:** BO của clan (clan phải `ACTIVE`)
- **Thành công:** `204`. Thu hồi hẳn tư cách Family Admin; hiệu lực từ request tiếp theo của người đó
- **Lỗi:** `403 FORBIDDEN`; `404 NOT_FOUND` nếu clan không nhìn thấy, hoặc user không phải FA còn hiệu lực trong clan; `422` (`user_id` sai định dạng)

### Thay đổi hợp đồng ở E4 (FE phải biết; E7 đưa vào `handoff_frontend.md`)

Các thay đổi này khác với bản hợp đồng "đề xuất" trước E4. FE đã dựng màn hình theo bản cũ cần sửa:

| # | Thay đổi | Ảnh hưởng FE |
| --- | --- | --- |
| 1 | **`representative_email` bị bỏ khỏi `BusinessRegistrationSummary`** (dòng của `GET /admin/business-registrations`). Email chỉ còn ở `GET /admin/business-registrations/{id}` | Màn danh sách không được hiển thị email; muốn xem email, mở chi tiết. Có thể tìm theo email bằng `q` |
| 2 | `BusinessRegistrationSummary` thêm `requested_plan_code` | Có thể hiển thị mã gói ngay trên danh sách |
| 3 | `GET /admin/business-registrations` thêm bộ lọc `q`, `created_from`, `created_to` (và sắp xếp cố định mới nhất trước) | Ô tìm kiếm và bộ lọc ngày; mốc ngày bắt buộc có múi giờ, `created_to` không bao gồm |
| 4 | `RegistrationReviewResponse` thêm `reason_visible_to_applicant` | Hiển thị cảnh báo "người nộp sẽ thấy lý do này" khi từ chối, và "ghi chú nội bộ" khi duyệt |
| 5 | `409 STATE_CONFLICT` của `review` nêu trạng thái hiện tại của hồ sơ; duyệt `APPROVED` gặp `409` khi gói không còn `ACTIVE` | Hiển thị thông điệp từ server; tải lại hồ sơ khi gặp `409` |
| 6 | `GET /admin/users?q=` trả `422` khi `q` có ký tự điều khiển (trước đây có thể `500`) | Không đổi cách dùng bình thường |

### Thay đổi hợp đồng ở E5 (FE phải biết; E7 đưa vào `handoff_frontend.md`)

| # | Thay đổi | Ảnh hưởng FE |
| --- | --- | --- |
| 1 | `POST /admin/business-registrations/{id}/business` **bắt buộc header `Idempotency-Key`** (8 đến 128 ký tự ASCII in được, không khoảng trắng; nên dùng UUID). Thiếu hoặc sai thì `422` | FE sinh một UUID cho mỗi lần người dùng bấm "Tạo Business" và **giữ nguyên key khi gửi lại** (mất mạng, hết thời gian chờ); sinh key mới cho một lần bấm mới |
| 2 | Phát lại: cùng key + cùng yêu cầu trả lại đúng `201` đã lưu kèm header **`Idempotency-Replayed: true`** (header này được CORS cho phép đọc) | Coi `201` phát lại như thành công; có thể dùng header để biết đây là phát lại |
| 3 | **`409 DUPLICATE_RESOURCE` có hai nghĩa** ở endpoint này: hồ sơ đã có clan, hoặc `clan_code` đã tồn tại. Phân biệt bằng `message`. `409 STATE_CONFLICT` cũng có nhiều nghĩa (chưa `APPROVED`, gói không còn `ACTIVE`, đang có request khác giữ khóa kèm `Retry-After`) | Hiển thị thông điệp của server; với `409` kèm `Retry-After`, thử lại sau số giây đó với **cùng key** |
| 4 | **Lỗi không được lưu**: sau một `409` hoặc `5xx`, gửi lại cùng key sẽ được kiểm tra lại từ đầu (không nhận lại lỗi cũ) | Có thể gửi lại cùng key sau khi sửa nguyên nhân (ví dụ hồ sơ vừa được duyệt) |
| 5 | Body tùy chọn: không gửi body hoặc `{}` nghĩa là server tự sinh `clan_code` dạng `CLAN-XXXXXXXX` | Ô nhập mã clan là tùy chọn |
| 6 | `starts_at` và `ends_at` của gói đăng ký là **tạm thời** (đến khi kích hoạt clan ở E7) | Không dùng làm ngày hết hạn chính thức trước khi clan `ACTIVE` |

## 5. Chưa nằm trong hợp đồng

NEED_SUPPLEMENT và luồng nộp lại hồ sơ, cấp tài khoản Member hàng loạt, chuyển Owner, sửa gói đang dùng, tải tệp đính kèm. Các phần này cần chốt phạm vi trước khi thêm schema (mục 8 của kế hoạch).

## 6. Giả định và quyết định

### Đã chốt ở Mốc C2 (phân quyền)

| # | Quyết định |
| --- | --- |
| 1 | SA và BO xét theo role code trong `user_roles` + `roles.code`. FA xét theo `family_admin_assignments` + `family_admin_permissions`. Không đọc và không seed `role_permissions` |
| 2 | BO trong một clan cần đủ ba điều kiện: role `BUSINESS_OWNER` đang hiệu lực đúng `clan_id`, dòng `clan_ownership_history` có `ended_at IS NULL` của chính user, membership `ACTIVE` |
| 3 | SA cần role `SYSTEM_ADMIN` đang hiệu lực với `clan_id IS NULL`. Role SA gắn với một clan không được tính. SA không tự động có quyền trong clan nào |
| 4 | FA cần membership `ACTIVE`, assignment chưa thu hồi trong đúng clan có mã quyền action yêu cầu. Assignment có `branch_id` chỉ bao phủ tài nguyên đúng branch đó; assignment không có `branch_id` bao phủ cả clan. Chưa hỗ trợ kế thừa branch con vì bảng `branches` chưa được map |
| 5 | Action theo clan yêu cầu `clans.status = ACTIVE`, nếu không trả `403 FORBIDDEN`. Không áp dụng cho `/auth/*` và action của SA |
| 6 | Không có membership `ACTIVE` trong clan (kể cả clan không tồn tại) trả `404 NOT_FOUND`. Có membership nhưng thiếu quyền trả `403 FORBIDDEN`. Action chưa khai báo luôn bị từ chối |
| 7 | User `PENDING` không có cờ đổi mật khẩu trả `403 ACCOUNT_BLOCKED`. **Xem lại sau khi chốt D03** |
| 8 | `TEMPORARY_PASSWORD_EXPIRED` chỉ khi `must_change_password = true` và `temporary_password_expires_at` đã qua |
| 9 | Phiên tạo trước `credential_metadata.password_changed_at` bị coi là `401 SESSION_INVALID` |
| 10 | Khóa, tạm ngưng, disable hoặc thu hồi role SA không được để hệ thống còn 0 SA `ACTIVE`, kể cả khi SA tự khóa mình. Trả `409 STATE_CONFLICT`. Kiểm tra chạy trong cùng transaction với thao tác ghi và khóa các dòng `user_roles` SA bằng `SELECT ... FOR UPDATE` |
| 11 | Phiên hạn chế chỉ dùng được `/auth/me`, `/auth/change-password`, `/auth/logout`. Mọi route khác trả `403 PASSWORD_CHANGE_REQUIRED` |

### Đã chốt ở Mốc D (đăng nhập Firebase)

| # | Quyết định |
| --- | --- |
| 12 | Firebase quản lý mật khẩu và cách đăng nhập (Email/Password, Google, Facebook). DB không lưu mật khẩu. ID token được xác minh bằng Admin SDK: chữ ký, issuer, audience = `FIREBASE_PROJECT_ID`, hạn dùng. Không có đường giải mã không kiểm chữ ký; thiếu cấu hình thì `503` (fail closed) |
| 13 | Chỉ tài khoản đã có dòng `users` với đúng `firebase_uid` mới có phiên. UID lạ: `401 INVALID_ID_TOKEN`, không tạo user. Không dùng `email_verified` để cho phép/chặn đăng nhập (liên kết theo UID, không theo email) |
| 14 | `login_history` chỉ ghi khi đã xác định được user: thành công, hoặc UID có trong DB nhưng bị từ chối (`ACCOUNT_BLOCKED`, `TEMPORARY_PASSWORD_EXPIRED`, `ID_TOKEN_BEFORE_PASSWORD_CHANGE`). Dòng thất bại được commit trước khi trả lỗi. Token lỗi hoặc UID lạ chỉ ghi log ứng dụng (request_id, mã lý do; không token, không UID) |
| 15 | Sau lần đổi mật khẩu đầu tiên thành công, `users.status` PENDING chuyển ACTIVE. Đây là **trạng thái tài khoản người dùng**, không phải trạng thái Business/clan; quy tắc kích hoạt Business (D03) vẫn chờ lead |
| 16 | `/auth/me` `permissions[]` **tạm thời, chờ lead chốt**: SA nhận mã action cấp hệ thống của policy (ví dụ `registration.review`); BO hiệu lực nhận mã action cấp clan của policy (`clan.users.list`, `clan.fa_permissions.update`); FA nhận mã lưu trong `family_admin_permissions` (ví dụ `MEMBER_ACCOUNT_MANAGE`). Hai nguồn mã khác nhau vì `role_permissions` không được dùng (quyết định 1). Clan hoặc membership không ACTIVE: vẫn liệt kê `roles`, `permissions` rỗng |
| 17 | Hạn phiên 8 giờ (`SESSION_TTL_HOURS`), `recent_id_token` tối đa 300 giây (`RECENT_LOGIN_MAX_AGE_SECONDS`). Chưa có refresh token ứng dụng |
| 18 | Kiểm tra token bị thu hồi phía Firebase (`check_revoked`) chỉ bật khi có service account (Admin API) |
| 19 | Reset mật khẩu và rate limit `/auth/session` chưa làm (KI-05, KI-06) |

### Đã chốt ở Mốc F (quản trị người dùng, ủy quyền FA)

| # | Quyết định |
| --- | --- |
| 20 | **Bảng chuyển trạng thái (tạm thời, chờ lead):** ACTIVE → LOCKED, SUSPENDED, DISABLED; LOCKED → ACTIVE, SUSPENDED, DISABLED; SUSPENDED → ACTIVE, LOCKED, DISABLED; DISABLED → ACTIVE (mở lại); PENDING → chỉ DISABLED (PENDING lên ACTIVE nhờ đổi mật khẩu lần đầu, không bằng tay). Đích trùng trạng thái hiện tại, hoặc ngoài bảng → `409 STATE_CONFLICT`. PENDING không phải đích hợp lệ (`422`). DISABLED chưa phải trạng thái cuối |
| 21 | Chuyển sang LOCKED/SUSPENDED/DISABLED thu hồi mọi phiên của user (`revoked_session_count`) và ghi `audit_logs` (`action` = `user.status.update`; `old_data`/`new_data` chỉ có `status`, `revoked_sessions`, `request_id`; lý do nhập từ API nằm ở cột `reason`). Mở khóa chỉ đổi `status`, không đụng `failed_login_count`/`locked_until`. SA tự khóa mình hoặc khóa SA khác được, trừ khi sẽ còn 0 SA ACTIVE (quyết định 10) |
| 22 | Thứ tự khóa của PATCH status (chống deadlock): (1) tập dòng `user_roles` SYSTEM_ADMIN còn hiệu lực, `ORDER BY user_id, user_role_id`, chỉ khi đích là LOCKED/SUSPENDED/DISABLED; (2) dòng `users` đích bằng `FOR NO KEY UPDATE` (không phải `FOR UPDATE`, vì khóa ngoại `audit_logs.actor_id` cần `FOR KEY SHARE` trên dòng actor). Không đảo thứ tự |
| 23 | Khóa tài khoản chỉ chặn ở DB; không gọi Firebase. ID token Firebase còn sống tối đa 1 giờ nhưng không đổi được phiên, và phiên cũ đã bị thu hồi (KI-10) |
| 24 | `GET /admin/users`: sắp xếp `created_at` giảm dần; `q` tìm không phân biệt hoa thường trên `email` và `display_name` (ký tự `%`, `_`, `\` được escape); email giữ nguyên, không lowercase; không trả `firebase_uid` |
| 25 | `GET /clans/{id}/users`: luôn lọc theo `clan_id` của đường dẫn; `roles` chỉ là role giữ **trong clan đó**; `is_family_admin` = có assignment chưa thu hồi; mặc định liệt kê mọi trạng thái membership (kể cả REVOKED), `membership_status` thu hẹp; sắp xếp theo `display_name` |
| 26 | `PUT .../permissions`: chỉ BO; thay toàn bộ tập mã của assignment toàn clan (`branch_id` NULL) còn hiệu lực. Mã phải có trong bảng `permissions` (lạ → `422`); mã `ADMIN_MANAGE` bị `403` từ Mốc F2 (quyết định 30, KI-09). Danh sách rỗng giữ assignment. Tập không đổi → `200`, không ghi gì, không audit. Đổi tập → `audit_logs` (`action` = `family_admin.permissions.update`, `clan_id`, tập quyền trước/sau). `404` nếu user không có membership ACTIVE trong clan, không có assignment chưa thu hồi, hoặc chỉ có assignment theo chi/ngành; `409` nếu có nhiều hơn một assignment toàn clan (KI-08). Cấp FA mới và thu hồi FA hẳn: Mốc F2 (quyết định 29, 33) |
| 27 | Quyền được kiểm tra trước khi đọc body/query: người không có quyền chỉ nhận `403`/`404`, không bao giờ nhận `422` của body |

### Đã chốt ở Mốc F2 (cấp và thu hồi Family Admin)

| # | Quyết định |
| --- | --- |
| 28 | Hai action mới `clan.fa.assign` và `clan.fa.revoke`: chỉ BO, clan phải `ACTIVE` (giống `clan.fa_permissions.update`). `/auth/me` của BO liệt kê thêm hai mã này; **tạm thời, chờ lead chốt** như mọi mã trong `permissions[]` (quyết định 16) |
| 29 | `POST /clans/{id}/admins` đề bạt một thành viên `ACTIVE` của clan thành FA **toàn clan** (`branch_id` NULL), kèm tập quyền ban đầu (có thể rỗng) và một dòng `user_roles` `FAMILY_ADMIN` trong clan (để `roles[]` của `/auth/me` và danh sách thành viên khớp với assignment; quyền FA vẫn chỉ xét qua assignment, quyết định 1). Người từng bị thu hồi được đề bạt lại: tạo assignment **mới**, không bật lại dòng cũ |
| 30 | **Mã không được ủy quyền** (hằng số `NON_DELEGABLE_PERMISSION_CODES`, hiện chỉ `ADMIN_MANAGE`) → `403 FORBIDDEN`, cho cả `POST` và `PUT .../permissions`, đúng dòng "cấp vượt quyền được ủy quyền" của hợp đồng gốc; kiểm tra này chạy trước kiểm tra mã không tồn tại (`422`) và không phản hồi lại mã. **Hệ quả:** `PUT` mà tập quyền gửi lên vẫn chứa `ADMIN_MANAGE` cũng bị `403`, kể cả khi assignment cũ đã giữ mã này từ trước: muốn lưu thì phải bỏ mã đó khỏi danh sách (khi đó nó bị gỡ khỏi assignment). Danh sách cấm do lead mở rộng (KI-09) |
| 31 | Chống trùng: DB chưa có unique cho assignment còn hiệu lực (KI-08) nên code bảo đảm: mọi đề bạt xếp hàng trên dòng `clan_memberships (clan, user)` bằng `FOR NO KEY UPDATE`; request sau thấy assignment của request trước và trả `409`. Thứ tự khóa của vòng đời FA: dòng membership, rồi các dòng assignment (`FOR NO KEY UPDATE`, `ORDER BY assignment_id`), rồi `user_roles`. Không khóa dòng `users`. `uq_active_user_role_scope` là lớp bảo vệ thứ hai ở DB cho dòng vai trò. **Migration `0002` (đã áp dụng lên dev_minhquan ngày 06/10/2026, production chưa; `docs/migrations.md`)** thêm `uq_family_admin_active_assignment` cho assignment: request lọt qua khóa gặp `IntegrityError` và cũng nhận `409`, không bao giờ `500`. Khi đó nhánh `409` của `PUT .../permissions` (nhiều assignment toàn clan, quyết định 26) chỉ còn đạt được trên DB chưa migrate |
| 32 | Đích đề bạt là chủ họ hiện tại (kể cả BO tự đề bạt mình) hoặc người còn vai trò `BUSINESS_OWNER` trong clan → `409`. User không có membership `ACTIVE` trong clan (kể cả thành viên của clan khác) → `404`. Không kiểm tra trạng thái tài khoản (`users.status`) của đích: chỉ cần membership `ACTIVE` |
| 33 | `DELETE /clans/{id}/admins/{user_id}` thu hồi **mọi** assignment còn hiệu lực của user trong clan (toàn clan, theo chi/ngành hoặc trùng): đặt `revoked_at`, **xóa các dòng permission** của chúng (lịch sử mã quyền nằm trong `audit_logs.old_data`) và đặt `revoked_at` cho dòng `user_roles` `FAMILY_ADMIN` của clan. Không yêu cầu membership còn `ACTIVE`. Không phải FA → `404`. Sau đó `PUT .../permissions` trả `404` cho user đó |
| 34 | Audit: `family_admin.assign` (`new_data`: `user_id`, `permission_codes`, `role_granted`, `request_id`) và `family_admin.revoke` (`old_data`: `user_id`, `assignment_ids`, `permission_codes` trước khi thu hồi; `new_data`: số assignment và dòng vai trò đã thu hồi, `request_id`); không chứa `firebase_uid`, email hay token |

### Đã chốt ở Mốc E, bước E3 (Guest: gói, đăng ký, theo dõi)

| # | Quyết định |
| --- | --- |
| 35 | Mã theo dõi: `secrets.token_urlsafe(32)` (256 bit), chỉ lưu SHA-256 trong `tracking_code_hash`, trả đúng một lần ở `201` kèm `no-store`; không có trong log, audit, lịch sử hay phản hồi nào khác. Tra cứu không trim, không chuẩn hóa mã; mã sai nào cũng `404` cùng một thông điệp |
| 36 | Gói không tồn tại và gói không `ACTIVE` đều trả `422 VALIDATION_ERROR` với cùng thông điệp (chỉ nêu vị trí `requested_plan_id`), không phải `404`: hợp đồng đã ghi `422`, và một mã chung không cho Guest dò gói nào có thật |
| 37 | Hồ sơ trùng: một hồ sơ `PENDING` cùng `lower(email)` và `lower(tên họ)`. Kiểm tra trước trả `409 DUPLICATE_RESOURCE`; chỉ mục `uq_registration_pending_same_applicant` là lớp cuối và `IntegrityError` của nó cho cùng `409`. Hồ sơ không còn `PENDING` thì không chặn hồ sơ mới. Thông điệp `409` chung nhưng vẫn cho biết đã có hồ sơ chờ trùng người nộp (chấp nhận một mức lộ nhỏ). Đăng ký không kiểm tra email đã có tài khoản hay chưa (không lộ email nào đã đăng ký) |
| 38 | Audit của Guest: `actor_id` NULL và `clan_id` NULL (schema `audit_logs` cho phép), `action = registration.create`, `entity_type = business_registration`, `entity_id` là mã hồ sơ, `new_data` chỉ có `plan_id`, `status`, `request_id`; `ip_address` là IP kết nối. Không email, tên, điện thoại, tên họ hay mã theo dõi. Hồ sơ, `registration_status_history` (`from_status` NULL, `changed_by` NULL) và audit nằm trong một giao dịch |
| 39 | Giới hạn tần suất: cửa sổ trượt chính xác trong bộ nhớ, khóa theo IP (IPv6 gom theo /64), đăng ký 5 mỗi giờ và track 20 mỗi 10 phút (cấu hình được, bật tắt được bằng `RATE_LIMIT_ENABLED`). Đếm mọi request tới endpoint, kể cả body sai và kết quả `404`/`409`; request bị từ chối không được ghi lại nên chờ là hết. Bộ nhớ có trần (10.000 khóa, dọn khóa hết hạn, đẩy khóa ít dùng nhất khi đầy). Chỉ đếm theo từng process (KI-17). Body không phải JSON hợp lệ bị từ chối trước khi bộ giới hạn chạy nên không bị đếm |
| 40 | IP người gọi: mặc định chỉ dùng IP kết nối trực tiếp và **bỏ qua `X-Forwarded-For`** (header do người gọi tự điền). Chỉ khi `TRUST_PROXY_HEADERS=true` mới đọc header, lấy phần tử thứ `TRUSTED_PROXY_COUNT` tính từ **bên phải**; header thiếu hoặc không hợp lệ thì quay về IP kết nối. Nếu header đến trong khi cờ tắt, ghi một WARNING mỗi process (không kèm IP). Sau reverse proxy mà không bật cờ thì mọi người dùng chung một IP và bị giới hạn chung (KI-11, KI-17) |
| 41 | Văn bản: `Email` và `Str255` từ chối ký tự điều khiển (`422`) và chuẩn hóa NFC; `Str255` còn gộp khoảng trắng bên trong. Các trường lý do dùng kiểu `MultilineText` (cho phép xuống dòng và tab, cấm NUL và mọi ký tự điều khiển khác): đã chuyển từ kiểu cũ `ReasonText` (chỉ trim) ngay trong E3 vì một lý do chứa NUL làm driver DB ném lỗi và trả `500` ở `PATCH /admin/users/{id}/status`. Các kiểu bí mật (`Password`, `SecretToken`) không bao giờ bị chuẩn hóa |

### Đã chốt ở Mốc E, bước E4 (SA duyệt hồ sơ)

| # | Quyết định |
| --- | --- |
| 42 | Chỉ SA (phạm vi hệ thống) gọi được cả ba API; mọi người khác `403` trước cả bước kiểm tra path, query và body, nên người không phải SA không dò được hồ sơ có tồn tại hay không. Không giới hạn tần suất; mọi response `no-store` vì có dữ liệu cá nhân của người nộp |
| 43 | Danh sách chỉ chọn các cột nó hiển thị (không tải email, điện thoại, nơi gốc, lý do). Tìm kiếm là `ILIKE` với mẫu `%q%` đã thoát `%`, `_`, `\` (tham số ràng buộc, không bao giờ nối vào câu SQL) trên đúng ba cột `clan_name`, `representative_name`, `representative_email`. Khoảng ngày `[created_from, created_to)`. Không thêm chỉ mục: số hồ sơ còn nhỏ, tách riêng nếu sau này chậm |
| 44 | Duyệt: khóa dòng hồ sơ `FOR NO KEY UPDATE` (kèm `populate_existing`) **đầu tiên**, rồi mới kiểm tra `PENDING`; hai SA cùng lúc thì người sau chờ, đọc lại và nhận `409`. Chỉ khóa dòng hồ sơ, **không khóa `users`** (khóa ngoại của audit và `reviewed_by` cần KEY SHARE; bài học Mốc F). Hồ sơ, một dòng lịch sử và một dòng audit trong một giao dịch, commit một lần ở use case |
| 45 | `APPROVED` kiểm tra gói đã đăng ký còn `ACTIVE` (không thì `409`); `REJECTED` không kiểm tra gói. Kiểm tra trạng thái hồ sơ đi trước kiểm tra gói. E5 kiểm tra lại khi tạo Business |
| 46 | Lý do từ chối là công khai: lưu ở `business_registrations.rejection_reason` (hiển thị qua `public_reason` của track) và `registration_status_history.reason`. Ghi chú khi duyệt chỉ lưu ở lịch sử (nội bộ), `rejection_reason` để `NULL` |
| 47 | Audit của review: `action = registration.review`, `entity_type = business_registration`, `actor_id` là SA, `clan_id` NULL, `old_data = {status: PENDING}`, `new_data = {status, reason_length, request_id}`; `audit_logs.reason` luôn `NULL`. Không email, tên, điện thoại, tên họ hay nội dung lý do (độ dài thì được: quy tắc 3.5 của `security_review.md`). Log ứng dụng chỉ ghi quyết định và `request_id` |
| 48 | Thông điệp `409 STATE_CONFLICT` nêu trạng thái hiện tại của hồ sơ (chỉ SA gọi được nên không lộ thông tin cho Guest) |
| 49 | Kiểm tra `created_from` không sau `created_to` làm ở use case (trả `422` qua `AppError`), không ở model query: lỗi của model nằm trong `Depends()` không được đổi thành envelope `422`, và việc phân quyền phải chạy trước mọi validation |
| 50 | `GET /admin/users?q=` dùng `UserSearchText` (0 đến 255 ký tự như cũ, từ chối ký tự điều khiển): sửa một lỗi có sẵn khi NUL trong `q` làm driver DB ném lỗi và thành `500` |

### Đã chốt ở Mốc E, bước E5 (tạo Business và hạ tầng idempotency)

| # | Quyết định |
| --- | --- |
| 51 | Idempotency theo (người gọi, endpoint dạng mẫu `POST /admin/business-registrations/{registration_id}/business`, key), sống 7 ngày, không có tác vụ dọn (KI-21): dòng hết hạn chỉ được xét khi key được dùng lại và khi đó bị ghi đè tại chỗ. `request_hash` là SHA-256 của JSON chuẩn tắc gồm phương thức, endpoint mẫu, tham số đường dẫn (UUID chữ thường) và body đã chuẩn hóa (`exclude_none`), nên dùng lại một key cho hồ sơ khác là `409 IDEMPOTENCY_KEY_CONFLICT` |
| 52 | Hạ tầng dùng được ở hai pha cho E6: `claim_idempotency` và `complete_idempotency` là hàm công khai riêng; `run_idempotent` (một giao dịch) chỉ là lớp bọc mỏng. Dạng hai pha **chưa cài**: E6 sẽ claim và tạo job rồi **commit trước khi gọi Firebase**, sau đó mở giao dịch mới để `complete`; request cùng key đến giữa chừng nhận kết quả `IN_PROGRESS` (E6 trả `409` kèm `Retry-After` hoặc trỏ tới job). Hàng `IN_PROGRESS` bị bỏ lại khi tiến trình chết hết hạn sau 7 ngày; khôi phục là việc retry job của E6 |
| 53 | Một giao dịch (E5): hàng idempotency nằm cùng giao dịch với việc tạo, nên lỗi hay chết giữa chừng rollback cả key; không bao giờ có key kẹt. Chỉ phản hồi thành công được lưu và phát lại; phát lại không chạy lại và không kiểm tra lại trạng thái. Hai request cùng key cùng lúc: `INSERT ... ON CONFLICT DO NOTHING` **chờ** khóa duy nhất của `uq_idempotency_actor_endpoint_key` cho tới khi request trước commit (rồi phát lại) hoặc rollback (rồi tự chạy mới). Chọn chờ thay vì `409` kèm `Retry-After` vì giao dịch đầu chỉ kéo dài mili giây, client không cần tự thử lại và không có trạng thái lơ lửng. `SET LOCAL lock_timeout = '10s'`: quá hạn thì `409 STATE_CONFLICT` kèm `Retry-After: 1` (không phải `503`) |
| 54 | Thứ tự khóa cố định: hàng idempotency, hồ sơ (`FOR NO KEY UPDATE` kèm `populate_existing`), rồi clan và các bảng khác. Không bao giờ khóa dòng `users`. `review` (E4) chỉ khóa hồ sơ nên không có chu trình khóa |
| 55 | Điều kiện: chưa `APPROVED` hoặc gói không `ACTIVE` hoặc không tồn tại là `409 STATE_CONFLICT`; hồ sơ đã có clan và `clan_code` trùng là `409 DUPLICATE_RESOURCE`; hồ sơ không tồn tại là `404`. Mã tự sinh trùng thì sinh lại (tối đa 3 lần, hết thì `500`); mã do SA nhập trùng là `409`. `IntegrityError` của `clans_clan_code_key` và `clans_registration_id_key` là lớp bảo vệ cuối và cho cùng `409`; mọi `IntegrityError` khác là lỗi và thành `500` |
| 56 | Ghi: clan `PENDING` (`created_by` là SA, `name` là tên họ trong hồ sơ), `clan_profiles` (kèm `origin_place`), `clan_subscriptions` `PENDING` (`auto_renew = false`), một dòng audit. **Không ghi `registration_status_history`**: trạng thái hồ sơ không đổi; `clans.registration_id` là liên kết. Audit: `action = business.create`, `entity_type = clan`, `entity_id` và `clan_id` là clan, `new_data = {registration_id, plan_id, plan_code, subscription_id, clan_status, subscription_status, request_id}`, không email, tên, điện thoại, tên họ, mã clan; `audit_logs.reason` NULL |
| 57 | Ngày gói đăng ký tạm thời: `starts_at` lúc tạo, `ends_at` cộng `billing_period_months` tháng lịch (ngày bị cắt về cuối tháng đích, không tràn sang tháng sau). E7 đặt lại khi kích hoạt. `clan_subscriptions` không chụp giá (KI-22) |
| 58 | `Idempotency-Replayed` được thêm vào `expose_headers` của CORS cùng `X-Request-ID` và `Retry-After` |

### Thay đổi hợp đồng ở E6a (FE phải biết; E7 đưa vào `handoff_frontend.md`)

| # | Thay đổi | Ảnh hưởng FE |
| --- | --- | --- |
| 1 | `POST /admin/clans/{id}/owner` trả **`201` kèm owner và mật khẩu tạm** (trước đây hợp đồng ghi `202 ProvisioningJobAccepted`). `ProvisioningJobAccepted` không còn dùng | Màn cấp Owner hiển thị mật khẩu ngay trong response, một lần, kèm hạn dùng; không có bước chờ job |
| 2 | **Mật khẩu tạm chỉ hiện một lần.** Phát lại cùng `Idempotency-Key` trả `201` với `temporary_password: null` (và các trường owner khác `null`) | FE không được thử lại để "lấy lại" mật khẩu; mất mật khẩu thì dùng endpoint đặt lại (E6b). Không lưu mật khẩu ở localStorage hay log phía FE |
| 3 | `Idempotency-Key` **bắt buộc** (8 đến 128 ký tự, nên là UUID); giữ nguyên key khi gửi lại sau lỗi mạng | Như E5 |
| 4 | Thông tin Owner mặc định lấy từ người đại diện của hồ sơ đăng ký; body ghi đè từng trường | Màn cấp Owner điền sẵn từ hồ sơ, cho phép sửa |
| 5 | `409 STATE_CONFLICT` có nhiều nghĩa, `409 DUPLICATE_RESOURCE` cho email trùng (tài khoản hoặc Firebase); thông điệp nêu `job_id` khi có job liên quan | Hiển thị thông điệp; với job lỗi, dùng `job_id` để theo dõi và thử lại (E6b) |
| 6 | `503 PROVIDER_UNAVAILABLE` khi Firebase lỗi hoặc không cấu hình; job được ghi lại ở `FAILED_RETRYABLE` | Cho phép nút "Thử lại" ở E6b |
| 7 | `GET /admin/provisioning-jobs/{id}` thêm `needs_cleanup`; không có email hay điện thoại | Hiển thị trạng thái job, không hiển thị dữ liệu cá nhân |
| 8 | `email_delivery_status` luôn `null` cho tới khi có `EmailSender` thật | Hướng dẫn SA chuyển mật khẩu thủ công cho Owner |

### Đã chốt ở Mốc E, bước E6a (cấp Owner qua Firebase)

| # | Quyết định |
| --- | --- |
| 59 | Cấp Owner là một **job** gồm các giao dịch DB ngắn, Firebase nằm **giữa** chúng (T1 nhận yêu cầu và chèn job `PENDING`; T2 `RUNNING`; Firebase; T3 ghi `firebase_user_created`; T4 ghi các dòng và `SUCCEEDED`). Mọi giao dịch được commit **trước** khi gọi Firebase: không giữ giao dịch hay kết nối khi gọi. Mọi lời gọi `firebase_admin` chạy qua `asyncio.to_thread`, mỗi lời gọi tối đa **15 giây**; lease **90 giây**; `3 x timeout < lease` được kiểm tra khi khởi động (và bởi test) |
| 60 | Firebase uid là **`own-<job_id>`** (CHECK ở DB). Adapter chỉ thao tác theo uid: `create_user` và `delete_user` chỉ nhận `own-<uuid>` chuẩn tắc và từ chối trước khi gọi SDK; **không có** tra cứu hay xóa theo email. `email_verified=false`, không gửi điện thoại sang Firebase. User có sẵn dưới uid của job (lần chạy trước đã tạo) thì dùng lại và **đặt mật khẩu mới** (mật khẩu cũ đã mất cùng response) |
| 61 | **Fencing** chỉ theo `attempt_count` và `status = RUNNING`, **không** theo lease đã hết hạn: lượt chạy chậm nhưng chưa bị thay thế vẫn hoàn tất được; lượt bị thay thế không ghi gì và không xóa gì. Lỗi tạm thời của lượt thứ `PROVISIONING_MAX_ATTEMPTS` (5) trở thành `FAILED` |
| 62 | **Bù trừ** khi lỗi cuối cùng: commit `FAILED` + `needs_cleanup` + `firebase_user_created` **trước**, rồi `delete_user(own-<job_id>)` (cả khi không chắc user có tồn tại; "không tìm thấy" tính là xong), rồi hạ cờ. Xóa lỗi thì cờ giữ nguyên và **chặn clan và email** cho tới khi dọn xong (chỉ mục duy nhất ở DB và kiểm tra trước ở API). Lỗi tạm thời giữ user Firebase để lần thử lại dùng lại. **Ngoại lệ `UID_MISMATCH`**: `get_user(own-<job_id>)` trả một user có email KHÁC email của job: user đó không thuộc quyền phán xét của app nên **không bao giờ bị xóa** (không gọi `delete_user`); job thành `FAILED`, `error_code = UID_MISMATCH`, `needs_cleanup = false` (không chặn clan hay email), có audit (không email, tên), phản hồi `409 STATE_CONFLICT` nêu `job_id`; cần người kiểm tra tài khoản Firebase đó (KI-24) |
| 63 | **Mật khẩu tạm:** 16 ký tự từ `secrets` (có chữ hoa, chữ thường, số; trộn; bỏ I, O, l, 0, 1), `OWNER_TEMP_PASSWORD_REQUIRE_SYMBOL` (mặc định `false`) thêm ký hiệu; hạn 72 giờ (`OWNER_TEMP_PASSWORD_TTL_HOURS`). Chỉ tồn tại trong bộ nhớ và trong đúng một response. Bản response lưu trong `idempotency_keys` **không có** field mật khẩu (guard của E5 không bị nới); lớp phát lại tự thêm `temporary_password: null` |
| 64 | Firebase từ chối mật khẩu theo chính sách có mã job riêng `PASSWORD_POLICY_REJECTED` (lỗi tạm thời, lần thử lại sinh mật khẩu khác) |
| 65 | **Audit** cho mọi chuyển trạng thái của job (`provisioning_job.transition`; sự kiện `created`, `started`, `succeeded`, `failed_retryable`, `failed`, `cleanup_done`, `cleanup_failed`): chỉ id, trạng thái, `attempt_count`, mã lỗi, cờ dọn và `request_id`. Không email, tên, điện thoại, Firebase uid hay mật khẩu |
| 66 | Idempotency của endpoint 1 dùng hai pha của E5: T1 `claim` và commit (key `IN_PROGRESS`, `resource_id` là job), `complete` ở T4. Lỗi thì **giải phóng** key (không lưu lỗi). Key đang `IN_PROGRESS` mà yêu cầu giống nhau: `409` kèm `job_id` và `Retry-After: 5`, không tạo job mới. Thứ tự khóa: hàng idempotency, clan, job; không khóa `users` |
| 67 | Dòng được ghi khi thành công: `users` (`PENDING`, `first_login_required`, uid `own-<job_id>`), `credential_metadata` (`must_change_password`, `temporary_password_issued_at`, `temporary_password_expires_at`), `clan_memberships` `ACTIVE`, `user_roles` `BUSINESS_OWNER` theo clan, `clan_ownership_history`, job `SUCCEEDED`. Không có phiên nào cho Owner |
| 68 | Chặn mật khẩu tạm hết hạn tại `POST /auth/session` **đã có từ Mốc D** (`evaluate_account`, dùng chung cho đăng nhập và mọi request); E6a kiểm chứng trên Owner do job tạo |
| 69 | Action `clan.owner.temp_password.reset` được khai báo giống `business.create`: một thành viên của `Action` và một dòng trong `ACTION_RULES` (chỉ SA, phạm vi hệ thống). **Không cần seed `role_permissions`**: bảng đó vẫn rỗng, quyền của SA kiểm bằng vai trò hệ thống `SYSTEM_ADMIN`, không bằng mã quyền |

### Thay đổi hợp đồng ở E6b (FE phải biết; E7 đưa vào `handoff_frontend.md`)

| # | Thay đổi | Ảnh hưởng FE |
| --- | --- | --- |
| 1 | Bốn endpoint mới (danh sách job, `retry`, `abandon`, đặt lại mật khẩu tạm của Owner), đều chỉ SA, đều `Cache-Control: no-store` | Màn quản lý job: bảng lọc theo clan và trạng thái; nút Thử lại, Bỏ; nút "Cấp lại mật khẩu tạm" ở màn Owner |
| 2 | `retry` thành công trả `200 OwnerProvisionResponse` với **mật khẩu mới, hiện một lần**; `reset` trả `200 OwnerPasswordResetResponse` cũng một lần | Cùng cách hiển thị một lần như `201` của E6a; không lưu, không log phía FE |
| 3 | `retry` một job chỉ còn nợ dọn Firebase trả `200` với `status: "FAILED"` và mọi trường sau `clan_id` là `null` | Không hiện hộp mật khẩu; tải lại job để thấy `needs_cleanup = false` |
| 4 | `409 STATE_CONFLICT` nêu **trạng thái hiện tại** của job và có thể kèm `Retry-After` (job đang chạy) | Hiển thị thông điệp; với `Retry-After`, tự bật nút lại sau số giây đó |
| 5 | Job có `error_code = ABANDONED` là job đã bị bỏ; `UID_MISMATCH` và job đã hết 5 lần là `FAILED` và không retry được | Chỉ hiện nút Thử lại cho `FAILED_RETRYABLE`, `PENDING` kẹt, `RUNNING` quá lease, và `FAILED` có `needs_cleanup`; nút Bỏ cho `FAILED_RETRYABLE`, `PENDING` kẹt, `RUNNING` quá lease |
| 6 | Đặt lại mật khẩu chỉ cho Owner còn `PENDING`; Owner `ACTIVE`/`LOCKED`/`DISABLED` nhận `409` | Ẩn nút khi Owner đã đăng nhập đổi mật khẩu |
| 7 | Không có `Idempotency-Key` ở các endpoint E6b: mất response của `retry` hay `reset` thì gọi `reset` để lấy mật khẩu mới | Không tự thử lại `retry` khi mất response; kiểm tra job rồi dùng `reset` |

### Đã chốt ở Mốc E, bước E6b (retry, bỏ job, danh sách, đặt lại mật khẩu tạm)

| # | Quyết định |
| --- | --- |
| 70 | **`set_owner_password(uid, mật khẩu)`** là lời gọi mật khẩu **duy nhất** của các luồng Owner (lần chạy đầu, retry, reset). Như `create_user`/`delete_user` nó chỉ nhận `own-<uuid>` chuẩn tắc và từ chối **trước khi** dựng ứng dụng SDK; chạy trong thread, timeout 15 giây mỗi lời gọi, rồi thu hồi refresh token. `set_password` chung (đổi mật khẩu, mọi uid đã liên kết) vẫn tồn tại nhưng test quét mã nguồn bảo đảm các luồng Owner và router không gọi nó, và chỉ `auth_access/use_cases.py` gọi nó. User không tồn tại là `ProviderUserNotFound` (không đổi gì) |
| 71 | Khóa của retry: clan rồi job (cùng thứ tự với T4; retry không cần khóa hàng key vì không ghi nó trước khi chạy). Abandon: hàng key rồi job. Hàng key được tìm **theo job** (`resource_type`, `resource_id`), không theo chuỗi key, nên retry hay abandon của SA khác giải quyết đúng key gốc; T4 và ghi lỗi đều dùng cách tìm này |
| 72 | Retry dùng cùng các bước T2 đến T4 và cùng cơ chế fencing, bù trừ, giải phóng key như lần đầu (`_execute` dùng chung); người thực hiện (audit, `granted_by` của vai trò Owner) là SA gọi retry. Sự kiện audit mới: `retried` (từ trạng thái nào sang `RUNNING`) và `abandoned`. Job `FAILED_RETRYABLE` ở lần thử thứ 5 không còn retry (đã thành `FAILED` ở lần lỗi đó); `RUNNING` quá lease ở lần thứ 5 bị từ chối retry và chỉ `abandon` được |
| 73 | `abandon` dùng trạng thái cuối `FAILED` + `error_code = ABANDONED`. Không áp dụng cho `RUNNING` còn lease (một lượt có thể đang ghi). Nếu lượt cũ quá lease vẫn còn sống và tạo user Firebase **sau** khi abandon đã xóa, user `own-<job_id>` mồ côi nằm lại, không cờ nào (KI-28) |
| 74 | Đặt lại mật khẩu: giao dịch kiểm tra được **kết thúc trước** lời gọi Firebase; sau Firebase mở giao dịch mới, khóa clan rồi `credential_metadata` (`FOR NO KEY UPDATE`, không bao giờ khóa `users`), đọc lại `users` không khóa (trạng thái được commit cùng giao dịch với dòng credential nên nhất quán). Ngoài việc kiểm tra lại trạng thái, so sánh `(temporary_password_issued_at, updated_at)` với giá trị đã thấy lúc kiểm tra: nếu khác thì `409` không ghi (hai reset đồng thời: một bên thắng, bên kia `409`). Cách này không giải được mọi thứ tự (mật khẩu Firebase cuối cùng thuộc lời gọi Firebase kết thúc sau cùng, có thể không phải bên thắng ở DB): ghi ở KI-25 |
| 75 | Reset thu hồi **mọi** phiên của Owner (`revoke_reason = TEMPORARY_PASSWORD_RESET`) và đặt lại `temporary_password_issued_at`/`expires_at` (72 giờ) và `must_change_password = true`. Không đụng `password_changed_at` (chỉ Owner tự đổi mới đặt). `POST /auth/session` sau reset: mật khẩu mới dùng được, hết hạn thì lại bị `TEMPORARY_PASSWORD_EXPIRED` |
| 76 | Danh sách job: lọc `clan_id`, `status`, `page_size <= 100`, mới nhất trước; dùng `Page[ProvisioningJobResponse]` nên không thể có email, điện thoại, tên hay uid |
| 77 | Action: retry và abandon dùng `clan.owner.provision`, danh sách dùng `provisioning_job.read`, reset dùng `clan.owner.temp_password.reset`. Không action mới, không seed `role_permissions` |

### Chưa chốt (giả định từ Mốc C1)

- `GET /auth/me`: `permissions` ở ngoài cùng là quyền cấp hệ thống; quyền theo clan nằm trong `memberships[]`.
- Mã theo dõi hồ sơ sai trả `404`; gói không hợp lệ khi đăng ký trả `422`.
- Mọi field khi cấp Owner là tùy chọn, mặc định lấy người đại diện trên hồ sơ.
- API xem provisioning job cần migration bảng job trước khi cài.
