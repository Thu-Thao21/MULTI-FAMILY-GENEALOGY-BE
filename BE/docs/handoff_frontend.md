# Bàn giao cho Frontend — API xác thực và quản trị người dùng

Cập nhật 06/10/2026 (Mốc F2). Tài liệu này nói **cách dùng** API đã cài. Hợp đồng đầy đủ nằm ở [`api_contract.md`](api_contract.md); sơ đồ OpenAPI sống ở `/docs` và `/openapi.json` của server (khai báo cả mã lỗi từng endpoint).

## 1. Tóm tắt

| Mục | Giá trị |
| --- | --- |
| Tiền tố | `/api/v1` (health ở `/api/health`, `/api/health/ready`) |
| Cổng | dev: `uvicorn app.main:app --port 8001`; Docker: `8000` |
| Xác thực | `Authorization: Bearer <access_token>` lấy từ `POST /auth/session` |
| Định dạng | JSON; ID là UUID; thời gian ISO 8601 UTC có hậu tố `Z`; email giữ nguyên chữ hoa/thường người dùng nhập |
| Trường lạ trong body | bị từ chối `422` (đừng gửi trường thừa) |
| Origin được phép | các origin trong biến `FRONTEND_ORIGINS` của server (dev: `http://localhost:5173`, `http://localhost:8080`) |

Endpoint đã cài:

| Endpoint | Ai dùng |
| --- | --- |
| `POST /auth/session` | Guest (đổi Firebase ID token lấy phiên) |
| `GET /auth/me`, `POST /auth/logout`, `POST /auth/change-password` | Mọi người đã đăng nhập, **kể cả phiên hạn chế** |
| `GET /admin/users`, `GET /admin/users/{user_id}`, `PATCH /admin/users/{user_id}/status` | System Admin |
| `GET /clans/{clan_id}/users` | Business Owner, hoặc Family Admin được ủy quyền `MEMBER_ACCOUNT_MANAGE` |
| `POST /clans/{clan_id}/admins` (đề bạt Family Admin), `DELETE /clans/{clan_id}/admins/{user_id}` (thu hồi), `PUT /clans/{clan_id}/admins/{user_id}/permissions` (sửa quyền) | Business Owner |

**Chưa có** (đừng nối màn hình): đăng ký và duyệt Business, cấp Owner, kích hoạt dòng họ (Mốc E); reset mật khẩu qua BE (xem mục 9).

## 2. Luồng đăng nhập

Firebase Authentication (Email/Password, Google, Facebook) lo mật khẩu và việc đăng nhập. Backend **không** nhận mật khẩu và không lưu mật khẩu. Backend chỉ đổi Firebase ID token lấy một phiên của hệ thống.

1. FE đăng nhập bằng Firebase SDK.
2. FE lấy ID token và gửi cho BE: `POST /api/v1/auth/session` với `{"id_token": "..."}`.
3. BE xác minh token (chữ ký, issuer, audience, hạn dùng) và tìm tài khoản theo UID Firebase. Thành công trả `201` kèm `access_token` (**chỉ trả một lần**), `expires_at` (8 giờ), thông tin người dùng và `requires_password_change`.
4. Mọi API sau đó gửi `Authorization: Bearer <access_token>`.
5. Hết hạn hoặc bị thu hồi (đăng xuất, bị khóa, đổi mật khẩu): API trả `401 SESSION_INVALID`. Chưa có refresh token: FE đăng nhập lại, hoặc lấy ID token mới từ Firebase (`getIdToken(true)`) rồi gọi lại `POST /auth/session`.

```js
import { getAuth, signInWithEmailAndPassword } from "firebase/auth";

const credential = await signInWithEmailAndPassword(getAuth(), email, password);
// Google/Facebook: signInWithPopup(...) cho cùng kết quả.
const idToken = await credential.user.getIdToken();

const res = await fetch(`${API_BASE}/api/v1/auth/session`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ id_token: idToken }),
});
if (res.status === 201) {
  const { access_token, expires_at, user, requires_password_change } = await res.json();
  // Giữ access_token trong bộ nhớ của ứng dụng; đừng ghi vào URL hay log.
}
```

Lưu ý:

- **Chỉ tài khoản đã được cấp** (có sẵn trong hệ thống, gắn với UID Firebase) mới đăng nhập được. Tự đăng ký trên Firebase không tạo tài khoản trong hệ thống: BE trả `401 INVALID_ID_TOKEN`, giống hệt khi token sai. Đây là chủ ý, FE không được dựa vào thông điệp để phân biệt.
- `access_token` và ID token là **bí mật**: không ghi log, không đưa vào URL, không gửi cho bên thứ ba.
- Đừng dựa vào vai trò trong token: BE đọc lại quyền từ database ở mỗi request. FE ẩn nút theo `GET /auth/me` chỉ để giao diện gọn; BE vẫn kiểm tra quyền.

## 3. Phiên hạn chế (phải đổi mật khẩu lần đầu)

Tài khoản do hệ thống cấp (mật khẩu tạm) hoặc đang bị buộc đổi mật khẩu nhận `requires_password_change: true`. Phiên này **chỉ** gọi được:

- `GET /auth/me`
- `POST /auth/change-password`
- `POST /auth/logout`

Mọi API khác trả `403 PASSWORD_CHANGE_REQUIRED`. FE nên chuyển thẳng sang màn hình đổi mật khẩu khi `requires_password_change` là `true`.

Đổi mật khẩu: `POST /auth/change-password` với `{"new_password": "...", "recent_id_token": "..."}`.

- `recent_id_token` là ID token Firebase **của chính người đang đăng nhập** và phải do lần đăng nhập **trong vòng 5 phút** (`auth_time`). Nếu không BE trả `401 RECENT_LOGIN_REQUIRED`: yêu cầu người dùng xác thực lại với Firebase rồi gọi lại. (Cách xác thực lại bằng Firebase SDK cần thử trên môi trường dev thật: BE chỉ kiểm `auth_time`.)
- Mật khẩu tạm đã hết hạn: `403 TEMPORARY_PASSWORD_EXPIRED` (kể cả lúc đăng nhập). Cần quản trị cấp lại.
- Mật khẩu mới không đạt chính sách của Firebase (tối thiểu 6 ký tự, BE kiểm sơ bộ): `422`.
- Thành công: `204`. Từ lúc đó **mọi phiên của người dùng bị thu hồi và mọi ID token lấy trước lúc đổi bị từ chối**. FE phải: xóa `access_token`, gọi `signOut` của Firebase, rồi **bắt đăng nhập lại** bằng mật khẩu mới để có ID token mới.
- Tài khoản mới ở trạng thái `PENDING` tự chuyển `ACTIVE` sau lần đổi mật khẩu đầu tiên thành công. (Đây là trạng thái tài khoản người dùng, không phải trạng thái dòng họ.)
- Nếu Firebase đã đổi mật khẩu nhưng database lỗi, BE trả `503 DATABASE_UNAVAILABLE` kèm `request_id`. Tài khoản vẫn ở trạng thái hạn chế: gọi lại `POST /auth/change-password` để hoàn tất.

## 4. Đăng xuất

`POST /auth/logout` (không body) → `204`, thu hồi phiên hiện tại. Sau đó FE xóa `access_token` và gọi `signOut` của Firebase. Token đã đăng xuất không dùng lại được (`401 SESSION_INVALID`).

## 5. Lỗi

Mọi lỗi có cùng một dạng (kể cả `404`, `405`, `422`, `500`, `503`):

```json
{"error": {"code": "ACCOUNT_BLOCKED", "message": "This account cannot be used.", "request_id": "..."}}
```

**Rẽ nhánh theo `code`, không theo `message`** (thông điệp bằng tiếng Anh, chung chung, có thể đổi). `422` chỉ nêu tên trường lỗi, không lặp lại giá trị đã nhập. Mọi response có header `X-Request-ID`; khi báo lỗi cho BE hãy gửi kèm `request_id`. FE có thể tự gửi `X-Request-ID` (8–128 ký tự `A-Z a-z 0-9 . _ -`).

| HTTP | `code` | Ý nghĩa | FE nên làm |
| --- | --- | --- | --- |
| 400 | `BAD_REQUEST` | Request sai ngoài phạm vi validation | Báo lỗi chung |
| 401 | `UNAUTHENTICATED` | Thiếu `Authorization: Bearer` | Chuyển sang đăng nhập |
| 401 | `INVALID_ID_TOKEN` | ID token sai/hết hạn/thu hồi, hoặc tài khoản chưa có trong hệ thống, hoặc ID token lấy trước lần đổi mật khẩu | Đăng nhập lại bằng Firebase |
| 401 | `SESSION_INVALID` | Phiên hết hạn, đã đăng xuất, bị thu hồi (khóa, đổi mật khẩu) | Xóa phiên, đăng nhập lại |
| 401 | `RECENT_LOGIN_REQUIRED` | `recent_id_token` không đủ mới hoặc sai người | Yêu cầu xác thực lại rồi thử lại |
| 403 | `FORBIDDEN` | Thiếu quyền, hoặc dòng họ chưa `ACTIVE`, hoặc mã quyền không được ủy quyền (hiện là `ADMIN_MANAGE`) khi đề bạt/sửa quyền Family Admin | Ẩn/vô hiệu chức năng, báo không đủ quyền |
| 403 | `ACCOUNT_BLOCKED` | Tài khoản `LOCKED`, `SUSPENDED`, `DISABLED` (hoặc `PENDING` không có cờ đổi mật khẩu) | Báo tài khoản không dùng được, liên hệ quản trị |
| 403 | `PASSWORD_CHANGE_REQUIRED` | Phiên hạn chế gọi API ngoài 3 API được phép | Chuyển sang màn đổi mật khẩu |
| 403 | `TEMPORARY_PASSWORD_EXPIRED` | Mật khẩu tạm đã hết hạn | Báo cần quản trị cấp lại |
| 404 | `NOT_FOUND` | Không tồn tại **hoặc không nhìn thấy** (kể cả dòng họ khác) | Báo không tìm thấy; đừng suy ra tồn tại hay không |
| 405 | `METHOD_NOT_ALLOWED` | Sai phương thức | Lỗi lập trình |
| 409 | `STATE_CONFLICT` | Trạng thái đã đổi hoặc chuyển không hợp lệ (ví dụ khóa System Admin cuối cùng); đề bạt người đã là Family Admin, hoặc là chủ họ | Tải lại dữ liệu, báo người dùng |
| 422 | `VALIDATION_ERROR` | Sai schema, thiếu trường, trường lạ, mã quyền không tồn tại | Hiện lỗi theo tên trường |
| 429 | `RATE_LIMITED` | Hợp đồng có, **BE chưa cài** (KI-06) | Chưa gặp |
| 500 | `INTERNAL_ERROR` | Lỗi không lường trước | Báo lỗi chung kèm `request_id` |
| 503 | `PROVIDER_UNAVAILABLE` | Firebase không khả dụng | Cho thử lại sau |
| 503 | `DATABASE_UNAVAILABLE` | Database không khả dụng | Cho thử lại sau |

`403` và `404` có ý nghĩa phân biệt: trong dòng họ của mình mà thiếu quyền → `403`; dòng họ khác hoặc không tồn tại → `404`.

## 6. Phân trang

Mọi API danh sách nhận `page` (≥ 1, mặc định 1) và `page_size` (1–100, mặc định 20) và trả:

```json
{"items": [], "total": 0, "page": 1, "page_size": 20}
```

`page_size` > 100 hoặc `page` < 1 trả `422`. `GET /admin/users` lọc thêm `status` và `q` (tìm không phân biệt hoa thường trong email và tên). `GET /clans/{clan_id}/users` lọc thêm `membership_status` (mặc định liệt kê mọi trạng thái, kể cả `REVOKED`).

## 7. CORS và header

- Trình duyệt chỉ đọc được response từ các origin trong `FRONTEND_ORIGINS`. Mọi response, **kể cả lỗi `500`**, có header CORS đúng.
- FE đọc được `X-Request-ID` và `Retry-After` (đã được expose).
- Header FE được phép gửi: bất kỳ (gồm `Authorization`, `Content-Type`, `X-Request-ID`, `Idempotency-Key`). Dùng `credentials: "include"` được, nhưng BE **không dùng cookie**: chỉ cần header `Authorization`.

## 8. Quyền và dữ liệu hiển thị

- `GET /auth/me` trả `memberships[]` (mỗi dòng họ: vai trò và quyền hiệu lực **trong dòng họ đó**) và `permissions[]` (quyền cấp hệ thống). Giá trị trong `permissions[]` **tạm thời, chờ trưởng nhóm chốt**: với System Admin và Business Owner là mã action của policy (ví dụ `user.list`, `clan.users.list`), với Family Admin là mã quyền ủy quyền (ví dụ `MEMBER_ACCOUNT_MANAGE`). Đừng hard-code danh sách này; có thể đổi.
- Quyền chỉ có hiệu lực khi membership **và** dòng họ đều `ACTIVE`. Dòng họ chưa `ACTIVE`: vẫn thấy vai trò, `permissions` rỗng, API theo dòng họ trả `403`.
- API không trả `firebase_uid`, mật khẩu, mã băm token hay thông tin xác thực nhạy cảm.
- System Admin không tự động có quyền trong dòng họ nào: `GET /clans/{id}/users` với System Admin trả `404`.
- Khóa tài khoản (`PATCH .../status`) thu hồi mọi phiên của người đó: lần gọi tiếp theo của họ trả `401 SESSION_INVALID`, và đổi lại ID token trả `403 ACCOUNT_BLOCKED`.
- Bảng chuyển trạng thái tài khoản (tạm thời, chờ trưởng nhóm): `ACTIVE` → `LOCKED`/`SUSPENDED`/`DISABLED`; `LOCKED`/`SUSPENDED` → `ACTIVE`/(nhau)/`DISABLED`; `DISABLED` → `ACTIVE`; `PENDING` → chỉ `DISABLED`. Mọi chuyển khác, hoặc chuyển về chính trạng thái hiện tại, trả `409`. Không thể khóa hoặc vô hiệu hóa System Admin cuối cùng (`409`).
- **Vòng đời Family Admin** (chỉ Business Owner, dòng họ phải `ACTIVE`):
  - `POST /clans/{clan_id}/admins` với `{user_id, permission_codes}` đề bạt một **thành viên `ACTIVE`** của dòng họ thành Family Admin cho **cả dòng họ**; `permission_codes` có thể rỗng hoặc bỏ qua. `201` trả `assignment_id`. Người không phải thành viên `ACTIVE` của dòng họ này: `404`. Người đã là Family Admin, hoặc là chủ họ/người còn vai trò Business Owner của dòng họ: `409`. Gọi hai lần cùng lúc cho cùng một người thì chỉ một lần thành công.
  - `PUT .../permissions` thay **toàn bộ** tập quyền của Family Admin; danh sách rỗng xóa hết quyền nhưng vẫn giữ tư cách Family Admin.
  - `DELETE /clans/{clan_id}/admins/{user_id}` thu hồi **hẳn** (`204`): mất mọi quyền ngay ở request kế tiếp của người đó, vẫn là thành viên của dòng họ. Không phải Family Admin: `404`. Có thể đề bạt lại sau đó (tạo assignment mới).
  - Mã quyền phải có trong hệ thống (mã lạ: `422`) và **không được ủy quyền** `ADMIN_MANAGE` (`403`); với `PUT`, tập quyền gửi lên vẫn chứa `ADMIN_MANAGE` cũng bị `403`, phải bỏ mã đó. Hiện chỉ `MEMBER_ACCOUNT_MANAGE` thật sự mở thêm chức năng (xem danh sách tài khoản của dòng họ); các mã khác được lưu nhưng chưa có tác dụng.
  - Danh sách tài khoản của dòng họ (`GET /clans/{clan_id}/users`) và `GET /auth/me` phản ánh thay đổi ngay: `is_family_admin`, `roles` có `FAMILY_ADMIN`.

## 9. Giới hạn đã biết

- **Chưa có API reset mật khẩu** (KI-05): FE dùng `sendPasswordResetEmail` của Firebase. Sau reset, phiên ứng dụng cũ của người đó vẫn dùng được đến khi hết hạn (tối đa 8 giờ) vì BE không biết mật khẩu đã đổi.
- **Chưa có giới hạn tần suất** (`429`) cho `/auth/session` (KI-06).
- Khóa tài khoản chỉ chặn ở BE; Firebase vẫn cho người đó đăng nhập, nhưng ID token của họ không đổi được phiên (KI-10).
- **Triển khai sau reverse proxy:** `login_history` sẽ ghi IP của proxy, cần cấu hình `--proxy-headers` kèm danh sách proxy tin cậy khi triển khai (KI-11). Không ảnh hưởng cách FE gọi API.
- Các quyết định còn chờ trưởng nhóm được đánh dấu "tạm thời" trong `api_contract.md` mục 6.

## 10. Ví dụ request và response

Các ví dụ dưới đây là **phản hồi thật** của ứng dụng (chạy với database và Firebase giả lập trong test), chỉ chuẩn hóa các giá trị thay đổi mỗi lần chạy: UUID, thời gian, email và `access_token` (luôn là `<access_token>`). Không có token hoặc UID thật. Trong ví dụ, `{user_id}` và `{clan_id}` là chỗ điền UUID.

#### Đổi ID token lấy phiên (đăng nhập thành công)

`access_token` chỉ xuất hiện trong phản hồi này, một lần duy nhất.

Yêu cầu:

```http
POST /api/v1/auth/session
Content-Type: application/json
```

```json
{
  "id_token": "<Firebase ID token>"
}
```

Phản hồi: **201**

```json
{
  "access_token": "<access_token>",
  "token_type": "Bearer",
  "expires_at": "2026-10-06T16:00:00Z",
  "user": {
    "user_id": "00000000-0000-4000-8000-000000000001",
    "display_name": "Nguyễn Văn An",
    "email": "an.nguyen@example.test",
    "status": "ACTIVE"
  },
  "requires_password_change": false
}
```

#### Thông tin tài khoản hiện tại (vai trò Business Owner)

Yêu cầu:

```http
GET /api/v1/auth/me
Authorization: Bearer <access_token>
```

Phản hồi: **200**

```json
{
  "user_id": "00000000-0000-4000-8000-000000000001",
  "display_name": "Nguyễn Văn An",
  "status": "ACTIVE",
  "memberships": [
    {
      "clan_id": "00000000-0000-4000-8000-000000000002",
      "clan_name": "Họ Nguyễn - Chi 1",
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
  ],
  "permissions": [],
  "requires_password_change": false
}
```

#### Thông tin tài khoản hiện tại (vai trò System Admin)

Yêu cầu:

```http
GET /api/v1/auth/me
Authorization: Bearer <access_token>
```

Phản hồi: **200**

```json
{
  "user_id": "00000000-0000-4000-8000-000000000003",
  "display_name": "Quản trị hệ thống",
  "status": "ACTIVE",
  "memberships": [],
  "permissions": [
    "business.create",
    "clan.activate",
    "clan.owner.provision",
    "provisioning_job.read",
    "registration.list",
    "registration.read",
    "registration.review",
    "user.list",
    "user.read",
    "user.status.update"
  ],
  "requires_password_change": false
}
```

#### Đăng nhập lần đầu bằng mật khẩu tạm: phiên hạn chế

`requires_password_change` là `true`: phiên này chỉ dùng được `/auth/me`, `/auth/change-password`, `/auth/logout`.

Yêu cầu:

```http
POST /api/v1/auth/session
Content-Type: application/json
```

```json
{
  "id_token": "<Firebase ID token>"
}
```

Phản hồi: **201**

```json
{
  "access_token": "<access_token>",
  "token_type": "Bearer",
  "expires_at": "2026-10-06T16:00:00Z",
  "user": {
    "user_id": "00000000-0000-4000-8000-000000000004",
    "display_name": "Trần Thị Mai",
    "email": "binh.tran@example.test",
    "status": "PENDING"
  },
  "requires_password_change": true
}
```

#### Phiên hạn chế gọi API khác

Yêu cầu:

```http
GET /api/v1/admin/users
Authorization: Bearer <access_token>
```

Phản hồi: **403**

```json
{
  "error": {
    "code": "PASSWORD_CHANGE_REQUIRED",
    "message": "You must change your password first.",
    "request_id": "6df2c3e1-27f4-43c4-b2e3-97fe67742e24"
  }
}
```

#### Đổi mật khẩu (thành công, mọi phiên bị thu hồi)

Yêu cầu:

```http
POST /api/v1/auth/change-password
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "new_password": "<mật khẩu mới>",
  "recent_id_token": "<Firebase ID token vừa đăng nhập lại>"
}
```

Phản hồi: **204**

#### Dùng lại phiên cũ sau khi đổi mật khẩu

Yêu cầu:

```http
GET /api/v1/auth/me
Authorization: Bearer <access_token>
```

Phản hồi: **401**

```json
{
  "error": {
    "code": "SESSION_INVALID",
    "message": "The session is invalid, expired or revoked.",
    "request_id": "6df2c3e1-27f4-43c4-b2e3-97fe67742e24"
  }
}
```

#### Đổi lại ID token cũ (lấy trước lúc đổi mật khẩu) bị từ chối

Phải đăng nhập lại bằng Firebase để có ID token mới.

Yêu cầu:

```http
POST /api/v1/auth/session
Content-Type: application/json
```

```json
{
  "id_token": "<Firebase ID token>"
}
```

Phản hồi: **401**

```json
{
  "error": {
    "code": "INVALID_ID_TOKEN",
    "message": "The identity token is invalid or revoked.",
    "request_id": "6df2c3e1-27f4-43c4-b2e3-97fe67742e24"
  }
}
```

#### Đăng xuất

Yêu cầu:

```http
POST /api/v1/auth/logout
Authorization: Bearer <access_token>
```

Phản hồi: **204**

#### Dùng phiên đã đăng xuất

Yêu cầu:

```http
GET /api/v1/auth/me
Authorization: Bearer <access_token>
```

Phản hồi: **401**

```json
{
  "error": {
    "code": "SESSION_INVALID",
    "message": "The session is invalid, expired or revoked.",
    "request_id": "6df2c3e1-27f4-43c4-b2e3-97fe67742e24"
  }
}
```

#### Tài khoản bị khóa

Yêu cầu:

```http
POST /api/v1/auth/session
Content-Type: application/json
```

```json
{
  "id_token": "<Firebase ID token>"
}
```

Phản hồi: **403**

```json
{
  "error": {
    "code": "ACCOUNT_BLOCKED",
    "message": "This account cannot be used.",
    "request_id": "6df2c3e1-27f4-43c4-b2e3-97fe67742e24"
  }
}
```

#### ID token sai, hết hạn hoặc tài khoản chưa có trong hệ thống

Cả ba trường hợp trả cùng một lỗi, cố ý không cho biết tài khoản có tồn tại hay không.

Yêu cầu:

```http
POST /api/v1/auth/session
Content-Type: application/json
```

```json
{
  "id_token": "<Firebase ID token>"
}
```

Phản hồi: **401**

```json
{
  "error": {
    "code": "INVALID_ID_TOKEN",
    "message": "The identity token is invalid or revoked.",
    "request_id": "6df2c3e1-27f4-43c4-b2e3-97fe67742e24"
  }
}
```

#### Thiếu trường bắt buộc

Yêu cầu:

```http
POST /api/v1/auth/session
Content-Type: application/json
```

```json
{}
```

Phản hồi: **422**

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid input. Fields: body.id_token",
    "request_id": "6df2c3e1-27f4-43c4-b2e3-97fe67742e24"
  }
}
```

#### Firebase không khả dụng

Yêu cầu:

```http
POST /api/v1/auth/session
Content-Type: application/json
```

```json
{
  "id_token": "<Firebase ID token>"
}
```

Phản hồi: **503**

```json
{
  "error": {
    "code": "PROVIDER_UNAVAILABLE",
    "message": "An external service is temporarily unavailable.",
    "request_id": "6df2c3e1-27f4-43c4-b2e3-97fe67742e24"
  }
}
```

#### System Admin: danh sách người dùng (phân trang, lọc)

Yêu cầu:

```http
GET /api/v1/admin/users?page=1&page_size=2&status=ACTIVE&q=example
Authorization: Bearer <access_token>
```

Phản hồi: **200**

```json
{
  "items": [
    {
      "user_id": "00000000-0000-4000-8000-000000000005",
      "email": "chi.le@example.test",
      "display_name": "Trần Văn Bình",
      "status": "ACTIVE",
      "last_login_at": null,
      "created_at": "2026-10-05T08:00:00Z"
    },
    {
      "user_id": "00000000-0000-4000-8000-000000000006",
      "email": "dung.pham@example.test",
      "display_name": "Phạm Văn Dũng",
      "status": "ACTIVE",
      "last_login_at": null,
      "created_at": "2026-10-05T08:00:00Z"
    }
  ],
  "total": 5,
  "page": 1,
  "page_size": 2
}
```

#### System Admin: chi tiết một người dùng

Yêu cầu:

```http
GET /api/v1/admin/users/{user_id}
Authorization: Bearer <access_token>
```

Phản hồi: **200**

```json
{
  "user_id": "00000000-0000-4000-8000-000000000005",
  "email": "chi.le@example.test",
  "display_name": "Trần Văn Bình",
  "status": "ACTIVE",
  "last_login_at": null,
  "created_at": "2026-10-05T08:00:00Z",
  "username": null,
  "phone": null,
  "email_verified": false,
  "phone_verified": false,
  "requires_password_change": false,
  "updated_at": "2026-10-05T08:00:00Z",
  "memberships": [
    {
      "clan_id": "00000000-0000-4000-8000-000000000007",
      "clan_name": "Họ Trần - Chi 2",
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

#### System Admin: khóa tài khoản (thu hồi mọi phiên của người đó)

Yêu cầu:

```http
PATCH /api/v1/admin/users/{user_id}/status
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "status": "LOCKED",
  "reason": "Nghi ngờ lộ tài khoản"
}
```

Phản hồi: **200**

```json
{
  "user_id": "00000000-0000-4000-8000-000000000008",
  "status": "LOCKED",
  "revoked_session_count": 1,
  "updated_at": "2026-10-05T08:00:00Z"
}
```

#### Chuyển trạng thái không hợp lệ

Yêu cầu:

```http
PATCH /api/v1/admin/users/{user_id}/status
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "status": "LOCKED",
  "reason": "Khóa lại"
}
```

Phản hồi: **409**

```json
{
  "error": {
    "code": "STATE_CONFLICT",
    "message": "A user in status LOCKED cannot be changed to LOCKED.",
    "request_id": "6df2c3e1-27f4-43c4-b2e3-97fe67742e24"
  }
}
```

#### Business Owner: danh sách tài khoản trong dòng họ của mình

Yêu cầu:

```http
GET /api/v1/clans/{clan_id}/users?page_size=10
Authorization: Bearer <access_token>
```

Phản hồi: **200**

```json
{
  "items": [
    {
      "user_id": "00000000-0000-4000-8000-000000000009",
      "display_name": "Hoàng Văn Nam",
      "email": "em.vo@example.test",
      "user_status": "ACTIVE",
      "membership_status": "ACTIVE",
      "roles": [
        "FAMILY_MEMBER"
      ],
      "is_family_admin": false,
      "joined_at": "2026-10-05T08:00:00Z"
    },
    {
      "user_id": "00000000-0000-4000-8000-000000000010",
      "display_name": "Lê Thị Chi",
      "email": "phuc.do@example.test",
      "user_status": "ACTIVE",
      "membership_status": "ACTIVE",
      "roles": [
        "FAMILY_ADMIN"
      ],
      "is_family_admin": true,
      "joined_at": "2026-10-05T08:00:00Z"
    },
    {
      "user_id": "00000000-0000-4000-8000-000000000006",
      "display_name": "Phạm Văn Dũng",
      "email": "dung.pham@example.test",
      "user_status": "ACTIVE",
      "membership_status": "SUSPENDED",
      "roles": [
        "FAMILY_MEMBER"
      ],
      "is_family_admin": false,
      "joined_at": "2026-10-05T08:00:00Z"
    },
    {
      "user_id": "00000000-0000-4000-8000-000000000005",
      "display_name": "Trần Văn Bình",
      "email": "chi.le@example.test",
      "user_status": "ACTIVE",
      "membership_status": "ACTIVE",
      "roles": [
        "BUSINESS_OWNER"
      ],
      "is_family_admin": false,
      "joined_at": "2026-10-05T08:00:00Z"
    }
  ],
  "total": 4,
  "page": 1,
  "page_size": 10
}
```

#### Dòng họ khác: luôn là 404, không lộ sự tồn tại

Yêu cầu:

```http
GET /api/v1/clans/{clan_id}/users
Authorization: Bearer <access_token>
```

Phản hồi: **404**

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Resource not found.",
    "request_id": "6df2c3e1-27f4-43c4-b2e3-97fe67742e24"
  }
}
```

#### Business Owner: thay toàn bộ quyền ủy quyền của một Family Admin

Danh sách rỗng (`[]`) xóa hết quyền nhưng vẫn giữ tư cách Family Admin.

Yêu cầu:

```http
PUT /api/v1/clans/{clan_id}/admins/{user_id}/permissions
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "permission_codes": [
    "MEMBER_ACCOUNT_MANAGE",
    "PERSON_VIEW"
  ]
}
```

Phản hồi: **200**

```json
{
  "clan_id": "00000000-0000-4000-8000-000000000007",
  "user_id": "00000000-0000-4000-8000-000000000010",
  "assignment_id": "00000000-0000-4000-8000-000000000011",
  "permission_codes": [
    "MEMBER_ACCOUNT_MANAGE",
    "PERSON_VIEW"
  ],
  "updated_at": "2026-10-05T08:00:00Z"
}
```

#### Mã quyền không tồn tại

Yêu cầu:

```http
PUT /api/v1/clans/{clan_id}/admins/{user_id}/permissions
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "permission_codes": [
    "NOT_A_REAL_CODE"
  ]
}
```

Phản hồi: **422**

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid input. Fields: permission_codes (unknown permission code)",
    "request_id": "6df2c3e1-27f4-43c4-b2e3-97fe67742e24"
  }
}
```

#### Business Owner: đề bạt một thành viên thành Family Admin

`permission_codes` có thể rỗng hoặc bỏ qua. Hiệu lực ngay ở request kế tiếp của người được đề bạt.

Yêu cầu:

```http
POST /api/v1/clans/{clan_id}/admins
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "user_id": "<user_id của thành viên>",
  "permission_codes": [
    "MEMBER_ACCOUNT_MANAGE"
  ]
}
```

Phản hồi: **201**

```json
{
  "clan_id": "00000000-0000-4000-8000-000000000007",
  "user_id": "00000000-0000-4000-8000-000000000012",
  "assignment_id": "00000000-0000-4000-8000-000000000013",
  "permission_codes": [
    "MEMBER_ACCOUNT_MANAGE"
  ],
  "created_at": "2026-10-05T08:00:00Z"
}
```

#### Đề bạt người đã là Family Admin

Yêu cầu:

```http
POST /api/v1/clans/{clan_id}/admins
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "user_id": "<user_id của thành viên>"
}
```

Phản hồi: **409**

```json
{
  "error": {
    "code": "STATE_CONFLICT",
    "message": "The user is already a Family Admin of this clan.",
    "request_id": "6df2c3e1-27f4-43c4-b2e3-97fe67742e24"
  }
}
```

#### Mã quyền không được ủy quyền

Yêu cầu:

```http
POST /api/v1/clans/{clan_id}/admins
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "user_id": "<user_id của thành viên>",
  "permission_codes": [
    "ADMIN_MANAGE"
  ]
}
```

Phản hồi: **403**

```json
{
  "error": {
    "code": "FORBIDDEN",
    "message": "One or more permission codes cannot be delegated.",
    "request_id": "6df2c3e1-27f4-43c4-b2e3-97fe67742e24"
  }
}
```

#### Người không phải thành viên đang hoạt động của dòng họ

Yêu cầu:

```http
POST /api/v1/clans/{clan_id}/admins
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "user_id": "<user_id>"
}
```

Phản hồi: **404**

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Resource not found.",
    "request_id": "6df2c3e1-27f4-43c4-b2e3-97fe67742e24"
  }
}
```

#### Business Owner: thu hồi Family Admin

Mất mọi quyền Family Admin ngay; vẫn là thành viên của dòng họ.

Yêu cầu:

```http
DELETE /api/v1/clans/{clan_id}/admins/{user_id}
Authorization: Bearer <access_token>
```

Phản hồi: **204**

#### Thu hồi người không còn là Family Admin

Yêu cầu:

```http
DELETE /api/v1/clans/{clan_id}/admins/{user_id}
Authorization: Bearer <access_token>
```

Phản hồi: **404**

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Resource not found.",
    "request_id": "6df2c3e1-27f4-43c4-b2e3-97fe67742e24"
  }
}
```

#### Thành viên thường (không có quyền quản lý tài khoản) trong dòng họ của mình

Yêu cầu:

```http
GET /api/v1/clans/{clan_id}/users
Authorization: Bearer <access_token>
```

Phản hồi: **403**

```json
{
  "error": {
    "code": "FORBIDDEN",
    "message": "You do not have permission to perform this action.",
    "request_id": "6df2c3e1-27f4-43c4-b2e3-97fe67742e24"
  }
}
```

#### Lỗi không lường trước (không có chi tiết nội bộ)

Yêu cầu:

```http
GET /api/v1/<bất kỳ>
```

Phản hồi: **500**

```json
{
  "error": {
    "code": "INTERNAL_ERROR",
    "message": "An unexpected error occurred.",
    "request_id": "6df2c3e1-27f4-43c4-b2e3-97fe67742e24"
  }
}
```

#### Database không khả dụng

Yêu cầu:

```http
GET /api/v1/<bất kỳ>
```

Phản hồi: **503**

```json
{
  "error": {
    "code": "DATABASE_UNAVAILABLE",
    "message": "The database is temporarily unavailable.",
    "request_id": "6df2c3e1-27f4-43c4-b2e3-97fe67742e24"
  }
}
```

