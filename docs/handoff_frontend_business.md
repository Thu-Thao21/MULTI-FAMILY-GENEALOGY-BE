# Bàn giao cho Frontend — Business, Owner và kích hoạt (Mốc E)

> File này **bổ sung** cho [`handoff_frontend.md`](handoff_frontend.md) (đăng nhập, phiên hạn chế, quản trị người dùng, Family Admin). Số mục ở đây bắt đầu từ 1. Hợp đồng đầy đủ và các quyết định nằm ở [`api_contract.md`](api_contract.md). **Mọi ví dụ dùng dữ liệu giả**: email `@example.test`, id dạng `00000000-0000-4000-8000-…`, `<access-token>`, `<temporary-password-shown-once>`. Không có dữ liệu thật hay bí mật nào ở file này.

## 1. Tóm tắt

Từ hồ sơ đăng ký tới một dòng họ dùng được, có ba nhóm người gọi và các endpoint sau:

| Ai | Endpoint | Việc |
| --- | --- | --- |
| Guest | `GET /service-plans` | Gói dịch vụ đang bán |
| Guest | `POST /business-registrations` | Nộp hồ sơ; trả **mã tra cứu một lần** |
| Guest | `POST /business-registrations/track` | Tra cứu trạng thái bằng mã |
| SA | `GET /admin/business-registrations`, `GET /admin/business-registrations/{id}` | Danh sách (không email, điện thoại) và chi tiết hồ sơ |
| SA | `POST /admin/business-registrations/{id}/review` | Duyệt hoặc từ chối |
| SA | `POST /admin/business-registrations/{id}/business` | Tạo Business: clan và gói đều `PENDING` (**cần `Idempotency-Key`**) |
| SA | `POST /admin/clans/{id}/owner` | Cấp tài khoản Owner qua Firebase; trả **mật khẩu tạm một lần** (**cần `Idempotency-Key`**) |
| SA | `GET /admin/provisioning-jobs`, `GET /admin/provisioning-jobs/{id}` | Theo dõi việc cấp Owner |
| SA | `POST /admin/provisioning-jobs/{id}/retry`, `.../abandon` | Thử lại, hoặc bỏ một job lỗi |
| SA | `POST /admin/clans/{id}/owner/temporary-password` | Cấp lại mật khẩu tạm của Owner chưa đổi mật khẩu |
| SA | `POST /admin/clans/{id}/activate`, `GET /admin/clans/{id}` | Kích hoạt clan (xác nhận thủ công) và đọc clan |

Mọi endpoint SA chỉ cho System Admin phạm vi hệ thống (`403 FORBIDDEN` cho người khác, kể cả Owner) và trả `Cache-Control: no-store`.

## 2. Luồng tổng thể và trạng thái

| Bước | Ai | Gọi | Clan | Gói (subscription) | Owner | Ghi chú |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Guest | nộp hồ sơ | chưa có | chưa có | chưa có | Giữ mã tra cứu: không lấy lại được |
| 2 | SA | review `APPROVED` | chưa có | chưa có | chưa có | Hồ sơ `APPROVED` là kết quả cuối |
| 3 | SA | tạo Business | `PENDING` | `PENDING` (ngày **tạm thời**) | chưa có | Cần `Idempotency-Key`; có `clan_id` |
| 4 | SA | cấp Owner | `PENDING` | `PENDING` | `PENDING`, phải đổi mật khẩu | Mật khẩu tạm hiện **một lần**, hạn 72 giờ |
| 5 | Owner | đăng nhập lần đầu, đổi mật khẩu | `PENDING` | `PENDING` | `ACTIVE` | Làm được **trước hoặc sau** bước 6 |
| 6 | SA | kích hoạt | `ACTIVE` | `ACTIVE` (bắt đầu **bây giờ**) | không đổi | Là **xác nhận thủ công** của SA; không kiểm thanh toán |

Trong lúc clan còn `PENDING` Owner đăng nhập được và đổi mật khẩu được, nhưng **mọi chức năng của clan trả `403`**; `GET /auth/me` cho `clan_status: "PENDING"` và `permissions: []`. Ngay khi SA kích hoạt, **cùng phiên đó** dùng được (xem mục 8).

## 3. Thay đổi so với hợp đồng cũ (E3 đến E7)

| Thay đổi | Việc FE cần làm |
| --- | --- |
| **Danh sách hồ sơ không còn `representative_email`** (và điện thoại, nơi gốc, lý do). Chúng chỉ có ở chi tiết hồ sơ | Bỏ cột email khỏi bảng danh sách; mở chi tiết để xem |
| Response review: `{registration_id, status, reviewed_by, reviewed_at, reason_visible_to_applicant}`. `REJECTED` bắt buộc có `reason`, và **người nộp thấy lý do đó** khi tra cứu | Cảnh báo SA khi nhập lý do từ chối; ghi chú duyệt `APPROVED` thì chỉ nội bộ |
| Tạo Business và cấp Owner cần header `Idempotency-Key`; phát lại trả header `Idempotency-Replayed: true` | Mục 4 |
| Cấp Owner trả **`201`** kèm owner và mật khẩu tạm (trước đây hợp đồng ghi `202`) | Hiển thị mật khẩu ngay trong response, một lần |
| Bốn endpoint job/mật khẩu (danh sách, thử lại, bỏ, đặt lại) | Mục 7 |
| `POST /admin/clans/{id}/activate` trả `200` với thông tin gói; **không dùng `Idempotency-Key`** | Mục 9 |
| `GET /admin/clans/{id}` mới | Mục 9 |
| Guest bị giới hạn tần suất: `429 RATE_LIMITED` | Mục 10 |

## 4. `Idempotency-Key` và `Idempotency-Replayed`

- **Chỉ hai endpoint cần key:** tạo Business và cấp Owner. Thiếu hoặc sai định dạng (8 đến 128 ký tự ASCII in được, không khoảng trắng) là `422`. Dùng UUID.
- FE sinh **một key cho mỗi lần người dùng bấm nút**, và **giữ nguyên key khi gửi lại** sau lỗi mạng. Bấm lần mới thì sinh key mới.
- Gửi lại cùng key và cùng yêu cầu sau khi đã thành công: nhận lại đúng `201` đã lưu kèm header `Idempotency-Replayed: true` (header này đọc được qua CORS). Coi đó là thành công.
- **Mật khẩu không bao giờ được lưu**: phát lại của endpoint cấp Owner trả `job_id`, `status`, `clan_id`, `user_id` và **mọi trường còn lại là `null`, kể cả `temporary_password`**. Đừng dùng phát lại để "lấy lại mật khẩu"; dùng đặt lại mật khẩu (mục 7).
- Cùng key nhưng yêu cầu khác (ví dụ hồ sơ khác): `409 IDEMPOTENCY_KEY_CONFLICT`.
- Yêu cầu đầu còn đang chạy: `409 STATE_CONFLICT` kèm `Retry-After` (cấp Owner còn nêu `job_id`). Đợi theo `Retry-After` rồi gửi lại cùng key.
- **Lỗi không được lưu**: sau `409` hay `5xx`, gửi lại cùng key được kiểm tra lại từ đầu.
- Review, thử lại, bỏ, đặt lại mật khẩu và kích hoạt **không** dùng key (xem mục 5 để biết cách xử lý khi mất response).

## 5. Ý nghĩa các `409`

Thông điệp của `409` nêu điều đang sai và **trạng thái hiện tại**; FE chỉ cần hiển thị `error.message`. Mã `error.code` cho biết nhóm:

| `error.code` | Khi nào | Gợi ý xử lý |
| --- | --- | --- |
| `STATE_CONFLICT` | Trạng thái hiện tại không cho phép việc này: hồ sơ chưa `APPROVED`, clan không `PENDING`, đã có Owner, job không thử lại được, Owner không `PENDING` khi đặt lại, v.v.; hoặc có request khác đang giữ khóa quá 10 giây (kèm `Retry-After`) | Tải lại dữ liệu; nếu có `Retry-After` thì đợi rồi thử lại |
| `DUPLICATE_RESOURCE` | Hồ sơ đã có clan, `clan_code` trùng, email đã là tài khoản hoặc đã thuộc tài khoản Firebase khác | Sửa dữ liệu nhập |
| `IDEMPOTENCY_KEY_CONFLICT` | Cùng `Idempotency-Key` cho yêu cầu khác | Sinh key mới |

**Quan trọng:** với `POST /admin/clans/{id}/activate`, một `409` có thông điệp **"The clan is ACTIVE (activated at …)" nghĩa là lần gọi trước đã THÀNH CÔNG** (thường do mất response). Hiển thị như thành công và tải lại bằng `GET /admin/clans/{id}`. Tương tự, review hai lần cho cùng hồ sơ: lần hai là `409` nêu trạng thái đã duyệt.

Các mã khác hay gặp: `403 FORBIDDEN` (không phải SA), `404 NOT_FOUND`, `422 VALIDATION_ERROR` (kể cả mã không phải UUID), `429 RATE_LIMITED` (Guest), `503 PROVIDER_UNAVAILABLE` (Firebase), `503 DATABASE_UNAVAILABLE` (thử lại sau). Mọi lỗi có dạng `{"error": {"code", "message", "request_id"}}`; hiển thị `request_id` khi báo lỗi cho BE.

## 6. Cấp Owner và mật khẩu tạm

- `POST /admin/clans/{id}/owner` (cần `Idempotency-Key`; body tùy chọn `{email?, display_name?, phone?}`, mặc định lấy từ người đại diện của hồ sơ) trả **`201`** với `temporary_password`, hạn 72 giờ (`temporary_password_expires_at`).
- **Mật khẩu chỉ hiện đúng một lần**, trong response này, kèm `Cache-Control: no-store`. FE **không lưu** (localStorage, log, analytics, URL) và nên cho SA nút sao chép. Mất response thì dùng "Cấp lại mật khẩu tạm" (mục 7).
- Chưa có dịch vụ gửi email thật (KI-26): `email_delivery_status` luôn `null`. **SA tự chuyển mật khẩu cho Owner qua kênh riêng.**
- Owner sinh ra ở trạng thái `PENDING` và phải đổi mật khẩu ở lần đăng nhập đầu (mục 8). Clan **vẫn `PENDING`**.
- Nếu Firebase lỗi, response là `503` nhưng đã có một **job** ở `FAILED_RETRYABLE` (thông điệp nêu `job_id`): SA thử lại bằng nút "Thử lại" (mục 7), không cần gửi lại yêu cầu.

## 7. Job: danh sách, thử lại, bỏ, đặt lại mật khẩu

Một job là việc "tạo tài khoản Owner". Trạng thái: `PENDING`, `RUNNING`, `SUCCEEDED`, `FAILED_RETRYABLE`, `FAILED`. Job **không bao giờ** trả email, điện thoại, tên hay mật khẩu; có `needs_cleanup` và `error_code`.

| Trạng thái | Hiện nút Thử lại | Hiện nút Bỏ | Ghi chú |
| --- | --- | --- | --- |
| `FAILED_RETRYABLE` | có | có | Lỗi tạm thời (Firebase, DB) |
| `PENDING` đã quá 90 giây | có | có | Request đầu bị chết trước khi bắt đầu |
| `RUNNING` đã quá lease (90 giây) | có | có | Lượt chạy bị chết; thử lại sẽ tiếp quản |
| `RUNNING` còn lease | không (409 kèm `Retry-After`) | không | Đang chạy: chờ |
| `FAILED` với `needs_cleanup = true` | có (**chỉ dọn**, xem dưới) | không | Còn nợ xóa user Firebase; **đang chặn clan và email** |
| `FAILED` với `needs_cleanup = false` (kể cả `UID_MISMATCH`, `ABANDONED`, hết 5 lần) | không | không | Kết quả cuối; tạo job mới bằng cách cấp Owner lại |
| `SUCCEEDED` | không | không | Xong |

- **Thử lại** `POST /admin/provisioning-jobs/{id}/retry` (không body, không key): thành công trả `200` cùng dạng response cấp Owner, với **mật khẩu MỚI hiện một lần**. Không tự thử lại khi mất response: kiểm tra job rồi dùng "Cấp lại mật khẩu tạm".
- **Thử lại job chỉ-dọn:** job `FAILED` còn `needs_cleanup` chỉ cần xóa user Firebase. Response là `200` với `status: "FAILED"` và **mọi field Owner là `null`** (`user_id`, `owner_email`, `owner_display_name`, `temporary_password`, …): **không có mật khẩu, đừng hiện hộp mật khẩu**. Tải lại job để thấy `needs_cleanup = false`. Dọn không xác nhận được thì `503`; thử lại sau.
- **Bỏ** `POST /admin/provisioning-jobs/{id}/abandon`: job thành `FAILED` với `error_code: "ABANDONED"`, và user Firebase của job bị xóa. Nếu xóa lỗi thì `needs_cleanup` vẫn `true` (xem hàng `FAILED` ở bảng trên); response vẫn là `200`.
- **Cấp lại mật khẩu tạm** `POST /admin/clans/{id}/owner/temporary-password` (không body, không key): chỉ khi Owner còn `PENDING` (chưa đổi mật khẩu). Trả `200` với mật khẩu mới hiện một lần, hạn 72 giờ, và **thu hồi mọi phiên** của Owner. Owner đã `ACTIVE`, `LOCKED`, `DISABLED` thì `409` (nêu trạng thái).
- Danh sách: `GET /admin/provisioning-jobs?clan_id=&status=&page=&page_size=` (`page_size` tối đa 100, mới nhất trước).

## 8. Owner đăng nhập lần đầu bằng mật khẩu tạm

Hướng dẫn chi tiết về phiên hạn chế ở [`handoff_frontend.md`](handoff_frontend.md) mục 3. Tóm tắt cho luồng Business:

1. Owner đăng nhập Firebase bằng email và mật khẩu tạm, rồi `POST /auth/session`: nhận `requires_password_change: true` và một **phiên hạn chế** (chỉ gọi được `/auth/me`, `/auth/change-password`, `/auth/logout`; chức năng khác `403`).
2. Mật khẩu tạm quá 72 giờ: `POST /auth/session` trả `403 TEMPORARY_PASSWORD_EXPIRED`. Báo Owner liên hệ SA để cấp lại (mục 7).
3. Owner gọi `POST /auth/change-password` (kèm ID token mới đăng nhập): `204`, tài khoản thành `ACTIVE`, **mọi phiên bị thu hồi**. Owner phải đăng nhập lại.
4. Phiên mới là phiên đầy đủ. Nếu clan còn `PENDING`, `GET /auth/me` cho `clan_status: "PENDING"` và `permissions: []`; hãy hiện màn "Dòng họ đang chờ kích hoạt" (không phải lỗi). Chức năng của clan trả `403`.
5. Ngay khi SA kích hoạt, **cùng phiên** gọi `GET /auth/me` sẽ thấy `clan_status: "ACTIVE"` và có `permissions`; không cần đăng nhập lại.

Thứ tự "SA kích hoạt" và "Owner đăng nhập lần đầu" có thể đổi chỗ cho nhau: cả hai đều hợp lệ.

## 9. Kích hoạt clan và đọc clan

- `POST /admin/clans/{id}/activate`: không body, không `Idempotency-Key`. Là **xác nhận thủ công của SA**; hệ thống không kiểm thanh toán (thanh toán là Sprint 6). Thành công `200`: clan `ACTIVE`, gói `ACTIVE` với `starts_at` là **lúc kích hoạt** và `ends_at` sau đúng số tháng lịch của gói. Ngày gói ở bước tạo Business chỉ là tạm thời; đừng hiển thị là ngày hết hạn chính thức.
- Điều kiện (mỗi cái sai là `409` nêu lý do): clan đang `PENDING`; có Owner đang là thành viên hoạt động của clan; tài khoản Owner không bị khóa/vô hiệu (Owner **chưa cần** đổi mật khẩu); đúng một gói `PENDING`; gói vẫn đang bán. Gói đã ngừng bán thì **cần người vận hành xử lý** (KI-32), SA không tự gỡ qua giao diện được.
- **Mất response?** Gọi lại sẽ nhận `409` "đã ACTIVE": đó là thành công. Tải lại bằng `GET /admin/clans/{id}`.
- `GET /admin/clans/{id}`: `{clan_id, clan_code, status, registration_id, created_at, activated_at, subscription, owner_user_id, last_owner_job}`. Chỉ có id, mã, trạng thái và ngày; **không có email, tên, điện thoại** (tên họ có ở chi tiết hồ sơ qua `registration_id`). Chưa có danh sách clan (KI-31): lấy `clan_id` từ chi tiết hồ sơ sau khi tạo Business.

## 10. Giới hạn tần suất của Guest

- Nộp hồ sơ: tối đa **5 lần mỗi giờ** cho mỗi địa chỉ IP; tra cứu: tối đa **20 lần mỗi 10 phút**. Vượt quá: `429 RATE_LIMITED` kèm header `Retry-After` (giây).
- Khi nhận `429`, khóa nút gửi và hiện đếm ngược theo `Retry-After`; không tự gửi lại.
- Bộ đếm nằm trong bộ nhớ từng máy chủ (KI-17): khởi động lại máy chủ thì đếm lại. Nhiều người dùng chung một IP (ví dụ mạng văn phòng) dùng chung hạn mức; với buổi demo, báo BE nới ngưỡng.
- Endpoint của SA và Owner **không** bị giới hạn này.

## 11. Ví dụ request và response

Giá trị trong ví dụ là giả. `Authorization: Bearer <access-token>` nghĩa là token phiên của người gọi; `Idempotency-Key: <uuid-N>` nghĩa là một UUID do FE sinh.

### A. Guest

#### 11.1 Danh sách gói dịch vụ (Guest)

```http
GET /api/v1/service-plans
```

```http
HTTP 200

{
  "items": [
    {
      "plan_id": "00000000-0000-4000-8000-000000000001",
      "code": "STANDARD",
      "name": "Standard",
      "description": null,
      "price": "199000.00",
      "billing_period_months": 12,
      "max_members": 200,
      "max_family_admins": 5,
      "storage_mb": 2048,
      "features": [
        {
          "feature_code": "DATA_EXPORT",
          "enabled": true,
          "limit_value": null
        },
        {
          "feature_code": "MAX_PERSONS",
          "enabled": true,
          "limit_value": "5000"
        }
      ]
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

#### 11.2 Nộp hồ sơ đăng ký (Guest): mã tra cứu chỉ hiện một lần

```http
POST /api/v1/business-registrations
Content-Type: application/json

{
  "representative_name": "Nguyen Van A",
  "representative_email": "nguyen.van.a@example.test",
  "representative_phone": "+84 900 000 001",
  "clan_name": "Ho Nguyen Mau",
  "origin_place": "Que Mau",
  "requested_plan_id": "<plan-id>"
}
```

```http
HTTP 201
cache-control: no-store

{
  "registration_id": "00000000-0000-4000-8000-000000000002",
  "tracking_code": "<tracking-code-shown-once>",
  "status": "PENDING",
  "created_at": "2026-10-08T09:00:00Z"
}
```

#### 11.3 Tra cứu trạng thái hồ sơ (Guest)

```http
POST /api/v1/business-registrations/track
Content-Type: application/json

{
  "tracking_code": "<tracking-code-shown-once>"
}
```

```http
HTTP 200
cache-control: no-store

{
  "clan_name": "Ho Nguyen Mau",
  "status": "PENDING",
  "public_reason": null,
  "submitted_at": "2026-10-08T09:00:00Z",
  "updated_at": "2026-10-08T09:00:00Z"
}
```

#### 11.4 Guest: nộp hồ sơ quá nhiều lần từ một địa chỉ (429, Retry-After tính bằng giây)

```http
POST /api/v1/business-registrations
Content-Type: application/json

{
  "representative_name": "Nguyen Van A",
  "representative_email": "nguyen.van.a@example.test",
  "representative_phone": "+84 900 000 001",
  "clan_name": "Ho Thu 4",
  "origin_place": "Que Mau",
  "requested_plan_id": "<plan-id>"
}
```

```http
HTTP 429
retry-after: 3600

{
  "error": {
    "code": "RATE_LIMITED",
    "message": "Too many requests. Try again later.",
    "request_id": "00000000-0000-4000-8000-000000000021"
  }
}
```

### B. System Admin: hồ sơ, Business, Owner

#### 11.5 SA: danh sách hồ sơ (không còn email, điện thoại)

```http
GET /api/v1/admin/business-registrations?status=PENDING&page_size=20
Authorization: Bearer <access-token>
```

```http
HTTP 200
cache-control: no-store

{
  "items": [
    {
      "registration_id": "00000000-0000-4000-8000-000000000002",
      "clan_name": "Ho Nguyen Mau",
      "representative_name": "Nguyen Van A",
      "requested_plan_id": "00000000-0000-4000-8000-000000000001",
      "requested_plan_code": "STANDARD",
      "status": "PENDING",
      "created_at": "2026-10-08T09:00:00Z",
      "reviewed_at": null
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

#### 11.6 SA: duyệt hồ sơ

```http
POST /api/v1/admin/business-registrations/00000000-0000-4000-8000-000000000002/review
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "decision": "APPROVED",
  "reason": "Giay to hop le."
}
```

```http
HTTP 200
cache-control: no-store

{
  "registration_id": "00000000-0000-4000-8000-000000000002",
  "status": "APPROVED",
  "reviewed_by": "00000000-0000-4000-8000-000000000003",
  "reviewed_at": "2026-10-08T09:00:00Z",
  "reason_visible_to_applicant": false
}
```

#### 11.7 SA: tạo Business (clan và gói ở trạng thái PENDING)

```http
POST /api/v1/admin/business-registrations/00000000-0000-4000-8000-000000000002/business
Authorization: Bearer <access-token>
Idempotency-Key: <uuid-1>
```

```http
HTTP 201
cache-control: no-store

{
  "clan_id": "00000000-0000-4000-8000-000000000004",
  "clan_code": "CLAN-U2TP9JB8",
  "clan_status": "PENDING",
  "subscription_id": "00000000-0000-4000-8000-000000000005",
  "plan_id": "00000000-0000-4000-8000-000000000001",
  "subscription_status": "PENDING",
  "starts_at": "2026-10-08T09:00:00Z",
  "ends_at": "2027-10-08T09:00:00Z"
}
```

#### 11.8 SA: gửi lại cùng Idempotency-Key (phát lại, cùng 201)

```http
POST /api/v1/admin/business-registrations/00000000-0000-4000-8000-000000000002/business
Authorization: Bearer <access-token>
Idempotency-Key: <uuid-1>
```

```http
HTTP 201
cache-control: no-store
idempotency-replayed: true

{
  "clan_id": "00000000-0000-4000-8000-000000000004",
  "clan_code": "CLAN-U2TP9JB8",
  "clan_status": "PENDING",
  "subscription_id": "00000000-0000-4000-8000-000000000005",
  "plan_id": "00000000-0000-4000-8000-000000000001",
  "subscription_status": "PENDING",
  "starts_at": "2026-10-08T09:00:00Z",
  "ends_at": "2027-10-08T09:00:00Z"
}
```

#### 11.9 SA: cùng Idempotency-Key nhưng cho hồ sơ khác (409 IDEMPOTENCY_KEY_CONFLICT)

```http
POST /api/v1/admin/business-registrations/00000000-0000-4000-8000-000000000006/business
Authorization: Bearer <access-token>
Idempotency-Key: <uuid-1>
```

```http
HTTP 409

{
  "error": {
    "code": "IDEMPOTENCY_KEY_CONFLICT",
    "message": "Idempotency-Key was reused with a different payload.",
    "request_id": "00000000-0000-4000-8000-000000000007"
  }
}
```

#### 11.10 SA: đọc clan vừa tạo (PENDING, chưa có Owner)

```http
GET /api/v1/admin/clans/00000000-0000-4000-8000-000000000004
Authorization: Bearer <access-token>
```

```http
HTTP 200
cache-control: no-store

{
  "clan_id": "00000000-0000-4000-8000-000000000004",
  "clan_code": "CLAN-U2TP9JB8",
  "status": "PENDING",
  "registration_id": "00000000-0000-4000-8000-000000000002",
  "created_at": "2026-10-08T09:00:00Z",
  "activated_at": null,
  "subscription": {
    "subscription_id": "00000000-0000-4000-8000-000000000005",
    "plan_id": "00000000-0000-4000-8000-000000000001",
    "plan_code": "STANDARD",
    "status": "PENDING",
    "starts_at": "2026-10-08T09:00:00Z",
    "ends_at": "2027-10-08T09:00:00Z"
  },
  "owner_user_id": null,
  "last_owner_job": null
}
```

#### 11.11 SA: cấp Owner (201, mật khẩu tạm hiện đúng một lần, no-store)

```http
POST /api/v1/admin/clans/00000000-0000-4000-8000-000000000004/owner
Authorization: Bearer <access-token>
Idempotency-Key: <uuid-2>
```

```http
HTTP 201
cache-control: no-store

{
  "job_id": "00000000-0000-4000-8000-000000000008",
  "status": "SUCCEEDED",
  "clan_id": "00000000-0000-4000-8000-000000000004",
  "user_id": "00000000-0000-4000-8000-000000000009",
  "owner_email": "nguyen.van.a@example.test",
  "owner_display_name": "Nguyen Van A",
  "temporary_password": "<temporary-password-shown-once>",
  "temporary_password_expires_at": "2026-10-11T09:00:00Z",
  "email_delivery_status": null
}
```

#### 11.12 SA: phát lại cùng Idempotency-Key (mật khẩu là null)

```http
POST /api/v1/admin/clans/00000000-0000-4000-8000-000000000004/owner
Authorization: Bearer <access-token>
Idempotency-Key: <uuid-2>
```

```http
HTTP 201
cache-control: no-store
idempotency-replayed: true

{
  "job_id": "00000000-0000-4000-8000-000000000008",
  "status": "SUCCEEDED",
  "clan_id": "00000000-0000-4000-8000-000000000004",
  "user_id": "00000000-0000-4000-8000-000000000009",
  "owner_email": null,
  "owner_display_name": null,
  "temporary_password": null,
  "temporary_password_expires_at": null,
  "email_delivery_status": null
}
```

#### 11.13 SA: cấp Owner lần nữa với key mới (409, đã có Owner)

```http
POST /api/v1/admin/clans/00000000-0000-4000-8000-000000000004/owner
Authorization: Bearer <access-token>
Idempotency-Key: <uuid-3>
```

```http
HTTP 409

{
  "error": {
    "code": "STATE_CONFLICT",
    "message": "This clan already has an Owner.",
    "request_id": "00000000-0000-4000-8000-000000000010"
  }
}
```

#### 11.14 SA: đọc một job (không có email, điện thoại, tên)

```http
GET /api/v1/admin/provisioning-jobs/00000000-0000-4000-8000-000000000008
Authorization: Bearer <access-token>
```

```http
HTTP 200
cache-control: no-store

{
  "job_id": "00000000-0000-4000-8000-000000000008",
  "job_type": "OWNER_PROVISIONING",
  "clan_id": "00000000-0000-4000-8000-000000000004",
  "status": "SUCCEEDED",
  "user_id": "00000000-0000-4000-8000-000000000009",
  "email_delivery_status": null,
  "attempt_count": 1,
  "needs_cleanup": false,
  "error_code": null,
  "created_at": "2026-10-08T09:00:00Z",
  "updated_at": "2026-10-08T09:00:00Z"
}
```

#### 11.15 SA: cấp lại mật khẩu tạm cho Owner (hiện một lần, thu hồi mọi phiên cũ)

```http
POST /api/v1/admin/clans/00000000-0000-4000-8000-000000000004/owner/temporary-password
Authorization: Bearer <access-token>
```

```http
HTTP 200
cache-control: no-store

{
  "clan_id": "00000000-0000-4000-8000-000000000004",
  "user_id": "00000000-0000-4000-8000-000000000009",
  "owner_email": "nguyen.van.a@example.test",
  "owner_display_name": "Nguyen Van A",
  "temporary_password": "<new-temporary-password-shown-once>",
  "temporary_password_expires_at": "2026-10-11T09:00:00Z",
  "email_delivery_status": null
}
```

### C. Owner trước và sau khi kích hoạt

#### 11.16 Owner đã đổi mật khẩu nhưng clan còn PENDING: GET /auth/me (chỉ phần memberships)

```http
GET /api/v1/auth/me
Authorization: Bearer <access-token>
```

```http
HTTP 200

{
  "memberships": [
    {
      "clan_id": "00000000-0000-4000-8000-000000000004",
      "clan_name": "Ho Nguyen Mau",
      "clan_status": "PENDING",
      "membership_status": "ACTIVE",
      "roles": [
        "BUSINESS_OWNER"
      ],
      "permissions": []
    }
  ]
}
```

#### 11.17 Owner gọi một chức năng của clan khi clan còn PENDING (403)

```http
GET /api/v1/clans/00000000-0000-4000-8000-000000000004/users
Authorization: Bearer <access-token>
```

```http
HTTP 403

{
  "error": {
    "code": "FORBIDDEN",
    "message": "You do not have permission to perform this action.",
    "request_id": "00000000-0000-4000-8000-000000000011"
  }
}
```

#### 11.18 SA: kích hoạt clan (xác nhận thủ công; gói bắt đầu tính từ lúc này)

```http
POST /api/v1/admin/clans/00000000-0000-4000-8000-000000000004/activate
Authorization: Bearer <access-token>
```

```http
HTTP 200
cache-control: no-store

{
  "clan_id": "00000000-0000-4000-8000-000000000004",
  "status": "ACTIVE",
  "activated_at": "2026-10-08T09:00:00Z",
  "subscription_id": "00000000-0000-4000-8000-000000000005",
  "subscription_status": "ACTIVE",
  "starts_at": "2026-10-08T09:00:00Z",
  "ends_at": "2027-10-08T09:00:00Z"
}
```

#### 11.19 SA: gọi lại sau khi mất response: 409 "đã ACTIVE" nghĩa là lần đầu đã thành công

```http
POST /api/v1/admin/clans/00000000-0000-4000-8000-000000000004/activate
Authorization: Bearer <access-token>
```

```http
HTTP 409

{
  "error": {
    "code": "STATE_CONFLICT",
    "message": "The clan is ACTIVE (activated at 2026-10-08T09:00:00Z); only a PENDING clan can be activated.",
    "request_id": "00000000-0000-4000-8000-000000000012"
  }
}
```

#### 11.20 SA: đọc clan sau khi kích hoạt

```http
GET /api/v1/admin/clans/00000000-0000-4000-8000-000000000004
Authorization: Bearer <access-token>
```

```http
HTTP 200
cache-control: no-store

{
  "clan_id": "00000000-0000-4000-8000-000000000004",
  "clan_code": "CLAN-U2TP9JB8",
  "status": "ACTIVE",
  "registration_id": "00000000-0000-4000-8000-000000000002",
  "created_at": "2026-10-08T09:00:00Z",
  "activated_at": "2026-10-08T09:00:00Z",
  "subscription": {
    "subscription_id": "00000000-0000-4000-8000-000000000005",
    "plan_id": "00000000-0000-4000-8000-000000000001",
    "plan_code": "STANDARD",
    "status": "ACTIVE",
    "starts_at": "2026-10-08T09:00:00Z",
    "ends_at": "2027-10-08T09:00:00Z"
  },
  "owner_user_id": "00000000-0000-4000-8000-000000000009",
  "last_owner_job": {
    "job_id": "00000000-0000-4000-8000-000000000008",
    "status": "SUCCEEDED",
    "needs_cleanup": false
  }
}
```

#### 11.21 Sau khi SA kích hoạt: cùng phiên của Owner, GET /auth/me (chỉ phần memberships)

```http
GET /api/v1/auth/me
Authorization: Bearer <access-token>
```

```http
HTTP 200

{
  "memberships": [
    {
      "clan_id": "00000000-0000-4000-8000-000000000004",
      "clan_name": "Ho Nguyen Mau",
      "clan_status": "ACTIVE",
      "membership_status": "ACTIVE",
      "roles": [
        "BUSINESS_OWNER"
      ],
      "permissions": [
        "clan.fa.assign",
        "clan.fa.revoke",
        "clan.fa_permissions.update",
        "clan.users.list"
      ]
    }
  ]
}
```

### D. Job lỗi: danh sách, thử lại, bỏ, dọn

#### 11.22 SA: cấp Owner khi Firebase lỗi (503; job ở FAILED_RETRYABLE, thử lại được)

```http
POST /api/v1/admin/clans/00000000-0000-4000-8000-000000000013/owner
Authorization: Bearer <access-token>
Idempotency-Key: <uuid-4>
```

```http
HTTP 503

{
  "error": {
    "code": "PROVIDER_UNAVAILABLE",
    "message": "The identity provider is unavailable; job 00000000-0000-4000-8000-000000000014 can be retried.",
    "request_id": "00000000-0000-4000-8000-000000000015"
  }
}
```

#### 11.23 SA: danh sách job của một clan (lọc theo clan, trạng thái)

```http
GET /api/v1/admin/provisioning-jobs?clan_id=00000000-0000-4000-8000-000000000013&status=FAILED_RETRYABLE
Authorization: Bearer <access-token>
```

```http
HTTP 200
cache-control: no-store

{
  "items": [
    {
      "job_id": "00000000-0000-4000-8000-000000000014",
      "job_type": "OWNER_PROVISIONING",
      "clan_id": "00000000-0000-4000-8000-000000000013",
      "status": "FAILED_RETRYABLE",
      "user_id": null,
      "email_delivery_status": null,
      "attempt_count": 1,
      "needs_cleanup": false,
      "error_code": "PROVIDER_UNAVAILABLE",
      "created_at": "2026-10-08T09:00:00Z",
      "updated_at": "2026-10-08T09:00:00Z"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

#### 11.24 SA: thử lại job (200, mật khẩu MỚI hiện một lần)

```http
POST /api/v1/admin/provisioning-jobs/00000000-0000-4000-8000-000000000014/retry
Authorization: Bearer <access-token>
```

```http
HTTP 200
cache-control: no-store

{
  "job_id": "00000000-0000-4000-8000-000000000014",
  "status": "SUCCEEDED",
  "clan_id": "00000000-0000-4000-8000-000000000013",
  "user_id": "00000000-0000-4000-8000-000000000016",
  "owner_email": "tran.thi.b@example.test",
  "owner_display_name": "Tran Thi B",
  "temporary_password": "<temporary-password-shown-once-by-retry>",
  "temporary_password_expires_at": "2026-10-11T09:00:00Z",
  "email_delivery_status": null
}
```

#### 11.25 SA: bỏ job (FAILED, error_code ABANDONED; đã dọn user Firebase)

```http
POST /api/v1/admin/provisioning-jobs/00000000-0000-4000-8000-000000000017/abandon
Authorization: Bearer <access-token>
```

```http
HTTP 200
cache-control: no-store

{
  "job_id": "00000000-0000-4000-8000-000000000017",
  "job_type": "OWNER_PROVISIONING",
  "clan_id": "00000000-0000-4000-8000-000000000018",
  "status": "FAILED",
  "user_id": null,
  "email_delivery_status": null,
  "attempt_count": 1,
  "needs_cleanup": false,
  "error_code": "ABANDONED",
  "created_at": "2026-10-08T09:00:00Z",
  "updated_at": "2026-10-08T09:00:00Z"
}
```

#### 11.26 SA: một job FAILED còn nợ dọn Firebase (needs_cleanup = true chặn clan và email)

```http
GET /api/v1/admin/provisioning-jobs/00000000-0000-4000-8000-000000000019
Authorization: Bearer <access-token>
```

```http
HTTP 200
cache-control: no-store

{
  "job_id": "00000000-0000-4000-8000-000000000019",
  "job_type": "OWNER_PROVISIONING",
  "clan_id": "00000000-0000-4000-8000-000000000020",
  "status": "FAILED",
  "user_id": null,
  "email_delivery_status": null,
  "attempt_count": 1,
  "needs_cleanup": true,
  "error_code": "PROVIDER_REJECTED_USER",
  "created_at": "2026-10-08T09:00:00Z",
  "updated_at": "2026-10-08T09:00:00Z"
}
```

#### 11.27 SA: thử lại job chỉ-dọn (200, status FAILED, mọi field Owner là null, KHÔNG có mật khẩu)

```http
POST /api/v1/admin/provisioning-jobs/00000000-0000-4000-8000-000000000019/retry
Authorization: Bearer <access-token>
```

```http
HTTP 200
cache-control: no-store

{
  "job_id": "00000000-0000-4000-8000-000000000019",
  "status": "FAILED",
  "clan_id": "00000000-0000-4000-8000-000000000020",
  "user_id": null,
  "owner_email": null,
  "owner_display_name": null,
  "temporary_password": null,
  "temporary_password_expires_at": null,
  "email_delivery_status": null
}
```

## 12. Giới hạn đã biết

- **Chưa gửi email** (KI-26): SA chuyển mật khẩu tạm thủ công; `email_delivery_status` luôn `null`.
- **Chưa có danh sách clan** (KI-31); **không có tạm ngưng, ngừng hoạt động hay kích hoạt lại** (KI-29); **hết hạn gói chưa được thực thi** (KI-30): clan `ACTIVE` không tự chuyển trạng thái khi `ends_at` đã qua.
- **Chưa có API đổi gói** của một subscription (KI-32).
- **Đặt lại mật khẩu tạm có khoảng hở** (KI-25): nếu Owner tự đổi mật khẩu đúng lúc SA đặt lại, SA nhận `409` nhưng mật khẩu Firebase của Owner có thể đã bị đè; Owner dùng "quên mật khẩu" của Firebase.
- Bộ đếm giới hạn tần suất theo từng máy chủ (KI-17).
- `representative_email` không còn trong danh sách hồ sơ; dùng chi tiết hồ sơ.
