# Hợp đồng API Sprint 1 — MFGMS AI

Trạng thái: **đề xuất**. Schema Pydantic đã có trong `app/schemas/`. Đã cài trong `main`: Mốc D `POST /auth/session`, `GET /auth/me`, `POST /auth/logout`, `POST /auth/change-password`; Mốc F `GET /admin/users`, `GET /admin/users/{id}`, `PATCH /admin/users/{id}/status`, `GET /clans/{id}/users`, `PUT /clans/{id}/admins/{user_id}/permissions`. Các API khác chưa có endpoint. Tài liệu này là căn cứ để FE nối màn hình và để BE viết controller ở Mốc D, E, F. Nguồn: mục 6, 7, 8, 9 của `BE_Sprint1_Coding_Plan.md.md`.

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
| `PUT /clans/{clan_id}/admins/{user_id}/permissions` | Đã cài (Mốc F) | Chỉ sửa tập quyền, chưa cấp/thu hồi FA (KI-07) |
| `GET /service-plans`, `POST /business-registrations`, `POST /business-registrations/track` | Chưa cài | Mốc E |
| `GET /admin/business-registrations`, `GET /admin/business-registrations/{id}`, `POST .../review`, `POST .../business` | Chưa cài | Mốc E |
| `POST /admin/clans/{id}/owner`, `GET /admin/provisioning-jobs/{id}`, `POST /admin/clans/{id}/activate` | Chưa cài | Mốc E (job cần migration, D03) |

OpenAPI do FastAPI sinh ra (`/docs`, `/openapi.json`) khai báo mọi mã lỗi của từng endpoint đã cài bằng schema `ErrorResponse` (thay cho `HTTPValidationError` mặc định của FastAPI, vốn không phải body lỗi thật). Mã khai báo là các mã mà code có thể trả; có thể rộng hơn danh sách "Lỗi" của từng mục (ví dụ `503 DATABASE_UNAVAILABLE`, `403 TEMPORARY_PASSWORD_EXPIRED` áp dụng cho mọi API cần đăng nhập, theo mục 2).

## 1. Quy ước chung

| Mục | Quy ước |
| --- | --- |
| Prefix | `/api/v1` cho mọi API dưới đây |
| Xác thực | `Authorization: Bearer <access_token>` lấy từ `POST /auth/session`. API "Guest" không cần header này |
| Request ID | Gửi `X-Request-ID` (8–128 ký tự `A-Z a-z 0-9 . _ -`) nếu có; nếu thiếu hoặc không hợp lệ, server tự sinh UUID. Mọi response đều có header `X-Request-ID` |
| Idempotency | API có ghi "Idempotency-Key" bắt buộc gửi header `Idempotency-Key` (khuyến nghị UUID). Cùng key + cùng payload trả lại kết quả cũ; cùng key + khác payload trả `409 IDEMPOTENCY_KEY_CONFLICT`; thiếu header trả `422` |
| ID | UUID dạng chuỗi |
| Thời gian | ISO 8601 UTC có hậu tố `Z`, ví dụ `2026-10-05T08:00:00Z`. Input phải có múi giờ; datetime không múi giờ bị `422` |
| Tiền | `price`, `limit_value` là chuỗi thập phân, ví dụ `"199000.00"` |
| Email | Chỉ trim khoảng trắng hai đầu, **không** lowercase. Kiểm tra bằng regex đơn giản, tối đa 255 ký tự |
| Bí mật | `id_token`, `recent_id_token`, `oob_code`, `tracking_code`, mật khẩu: không trim, không ghi log. Mật khẩu tối thiểu 6 ký tự theo Firebase |
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
| 409 | `DUPLICATE_RESOURCE` | Vi phạm unique (clan_code, clan đã tạo cho hồ sơ...) |
| 409 | `IDEMPOTENCY_KEY_CONFLICT` | Dùng lại Idempotency-Key với payload khác |
| 422 | `VALIDATION_ERROR` | Input sai schema, thiếu header bắt buộc |
| 429 | `RATE_LIMITED` | Quá giới hạn; có thể kèm header `Retry-After` |
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
- **Quyền:** Guest
- **Query:** `page`, `page_size`
- **Thành công:** `200` `Page[ServicePlanResponse]`; mỗi gói có `features[]` (`PlanFeaturePublic` `{feature_code, enabled, limit_value}`). Chỉ gói `ACTIVE`
- **Lỗi:** `422`

### POST /business-registrations
- **Quyền:** Guest; có rate limit
- **Body:** `BusinessRegistrationCreateRequest` `{representative_name, representative_email, representative_phone?, clan_name, origin_place?, requested_plan_id}`
- **Thành công:** `201` `BusinessRegistrationCreateResponse` `{registration_id, tracking_code, status, created_at}`. `tracking_code` chỉ trả một lần, server chỉ lưu hash
- **Lỗi:** `422` (kể cả gói không tồn tại hoặc không được chọn); `429`

### POST /business-registrations/track
- **Quyền:** Guest; có rate limit
- **Body:** `BusinessRegistrationTrackRequest` `{tracking_code}`
- **Thành công:** `200` `BusinessRegistrationTrackResponse` `{clan_name, status, public_reason?, submitted_at, updated_at}`
- **Lỗi:** `404 NOT_FOUND` khi mã sai; `422`; `429`. Không có API liệt kê hồ sơ cho Guest

### GET /admin/business-registrations
- **Quyền:** SA
- **Query:** `BusinessRegistrationListQuery` `{page, page_size, status?}`
- **Thành công:** `200` `Page[BusinessRegistrationSummary]`
- **Lỗi:** `403 FORBIDDEN`; `422`

### GET /admin/business-registrations/{registration_id}
- **Quyền:** SA
- **Thành công:** `200` `BusinessRegistrationDetail` gồm thông tin hồ sơ, `clan_id?`, `status_history[]` và `attachments[]` (không có `storage_key`)
- **Lỗi:** `403 FORBIDDEN`; `404 NOT_FOUND`

### POST /admin/business-registrations/{registration_id}/review
- **Quyền:** SA
- **Body:** `RegistrationReviewRequest` `{decision: "APPROVED" | "REJECTED", reason?}`; `reason` bắt buộc khi `REJECTED`
- **Thành công:** `200` `RegistrationReviewResponse` `{registration_id, status, reviewed_by, reviewed_at}`
- **Lỗi:** `403 FORBIDDEN`; `404 NOT_FOUND`; `409 STATE_CONFLICT` nếu hồ sơ không còn `PENDING`; `422`

### POST /admin/business-registrations/{registration_id}/business
- **Quyền:** SA
- **Header:** `Idempotency-Key` bắt buộc
- **Body:** `BusinessCreateRequest` `{clan_code?}`; server tự sinh nếu bỏ trống
- **Thành công:** `201` `BusinessCreateResponse` `{clan_id, clan_code, clan_status, subscription_id, plan_id, subscription_status, starts_at, ends_at}`. Clan bắt đầu ở `PENDING`
- **Lỗi:** `403 FORBIDDEN`; `404 NOT_FOUND`; `409 STATE_CONFLICT` nếu hồ sơ chưa `APPROVED`; `409 DUPLICATE_RESOURCE` nếu hồ sơ đã có clan hoặc `clan_code` trùng; `409 IDEMPOTENCY_KEY_CONFLICT`; `422`

### POST /admin/clans/{clan_id}/owner
- **Quyền:** SA
- **Header:** `Idempotency-Key` bắt buộc
- **Body:** `OwnerProvisionRequest` `{email?, display_name?, phone?}`; mặc định lấy người đại diện trên hồ sơ
- **Thành công:** `202` `ProvisioningJobAccepted` `{job_id, status}`
- **Lỗi:** `403 FORBIDDEN`; `404 NOT_FOUND`; `409 STATE_CONFLICT` nếu clan đã có Owner hiệu lực hoặc sai trạng thái; `409 IDEMPOTENCY_KEY_CONFLICT`; `422`; `503 PROVIDER_UNAVAILABLE`

### GET /admin/provisioning-jobs/{job_id}
- **Quyền:** SA
- **Thành công:** `200` `ProvisioningJobResponse` `{job_id, job_type, clan_id, status, user_id?, email_delivery_status?, attempt_count, error_code?, created_at, updated_at}`. Không bao giờ chứa mật khẩu tạm
- **Lỗi:** `403 FORBIDDEN`; `404 NOT_FOUND`
- **Lưu ý:** DB chưa có bảng job; cần migration (mục 7 của kế hoạch)

### POST /admin/clans/{clan_id}/activate
- **Quyền:** SA; chờ chốt D03
- **Body:** không có
- **Thành công:** `200` `ClanActivateResponse` `{clan_id, status, activated_at?}`
- **Lỗi:** `403 FORBIDDEN`; `404 NOT_FOUND`; `409 STATE_CONFLICT` nếu chưa đủ điều kiện kích hoạt

### GET /admin/users
- **Quyền:** SA
- **Query:** `AdminUserListQuery` `{page, page_size, status?, q?}`
- **Thành công:** `200` `Page[AdminUserSummary]` `{user_id, email, display_name, status, last_login_at?, created_at}`
- **Lỗi:** `403 FORBIDDEN`; `422`

### GET /admin/users/{user_id}
- **Quyền:** SA
- **Thành công:** `200` `AdminUserDetail`: các field của summary + `username?, phone?, email_verified, phone_verified, requires_password_change, updated_at, memberships[]`
- **Lỗi:** `403 FORBIDDEN`; `404 NOT_FOUND`

### PATCH /admin/users/{user_id}/status
- **Quyền:** SA
- **Body:** `UserStatusUpdateRequest` `{status: "ACTIVE" | "LOCKED" | "SUSPENDED" | "DISABLED", reason}`
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
- **Lỗi:** `403 FORBIDDEN` nếu cấp vượt quyền được ủy quyền; `404 NOT_FOUND` nếu user không phải FA đang hiệu lực trong clan; `422`

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
| 26 | `PUT .../permissions`: chỉ BO; thay toàn bộ tập mã của assignment toàn clan (`branch_id` NULL) còn hiệu lực. Mã phải có trong bảng `permissions` (lạ → `422`; chưa cấm mã nào, xem KI-09). Danh sách rỗng giữ assignment. Tập không đổi → `200`, không ghi gì, không audit. Đổi tập → `audit_logs` (`action` = `family_admin.permissions.update`, `clan_id`, tập quyền trước/sau). `404` nếu user không có membership ACTIVE trong clan, không có assignment chưa thu hồi, hoặc chỉ có assignment theo chi/ngành; `409` nếu có nhiều hơn một assignment toàn clan (KI-08). Cấp FA mới và thu hồi FA hẳn chưa làm (KI-07) |
| 27 | Quyền được kiểm tra trước khi đọc body/query: người không có quyền chỉ nhận `403`/`404`, không bao giờ nhận `422` của body |

### Chưa chốt (giả định từ Mốc C1)

- `GET /auth/me`: `permissions` ở ngoài cùng là quyền cấp hệ thống; quyền theo clan nằm trong `memberships[]`.
- Mã theo dõi hồ sơ sai trả `404`; gói không hợp lệ khi đăng ký trả `422`.
- Mọi field khi cấp Owner là tùy chọn, mặc định lấy người đại diện trên hồ sơ.
- API xem provisioning job cần migration bảng job trước khi cài.
