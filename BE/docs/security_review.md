# Rà soát bảo mật — Mốc G

Ngày: 06/10/2026. Phạm vi: các endpoint đã cài (xác thực, quản trị người dùng, ủy quyền Family Admin), cấu hình khởi động, CORS, Docker và phụ thuộc. Mốc E (đăng ký Business, cấp Owner) chưa có nên chưa rà.

**Quy ước:** chỉ ghi điều đã kiểm chứng. Mỗi dòng nêu cách kiểm chứng: **Test** (tên test, chạy tự động), **Code** (đã đọc đoạn mã nêu tên), **Công cụ** (chạy ngày nêu). Điều chưa kiểm chứng nằm ở mục 8, không rải trong bảng.

## 1. Danh tính và phiên

| # | Kiểm tra | Kết quả | Cách kiểm chứng |
| --- | --- | --- | --- |
| 1.1 | Không có nhánh giải mã JWT không kiểm chữ ký (KI-01) | Đạt | **Test** `test_no_insecure_auth.py::test_app_code_has_no_insecure_auth_pattern[verify_signature]` (quét mã nguồn `app/`). **Code** `app/core/firebase.py`: xác minh chỉ qua `firebase_auth.verify_id_token` |
| 1.2 | SDK thật từ chối token giả mạo: `alg: none`, HS256, thiếu `kid`, sai project, rác; token RS256 hợp lệ về hình thức luôn đi tới bước kiểm chữ ký theo chứng chỉ `securetoken` với audience đúng | Đạt (không cần mạng) | **Test** `test_firebase_provider.py::test_real_sdk_rejects_forged_tokens`, `test_real_sdk_rejects_token_for_another_project`, `test_real_sdk_always_reaches_signature_check` |
| 1.3 | Fail closed khi cấu hình Firebase sai: thiếu `FIREBASE_PROJECT_ID`, có `FIREBASE_AUTH_EMULATOR_HOST` (SDK nhận token không chữ ký), `FIREBASE_SERVICE_ACCOUNT_PATH` trỏ file không tồn tại | Đạt: đăng nhập trả `503`, và app **dừng khi khởi động** | **Test** `test_firebase_provider.py::test_missing_project_id_fails_closed`, `::test_emulator_env_is_refused`, `::test_service_account_path_set_but_missing_fails_closed`; `test_startup_checks.py::test_startup_stops_on_bad_firebase_config_before_touching_the_db` |
| 1.4 | Thông báo lỗi cấu hình chỉ nêu tên biến, không nêu giá trị | Đạt | **Test** `test_startup_checks.py::test_all_problems_are_reported_together_without_values`, `::test_startup_failure_is_logged_without_values` |
| 1.5 | UID lạ không tạo user; không nối tài khoản theo email; trả cùng lỗi với token sai | Đạt | **Test** `test_auth_api.py::test_unknown_uid_is_rejected_without_creating_a_user`, `::test_same_email_different_uid_is_not_linked`; DB thật: `integration/test_auth_flow_db.py::test_unknown_uid_creates_no_user_and_no_history` |
| 1.6 | Token phiên 256 bit ngẫu nhiên; chỉ lưu SHA-256, token thô không là khóa tra cứu | Đạt | **Code** `app/core/tokens.py` (`secrets.token_urlsafe(32)`, `hashlib.sha256`). **Test** DB thật `integration/test_sessions_db.py::test_token_is_stored_as_sha256_not_raw` |
| 1.7 | Token phiên chỉ xuất hiện trong đúng một response (`SessionCreateResponse`) | Đạt | **Test** `test_security_checks.py::test_the_bearer_token_is_returned_by_exactly_one_response` (duyệt mọi schema response trong OpenAPI) |
| 1.8 | Phiên hết hạn, đã thu hồi, tài khoản bị khóa, phiên cũ hơn lần đổi mật khẩu đều bị chặn mỗi request | Đạt | **Test** DB thật `integration/test_sessions_db.py` (hết hạn, thu hồi, `LOCKED/SUSPENDED/DISABLED`, `password_changed_at`) |
| 1.9 | Phiên hạn chế chỉ dùng được `/auth/me`, `/auth/change-password`, `/auth/logout`; kể cả System Admin | Đạt | **Test** `test_auth_dependency.py`, `integration/test_http_access.py::test_restricted_session_reaches_only_the_three_auth_routes`, `::test_restricted_system_admin_is_still_blocked_on_business_routes` |
| 1.10 | Không có kho mật khẩu cục bộ; `core/security.py` (bcrypt, KI-02) đã xóa | Đạt | **Test** `test_no_insecure_auth.py` (không còn `bcrypt`, `passlib`, `hash_password`; `requirements.txt` không chứa) |
| 1.11 | Đổi mật khẩu: kiểm tra UID khớp và `auth_time` trong 300 giây; thu hồi mọi phiên; ID token cũ bị từ chối; Firebase lỗi thì DB không đổi | Đạt (với Firebase giả) | **Test** `test_auth_api.py::test_first_password_change_activates_account_and_revokes_sessions`, `::test_change_password_rejects_token_of_another_user`, `::test_change_password_requires_recent_sign_in`, `::test_change_password_provider_down_changes_nothing`; DB thật `integration/test_auth_flow_db.py::test_first_password_change_end_to_end` |

## 2. Phân quyền và cô lập dòng họ

| # | Kiểm tra | Kết quả | Cách kiểm chứng |
| --- | --- | --- | --- |
| 2.1 | Mặc định từ chối: action chưa khai báo bị từ chối; mọi action có luật | Đạt | **Test** `test_permissions.py::test_unknown_action_is_denied`, `::test_every_action_has_a_rule` |
| 2.2 | Quyền đọc lại từ database ở mỗi request, không lấy từ token; thu hồi vai trò hay quyền có hiệu lực ngay | Đạt | **Test** DB thật `integration/test_http_access.py::test_revoking_bo_role_takes_effect_on_next_request`; `integration/test_user_admin_db.py::test_bo_replaces_permissions_with_immediate_effect_and_audit` |
| 2.3 | Dòng họ khác → `404`; thiếu quyền trong dòng họ mình → `403`; dòng họ chưa `ACTIVE` chặn BO/FA nhưng không chặn `/auth/*`; SA không có quyền ngầm trong dòng họ | Đạt | **Test** DB thật `integration/test_http_access.py` (BO, FA, dòng họ không `ACTIVE`, SA), `integration/test_user_admin_db.py::test_clan_users_access_rules_on_db` |
| 2.4 | Mọi truy vấn của repository nhận `clan_id` đều lọc theo `clan_id` trong `WHERE` | Đạt | **Test** `test_security_checks.py::test_every_query_taking_clan_id_filters_by_it` (chạy từng phương thức với session giả, biên dịch SQL và kiểm `WHERE`) |
| 2.5 | Phương thức của `FamilyRepository` **không** nhận `clan_id` đều có lý do được ghi (tài nguyên toàn cục, tra theo mã bí mật, hoặc khóa theo `user_id`/`assignment_id` đã lọc theo clan); thêm phương thức mới buộc phải quyết định | Đạt | **Test** `test_security_checks.py::test_family_repository_methods_without_clan_id_are_all_accounted_for` (bảng lý do nằm trong file test) |
| 2.6 | Danh sách người dùng của clan không bao giờ lẫn người ở clan khác; `roles` chỉ là vai trò trong clan đó | Đạt | **Test** DB thật `integration/test_user_admin_db.py::test_clan_users_never_lists_another_clan` |
| 2.7 | `PUT .../permissions`: chỉ BO; mã phải có trong bảng `permissions` (lạ → `422`); mã không được ủy quyền `ADMIN_MANAGE` → `403` (kể cả khi assignment cũ đã giữ mã đó); BO clan khác nhận `404` | Đạt | **Test** `test_user_admin_api.py::test_put_rejects_admin_manage_with_403`, `::test_put_keeping_an_existing_admin_manage_is_403_and_dropping_it_works`; DB thật `integration/test_family_admin_lifecycle_db.py::test_non_delegable_code_is_403_on_post_and_put_and_unknown_is_422`, `integration/test_user_admin_db.py` |
| 2.8 | Không thể khóa/vô hiệu hóa System Admin cuối cùng, kể cả tự khóa; không deadlock khi hai SA khóa nhau | Đạt | **Test** DB thật `integration/test_user_admin_db.py`, `integration/test_user_admin_concurrency.py` (hai transaction song song, có test đối chứng tái hiện deadlock). **Code** khóa dòng `FOR NO KEY UPDATE` (`user_access/repository.py::get_user_for_update`) |
| 2.9 | Đề bạt và thu hồi Family Admin chỉ do BO của clan `ACTIVE` làm; FA (kể cả có `MEMBER_ACCOUNT_MANAGE`) và thành viên thường nhận `403`; BO clan khác và System Admin nhận `404`; người không phải thành viên `ACTIVE` của clan nhận `404` (không đề bạt được người của clan khác); chủ họ và người còn vai trò BO không đề bạt được (`409`); quyền được kiểm trước validation | Đạt | **Test** `test_user_admin_api.py::test_assign_access_rules`, `::test_revoke_access_rules`, `::test_target_must_be_an_active_member_of_this_clan`, `::test_the_owner_and_other_business_owner_role_holders_cannot_be_appointed`, `::test_authorization_wins_over_validation_for_assign`; DB thật `integration/test_family_admin_lifecycle_db.py::test_access_rules_for_appoint_and_revoke`, `::test_target_rules_on_db` |
| 2.10 | Thu hồi Family Admin có hiệu lực ngay ở request kế tiếp, xóa mọi dòng permission, đặt `revoked_at` cho assignment và dòng vai trò `FAMILY_ADMIN`; thu hồi mọi assignment còn hiệu lực của user (kể cả theo chi/ngành và trùng) nhưng không đụng người khác | Đạt | **Test** `test_user_admin_api.py::test_bo_revokes_a_family_admin_with_immediate_effect`, `::test_revoke_takes_every_active_assignment_including_branch_limited_and_duplicates`; DB thật `integration/test_family_admin_lifecycle_db.py::test_revoke_deletes_permissions_revokes_assignment_and_role_with_immediate_effect`, `::test_revoke_takes_every_active_assignment_and_leaves_other_users_alone` |
| 2.11 | Hai đề bạt đồng thời cho cùng một user: chỉ một thành công (code bảo vệ bằng khóa dòng membership; unique ở DB cho assignment, KI-08, nằm trong migration `0002`, **đã áp dụng lên dev_minhquan, production chưa**); PUT với DELETE, DELETE với POST không để lại quyền trên assignment đã thu hồi, không deadlock, không lỗi 500 | Đạt (với đột biến đã thử, xem `testing.md` mục 8) | **Test** DB thật `integration/test_family_admin_concurrency.py` (commit thật, dữ liệu `itest-conc-`, có test đối chứng tái hiện assignment trùng khi bỏ khóa) |

## 3. Dữ liệu và rò rỉ

| # | Kiểm tra | Kết quả | Cách kiểm chứng |
| --- | --- | --- | --- |
| 3.1 | Không schema response nào có `firebase_uid`, `token_jti_hash`, `tracking_code_hash`, `storage_key`, mật khẩu hay metadata xác thực nhạy cảm | Đạt | **Test** `test_security_checks.py::test_no_response_schema_exposes_sensitive_fields` (mọi schema tới được từ response trong OpenAPI); thêm kiểm response thật ở `test_user_admin_api.py`, `integration/test_user_admin_db.py` (không chứa `firebase_uid`) |
| 3.2 | Trường bí mật trong request (`id_token`, `recent_id_token`, `oob_code`, mật khẩu) đều là `SecretStr`; không hiện trong `repr`, JSON dump hay lỗi validation | Đạt | **Test** `test_security_checks.py::test_every_secret_looking_request_field_is_secretstr`, `::test_secrets_do_not_appear_in_repr_or_validation_errors` |
| 3.3 | Không log ID token, bearer token, UID, email: kiểm khi chạy và kiểm tĩnh mọi lời gọi `logger.*` | Đạt | **Test** `test_auth_api.py::test_no_token_or_uid_in_logs` (chạy), `test_security_checks.py::test_no_logging_call_takes_a_secret_looking_value`, `::test_log_message_templates_do_not_interpolate_exception_text` (quét AST toàn bộ `app/`) |
| 3.4 | Lỗi `422` chỉ nêu tên trường, không lặp lại giá trị; lỗi `500` và `503` không có thông điệp lỗi hay chi tiết driver | Đạt | **Test** `test_cors.py::test_unhandled_500_is_the_standard_envelope_without_internal_detail`, `::test_db_unavailable_does_not_leak_the_driver_message`, `test_auth_api.py::test_change_password_too_short_never_reaches_firebase` |
| 3.5 | `audit_logs` không chứa mật khẩu, token, `firebase_uid` hay email | Đạt (cho các luồng đang ghi audit: đổi mật khẩu, đổi trạng thái, sửa quyền, đề bạt và thu hồi FA) | **Test** `test_auth_api.py::test_first_password_change_activates_account_and_revokes_sessions`, `test_user_admin_api.py::test_lock_revokes_every_session_and_audits`, `::test_bo_appoints_a_member_and_it_takes_effect_at_once`, `::test_bo_revokes_a_family_admin_with_immediate_effect` |
| 3.6 | Chuỗi `DATABASE_URL` sai định dạng **không** hiện (kể cả một phần) trong lỗi hay log khởi động (KI-13) | Đạt sau khi sửa. Trước khi sửa: lộ cả mật khẩu | **Test** `test_config_secrets.py` (5 dạng sai, mật khẩu giả, subprocess, stdout + stderr + log DEBUG) |

## 4. Truy vấn và nhập liệu

| # | Kiểm tra | Kết quả | Cách kiểm chứng |
| --- | --- | --- | --- |
| 4.1 | Không dựng SQL bằng nối chuỗi; `text()` chỉ nhận hằng chuỗi (server default, điều kiện index); câu lệnh SQL thô duy nhất là `SELECT 1` | Đạt | **Test** `test_security_checks.py::test_every_text_fragment_is_a_plain_string_literal`, `::test_the_only_executed_statement_text_is_the_connectivity_probe`, `::test_no_sql_is_formatted_from_strings` |
| 4.2 | Tìm kiếm `q` escape ký tự đại diện của `LIKE` (`%`, `_`, `\`) | Đạt | **Test** DB thật `integration/test_user_admin_db.py::test_search_escapes_like_wildcards` |
| 4.3 | Body có trường lạ bị từ chối; phân trang giới hạn `page_size` ≤ 100 | Đạt | **Test** `test_auth_api.py::test_session_body_validation`, `test_user_admin_api.py::test_list_users_query_validation` |
| 4.4 | Quyền được kiểm trước khi đọc body/query (người không có quyền không thấy lỗi `422`) | Đạt | **Test** `test_user_admin_api.py::test_authorization_wins_over_validation_errors` |

## 5. CORS và mạng

| # | Kiểm tra | Kết quả | Cách kiểm chứng |
| --- | --- | --- | --- |
| 5.1 | Mọi loại response (200, 401, 403, 404, 405, 422, 503, **500**) và preflight có header CORS đúng với origin được phép | Đạt sau khi sửa. Trước khi sửa: 500 không có header CORS (KI-12) | **Test** `test_cors.py` (2 origin x 8 loại response; test trên app thật) |
| 5.2 | Origin lạ không nhận `Access-Control-Allow-Origin` trên bất kỳ response nào, kể cả lỗi 500; preflight từ origin lạ bị từ chối | Đạt | **Test** `test_cors.py::test_foreign_origin_gets_no_cors_headers_on_any_response`, `::test_preflight_from_foreign_origin_is_refused` |
| 5.3 | `X-Request-ID` có trên mọi response và được expose cho JS cùng `Retry-After` | Đạt | **Test** `test_cors.py::test_request_id_is_generated_or_echoed_even_on_500`, `assert_cors_ok` |
| 5.4 | Origin `*` không được chấp nhận (không dùng wildcard với credentials) | Đạt: app dừng khi khởi động | **Test** `test_startup_checks.py::test_wildcard_origin_is_a_problem`, `::test_startup_stops_on_wildcard_origin` |
| 5.5 | Ứng dụng không dùng cookie (không có CSRF theo cookie) | Đạt | **Code** không có `set_cookie` hay đọc cookie nào trong `app/`; xác thực chỉ bằng header `Authorization` |

## 6. Docker và phụ thuộc

| # | Kiểm tra | Kết quả | Cách kiểm chứng |
| --- | --- | --- | --- |
| 6.1 | Image build thành công trên Python 3.13 với phiên bản ghim | Đạt | **Công cụ** `docker build` ngày 06/10/2026 (Docker 23.0.5); phiên bản cài khớp bộ đã test (fastapi 0.142.2, uvicorn 0.54.0, sqlalchemy 2.1.3, psycopg 3.3.6, firebase-admin 7.7.0, alembic 1.20.0...) |
| 6.2 | `/app` trong image chỉ có `app/`, `alembic/`, `alembic.ini`, `requirements.txt`; không có `.env`, file service account, `scripts/`, `tests/`, `docs/`, `.git` | Đạt | **Công cụ** xuất hệ thống file của image (không chạy container) rồi liệt kê, ngày 06/10/2026 |
| 6.3 | Chạy bằng user không phải root; có `HEALTHCHECK`; chỉ `EXPOSE 8000` | Đạt | **Công cụ** `docker image inspect`, `docker history` |
| 6.4 | Phụ thuộc không có lỗ hổng đã biết | Đạt: "No known vulnerabilities found" | **Công cụ** `pip-audit 2.10.1`, quét các gói cài trong `.venv` của dự án (`--path`), chạy ngày 06/10/2026, cài trong venv tạm ngoài repo, dữ liệu từ PyPI. Chỉ phản ánh thời điểm chạy |
| 6.5 | `.gitignore` và `.dockerignore` chặn `.env`, `*service-account*.json`, `*firebase-adminsdk*.json` | Đạt | **Code** hai file; `git status` không có `.env` |

## 7. Việc đã sửa trong Mốc G từ phát hiện của rà soát

1. KI-12: lỗi 500 không có header CORS (sửa, có test).
2. KI-13: lỗi `DATABASE_URL` in cả chuỗi kết nối (sửa, có test).
3. `X-Request-ID` và `Retry-After` chưa được expose cho JS (sửa).
4. Cấu hình Firebase hoặc CORS sai chỉ lộ ra khi người dùng đăng nhập lỗi; nay app dừng khi khởi động.

## 8. Chưa kiểm chứng hoặc hạn chế đã biết (không phải kết luận "đạt")

- **Chưa có test tự động xác minh chữ ký trên ID token Firebase thật** (mục 1.2 chứng minh phần từ chối và đường dẫn tới bước kiểm chữ ký, không chứng minh chấp nhận token thật). Cách thử tay: `docs/testing.md` mục 4.
- **Chưa có giới hạn tần suất** cho `/auth/session` (KI-06).
- **Không có API reset mật khẩu** (KI-05): sau reset do FE, phiên ứng dụng cũ sống đến khi hết hạn.
- **Khóa tài khoản không đụng Firebase** (KI-10): ID token còn sống tối đa 1 giờ, không đổi được phiên.
- **Ràng buộc DB còn thiếu ở production cho tới khi áp dụng migration `0002`** (**đã áp dụng lên dev_minhquan ngày 06/10/2026, production chưa**, xem `docs/migrations.md`): KI-03 (trùng role SA), KI-04 (token hash không unique), KI-08 (trùng assignment FA: nay được code bảo vệ bằng khóa dòng, nhưng ghi thẳng vào DB vẫn tạo được dòng trùng), và email chỉ unique theo so khớp chính xác (KI-15). Các mục "Đạt" trong tài liệu này về những ràng buộc đó chỉ đúng cho tầng code ở production cho đến khi migration được áp dụng; trên dev_minhquan DB đã chặn (155 test tích hợp pass).
- **Guard chạy migration:** lệnh alembic có kết nối DB cần `ALLOW_MIGRATE=1` và `MIGRATE_EXPECT_FINGERPRINT` khớp (fingerprint của host và database, không in host hay mật khẩu). **Test:** `tests/test_migration_guard.py`.
- **Danh sách mã không được ủy quyền chỉ có `ADMIN_MANAGE`** (KI-09); các mã nhạy cảm khác vẫn ủy quyền được.
- **IP sau reverse proxy** (KI-11).
- **`allow_methods=["*"]` và `allow_headers=["*"]`** trong CORS: rộng hơn mức cần thiết; an toàn hơn khi giới hạn danh sách header/phương thức khi FE đã ổn định. Chưa thu hẹp để tránh làm gãy FE.
- **Không đặt security header** (HSTS, `X-Content-Type-Options`...) trong ứng dụng; thường do reverse proxy đảm nhiệm. Chưa kiểm.
- **TLS** (HTTPS) thuộc hạ tầng triển khai, chưa kiểm.
- **Container chưa được chạy** và **chưa quét CVE của image** (KI-14).
- **Kiểm tĩnh việc ghi log (3.3)** chỉ thấy các lời gọi `logger.<mức>(...)` bằng tên biến; không chứng minh được mọi đường dữ liệu động.
- **Test 2.4** chạy với session giả: chứng minh `WHERE` có `clan_id`, không chứng minh kết quả trên dữ liệu thật (phần đó do các test tích hợp ở 2.3 và 2.6 đảm nhiệm).
- **Mốc E** (đăng ký Business, cấp Owner, Idempotency-Key, job cấp tài khoản) chưa có nên chưa rà.
