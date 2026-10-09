# Kế hoạch code Backend Sprint 1 — MFGMS AI

> MFGMS AI • Bản cập nhật theo Neon và MVC

Mục tiêu của bạn là hoàn thiện xác thực, tiếp nhận và duyệt đăng ký Business, cấp tài khoản, quản lý người dùng và phân quyền. Triển khai trên repository BE riêng, dùng schema Neon hiện tại và nhánh database cá nhân; bàn giao code cùng migration để nhóm trưởng duyệt.

Cập nhật ngày 05/10/2026. Phần kết nối database: bạn đã xác nhận thực hiện các bước. Trước khi code, lưu kết quả kiểm tra kết nối và schema tại mục 3; trạng thái này chưa thay thế kiểm thử trực tiếp trên máy bạn.

> **Tiến độ BE (cập nhật 09/10/2026): Mốc E hoàn tất (E1 đến E8)** — migration 0003, đăng ký Guest và giới hạn tần suất, duyệt hồ sơ, tạo Business (idempotent), cấp Owner qua Firebase (job, bù trừ, thử lại, bỏ, cấp lại mật khẩu tạm), kích hoạt và đọc clan, tài liệu bàn giao cho FE (`docs/handoff_frontend_business.md`), và **E8: smoke test với Firebase thật trên project dev (09/10/2026) đã đạt** (probe, main 14 kiểm tra, cleanup và verify CLEAN; chi tiết ở `docs/testing.md` mục 5). `pytest -q`: 1462 passed. **Còn lại:** (1) **chạy integration sạch cả bộ** một lượt 0 failed (chưa có lượt nào kể từ E4: mỗi lần đều có lỗi hạ tầng Neon/DNS ngoài ý muốn, các test lỗi đều đã chạy riêng và pass); (2) **PR**: gộp các commit của Mốc E, mô tả thay đổi hợp đồng cho FE, chạy migration 0003 trên production theo `docs/migrations.md` (production chưa chạy); (3) các KI còn mở: 17, 21, 24, 25, 26 (email thật), 27, 28, 29, 30, 31, 32, 33 (script E8 ngoài repo), 34, 35, 36 (xem `docs/known_issues.md`).

# 1 Phạm vi và thứ tự ưu tiên

| **WBS 3.1.8** | **Hạng mục BE Sprint 1** | **Giờ gốc** |
| --- | --- | --- |
| 1–3 | Authentication API, đăng nhập, đăng xuất | 24 |
| 4–5 | Khôi phục mật khẩu, đổi mật khẩu lần đầu | 16 |
| 6–8 | Đăng ký, duyệt Business, cấp tài khoản Business | 30 |
| 9–10 | Quản lý tài khoản và phân quyền RBAC | 22 |
| 11 | Tích hợp Firebase Authentication | 10 |

Tổng 102 giờ là ước lượng trong Project Plan, chưa gồm đầy đủ việc đồng bộ ORM, migration, tích hợp và kiểm thử. Kế hoạch dùng mốc công việc tương đối; không tiếp tục dùng lịch Sprint cũ đã qua.

## Những thay đổi so với plan cũ

Thay mô hình Account/Family bằng users/clans và các bảng quyền, phiên, thông tin xác thực đang có trong Neon.

Chuyển căn cứ code sang MULTI-FAMILY-GENEALOGY-BE; không gán các lỗi của backend cũ trong repo FE cho repo BE mới.

Giữ file SQL trong Git để tham khảo. Schema đang dùng phải được xác nhận trên nhánh Neon; mọi thay đổi tiếp theo đi qua migration.

Đề xuất Firebase quản lý cả mật khẩu và Google login; quyết định này cần nhóm xác nhận trước khi triển khai luồng mật khẩu.

## Giới hạn Sprint

Tập trung C01 Auth and Access và C02 Family Management. Chỉ tạo dòng họ tối thiểu để cấp Business; chưa làm CRUD cây gia phả, quan hệ, AI, 3D, quỹ, thanh toán thật hoặc chuyển giao Owner. Không coi toàn bộ workbook FR là phạm vi Sprint 1.

# 2 Ánh xạ MVC và cấu trúc code

View là FE React. Controller tiếp nhận request, kiểm tra quyền và điều phối use case. Model chứa ORM và truy cập dữ liệu. Firebase và email nằm trong adapter để có thể thay thế bằng bản giả lập khi kiểm thử.

| **Module view** | **Phần Sprint 1** | **Trách nhiệm BE** |
| --- | --- | --- |
| C01 và M01 | Auth and Access và User Access | Danh tính, phiên, đổi mật khẩu, trạng thái tài khoản, quyền và audit. |
| C02 và M02 | Family Management và Family | Đăng ký Business, duyệt hồ sơ, cấp dòng họ và Owner, membership. |
| V01 đến V05 | SA, BO, FA, ME và Guest | Cùng API nền tảng, khác quyền và phạm vi dữ liệu. FE ẩn nút không thay kiểm tra quyền ở BE. |

## Điểm cần thống nhất trong sơ đồ

Module/deployment view đặt nghiệp vụ ở Controller; C&C lại mô tả services nghiệp vụ trong Model. Đề xuất lấy module view làm quy ước code: use_cases thuộc Controller, repositories thuộc Model. Nhóm cập nhật chú thích C&C tương ứng trước khi review; không tạo hai bộ service làm cùng việc.

| **Thư mục đề xuất trong BE/app** | **Nội dung** |
| --- | --- |
| controllers/auth_access/ | router.py và use_cases.py cho auth, users và quyền. |
| controllers/family_management/ | router.py và use_cases.py cho hồ sơ Business và cấp Owner. |
| models/user_access/ và models/family/ | entities.py ánh xạ bảng; repository.py truy vấn theo user_id và clan_id. |
| schemas/ | Pydantic request/response; không phải file tạo database. |
| dependencies/ | Xác thực phiên, trạng thái, permission và tenant scope. |
| integrations/ | Firebase adapter và email adapter; timeout, lỗi và retry rõ ràng. |
| db/ và models/registry.py | Engine/session và import metadata dùng chung cho Alembic. |

Giữ app/main.py, core/config.py và router health hiện có; đăng ký router mới vào main. Thay dần app/models/postgres.py cũ và các import phụ thuộc, không khai báo hai ORM cho cùng bảng. Mỗi use case quản lý transaction; repository không tự commit.

# 3 Chốt nền tảng Neon trước khi code

Căn cứ schema: mfgms_ai_production_schema(1).sql có 86 bảng. initial_schema.sql trong repo BE được đối chiếu có 74 bảng. Đây là hai snapshot khác nhau; số lượng bảng giống nhau cũng chưa chứng minh hai schema giống nhau.

| **Kiểm tra** | **Điều kiện đạt** |
| --- | --- |
| Kết nối cá nhân | DATABASE_URL trỏ đúng branch Neon được giao, ví dụ dev_minhquan; xác nhận branch trong Neon Console. Không dùng production để thử migration. |
| Runtime | SQLAlchemy async dùng postgresql+psycopg và psycopg đã cài. Khởi động từ thư mục BE để đọc đúng .env. |
| Startup | init_db chỉ SELECT 1. Không create_all, ALTER, seed tài khoản hay sửa mật khẩu khi app khởi động. |
| Schema | Đối chiếu users, clans, credential_metadata, user_sessions và các bảng ở mục 4 trên chính branch đang kết nối. |
| Trạng thái dịch vụ | Kết nối lỗi phải làm readiness không đạt; không nuốt lỗi rồi báo database initialized. Liveness không đồng nghĩa DB hoạt động. |

## SQL đọc để lưu bằng chứng

Chạy trên branch cá nhân trong SQL Editor; không gửi connection string hoặc mật khẩu vào tài liệu review.

```sql
SELECT current_database(), current_schema();
SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE';
SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema = 'public' AND table_name IN ('users','clans','credential_metadata','user_sessions') ORDER BY table_name, ordinal_position;
```

## Quản lý baseline và migration

Giữ SQL cũ trong Git, bổ sung README ghi rõ đây là snapshot cũ không dùng để khởi tạo schema Neon hiện tại.

Nhóm trưởng chốt baseline từ schema được duyệt. Tạo migration baseline có thể dựng database trống; chỉ alembic stamp khi đã đối chiếu database hiện hữu khớp baseline.

Không import nguyên file export một cách mù quáng: bản export có index trùng hoặc biểu thức/điều kiện cần kiểm chứng. Đọc pg_indexes để xác nhận index thật trước khi sửa.

Branch được tách trước thay đổi của production cần kiểm tra lại schema; không mặc định nhận mọi thay đổi mới từ parent. Hợp nhất bằng migration được review.

# 4 Ánh xạ database cho Sprint 1

| **Nghiệp vụ** | **Bảng đang có** | **Quy tắc triển khai** |
| --- | --- | --- |
| Danh tính | users; credential_metadata | users không có password_hash. firebase_uid là liên kết danh tính; metadata lưu cờ và thời điểm, không lưu mật khẩu. |
| Phiên và lịch sử | user_sessions; login_history; audit_logs | Lưu hash token phiên, hạn dùng và thu hồi. Log không chứa mật khẩu, token hay nội dung riêng tư không cần thiết. |
| Quyền | roles; permissions; role_permissions; user_roles | Dùng role code được seed có kiểm soát. user_roles.clan_id xác định phạm vi; revoked_at phải null khi cấp quyền. |
| Đăng ký Business | business_registrations; registration_status_history | Lưu yêu cầu, gói, quyết định duyệt và lịch sử chuyển trạng thái. |
| Dòng họ và gói | clans; clan_profiles; clan_subscriptions; subscription_plans; plan_feature_limits | Một registration chỉ tạo một clan. Gói và giới hạn lấy từ DB, không tin giá hoặc quyền do FE gửi. |
| Owner và membership | clan_ownership_history; clan_memberships | Owner đang hiệu lực duy nhất cho mỗi clan; cập nhật membership và quyền trong cùng transaction. |
| Tài khoản gắn gia phả | person_account_links; persons | Chỉ gắn Person đã có và cùng clan. Owner mới chưa có Person vẫn có thể được cấp theo nghiệp vụ. |
| Quyền FA | family_admin_assignments; family_admin_permissions | Quyền được ủy quyền cụ thể, xét phạm vi branch/clan và trạng thái assignment. |
| Mời và email | account_invitations; email_delivery_logs; email_delivery_attempts | Mời có purpose, hạn và dùng một lần. Delivery log chưa đủ thay durable outbox. |
| Reset và hỗ trợ | password_reset_tokens; support_access_grants | Reset phụ thuộc phương án Firebase. SA chỉ truy cập riêng tư khi có grant còn hiệu lực và đúng scope. |

## Tên cũ không tiếp tục dùng

member_accounts → person_account_links; clan_ownerships → clan_ownership_history; person_visibility_settings → person_privacy_settings. Không tạo thêm bảng mang tên cũ để làm cho ORM chạy được.

## Migration bổ sung chỉ khi có nhu cầu thật

Kiểm tra unique token hash, unique Owner đang hiệu lực, index tra cứu phiên/quyền, cơ chế idempotency và job cấp tài khoản/email bền vững. Liệt kê riêng phần đã có và phần cần migration trong PR; không coi các đề xuất này là schema đã tồn tại.

# 5 Thiết kế xác thực đề xuất

D01 cần chốt: dùng Firebase Authentication cho email/password và Google. Neon giữ user, quyền, trạng thái và phiên ứng dụng. Phương án này phù hợp auth_provider mặc định FIREBASE và việc users không có password_hash; đây là đề xuất, chưa phải quyết định của nhóm.

## Đăng nhập và tạo phiên

FE đăng nhập qua Firebase, gửi ID token vào POST /api/v1/auth/session. BE dùng Admin SDK xác minh chữ ký, issuer, audience, hạn và trạng thái thu hồi; cấu hình sai phải từ chối.

Ánh xạ bằng firebase_uid. Không tự cấp Owner/SA hoặc nối tài khoản đặc quyền chỉ vì email trùng. UID chưa có trong hệ thống bị từ chối, trừ quy trình cấp tài khoản đã được duyệt.

BE sinh bearer token ngẫu nhiên đủ mạnh; chỉ lưu SHA256 token trong user_sessions.token_jti_hash. Trả token một lần, expires_at, user và cờ requires_password_change.

API nghiệp vụ chỉ chấp nhận phiên ứng dụng; mỗi request kiểm tra session, users.status, cờ đổi mật khẩu và quyền hiện tại. Đề xuất hạn phiên 8 giờ, chưa triển khai refresh ở Sprint 1.

PENDING với mật khẩu tạm chỉ được cấp phiên hạn chế sau khi kiểm tra thời hạn. Chỉ /auth/me, /auth/change-password và /auth/logout được dùng. LOCKED, SUSPENDED, DISABLED bị chặn.

## Mật khẩu và thu hồi

Đổi/reset mật khẩu thực hiện qua Firebase adapter hoặc luồng khôi phục chính thức của Firebase. Không thêm kho mật khẩu local song song. users.first_login_required và credential_metadata.must_change_password được cập nhật cùng transaction; middleware chặn nếu một trong hai còn true.

Sau đổi/reset, thu hồi mọi phiên ứng dụng. Kiểm tra trạng thái thu hồi Firebase và auth_time khi trao đổi token; không cho ID token đăng nhập trước lần đổi mật khẩu đổi lấy phiên mới. Dùng password_changed_at làm mốc nếu phù hợp, bổ sung mốc riêng bằng migration nếu cần.

Firebase và PostgreSQL không có transaction chung. Nếu đổi mật khẩu phía Firebase thành công nhưng cập nhật DB lỗi, giữ chặn nghiệp vụ và trả lỗi có mã theo dõi; retry/reconcile mới hoàn tất trạng thái. Không trả thành công khi chỉ một phía thành công.

## Nếu nhóm chỉ dùng Firebase cho Google

Dừng nhánh triển khai password theo phương án trên và cập nhật D01: cần thiết kế credential local, thuật toán hash, reset token, migration và thêm kiểm thử. Không suy ra có mật khẩu local từ việc repo cài passlib/bcrypt.

# 6 Hợp đồng API xác thực

Prefix đề xuất /api/v1. Chốt OpenAPI trước khi FE nối màn hình. Login email/password được Firebase SDK xử lý; endpoint session là API Authentication/Login của BE, không nhận lại mật khẩu đăng nhập.

| **API** | **Input và output chính** | **Quyền và lỗi** |
| --- | --- | --- |
| POST /auth/session | {id_token} → 201 {access_token, token_type, expires_at, user, requires_password_change} | Public exchange; 401 token sai, 403 account bị chặn, 503 provider lỗi. |
| GET /auth/me | 200 {user_id, display_name, status, memberships, permissions, requires_password_change} | Phiên hợp lệ, kể cả phiên hạn chế; không trả secret hoặc ORM thô. |
| POST /auth/logout | Không body → 204; thu hồi phiên hiện tại | Phiên hiện tại; FE xóa token và signOut Firebase. |
| POST /auth/password-reset/request | {email} → 202 thông báo chung | Public, rate limit; không tiết lộ email tồn tại. Gửi reset link bằng provider đã chốt. |
| POST /auth/password-reset/confirm | {oob_code, new_password} → 204 | BE adapter xác minh/hoàn tất với Firebase; code hết hạn/sai trả 400. Không kiểm tra bằng token DB tự chế. |
| POST /auth/change-password | {new_password, recent_id_token} → 204 và yêu cầu login lại | Phiên hợp lệ/hạn chế; UID phải trùng, xác thực gần đây, mật khẩu tạm chưa hết hạn. |

## Quy ước validation và lỗi

Dùng UUID, timestamp UTC ISO 8601 và schema Pydantic rõ ràng. Không trim/cắt mật khẩu. Chuẩn hóa email theo chính sách thống nhất; không tự gộp hai người dùng chỉ dựa vào phép lowercase. Chính sách mật khẩu phải đồng bộ với Firebase.

Envelope lỗi: {"error":{"code":"ACCOUNT_BLOCKED","message":"...","request_id":"..."}}. Thống nhất 401 chưa xác thực; 403 thiếu quyền; 404 tài nguyên không nhìn thấy; 409 xung đột trạng thái; 422 input; 429 quá giới hạn; 503 dependency lỗi.

## Tiêu chí nghiệm thu auth

Token sai và token thu hồi đều bị chặn; logout xong token không dùng lại được; restart không đổi mật khẩu; phiên hạn chế không gọi được nghiệp vụ; reset không dò được danh sách email. Password reset thành công phải làm phiên cũ mất hiệu lực, kể cả phiên ứng dụng độc lập với Firebase.

# 7 Luồng đăng ký và cấp Business

Tách duyệt hồ sơ, tạo dòng họ, cấp Owner và kích hoạt thành các bước có trạng thái. Duyệt hồ sơ không mặc định đồng nghĩa tài khoản dùng được ngay hoặc đã thanh toán.

| **Bước** | **Điều kiện và cập nhật** | **Kết quả** |
| --- | --- | --- |
| 1 Đăng ký | Guest gửi thông tin đại diện, clan_name, requested_plan_id. Validate gói được phép chọn; sinh tracking secret và chỉ lưu hash. | PENDING và lịch sử đăng ký; trả mã theo dõi một lần. |
| 2 Duyệt | SA đọc hồ sơ; khóa bản ghi hoặc cập nhật có điều kiện status=PENDING. APPROVED hoặc REJECTED; từ chối cần lý do. | Lưu reviewer, thời điểm và status history trong cùng transaction. |
| 3 Tạo Business | Hồ sơ APPROVED. Tạo clans, profile tối thiểu, subscription theo gói; unique registration_id chống trùng. | Clan PENDING; chưa cấp quyền từ payload của Guest. |
| 4 Cấp Owner | Kiểm tra clan và Owner hiện hữu. Cấp Firebase identity và users/metadata; gắn membership, role và ownership có kiểm soát. | Account PENDING, bắt buộc đổi mật khẩu. Lưu trạng thái job để retry. |
| 5 Gửi thông tin | Gửi email mật khẩu tạm theo FR-SA-09; thời hạn cấu hình. Không ghi mật khẩu rõ vào DB, log hoặc response quản trị. | Lưu delivery attempts; gửi thất bại cho phép retry an toàn. |
| 6 Kích hoạt | Kiểm tra duyệt, gói và account hợp lệ; áp dụng quy tắc kích hoạt D03. Người dùng đổi mật khẩu lần đầu. | Cập nhật ACTIVE khi đủ điều kiện, có audit; không tự giả lập thanh toán thành công. |

## Chống trùng và xử lý lỗi ngoài database

API tạo Business/cấp Owner nhận Idempotency-Key; cùng key và cùng payload trả kết quả cũ, khác payload trả 409. Khóa/unique ở DB bảo vệ hai request đồng thời; kiểm tra tồn tại bằng SELECT đơn thuần không đủ.

Đề xuất một job cấp tài khoản/email có trạng thái bền vững và khóa xử lý, bổ sung bằng migration nếu thiếu. Firebase UID được ràng buộc với job để retry không tạo identity trùng. Job có trạng thái chờ, thành công, lỗi có thể retry; quyền chưa hoàn tất thì account chưa được sử dụng.

Không gửi email trong transaction DB. Nếu mật khẩu chỉ tồn tại trong bộ nhớ và gửi lỗi, lần retry cấp mật khẩu tạm mới rồi gửi lại; không reset mật khẩu tài khoản đã kích hoạt. Nếu cần lưu payload để retry, phải mã hóa, giới hạn thời gian lưu và xóa sau gửi; email log hiện tại chưa cung cấp cơ chế này.

# 8 Hợp đồng API Business và người dùng

| **API đề xuất** | **Input hoặc output** | **Quyền** |
| --- | --- | --- |
| GET /service-plans | Danh sách gói public và giới hạn được công bố | Guest |
| POST /business-registrations | Thông tin đại diện, clan_name, origin_place, requested_plan_id → 201 registration_id và tracking_code | Guest; rate limit |
| POST /business-registrations/track | {tracking_code} → trạng thái và lý do được phép công bố | Guest; không trả danh sách hồ sơ |
| GET /admin/business-registrations | Lọc status, phân trang; GET /{id} xem chi tiết | SA |
| POST /admin/business-registrations/{id}/review | {decision, reason} → trạng thái mới; decision APPROVED hoặc REJECTED | SA; 409 nếu trạng thái đã đổi |
| POST /admin/business-registrations/{id}/business | Tạo clan/subscription → 201 clan_id | SA; Idempotency-Key |
| POST /admin/clans/{id}/owner | Cấp Owner → **201** kèm owner và mật khẩu tạm (hiện một lần); GET /admin/provisioning-jobs/{id} xem job; thêm danh sách job, `retry`, `abandon` và `POST /admin/clans/{id}/owner/temporary-password` (E6b) | SA; Idempotency-Key cho POST cấp Owner |
| POST /admin/clans/{id}/activate | Kích hoạt nếu đủ điều kiện → 200 trạng thái clan và gói; thêm `GET /admin/clans/{id}` (đọc) | SA; D03 đã chốt: xác nhận thủ công, không kiểm thanh toán (Sprint 6); không Idempotency-Key |
| GET /admin/users và GET /admin/users/{id} | Thông tin tài khoản tối thiểu; lọc/pagination | SA quản trị tài khoản |
| PATCH /admin/users/{id}/status | {status, reason} → 200; khóa/disable thu hồi phiên | SA; kiểm tra chuyển trạng thái |
| GET /clans/{id}/users | Danh sách tài khoản thuộc clan | BO hoặc FA được cấp quyền |
| PUT /clans/{id}/admins/{user_id}/permissions | {permission_codes} → bộ quyền hiệu lực | BO; không cấp vượt quyền được ủy quyền |

Các đường dẫn trên là contract đề xuất để triển khai, không phải API đã có trong main. List dùng page, page_size tối đa 100; response {items,total,page,page_size}. Không trả credential metadata nhạy cảm hoặc tracking hash.

NEED_SUPPLEMENT và luồng sửa/nộp lại hồ sơ, cấp tài khoản Member hàng loạt, chuyển Owner và sửa gói đang dùng cần xác nhận phạm vi trước khi bổ sung endpoint. Không suy từ bảng đã có ra yêu cầu phải code toàn bộ trong Sprint 1.

# 9 Phân quyền và chuyển trạng thái

| **Vai trò** | **Cho phép trong Sprint 1** | **Giới hạn bắt buộc** |
| --- | --- | --- |
| SA | Duyệt hồ sơ; tạo/kích hoạt Business; cấp Owner; quản trị trạng thái user | Không tự động được xem dữ liệu gia phả PRIVATE. Hỗ trợ cần support_access_grants hợp lệ. |
| BO | Xem user cùng clan; quản lý quyền FA trong phạm vi được phép | Owner của clan A không được đọc/sửa clan B; không tự cấp SA. |
| FA | Các chức năng được Owner ủy quyền rõ ràng | Kiểm tra assignment, permission và branch/clan; không suy quyền từ nhãn FA đơn thuần. |
| ME | Đăng nhập, logout, đổi/reset mật khẩu, xem thông tin tài khoản bản thân | Không có quyền quản trị tài khoản khác hoặc nâng vai trò. |
| Guest | Xem gói, gửi và theo dõi hồ sơ bằng mã bí mật | Không liệt kê user, hồ sơ hoặc tự đăng ký thành Owner. |

## Một cách kiểm tra quyền dùng chung

Dependency lấy principal từ phiên; policy nhận action và resource scope. Repository luôn lọc clan_id với tài nguyên tenant. Kiểm tra membership, assignment và quyền đang hiệu lực trên DB; không chỉ đọc role đã nhúng trong token. Mặc định từ chối khi thiếu chính sách.

Khóa tài khoản, thu hồi role hoặc membership phải có hiệu lực từ request tiếp theo. Tránh tự khóa tài khoản SA cuối cùng; việc cấp SA và thay Owner không nằm trong API chỉnh sửa user chung.

## Đối chiếu trạng thái với schema

users.status cho phép PENDING, ACTIVE, LOCKED, SUSPENDED, DISABLED. FR dùng PENDING_ACTIVATION: biểu diễn bằng PENDING cùng cờ bắt buộc đổi mật khẩu; không ghi chuỗi ngoài CHECK constraint.

business_registrations.status có DRAFT, PENDING, APPROVED, NEED_SUPPLEMENT, REJECTED, CANCELLED. Sprint cơ bản dùng PENDING → APPROVED/REJECTED; các cạnh khác chỉ mở khi chốt yêu cầu.

clans.status độc lập với users.status. Một user có thể thuộc nhiều clan; khóa một Business không mặc định khóa toàn bộ tài khoản trên các clan khác.

Xác minh index unique Owner đang hiệu lực trong pg_indexes. Nếu thiếu điều kiện partial index ở file export, kiểm tra DB thật trước khi đề xuất migration.

## Audit

Ghi actor, action, target, clan, trạng thái trước/sau, thời gian và request_id cho duyệt, cấp quyền, khóa và kích hoạt. Không đưa password, bearer token, Firebase ID token hoặc reset code vào audit.

# 10 Danh sách công việc theo thứ tự code

| **Mốc** | **Việc thực hiện và vị trí chính** | **Điều kiện hoàn tất** |
| --- | --- | --- |
| A Nền tảng | db/postgres.py; core/config.py; main.py; .env.example. Xác nhận branch, startup SELECT 1, readiness, CORS theo origin FE. | App chạy đúng branch, lỗi DB quan sát được, không sửa schema khi startup. |
| B Model và migration | models/user_access, models/family, models/registry; alembic/env.py và versions. Chỉ map bảng cần dùng. | ORM trùng schema; baseline dựng được DB test; migration không thay bảng ngoài phạm vi. |
| C Contract và policy | schemas; dependencies/auth.py và permissions.py; seed role/permission dev riêng. | OpenAPI thống nhất với FE, có fixture SA/BO/FA/ME ở hai clan. |
| D Auth | controllers/auth_access; integrations/firebase.py. Session, logout, reset, first password change. | Kiểm thử token, revoke, hạn chế first-login và lỗi provider đạt. |
| E Business | controllers/family_management; repositories; provisioning job; email adapter. | Guest → duyệt → clan → Owner → đổi mật khẩu hoạt động; retry không tạo trùng. |
| F Users và RBAC | Danh sách, khóa, permission FA và scope tenant. | Role bị thu hồi có hiệu lực; không truy cập chéo clan; SA private bị chặn. |
| G Tích hợp và bàn giao | tests; docs/api.md; README; .env.example; migration và ảnh/kết quả demo. | FE dùng API thật, toàn bộ kiểm thử chặn lỗi nghiêm trọng đạt, PR có hướng dẫn áp dụng. |

## Làm phần nào trước khi các quyết định còn mở

Có thể bắt đầu A, đối chiếu model B, dựng request/response và policy C ngay. Chốt D01 trước khi code mật khẩu; chốt D02 trước khi chốt vị trí use case; chốt D03 trước luồng kích hoạt. Không cần chờ email thật để viết adapter và test lỗi gửi.

## Ước lượng để lên lịch

Lấy 102 giờ code trong WBS làm mốc tham chiếu. Đề xuất cộng 12–20 giờ nền tảng/schema, 24–32 giờ kiểm thử và tích hợp, 12–20 giờ dự phòng: khoảng 150–174 giờ công. Đây là ước lượng lập kế hoạch, cần cập nhật sau A và sau khi chốt D01; không cam kết hoàn thành toàn bộ bằng một người trong hai tuần.

# 11 Kiểm thử bắt buộc trước khi bàn giao

Dùng PostgreSQL/Neon test branch riêng; không dùng SQLite để kết luận về FK, CHECK, UUID, partial index hay transaction PostgreSQL. Unit test policy/validation; integration test API + DB; adapter Firebase/email có bản giả lập và ít nhất một luồng thử trên môi trường dev thật.

| **Nhóm** | **Tình huống phải kiểm thử** | **Kết quả mong đợi** |
| --- | --- | --- |
| T01–03 Auth | Token giả/hết hạn/đã revoke; UID lạ; account khóa | 401/403 đúng quy ước; không tạo quyền tự động. |
| T04–06 Phiên | Logout; hết hạn; restart ứng dụng | Phiên thu hồi/hết hạn bị chặn; restart không đổi tài khoản. |
| T07–09 Mật khẩu | Mật khẩu tạm hết hạn; first-login gọi Business; đổi mật khẩu thành công | Chặn đúng; chỉ phiên hạn chế được đổi; phiên cũ mất hiệu lực. |
| T10–12 Reset | Email có/không tồn tại; code sai/hết hạn/dùng lại; spam request | Response không lộ email; code không tái sử dụng; có giới hạn. |
| T13–15 Tenant | BO A gọi tài nguyên B; FA thiếu quyền; ME tự nâng role | 403/404 theo contract, không rò dữ liệu hoặc thay quyền. |
| T16–18 Quyền | Thu hồi membership/role; SA xem PRIVATE; sửa field nhạy cảm ngoài schema | Hiệu lực ngay; cần support grant; Pydantic/policy từ chối. |
| T19–21 Duyệt | Hồ sơ trùng; hai SA duyệt đồng thời; tạo clan khi chưa duyệt | Không tạo trùng; một chuyển trạng thái thắng; chặn sai thứ tự. |
| T22–24 Cấp Owner | Hai request đồng thời; retry cùng key; key cũ với payload khác | Một Owner hiệu lực; trả kết quả cũ hoặc 409; không tạo Firebase user trùng. |
| T25–27 Lỗi ngoài DB | Firebase timeout; email lỗi; Firebase thành công nhưng DB lỗi | Có trạng thái retry/reconcile; không cấp quyền nửa chừng, không lộ mật khẩu. |
| T28–30 Migration | DB trống; DB baseline; rollback hoặc forward-fix trên test branch | Nâng cấp tái lập được; giữ dữ liệu; không cần startup ALTER. |
| T31–33 Tích hợp | CORS FE; luồng Guest đến Owner; log lỗi | FE đọc đúng schema; flow hoàn chỉnh; log có request_id, không có secret. |

Ưu tiên kiểm thử hành vi và rủi ro thật. Không dùng mock cho mọi kiểm tra constraint/đồng thời. Race test phải dùng hai transaction/request độc lập; provider failure cần kiểm tra dữ liệu sau lỗi, không chỉ HTTP status.

# 12 Quy trình nhánh và tiêu chí hoàn thành

## Git và Neon là hai loại nhánh khác nhau

Git branch chứa code và migration, ví dụ feature/sprint1-auth-business. Neon branch chứa schema và dữ liệu môi trường làm việc, ví dụ dev_minhquan. Tạo Git branch không tự đổi database; kiểm tra DATABASE_URL trước mỗi lần chạy migration.

Cập nhật code nền đã được nhóm duyệt, tạo Git branch và xác nhận Neon branch của mình đã khớp baseline.

Commit theo mốc A–G. Khi cần sửa DB, tạo revision Alembic mới và thử trên branch test/cá nhân; ghi cả cách áp dụng và rollback/forward-fix.

Mở PR kèm contract, migration, test evidence và hướng dẫn demo. Nhóm trưởng review rồi áp dụng migration đã duyệt lên môi trường chung.

Không đẩy .env, service-account JSON hoặc dữ liệu thật lên Git. .env.example chỉ chứa placeholder; thông tin kết nối từng xuất hiện trong repo cần nhóm trưởng thay thế nếu còn hiệu lực.

## Cấu hình cần có trên máy lập trình

| **Biến hoặc cấu hình** | **Mục đích** |
| --- | --- |
| DATABASE_URL | Kết nối branch cá nhân; secret chỉ lưu ở môi trường local/deploy. |
| Firebase project và Admin credentials | Project ID, phương thức cấp credentials; email/password provider và domain FE được bật đúng. |
| FRONTEND_ORIGINS và FRONTEND_URL | CORS cho origin cụ thể và URL quay về sau reset; không dùng wildcard với credentials. |
| SESSION_TTL và TEMP_PASSWORD_TTL | Thời hạn cấu hình theo chính sách được duyệt. |
| Email provider và cấu hình gửi | Sender, template và thông tin xác thực local; mock/sandbox khi phát triển. |

Tên biến ngoài DATABASE_URL là đề xuất; đối chiếu core/config.py khi triển khai. Chạy từ BE: .venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8001. Lệnh Windows này giả định đã tạo .venv và cài requirements.

## Definition of Done

API có OpenAPI và ví dụ request; đủ kiểm thử mục 11; không lỗi phân quyền chéo clan; migration chạy được; FE hoàn thành luồng Sprint 1; lỗi email/provider có đường phục hồi; secrets không ở Git; nhóm trưởng duyệt code và thay đổi schema. Chỉ báo hoàn thành sau khi có bằng chứng chạy, không dựa vào việc endpoint đã xuất hiện trong /docs.

# 13 Quyết định cần chốt và tài liệu căn cứ

| **Mã** | **Đề xuất để nhóm xác nhận** | **Ảnh hưởng** |
| --- | --- | --- |
| D01 Auth | Firebase quản lý toàn bộ email/password và Google; Neon không lưu password_hash. | Chốt trước khi làm reset, first password change và cấp Owner. |
| D02 MVC | Controller chứa use case; Model chứa ORM/repository. Cập nhật chú thích C&C cho thống nhất module view. | Chốt trước khi review cấu trúc thư mục. |
| D03 Kích hoạt | Xác định Business ACTIVE khi nào; gói trial hay xác nhận thủ công; không tích hợp thanh toán thật trong Sprint 1. | Quyết định điều kiện FR-SA-10 và thời điểm Owner được truy cập. |
| D04 Email | Chọn provider dev/sandbox và nơi gửi mật khẩu tạm/reset link; TTL mật khẩu tạm, giới hạn retry. | Cần trước demo luồng cấp tài khoản hoàn chỉnh. |
| D05 Phạm vi | Xác nhận có NEED_SUPPLEMENT, mời Member/FA và cấp quyền chi tiết trong Sprint này hay chỉ phần tối thiểu WBS. | Ngăn mở rộng Sprint từ toàn bộ workbook FR. |

## Thông tin bạn cần cung cấp tiếp

Ưu tiên trả lời D01 và D02, cho biết dịch vụ email dự định dùng và quy tắc kích hoạt D03. Khi bắt đầu sửa code, cung cấp nhánh/commit BE bạn đã chỉnh sau bước database hoặc tải code đã bỏ secrets. Chỉ cần tên Firebase project/provider và trạng thái cấu hình; không gửi mật khẩu, DATABASE_URL đầy đủ hay private key.

## Đối chiếu yêu cầu chức năng

Authentication: FR-SA-01–03, FR-BO-01–03, FR-FA-01, FR-ME-01–04. First password change là FR-ME-02. Business: FR-GU-05–07 và FR-SA-04–10. Quản trị tài khoản tham chiếu FR-SA-17, FR-SA-19; phần cấp quyền FA tham chiếu FR-BO-14–16 và phải đối chiếu D05. Mapping Sprint được suy từ WBS, không phải nhãn Sprint có sẵn cho mọi FR.

Điểm cần làm rõ trong đặc tả: precondition “đã đăng nhập” ở một số chức năng login/reset không phù hợp luồng public; FR-GU-06 có mô tả giống nâng gói. Plan hiểu đây là chọn gói lúc đăng ký và yêu cầu nhóm xác nhận khi chốt contract.

## Căn cứ dùng cho bản cập nhật

Project Plan C1SE.19 ver1.2 bản (2), mục WBS 3.1.8; Đặc Tả FR.xlsx được cung cấp trong cuộc trao đổi; ba ảnh module, C&C và deployment; schema Neon mfgms_ai_production_schema(1).sql; repository BE main được đọc ngày 05/10/2026. Nếu nhóm đổi FR hoặc schema sau các snapshot này, cập nhật mapping trước khi viết migration.

Repository: https://github.com/Thu-Thao21/MULTI-FAMILY-GENEALOGY-BE

Firebase: https://firebase.google.com/docs/auth/admin/manage-sessions ; https://firebase.google.com/docs/auth/admin ; https://firebase.google.com/docs/reference/rest/auth . Tham khảo để xác minh ID token, quản lý user và reset password, không thay thế chính sách nghiệp vụ của nhóm.

05 10 2026  •  Trang
