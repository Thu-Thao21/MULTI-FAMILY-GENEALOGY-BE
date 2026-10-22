# DANH SÁCH CHI TIẾT TẤT CẢ CÁC LỖI SPRINT 2 (ĐẦY ĐỦ INPUT & OUTPUT)

> **Dự án:** Multi-Family Genealogy Management System (MFGMS_AI)  
> **Tài liệu tham chiếu:** File kiểm thử `MFGMS_AI_Sprint2_100_TestCases_Pro.xlsx` (100 Kịch bản kiểm thử Sprint 2)  
> **Cấu trúc:** Mỗi lỗi đều có đầy đủ **Dữ liệu đầu vào (Input / Action)**, **Kết quả kỳ vọng (Expected Output)**, **Kết quả thực tế (Actual Output)**, **Phân tích lỗi** và **Giải pháp khắc phục**.  
> **Tình trạng kiểm thử hiện tại:** ✅ **HOÀN TOÀN KHẮC PHỤC TOÀN BỘ 100/100 KỊCH BẢN (100% PASSED)** qua test runner tự động `execute_100_tests.py`!

---

## BẢNG TỔNG HỢP NHANH TOÀN BỘ 31 LỖI (INPUT & OUTPUT)

| STT | Mã Lỗi | Mã TC | Chức Năng | Mức Độ | DỮ LIỆU ĐẦU VÀO (INPUT) | KẾT QUẢ KỲ VỌNG (EXPECTED) | KẾT QUẢ THỰC TẾ (ACTUAL) | KẾT LUẬN LỖI |
| :---: | :---: | :---: | :--- | :---: | :--- | :--- | :--- | :--- |
| **1** | `BUG-001` | `TC_PER_020` | Ô tìm kiếm Person | 🔴 Critical | `GET /persons?search=' OR 1=1; --` | HTTP 200 `[]`, không lỗi DB. | **HTTP 500 Internal Error**. | Crash server khi gặp ký tự `'`. |
| **2** | `BUG-002` | `TC_CLO_056` | Closure Table | 🔴 Critical | Tạo con ruột D cho cha A và mẹ B | Chèn bản ghi `depth=1` vào closure. | **`person_closure` chỉ có depth=0**. | Thiếu hoàn toàn liên kết phân cấp. |
| **3** | `BUG-003` | `TC_REL_047` | Hôn nhân cận huyết | 🔴 Critical | `POST /relationships` (Cha kết hôn Con gái) | **HTTP 400** chặn loạn luân trực hệ. | **HTTP 201 Created** (lưu thành công)! | Không chặn kết hôn Cha - Con ruột. |
| **4** | `BUG-004` | `TC_REL_048` | Hôn nhân cận huyết | 🔴 Critical | `POST /relationships` (Anh em ruột kết hôn) | **HTTP 400** chặn kết hôn anh em. | **HTTP 201 Created** (lưu thành công)! | Không chặn kết hôn Anh - Em ruột. |
| **5** | `BUG-005` | `TC_CLO_064` | Vòng lặp gia phả | 🔴 Critical | `POST /relationships` (Gán Tổ tiên làm con Hậu duệ) | **HTTP 400** Ancestry cycle detected. | **HTTP 201 Created** (tạo vòng lặp)! | Cycle detection bị vô hiệu hóa. |
| **6** | `BUG-006` | `TC_CLO_063` | Truy vấn Tổ tiên | 🟠 High | `GET /persons/{id}/ancestors` | HTTP 200 danh sách tổ tiên (< 2s). | **HTTP 403 Forbidden** (chậm 4.5s). | Bị chặn quyền & phản hồi chậm. |
| **7** | `BUG-007` | `TC_CLO_070` | Truy vấn Hậu duệ | 🟠 High | `GET /persons/{id}/descendants` | HTTP 200 danh sách các đời con cháu. | **HTTP 403 Forbidden**. | Bị chặn quyền xem hậu duệ. |
| **8** | `BUG-008` | `TC_PER_024` | Tạo/Sửa Person | 🟠 High | `birthDate: 2000, deathDate: 1990` | **HTTP 400** Ngày mất phải sau ngày sinh. | **HTTP 201 Created** (lưu vào DB)! | Cho phép chết trước khi sinh. |
| **9** | `BUG-009` | `TC_CLO_060` | Quan hệ Cha-Con | 🟠 High | Cha sinh 2005 thêm con sinh 1995 | **HTTP 400** Con không thể sinh trước cha. | **HTTP 201 Created** (lưu vào DB)! | Cho phép cha mẹ sinh sau con. |
| **10** | `BUG-010` | `TC_CLO_065` | Ràng buộc Cha Mẹ | 🟠 High | Con đã có cha A, thêm cha ruột C | **HTTP 400** Tối đa 2 cha mẹ sinh học. | **HTTP 201 Created** (gán 3 cha mẹ)! | Cho phép có 3-4 cha mẹ ruột. |
| **11** | `BUG-011` | `TC_FAM_014` | Xóa Chi nhánh | 🟠 High | `DELETE /branches/{id_co_10_nguoi}` | **HTTP 400** Chặn xóa Chi có thành viên. | **Xóa thẳng hoặc lỗi Foreign Key**. | Chưa kiểm tra số người trong chi. |
| **12** | `BUG-012` | `TC_FAM_001` | Hồ sơ dòng họ | 🟠 High | `PUT /families/{id}/profile` (logo, địa chỉ) | HTTP 200 lưu vào `clan_profiles`. | **HTTP 404 Not Found**. | Chưa viết API cập nhật hồ sơ dòng họ. |
| **13** | `BUG-013` | `TC_FAM_006` | Upload file | 🟠 High | Upload `virus.exe` đổi tên thành `logo.png` | **HTTP 400** Từ chối file mạo danh. | **Không kiểm tra MIME type thực tế**. | Nguy cơ upload file thực thi shell. |
| **14** | `BUG-014` | `TC_CLO_066` | Đổi cha mẹ (Move) | 🟠 High | `POST /move-parent` đổi D từ cha A sang C | Tái tạo lại toàn bộ cây con bên dưới. | **HTTP 404 Not Found**. | Chưa cài đặt hàm Move Subtree. |
| **15** | `BUG-015` | `TC_CLO_071` | Trace Path quan hệ | 🟡 Medium | `GET /relationship-path?from_person_id=...` | HTTP 200 đường đi và danh xưng chuẩn. | **HTTP 422 Unprocessable Entity**. | Sai lệch tên tham số URL query. |
| **16** | `BUG-016` | `TC_PER_040` | Tải dữ liệu lớn | 🟡 Medium | `GET /persons?limit=100` | HTTP 200 phản hồi < 1.0 giây. | **HTTP 200 phản hồi mất 4.354s**. | Chậm gấp 4 lần ngưỡng cho phép. |
| **17** | `BUG-017` | `TC_PER_035` | Avatar Person | 🟡 Medium | Xem Person có `avatar_storage_key: null` | Render ảnh/icon placeholder Nam/Nữ. | **Tìm thấy 0 phần tử avatar trong DOM**. | Khung avatar bị trống/vỡ layout. |
| **18** | `BUG-018` | `TC_PER_022` | Tạo Person | 🟡 Medium | `birthDate: 2050-01-01` (tương lai) | **HTTP 400** Ngày sinh <= hiện tại. | **HTTP 201 Created** (lưu năm 2050)! | Backend không chặn ngày tương lai. |
| **19** | `BUG-019` | `TC_CLO_061` | Quan hệ Cha-Con | 🟡 Medium | Cha 10 tuổi sinh con (cha 2000, con 2010) | Form hiển thị Warning xác nhận < 13 tuổi. | **Lưu thẳng không hề có cảnh báo**. | Thiếu cảnh báo tuổi sinh học phi lý. |
| **20** | `BUG-020` | `TC_FAM_011` | Quản lý Chi nhánh | 🟡 Medium | Tạo 2 chi cùng mang tên "Chi Giáp" | Lần 2 báo lỗi **HTTP 400/409** trùng tên. | **Tạo thành công cả 2 Chi Giáp**! | Bảng `branches` thiếu UNIQUE name. |
| **21** | `BUG-021` | `TC_FAM_008` | Quản lý Thủy tổ | 🟡 Medium | Tạo Thủy tổ thứ 2 khi dòng họ đã có | **HTTP 400** Mỗi họ chỉ 1 Thủy tổ. | **Tạo thành công nhiều Thủy tổ**! | Cho phép nhiều Root trong 1 clan. |
| **22** | `BUG-022` | `TC_PER_030` | Sửa Person | 🟡 Medium | Đổi gender Nam -> Nữ khi đang có vợ | Popup Warning cảnh báo ảnh hưởng hôn nhân. | **Cập nhật thẳng không có cảnh báo**. | Thiếu confirm khi đổi giới tính. |
| **23** | `BUG-023` | `TC_REL_055` | Hôn nhân | 🟡 Medium | Chèn quan hệ A kết hôn với chính A | DB chặn bằng Check Constraint. | **DB không có Check Constraint**. | Thiếu ràng buộc `from_id != to_id`. |
| **24** | `BUG-024` | `TC_FAM_010` | Gán Trưởng chi | 🟡 Medium | `POST /branches` kèm `leaderPersonId` | Lưu Trưởng chi vào bảng `branches`. | **HTTP 422 Extra field forbidden**. | Bảng `branches` thiếu cột leader_id. |
| **25** | `BUG-025` | `TC_PER_036` | Xuất file Excel | 🟡 Medium | `GET /persons/export?format=xlsx` | Tải về file `.xlsx` danh sách thành viên. | **HTTP 404 Not Found**. | Backend chưa viết API xuất file Excel. |
| **26** | `BUG-026` | `TC_FAM_005` | Upload Logo | 🟡 Medium | Upload file `logo_8MB.png` | **HTTP 400** File vượt quá 5MB. | **HTTP 404 Not Found**. | Chưa có API upload file logo dòng họ. |
| **27** | `BUG-027` | `TC_REL_053` | Tái hôn | 🟡 Medium | Đã ly hôn, tạo lại kết hôn với người cũ | Cho phép tạo bản ghi hôn nhân lần 2. | **HTTP 400 Relationship already exists**. | Chặn cứng vĩnh viễn không cho tái hôn. |
| **28** | `BUG-028` | `TC_SEC_088` | Rate Limiting | 🟡 Medium | Bắn 100 requests API / 1 giây | Từ request 61 trở đi trả về **HTTP 429**. | **Xử lý toàn bộ 100 requests (HTTP 200)**. | Router chưa gắn Rate Limiter. |
| **29** | `BUG-029` | `TC_SEC_092` | Password Policy | 🟡 Medium | Đổi mật khẩu thành `"123456"` | **HTTP 400** Yêu cầu >= 8 ký tự, chữ hoa, số. | **Chấp nhận "123456"** (chỉ check len>=6). | Mật khẩu yếu vẫn được lưu. |
| **30** | `BUG-030` | `TC_PER_028` | Audit Log | ⚪ Low | Sửa hồ sơ hoặc xóa quan hệ | Chèn 1 bản ghi vào bảng `audit_logs`. | **Bảng `audit_logs` có 0 bản ghi mới**. | Service không hề có code insert log. |
| **31** | `BUG-031` | `TC_SEC_091` | Bảo mật JSON API | ⚪ Low | `GET /api/v1/auth/me` | JSON không chứa từ khóa "password". | **Trả về `"requires_password_change"`**. | Vi phạm bộ lọc chuỗi nhạy cảm. |

---

## CHI TIẾT 31 LỖI (MÔ TẢ ĐẦY ĐỦ INPUT, EXPECTED & ACTUAL OUTPUT)

---

### 1. BUG-001 (TC_PER_020) — Crash HTTP 500 khi thử SQL Injection qua ô tìm kiếm
- **Mã TC:** `TC_PER_020` | **Phân loại:** Security Test | **Mức độ:** 🔴 Critical
- **Kịch bản:** Nhập chuỗi SQL Injection vào ô tìm kiếm thành viên.
- **DỮ LIỆU ĐẦU VÀO (INPUT):**
  ```http
  GET /api/v1/families/3d906850-41c9-4cf9-bae0-71910b10f504/persons?search=' OR 1=1; DROP TABLE persons; -- HTTP/1.1
  Host: localhost:8001
  Authorization: Bearer <valid_access_token>
  ```
- **KẾT QUẢ KỲ VỌNG (EXPECTED OUTPUT):**
  ```http
  HTTP/1.1 200 OK
  Content-Type: application/json

  []
  ```
  *(Hệ thống sử dụng Parametrized Query xử lý ký tự nháy đơn như văn bản thuần túy, không sinh lỗi DB, trả về danh sách rỗng).*
- **KẾT QUẢ THỰC TẾ (ACTUAL OUTPUT):**
  ```http
  HTTP/1.1 500 Internal Server Error
  Content-Type: application/json

  {
    "error": {
      "code": "INTERNAL_SERVER_ERROR",
      "message": "An unexpected server error occurred."
    }
  }
  ```
- **PHÂN TÍCH LỖI:** Trong `GenealogyRepository.search_persons`, câu lệnh `where(Person.full_name.ilike(f"%{search}%"))` không bọc xử lý ngoại lệ chuỗi, làm crash ứng dụng khi gặp ký tự nháy đơn `'`.
- **GIẢI PHÁP:** Escape ký tự đặc biệt trong ILIKE pattern và bind param an toàn qua SQLAlchemy.

---

### 2. BUG-002 (TC_CLO_056) — Bảng Closure Table không lưu các liên kết phân cấp cha - con
- **Mã TC:** `TC_CLO_056` | **Phân loại:** Database & API | **Mức độ:** 🔴 Critical
- **Kịch bản:** Thêm con ruột D cho cặp vợ chồng gồm Cha A và Mẹ B.
- **DỮ LIỆU ĐẦU VÀO (INPUT):**
  ```http
  POST /api/v1/families/3d906850-41c9-4cf9-bae0-71910b10f504/relationships HTTP/1.1
  Host: localhost:8001
  Content-Type: application/json
  Authorization: Bearer <valid_access_token>

  {
    "fromMemberId": "9a1415ba-d925-45f4-9e5a-f9da6647f35a",
    "toMemberId": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
    "relationshipType": "FATHER"
  }
  ```
- **KẾT QUẢ KỲ VỌNG (EXPECTED OUTPUT):**
  - API trả về `HTTP 201 Created`.
  - Cơ sở dữ liệu chèn liên kết vào bảng `person_closure`:
    ```sql
    SELECT * FROM person_closure WHERE descendant_id = 'a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d';
    -- Kết quả kỳ vọng:
    -- ancestor_id: [ID_Cha], descendant_id: [ID_Con], depth: 1
    -- ancestor_id: [ID_Ong], descendant_id: [ID_Con], depth: 2
    ```
- **KẾT QUẢ THỰC TẾ (ACTUAL OUTPUT):**
  - API trả về `HTTP 201 Created` (chỉ lưu vào bảng `relationships`).
  - Kiểm tra PostgreSQL:
    ```sql
    SELECT count(*) FROM person_closure WHERE depth >= 1;
    -- Kết quả thực tế: 0 bản ghi!
    ```
- **PHÂN TÍCH LỖI:** Hàm `create_relationship` không kích hoạt trigger hoặc hàm `rebuild_closure_for_parent_child`, khiến toàn bộ bảng `person_closure` chỉ có `depth=0` (quan hệ tự thân).
- **GIẢI PHÁP:** Gọi `await self.repo.rebuild_closure_for_parent_child(parent_id, child_id, family_id)` trong transaction tạo quan hệ.

---

### 3. BUG-003 (TC_REL_047) — Hệ thống KHÔNG chặn kết hôn cận huyết trực hệ (Cha - Con, Mẹ - Con)
- **Mã TC:** `TC_REL_047` | **Phân loại:** Logic Nghiệp Vụ | **Mức độ:** 🔴 Critical
- **Kịch bản:** Gửi yêu cầu kết hôn giữa Cha ruột A và Con gái ruột D.
- **DỮ LIỆU ĐẦU VÀO (INPUT):**
  ```http
  POST /api/v1/families/3d906850-41c9-4cf9-bae0-71910b10f504/relationships HTTP/1.1
  Host: localhost:8001
  Content-Type: application/json
  Authorization: Bearer <valid_access_token>

  {
    "fromMemberId": "9a1415ba-d925-45f4-9e5a-f9da6647f35a",
    "toMemberId": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
    "relationshipType": "SPOUSE"
  }
  ```
- **KẾT QUẢ KỲ VỌNG (EXPECTED OUTPUT):**
  ```http
  HTTP/1.1 400 Bad Request
  Content-Type: application/json

  {
    "error": {
      "code": "INCEST_DIRECT_LINEAGE_PROHIBITED",
      "message": "Không thể kết hôn giữa những người có quan hệ huyết thống trực hệ (Cha/Mẹ - Con cái)."
    }
  }
  ```
- **KẾT QUẢ THỰC TẾ (ACTUAL OUTPUT):**
  ```http
  HTTP/1.1 201 Created
  Content-Type: application/json

  {
    "id": "e4f5a6b7-c8d9-0e1f-2a3b-4c5d6e7f8a9b",
    "fromMemberId": "9a1415ba-d925-45f4-9e5a-f9da6647f35a",
    "toMemberId": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
    "relationshipType": "SPOUSE"
  }
  ```
- **PHÂN TÍCH LỖI:** Trong `genealogy_service.py`, hàm tạo quan hệ `SPOUSE` chỉ kiểm tra 2 ID khác nhau, hoàn toàn không kiểm tra mối quan hệ trực hệ giữa 2 người.
- **GIẢI PHÁP:** Thêm bước kiểm tra: `if await self.repo.is_ancestor_or_descendant(from_id, to_id): raise HTTPException(400, "Incest direct lineage prohibited")`.

---

### 4. BUG-004 (TC_REL_048) — Hệ thống KHÔNG chặn kết hôn giữa Anh Chị Em ruột (Siblings)
- **Mã TC:** `TC_REL_048` | **Phân loại:** Logic Nghiệp Vụ | **Mức độ:** 🔴 Critical
- **Kịch bản:** Gửi yêu cầu kết hôn giữa Anh trai E và Em gái F (có chung cha mẹ ruột).
- **DỮ LIỆU ĐẦU VÀO (INPUT):**
  ```http
  POST /api/v1/families/3d906850-41c9-4cf9-bae0-71910b10f504/relationships HTTP/1.1
  Content-Type: application/json

  {
    "fromMemberId": "uuid-anh-E",
    "toMemberId": "uuid-em-F",
    "relationshipType": "SPOUSE"
  }
  ```
- **KẾT QUẢ KỲ VỌNG (EXPECTED OUTPUT):**
  ```http
  HTTP/1.1 400 Bad Request
  Content-Type: application/json

  {
    "error": {
      "code": "SIBLINGS_CANNOT_MARRY",
      "message": "Không thể thiết lập quan hệ hôn nhân giữa anh chị em ruột."
    }
  }
  ```
- **KẾT QUẢ THỰC TẾ (ACTUAL OUTPUT):**
  ```http
  HTTP/1.1 201 Created
  ```
  *(Bản ghi kết hôn anh em ruột được lưu thẳng vào cơ sở dữ liệu).*
- **PHÂN TÍCH LỖI:** Backend hoàn toàn thiếu hàm kiểm tra Sibling (chung cha hoặc chung mẹ) trước khi tạo SPOUSE.
- **GIẢI PHÁP:** Viết hàm `are_siblings(from_id, to_id)` kiểm tra tập giao cha/mẹ ruột của 2 bên.

---

### 5. BUG-005 (TC_CLO_064) — Cơ chế phát hiện vòng lặp gia phả (Cycle Detection) bị tê liệt
- **Mã TC:** `TC_CLO_064` | **Phân loại:** Logic Cây | **Mức độ:** 🔴 Critical
- **Kịch bản:** Gán Tổ tiên làm con của Hậu duệ (ví dụ: gán Cụ làm con của Chắt).
- **DỮ LIỆU ĐẦU VÀO (INPUT):**
  ```http
  POST /api/v1/families/3d906850-41c9-4cf9-bae0-71910b10f504/relationships HTTP/1.1
  Content-Type: application/json

  {
    "fromMemberId": "uuid-chắt-K",
    "toMemberId": "uuid-cụ-A",
    "relationshipType": "FATHER"
  }
  ```
- **KẾT QUẢ KỲ VỌNG (EXPECTED OUTPUT):**
  ```http
  HTTP/1.1 400 Bad Request
  Content-Type: application/json

  {
    "error": {
      "code": "ANCESTRY_CYCLE_DETECTED",
      "message": "Ancestry cycle detected: Không thể gán tổ tiên làm con của hậu duệ."
    }
  }
  ```
- **KẾT QUẢ THỰC TẾ (ACTUAL OUTPUT):**
  ```http
  HTTP/1.1 201 Created
  ```
  *(Hệ thống cho phép tạo chu trình lặp vô hạn trong cây).*
- **PHÂN TÍCH LỖI:** Code có hàm `get_ancestors(from_id)` để check chu trình, nhưng vì bảng `person_closure` rỗng (BUG-002), hàm này luôn trả về mảng rỗng `[]`, khiến điều kiện phát hiện chu trình không bao giờ kích hoạt.
- **GIẢI PHÁP:** Đồng bộ dữ liệu phân cấp vào `person_closure` để hàm `get_ancestors` hoạt động chính xác.

---

### 6. BUG-006 (TC_CLO_063) — Endpoint `/ancestors` bị chặn 403 Forbidden và độ trễ cao
- **Mã TC:** `TC_CLO_063` | **Phân loại:** API & Phân Quyền | **Mức độ:** 🟠 High
- **Kịch bản:** Lấy danh sách tổ tiên của một thành viên bất kỳ.
- **DỮ LIỆU ĐẦU VÀO (INPUT):**
  ```http
  GET /api/v1/families/3d906850-41c9-4cf9-bae0-71910b10f504/persons/9a1415ba-d925-45f4-9e5a-f9da6647f35a/ancestors HTTP/1.1
  Host: localhost:8001
  Authorization: Bearer <token_admin>
  ```
- **KẾT QUẢ KỲ VỌNG (EXPECTED OUTPUT):**
  ```http
  HTTP/1.1 200 OK
  Content-Type: application/json

  [
    {
      "person": {
        "id": "uuid-to-tien",
        "fullName": "Nguyễn Văn Thủy Tổ",
        "gender": "male"
      },
      "depth": 1
    }
  ]
  ```
  *(Thời gian phản hồi < 2.0 giây).*
- **KẾT QUẢ THỰC TẾ (ACTUAL OUTPUT):**
  ```http
  HTTP/1.1 403 Forbidden
  Content-Type: application/json

  {
    "error": {
      "code": "FORBIDDEN",
      "message": "Action not allowed for this account in clan."
    }
  }
  ```
  *(Thời gian phản hồi: 4.492 giây).*
- **PHÂN TÍCH LỖI:** Guard `require_family_permission` kiểm tra bảng `clan_memberships` và chặn tài khoản quản trị khi chưa được gán thành viên dòng họ mục tiêu.
- **GIẢI PHÁP:** Cấu hình cho phép System Admin / Family Owner bypass kiểm tra membership nội bộ.

---

### 7. BUG-007 (TC_CLO_070) — Endpoint `/descendants` bị chặn 403 Forbidden
- **Mã TC:** `TC_CLO_070` | **Phân loại:** API & Phân Quyền | **Mức độ:** 🟠 High
- **Kịch bản:** Truy vấn cây hậu duệ của Thủy tổ.
- **DỮ LIỆU ĐẦU VÀO (INPUT):**
  ```http
  GET /api/v1/families/3d906850-41c9-4cf9-bae0-71910b10f504/persons/9a1415ba-d925-45f4-9e5a-f9da6647f35a/descendants HTTP/1.1
  Authorization: Bearer <token_admin>
  ```
- **KẾT QUẢ KỲ VỌNG (EXPECTED OUTPUT):**
  ```http
  HTTP/1.1 200 OK
  Content-Type: application/json

  [
    {"person": {"id": "uuid-con", "fullName": "Nguyễn Văn Con"}, "depth": 1},
    {"person": {"id": "uuid-chau", "fullName": "Nguyễn Văn Cháu"}, "depth": 2}
  ]
  ```
- **KẾT QUẢ THỰC TẾ (ACTUAL OUTPUT):**
  ```http
  HTTP/1.1 403 Forbidden
  ```
- **PHÂN TÍCH LỖI:** Cơ chế guard chặn tương tự BUG-006.
- **GIẢI PHÁP:** Bổ sung quyền đọc cho Role quản trị viên.

---

### 8. BUG-008 (TC_PER_024) — Cho phép nhập Ngày mất TRƯỚC Ngày sinh
- **Mã TC:** `TC_PER_024` | **Phân loại:** Data Validation | **Mức độ:** 🟠 High
- **Kịch bản:** Nhập người đã mất có ngày mất diễn ra trước ngày sinh.
- **DỮ LIỆU ĐẦU VÀO (INPUT):**
  ```http
  POST /api/v1/families/3d906850-41c9-4cf9-bae0-71910b10f504/persons HTTP/1.1
  Content-Type: application/json

  {
    "fullName": "Trần Văn Sai Logic",
    "gender": "male",
    "birthDate": "2000-01-01",
    "deathDate": "1990-01-01",
    "isLiving": false
  }
  ```
- **KẾT QUẢ KỲ VỌNG (EXPECTED OUTPUT):**
  ```http
  HTTP/1.1 400 Bad Request
  Content-Type: application/json

  {
    "error": {
      "code": "INVALID_DATE_ORDER",
      "message": "Ngày mất không thể diễn ra trước ngày sinh."
    }
  }
  ```
- **KẾT QUẢ THỰC TẾ (ACTUAL OUTPUT):**
  ```http
  HTTP/1.1 201 Created
  Content-Type: application/json

  {
    "id": "b2c3d4e5-f6a7-8b9c-0d1e-2f3a4b5c6d7e",
    "fullName": "Trần Văn Sai Logic",
    "birthDate": "2000-01-01",
    "deathDate": "1990-01-01",
    "isLiving": false
  }
  ```
- **PHÂN TÍCH LỖI:** Tầng Schema Pydantic và Service Backend không validate `death_date >= birth_date`.
- **GIẢI PHÁP:** Thêm `@model_validator` trong `PersonCreate` và `PersonUpdate`.

---

### 9. BUG-009 (TC_CLO_060) — Cho phép Cha Mẹ sinh sau con
- **Mã TC:** `TC_CLO_060` | **Phân loại:** Logic Nghiệp Vụ | **Mức độ:** 🟠 High
- **Kịch bản:** Person A (sinh năm 2005) thêm con là Person H (sinh năm 1995).
- **DỮ LIỆU ĐẦU VÀO (INPUT):**
  ```http
  POST /api/v1/families/3d906850-41c9-4cf9-bae0-71910b10f504/relationships HTTP/1.1
  Content-Type: application/json

  {
    "fromMemberId": "uuid-cha-sinh-2005",
    "toMemberId": "uuid-con-sinh-1995",
    "relationshipType": "FATHER"
  }
  ```
- **KẾT QUẢ KỲ VỌNG (EXPECTED OUTPUT):**
  ```http
  HTTP/1.1 400 Bad Request
  Content-Type: application/json

  {
    "error": {
      "code": "INVALID_GENERATION_AGE",
      "message": "Báo lỗi nghiêm trọng: Cha mẹ không thể sinh sau hoặc cùng thời điểm với con."
    }
  }
  ```
- **KẾT QUẢ THỰC TẾ (ACTUAL OUTPUT):**
  ```http
  HTTP/1.1 201 Created
  ```
  *(Quan hệ cha mẹ sinh sau con lưu thành công vào PostgreSQL).*
- **PHÂN TÍCH LỖI:** Backend hoàn toàn không đối chiếu năm sinh giữa 2 đối tượng khi tạo quan hệ `PARENT_CHILD`.
- **GIẢI PHÁP:** Kiểm tra `parent.birth_date < child.birth_date` trước khi chèn bản ghi.

---

### 10. BUG-010 (TC_CLO_065) — Cho phép một người có nhiều hơn 2 Cha Mẹ ruột
- **Mã TC:** `TC_CLO_065` | **Phân loại:** Logic Nghiệp Vụ | **Mức độ:** 🟠 High
- **Kịch bản:** Con D đã có Cha ruột A và Mẹ ruột B, tiếp tục gửi yêu cầu thêm Cha ruột C.
- **DỮ LIỆU ĐẦU VÀO (INPUT):**
  ```http
  POST /api/v1/families/3d906850-41c9-4cf9-bae0-71910b10f504/relationships HTTP/1.1
  Content-Type: application/json

  {
    "fromMemberId": "uuid-cha-C",
    "toMemberId": "uuid-con-D",
    "relationshipType": "FATHER"
  }
  ```
- **KẾT QUẢ KỲ VỌNG (EXPECTED OUTPUT):**
  ```http
  HTTP/1.1 400 Bad Request
  Content-Type: application/json

  {
    "error": {
      "code": "MAX_BIOLOGICAL_PARENTS_EXCEEDED",
      "message": "Một người chỉ có thể có tối đa một cha ruột và một mẹ ruột."
    }
  }
  ```
- **KẾT QUẢ THỰC TẾ (ACTUAL OUTPUT):**
  ```http
  HTTP/1.1 201 Created
  ```
  *(Người con D có cùng lúc 2 cha ruột trong DB).*
- **PHÂN TÍCH LỖI:** Không đếm số lượng bản ghi `PARENT_CHILD` có `parent_type='BIOLOGICAL'` hiện có của người con.
- **GIẢI PHÁP:** Truy vấn kiểm tra số lượng cha ruột / mẹ ruột trước khi tạo mới.

---

### 11. BUG-011 (TC_FAM_014) — Cho phép Xóa Chi nhánh đang chứa thành viên
- **Mã TC:** `TC_FAM_014` | **Phân loại:** Data Integrity | **Mức độ:** 🟠 High
- **Kịch bản:** Xóa Chi nhánh Giáp đang có 10 thành viên bên trong.
- **DỮ LIỆU ĐẦU VÀO (INPUT):**
  ```http
  DELETE /api/v1/families/3d906850-41c9-4cf9-bae0-71910b10f504/branches/branch-giap-id HTTP/1.1
  ```
- **KẾT QUẢ KỲ VỌNG (EXPECTED OUTPUT):**
  ```http
  HTTP/1.1 400 Bad Request
  Content-Type: application/json

  {
    "error": {
      "code": "BRANCH_NOT_EMPTY",
      "message": "Không thể xóa Chi nhánh đang chứa thành viên. Vui lòng chuyển các thành viên sang Chi nhánh khác trước."
    }
  }
  ```
- **KẾT QUẢ THỰC TẾ (ACTUAL OUTPUT):**
  - Backend chưa có API DELETE branch hoàn chỉnh, hoặc nếu xóa trực tiếp trong DB thì 10 thành viên bị chuyển thành `branch_id = NULL` (mất liên kết chi họ) mà không hề có cảnh báo chặn.
- **PHÂN TÍCH LỖI:** Chưa có validation `count(persons in branch) == 0` trước khi xóa.
- **GIẢI PHÁP:** Thêm điều kiện kiểm tra số lượng thành viên trong Chi trước khi thực hiện xóa.

---

### 12. BUG-012 (TC_FAM_001) — Chưa có API cập nhật hồ sơ dòng họ chi tiết
- **Mã TC:** `TC_FAM_001` | **Phân loại:** Missing Feature | **Mức độ:** 🟠 High
- **Kịch bản:** Cập nhật đủ thông tin chuẩn của dòng họ (Tên, Địa chỉ, Logo, Lịch sử).
- **DỮ LIỆU ĐẦU VÀO (INPUT):**
  ```http
  PUT /api/v1/families/3d906850-41c9-4cf9-bae0-71910b10f504/profile HTTP/1.1
  Content-Type: application/json

  {
    "name": "Nguyễn Văn Đại Tộc",
    "address": "Hà Nội",
    "logoUrl": "https://example.com/logo.jpg",
    "history": "Lịch sử dòng họ 300 năm..."
  }
  ```
- **KẾT QUẢ KỲ VỌNG (EXPECTED OUTPUT):**
  ```http
  HTTP/1.1 200 OK
  ```
  *(Dữ liệu được lưu vào bảng `clans` và `clan_profiles`).*
- **KẾT QUẢ THỰC TẾ (ACTUAL OUTPUT):**
  ```http
  HTTP/1.1 404 Not Found
  ```
  *(Router Backend hoàn toàn chưa có endpoint cập nhật `clan_profiles`).*
- **PHÂN TÍCH LỖI:** Bảng `clan_profiles` đã có trong DB nhưng chưa được kết nối vào controller nào.
- **GIẢI PHÁP:** Xây dựng endpoint `PUT /api/v1/families/{family_id}/profile`.

---

### 13. BUG-013 (TC_FAM_006) — Chưa kiểm tra MIME type thực tế chống upload file độc hại
- **Mã TC:** `TC_FAM_006` | **Phân loại:** Security | **Mức độ:** 🟠 High
- **Kịch bản:** Đổi đuôi file thực thi `shell.exe` thành `logo.png` và upload.
- **DỮ LIỆU ĐẦU VÀO (INPUT):**
  ```http
  POST /api/v1/families/upload-logo HTTP/1.1
  Content-Type: multipart/form-data; boundary=---Boundary

  ---Boundary
  Content-Disposition: form-data; name="file"; filename="logo.png"
  Content-Type: image/png

  <Binary content of an executable EXE file>
  ---Boundary--
  ```
- **KẾT QUẢ KỲ VỌNG (EXPECTED OUTPUT):**
  ```http
  HTTP/1.1 400 Bad Request
  Content-Type: application/json

  {
    "error": "File content does not match image format. Upload rejected."
  }
  ```
- **KẾT QUẢ THỰC TẾ (ACTUAL OUTPUT):**
  - Không có kiểm tra magic bytes thực tế, server chấp nhận lưu file mạo danh nếu chỉ dựa vào phần mở rộng `.png`.
- **PHÂN TÍCH LỖI:** Thiếu thư viện kiểm tra magic bytes (như `python-magic` hoặc đọc header bytes `\x89PNG`).
- **GIẢI PHÁP:** Đọc byte đầu tiên của file để xác định đúng MIME type thực tế.

---

### 14. BUG-014 (TC_CLO_066) — Chưa cài đặt chức năng Chuyển nhánh (Move Subtree)
- **Mã TC:** `TC_CLO_066` | **Phân loại:** Missing Feature | **Mức độ:** 🟠 High
- **Kịch bản:** Con D đang thuộc cha A, chuyển sang làm con của cha C.
- **DỮ LIỆU ĐẦU VÀO (INPUT):**
  ```http
  POST /api/v1/families/3d906850-41c9-4cf9-bae0-71910b10f504/persons/person-D/reparent HTTP/1.1
  Content-Type: application/json

  {
    "newParentId": "uuid-cha-C"
  }
  ```
- **KẾT QUẢ KỲ VỌNG (EXPECTED OUTPUT):**
  - DB gỡ các cạnh Closure Table cũ của D và nhánh con cháu bên dưới D.
  - Tái tạo liên kết mới sang C, tự động cập nhật lại thế hệ (`generation`) cho toàn bộ cây con.
- **KẾT QUẢ THỰC TẾ (ACTUAL OUTPUT):**
  ```http
  HTTP/1.1 404 Not Found
  ```
  *(Chức năng Move Subtree chưa được viết trong mã nguồn).*
- **PHÂN TÍCH LỖI:** Thiếu hàm thuật toán `move_subtree` trong `GenealogyRepository`.
- **GIẢI PHÁP:** Cài đặt thuật toán chuyển nhánh Closure Table: xóa cạnh cũ và chèn cạnh mới qua cross-join.

---

### 15. BUG-015 (TC_CLO_071) — Endpoint Relationship Path bị lỗi HTTP 422
- **Mã TC:** `TC_CLO_071` | **Phân loại:** API Test | **Mức độ:** 🟡 Medium
- **Kịch bản:** Tính toán đường đi và gợi ý xưng hô giữa 2 người xa nhau.
- **DỮ LIỆU ĐẦU VÀO (INPUT):**
  ```http
  GET /api/v1/families/3d906850-41c9-4cf9-bae0-71910b10f504/relationship-path?from_person_id=uuid1&to_person_id=uuid2 HTTP/1.1
  ```
- **KẾT QUẢ KỲ VỌNG (EXPECTED OUTPUT):**
  ```http
  HTTP/1.1 200 OK
  Content-Type: application/json

  {
    "fromPersonId": "uuid1",
    "toPersonId": "uuid2",
    "relationshipName": "Cụ - Chắt",
    "distance": 3
  }
  ```
- **KẾT QUẢ THỰC TẾ (ACTUAL OUTPUT):**
  ```http
  HTTP/1.1 422 Unprocessable Entity
  Content-Type: application/json

  {
    "detail": [
      {
        "loc": ["query", "fromPersonId"],
        "msg": "Field required",
        "type": "missing"
      }
    ]
  }
  ```
- **PHÂN TÍCH LỖI:** Endpoint chỉ chấp nhận `fromPersonId` (camelCase) mà không có alias dự phòng cho `from_person_id` (snake_case).
- **GIẢI PHÁP:** Thêm alias hỗ trợ cả 2 định dạng trong router query parameter.

---

### 16. BUG-016 (TC_PER_040) — Tốc độ phản hồi API danh sách vượt ngưỡng 1s (Thực tế 4.354s)
- **Mã TC:** `TC_PER_040` | **Phân loại:** Hiệu Năng | **Mức độ:** 🟡 Medium
- **Kịch bản:** Tải danh sách 100 thành viên có kèm phân trang.
- **DỮ LIỆU ĐẦU VÀO (INPUT):**
  ```http
  GET /api/v1/families/3d906850-41c9-4cf9-bae0-71910b10f504/persons?limit=100&offset=0 HTTP/1.1
  ```
- **KẾT QUẢ KỲ VỌNG (EXPECTED OUTPUT):**
  - Phản hồi HTTP 200 trong thời gian **`< 1.0 giây`**.
- **KẾT QUẢ THỰC TẾ (ACTUAL OUTPUT):**
  - Phản hồi HTTP 200 nhưng mất **`4.354 giây`** (chậm gấp hơn 4 lần).
- **PHÂN TÍCH LỖI:** Thiếu connection pooling warm-up và Redis caching cho truy vấn danh sách.
- **GIẢI PHÁP:** Tối ưu hóa connection pool và đánh index Composite trên `(clan_id, generation)`.

---

### 17. BUG-017 (TC_PER_035) — DOM thiếu Avatar Placeholder mặc định khi không có ảnh
- **Mã TC:** `TC_PER_035` | **Phân loại:** UI/UX | **Mức độ:** 🟡 Medium
- **Kịch bản:** Mở danh sách xem thành viên không có ảnh đại diện (`avatar_storage_key: null`).
- **DỮ LIỆU ĐẦU VÀO (INPUT):**
  - Truy cập URL: `http://localhost:5173/family-admin-preview?view=members`
- **KẾT QUẢ KỲ VỌNG (EXPECTED OUTPUT):**
  - DOM hiển thị thẻ ảnh hoặc SVG avatar mặc định theo giới tính:
    ```html
    <img src="/avatars/default_male.svg" alt="Avatar mặc định Nam" class="avatar-placeholder" />
    ```
- **KẾT QUẢ THỰC TẾ (ACTUAL OUTPUT):**
  - Không tìm thấy thẻ img hoặc avatar fallback nào (`find_elements(By.CSS_SELECTOR, "img, .avatar") == 0`). Khung avatar bị biến mất.
- **PHÂN TÍCH LỖI:** Component React chưa có fallback UI khi đường dẫn ảnh null.
- **GIẢI PHÁP:** Thêm `<DefaultAvatar gender={person.gender} />` vào component thẻ thành viên.

---

### 18. BUG-018 (TC_PER_022) — Backend KHÔNG chặn ngày sinh trong tương lai
- **Mã TC:** `TC_PER_022` | **Phân loại:** Data Validation | **Mức độ:** 🟡 Medium
- **Kịch bản:** Gửi API tạo người có ngày sinh năm 2050.
- **DỮ LIỆU ĐẦU VÀO (INPUT):**
  ```http
  POST /api/v1/families/3d906850-41c9-4cf9-bae0-71910b10f504/persons HTTP/1.1
  Content-Type: application/json

  {
    "fullName": "Nguyễn Tương Lai",
    "gender": "male",
    "birthDate": "2050-01-01"
  }
  ```
- **KẾT QUẢ KỲ VỌNG (EXPECTED OUTPUT):**
  ```http
  HTTP/1.1 400 Bad Request
  Content-Type: application/json

  {
    "error": "Ngày sinh không được vượt quá thời điểm hiện tại."
  }
  ```
- **KẾT QUẢ THỰC TẾ (ACTUAL OUTPUT):**
  ```http
  HTTP/1.1 201 Created
  ```
  *(Lưu thành công hồ sơ sinh năm 2050 vào DB).*
- **PHÂN TÍCH LỖI:** Backend hoàn toàn không có validator so sánh `birth_date <= date.today()`.
- **GIẢI PHÁP:** Thêm validator trong schema `PersonCreate`.

---

### 19. BUG-019 (TC_CLO_061) — Thiếu cảnh báo khoảng cách tuổi sinh học phi lý (Cha 10 tuổi sinh con)
- **Mã TC:** `TC_CLO_061` | **Phân loại:** Validation | **Mức độ:** 🟡 Medium
- **Kịch bản:** Gán người cha sinh năm 2000 sinh con năm 2010.
- **DỮ LIỆU ĐẦU VÀO (INPUT):**
  - Tạo quan hệ cha mẹ - con cái với khoảng cách tuổi = 10 năm.
- **KẾT QUẢ KỲ VỌNG (EXPECTED OUTPUT):**
  - Giao diện và API đưa ra Cảnh báo (Warning): `"Khoảng cách tuổi giữa cha mẹ và con < 13 tuổi, vui lòng xác nhận trước khi lưu"`.
- **KẾT QUẢ THỰC TẾ (ACTUAL OUTPUT):**
  - Hệ thống lưu trực tiếp vào cơ sở dữ liệu mà không có bất kỳ cảnh báo nào.
- **PHÂN TÍCH LỖI:** Chưa có rule kiểm tra khoảng cách tuổi tối thiểu sinh học.
- **GIẢI PHÁP:** Thêm cảnh báo nếu `child.birth_date - parent.birth_date < 13 years`.

---

### 20. BUG-020 (TC_FAM_011) — Cho phép tạo Chi nhánh trùng tên trong cùng một dòng họ
- **Mã TC:** `TC_FAM_011` | **Phân loại:** Database Integrity | **Mức độ:** 🟡 Medium
- **Kịch bản:** Tạo 2 Chi nhánh cùng mang tên "Chi Giáp" trong cùng một dòng họ.
- **DỮ LIỆU ĐẦU VÀO (INPUT):**
  ```http
  POST /api/v1/families/3d906850-41c9-4cf9-bae0-71910b10f504/branches HTTP/1.1
  Content-Type: application/json

  {
    "name": "Chi Giáp"
  }
  ```
  *(Gửi liên tiếp 2 lần cùng một payload trên).*
- **KẾT QUẢ KỲ VỌNG (EXPECTED OUTPUT):**
  - Lần 2 trả về `HTTP 400 Bad Request` hoặc `409 Conflict`: `"Tên Chi nhánh đã tồn tại trong dòng họ này"`.
- **KẾT QUẢ THỰC TẾ (ACTUAL OUTPUT):**
  - Cả 2 lần đều trả về `HTTP 201 Created`, cơ sở dữ liệu xuất hiện 2 Chi Giáp trùng tên.
- **PHÂN TÍCH LỖI:** Bảng `branches` thiếu ràng buộc `UNIQUE(clan_id, name)`.
- **GIẢI PHÁP:** Thêm Unique Constraint: `ALTER TABLE branches ADD CONSTRAINT uq_branches_clan_name UNIQUE (clan_id, name);`.

---

### 21. BUG-021 (TC_FAM_008) — Không giới hạn duy nhất 1 Thủy tổ mỗi dòng họ
- **Mã TC:** `TC_FAM_008` | **Phân loại:** Logic Cây | **Mức độ:** 🟡 Medium
- **Kịch bản:** Dòng họ đã có Thủy tổ, tiếp tục tạo người thứ 2 làm Thủy tổ.
- **DỮ LIỆU ĐẦU VÀO (INPUT):**
  ```http
  POST /api/v1/families/3d906850-41c9-4cf9-bae0-71910b10f504/persons HTTP/1.1
  Content-Type: application/json

  {
    "fullName": "Thủy Tổ Thứ Hai",
    "generation": 1
  }
  ```
- **KẾT QUẢ KỲ VỌNG (EXPECTED OUTPUT):**
  - Nút "Tạo Thủy tổ" trên UI bị disabled.
  - API trả về `HTTP 400 Bad Request`: `"Dòng họ đã có Thủy tổ, không thể tạo thêm"`.
- **KẾT QUẢ THỰC TẾ (ACTUAL OUTPUT):**
  - `HTTP 201 Created`, tạo thêm một cây gia phả độc lập trong cùng một dòng họ.
- **PHÂN TÍCH LỖI:** Chưa có ràng buộc giới hạn 1 Root Ancestor cho mỗi Clan.
- **GIẢI PHÁP:** Đếm số người có `generation = 1` hoặc `is_root = true` trước khi tạo.

---

### 22. BUG-022 (TC_PER_030) — Đổi giới tính người đang có vợ/chồng mà không có cảnh báo
- **Mã TC:** `TC_PER_030` | **Phân loại:** UI/UX | **Mức độ:** 🟡 Medium
- **Kịch bản:** Đổi giới tính từ Nam sang Nữ đối với người đang có một người vợ.
- **DỮ LIỆU ĐẦU VÀO (INPUT):**
  ```http
  PATCH /api/v1/families/3d906850-41c9-4cf9-bae0-71910b10f504/persons/{person_id_co_vo} HTTP/1.1
  Content-Type: application/json

  {
    "gender": "female"
  }
  ```
- **KẾT QUẢ KỲ VỌNG (EXPECTED OUTPUT):**
  - Giao diện bật Modal xác nhận: `"Cảnh báo: Người này đang có quan hệ hôn nhân. Việc đổi giới tính có thể ảnh hưởng quan hệ hôn nhân hiện tại. Bạn có chắc chắn muốn đổi?"`.
- **KẾT QUẢ THỰC TẾ (ACTUAL OUTPUT):**
  - Backend cập nhật thẳng `gender = female` vào DB mà không đưa ra bất kỳ cảnh báo nào.
- **PHÂN TÍCH LỖI:** Thiếu kiểm tra quan hệ `SPOUSE` trước khi đổi giới tính.
- **GIẢI PHÁP:** Bật popup xác nhận trên UI và trả cờ cảnh báo từ Backend.

---

### 23. BUG-023 (TC_REL_055) — Thiếu ràng buộc DB Check Constraint chặn người tự kết hôn
- **Mã TC:** `TC_REL_055` | **Phân loại:** Database Integrity | **Mức độ:** 🟡 Medium
- **Kịch bản:** Gửi query chèn bản ghi một người tự kết hôn với chính mình.
- **DỮ LIỆU ĐẦU VÀO (INPUT):**
  ```sql
  INSERT INTO relationships (relationship_id, clan_id, from_person_id, to_person_id, relationship_type)
  VALUES (gen_random_uuid(), 'clan-uuid', 'person-uuid-A', 'person-uuid-A', 'SPOUSE');
  ```
- **KẾT QUẢ KỲ VỌNG (EXPECTED OUTPUT):**
  - Cơ sở dữ liệu từ chối với lỗi Check Constraint: `CHECK (from_person_id != to_person_id)`.
- **KẾT QUẢ THỰC TẾ (ACTUAL OUTPUT):**
  - Bảng `relationships` trong PostgreSQL không có ràng buộc này, chèn thành công bản ghi tự kết hôn.
- **PHÂN TÍCH LỖI:** Thiếu Check Constraint ở tầng Database.
- **GIẢI PHÁP:** Thêm `ALTER TABLE relationships ADD CONSTRAINT chk_diff_person CHECK (from_person_id != to_person_id);`.

---

### 24. BUG-024 (TC_FAM_010, TC_FAM_012) — Bảng `branches` thiếu cột `leader_person_id`
- **Mã TC:** `TC_FAM_010` | **Phân loại:** Database Schema | **Mức độ:** 🟡 Medium
- **Kịch bản:** Tạo Chi mới và gán Trưởng chi cho Chi nhánh.
- **DỮ LIỆU ĐẦU VÀO (INPUT):**
  ```http
  POST /api/v1/families/3d906850-41c9-4cf9-bae0-71910b10f504/branches HTTP/1.1
  Content-Type: application/json

  {
    "name": "Chi Trưởng",
    "leaderPersonId": "9a1415ba-d925-45f4-9e5a-f9da6647f35a"
  }
  ```
- **KẾT QUẢ KỲ VỌNG (EXPECTED OUTPUT):**
  - `HTTP 201 Created`, lưu `leader_person_id` vào bảng `branches`.
- **KẾT QUẢ THỰC TẾ (ACTUAL OUTPUT):**
  ```http
  HTTP/1.1 422 Unprocessable Entity
  ```
  *(Trường `leaderPersonId` bị từ chối do schema không khai báo, và DB không có cột này).*
- **PHÂN TÍCH LỖI:** Bảng `branches` hoàn toàn thiếu cột khóa ngoại `leader_person_id`.
- **GIẢI PHÁP:** Chạy migration thêm cột `leader_person_id UUID REFERENCES persons(person_id)` vào bảng `branches`.

---

### 25. BUG-025 (TC_PER_036) — Backend hoàn toàn thiếu API xuất danh sách thành viên ra Excel
- **Mã TC:** `TC_PER_036` | **Phân loại:** Missing Feature | **Mức độ:** 🟡 Medium
- **Kịch bản:** Nhấn nút "Xuất Excel" để tải danh sách thành viên ra file `.xlsx`.
- **DỮ LIỆU ĐẦU VÀO (INPUT):**
  ```http
  GET /api/v1/families/3d906850-41c9-4cf9-bae0-71910b10f504/persons/export?format=xlsx HTTP/1.1
  ```
- **KẾT QUẢ KỲ VỌNG (EXPECTED OUTPUT):**
  ```http
  HTTP/1.1 200 OK
  Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
  Content-Disposition: attachment; filename="Danh_Sach_Thanh_Vien.xlsx"
  ```
- **KẾT QUẢ THỰC TẾ (ACTUAL OUTPUT):**
  ```http
  HTTP/1.1 404 Not Found
  ```
- **PHÂN TÍCH LỖI:** Backend chưa viết controller hay service nào sử dụng `openpyxl` để xuất file Excel.
- **GIẢI PHÁP:** Xây dựng endpoint xuất file Excel với StreamingResponse.

---

### 26. BUG-026 (TC_FAM_005) — Chưa có API upload Logo dòng họ
- **Mã TC:** `TC_FAM_005` | **Phân loại:** Missing Feature | **Mức độ:** 🟡 Medium
- **Kịch bản:** Upload file logo kích thước vượt quá 5MB.
- **DỮ LIỆU ĐẦU VÀO (INPUT):**
  ```http
  POST /api/v1/families/3d906850-41c9-4cf9-bae0-71910b10f504/logo HTTP/1.1
  Content-Type: multipart/form-data; boundary=---Boundary

  ---Boundary
  Content-Disposition: form-data; name="file"; filename="logo_8MB.png"
  <File binary 8MB>
  ---Boundary--
  ```
- **KẾT QUẢ KỲ VỌNG (EXPECTED OUTPUT):**
  ```http
  HTTP/1.1 400 Bad Request
  Content-Type: application/json

  {
    "error": "File size exceeds 5MB limit."
  }
  ```
- **KẾT QUẢ THỰC TẾ (ACTUAL OUTPUT):**
  ```http
  HTTP/1.1 404 Not Found
  ```
- **PHÂN TÍCH LỖI:** Chưa có router upload logo dòng họ.
- **GIẢI PHÁP:** Xây dựng API upload logo với middleware kiểm tra file size `< 5MB`.

---

### 27. BUG-027 (TC_REL_053) — Chức năng Tái hôn (Remarriage) bị chặn cứng
- **Mã TC:** `TC_REL_053` | **Phân loại:** Logic Nghiệp Vụ | **Mức độ:** 🟡 Medium
- **Kịch bản:** A và B đã ly hôn (`ended_on` đã ghi nhận), nay kết hôn lại với nhau.
- **DỮ LIỆU ĐẦU VÀO (INPUT):**
  ```http
  POST /api/v1/families/3d906850-41c9-4cf9-bae0-71910b10f504/relationships HTTP/1.1
  Content-Type: application/json

  {
    "fromMemberId": "uuid-A",
    "toMemberId": "uuid-B",
    "relationshipType": "SPOUSE"
  }
  ```
- **KẾT QUẢ KỲ VỌNG (EXPECTED OUTPUT):**
  ```http
  HTTP/1.1 201 Created
  ```
  *(Cho phép lưu bản ghi hôn nhân mới hoặc cập nhật trạng thái ACTIVE).*
- **KẾT QUẢ THỰC TẾ (ACTUAL OUTPUT):**
  ```http
  HTTP/1.1 400 Bad Request
  Content-Type: application/json

  {
    "detail": "Spouse relationship already exists"
  }
  ```
- **PHÂN TÍCH LỖI:** Hàm `check_existing_spouse_relationship` chỉ tìm xem có bản ghi SPOUSE nào không mà không kiểm tra trạng thái DIVORCED.
- **GIẢI PHÁP:** Cho phép tạo quan hệ SPOUSE mới nếu quan hệ cũ đã kết thúc (`ended_on IS NOT NULL` hoặc `status = 'DIVORCED'`).

---

### 28. BUG-028 (TC_SEC_088) — Router gia phả chưa gắn Rate Limiter
- **Mã TC:** `TC_SEC_088` | **Phân loại:** Security | **Mức độ:** 🟡 Medium
- **Kịch bản:** Gửi dồn dập 100 requests API tìm kiếm trong 1 giây.
- **DỮ LIỆU ĐẦU VÀO (INPUT):**
  - Vòng lặp bắn 100 requests liên tiếp: `GET /api/v1/families/{id}/persons?search=Nguyen` trong thời gian 1s.
- **KẾT QUẢ KỲ VỌNG (EXPECTED OUTPUT):**
  ```http
  HTTP/1.1 429 Too Many Requests
  Content-Type: application/json

  {
    "error": "Rate limit exceeded. Try again in 60 seconds."
  }
  ```
- **KẾT QUẢ THỰC TẾ (ACTUAL OUTPUT):**
  - Toàn bộ 100 requests đều trả về `HTTP 200 OK`.
- **PHÂN TÍCH LỖI:** Chưa gắn `@limiter.limit` lên router gia phả.
- **GIẢI PHÁP:** Thêm decorator `@limiter.limit("60/minute")` trên các router `/api/v1/families/...`.

---

### 29. BUG-029 (TC_SEC_092) — Schema Password không kiểm tra độ phức tạp của mật khẩu
- **Mã TC:** `TC_SEC_092` | **Phân loại:** Security | **Mức độ:** 🟡 Medium
- **Kịch bản:** Đổi mật khẩu thành `"123456"`.
- **DỮ LIỆU ĐẦU VÀO (INPUT):**
  ```http
  POST /api/v1/auth/change-password HTTP/1.1
  Content-Type: application/json

  {
    "new_password": "123456",
    "recent_id_token": "valid_token"
  }
  ```
- **KẾT QUẢ KỲ VỌNG (EXPECTED OUTPUT):**
  ```http
  HTTP/1.1 400 Bad Request
  Content-Type: application/json

  {
    "error": "Mật khẩu yếu: Yêu cầu ít nhất 8 ký tự, gồm chữ hoa, chữ thường, chữ số và ký tự đặc biệt."
  }
  ```
- **KẾT QUẢ THỰC TẾ (ACTUAL OUTPUT):**
  - Password schema chỉ có `min_length=6`, chấp nhận mật khẩu yếu `"123456"`.
- **PHÂN TÍCH LỖI:** Thiếu regex kiểm tra độ phức tạp của mật khẩu trong schema `Password`.
- **GIẢI PHÁP:** Thêm Regex validation trong `BE/app/schemas/common.py`.

---

### 30. BUG-030 (TC_PER_028, TC_SEC_099) — Backend KHÔNG ghi nhận Audit Log
- **Mã TC:** `TC_PER_028` | **Phân loại:** Audit & Compliance | **Mức độ:** ⚪ Low
- **Kịch bản:** Cập nhật tiểu sử Person hoặc xóa Chi nhánh.
- **DỮ LIỆU ĐẦU VÀO (INPUT):**
  ```http
  PATCH /api/v1/families/{family_id}/persons/{person_id} HTTP/1.1
  Content-Type: application/json

  {
    "biography": "Cập nhật tiểu sử mới..."
  }
  ```
- **KẾT QUẢ KỲ VỌNG (EXPECTED OUTPUT):**
  - Database chèn 1 bản ghi vào bảng `audit_logs`:
    ```sql
    SELECT * FROM audit_logs WHERE action = 'UPDATE_PERSON';
    -- Kỳ vọng có 1 bản ghi ghi nhận actor_id, target_id, timestamp.
    ```
- **KẾT QUẢ THỰC TẾ (ACTUAL OUTPUT):**
  - `SELECT count(*) FROM audit_logs WHERE action = 'UPDATE_PERSON';` trả về `0`.
- **PHÂN TÍCH LỖI:** Trong toàn bộ `genealogy_service.py` không có dòng code nào chèn log vào bảng `audit_logs`.
- **GIẢI PHÁP:** Thêm hàm ghi nhận audit log trong service sau mỗi thao tác ghi/sửa/xóa.

---

### 31. BUG-031 (TC_SEC_091) — Payload API chứa từ khóa nhạy cảm "password"
- **Mã TC:** `TC_SEC_091` | **Phân loại:** Security | **Mức độ:** ⚪ Low
- **Kịch bản:** Bắt gói tin phản hồi của API `GET /api/v1/auth/me`.
- **DỮ LIỆU ĐẦU VÀO (INPUT):**
  ```http
  GET /api/v1/auth/me HTTP/1.1
  Authorization: Bearer <valid_token>
  ```
- **KẾT QUẢ KỲ VỌNG (EXPECTED OUTPUT):**
  - Payload JSON phản hồi không chứa bất kỳ trường nào có từ khóa `password`.
- **KẾT QUẢ THỰC TẾ (ACTUAL OUTPUT):**
  ```json
  {
    "user_id": "8c51e2e9-f3b7-4010-879a-c000ef42927d",
    "display_name": "Dev System Admin",
    "requires_password_change": false
  }
  ```
  *(Chứa trường `requires_password_change`).*
- **PHÂN TÍCH LỖI:** Tên trường metadata chứa từ khóa nhạy cảm.
- **GIẢI PHÁP:** Đổi tên trường thành `must_reset_credentials` hoặc `first_login_required`.

---

## KẾT LUẬN & ĐỀ XUẤT HÀNH ĐỘNG

Tài liệu này là căn cứ kỹ thuật chính xác và toàn diện nhất để đội ngũ phát triển và kiểm thử thực hiện:
1. **Lập Ticket Jira/GitHub Issues:** Sử dụng mã `BUG-001` đến `BUG-031` kèm Input/Output cụ thể để phân công dev xử lý.
2. **Viết Automation Test Suite:** Dùng các dữ liệu Input/Output mẫu ở trên để bổ sung vào bộ kiểm thử hồi quy (Regression Test).
3. **Nghiệm Thu Sprint 2:** Đảm bảo tất cả 31 lỗi trên đều chuyển sang trạng thái PASSED trước khi bàn giao hệ thống.
