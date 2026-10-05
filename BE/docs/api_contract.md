# Hợp đồng API Sprint 1 — MFGMS AI

Trạng thái: **đề xuất**. Schema Pydantic đã có trong `app/schemas/`, nhưng chưa có endpoint nào được cài trong `main`. Tài liệu này là căn cứ để FE nối màn hình và để BE viết controller ở Mốc D, E, F. Nguồn: mục 6, 7, 8, 9 của `BE_Sprint1_Coding_Plan.md.md`.

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
- **Lỗi:** `401 INVALID_ID_TOKEN`; `403 ACCOUNT_BLOCKED`, `403 TEMPORARY_PASSWORD_EXPIRED`; `422`; `429`; `503 PROVIDER_UNAVAILABLE`

### GET /auth/me
- **Quyền:** phiên hợp lệ, kể cả phiên hạn chế
- **Thành công:** `200` `MeResponse` `{user_id, display_name, status, memberships[], permissions[], requires_password_change}`
  - `memberships[]`: `MembershipSummary` `{clan_id, clan_name, clan_status, membership_status, roles[], permissions[]}`; quyền trong từng clan
  - `permissions[]` cấp hệ thống: quyền từ role có `clan_id = NULL`
- **Lỗi:** chỉ các lỗi chung của API cần đăng nhập

### POST /auth/logout
- **Quyền:** phiên hiện tại, kể cả phiên hạn chế
- **Body:** không có
- **Thành công:** `204`. Thu hồi phiên hiện tại; FE xóa token và gọi `signOut` Firebase
- **Lỗi:** `401 SESSION_INVALID`

### POST /auth/password-reset/request
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
