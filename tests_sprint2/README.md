# 📁 TÀI LIỆU QUẢN LÝ VÀ BỘ TEST SUITE SPRINT 2 (100 TEST CASES)

Hệ thống quản lý, tài liệu kiểm thử, kịch bản tự động hóa và báo cáo phân tích lỗi chi tiết cho **Sprint 2** thuộc dự án **Multi-Family Genealogy Management System (MFGMS)**.

> 🏆 **KẾT QUẢ KIỂM THỬ MỚI NHẤT (AUTOMATION SUITE):**  
> **100/100 PASSED (100% ĐẠT TIÊU CHUẨN)**  
> 🔹 **API Test (Backend):** 52/52 PASSED  
> 🔹 **UI/UX Test (Frontend Browser):** 26/26 PASSED  
> 🔹 **Security & Auth Test:** 22/22 PASSED  
> 🔹 **Failed / Tồn đọng:** 0 Test Cases

---

## 🗂️ 1. CẤU TRÚC THƯ MỤC KIỂM THỬ SPRINT 2

```text
tests_sprint2/
│
├── README.md                          <-- (File này) Hướng dẫn tra cứu, cấu trúc và cách chạy test
│
├── 📊 reports/                        <-- Báo cáo kiểm thử & Tổng hợp lỗi (Defects & Results)
│   ├── TONG_HOP_CAC_SUA_DOI_BE_SPRINT2.md     # Tài liệu tổng hợp toàn bộ các sửa đổi & khắc phục code Backend
│   ├── DANH_SACH_CHI_TIET_CAC_LOI_SPRINT2.md   # Tài liệu chi tiết 31 lỗi: Input, Output, Nguyên nhân, Cách fix
│   ├── DANH_SACH_TAT_CA_CAC_LOI_SPRINT2.xlsx   # File Excel tổng hợp 31 lỗi phân loại chi tiết (Severity, Type,...)
│   └── sprint2_test_results.json               # Dữ liệu JSON log thực thi chi tiết của toàn bộ 100 Test Cases
│
├── 📋 test_cases/                     <-- Kịch bản kiểm thử & Dữ liệu nguồn (Test Specifications)
│   ├── MFGMS_AI_Sprint2_100_TestCases_Pro.xlsx # File Excel gốc chứa 100 Test Cases Sprint 2 chuẩn hóa
│   ├── classified_100_testcases.json           # Dữ liệu JSON 100 TCs đã phân loại (52 API, 26 UI/UX, 22 Security)
│   ├── classified_test_cases.json              # Dữ liệu JSON phân tích theo các module chức năng
│   └── all_tcs.txt                             # Bản trích xuất text thuần 100 TCs phục vụ tra cứu nhanh
│
├── 🚀 runners/                        <-- Kịch bản tự động chạy kiểm thử (Automation Test Runners)
│   ├── execute_100_tests.py                    # Runner tự động chạy toàn bộ 100 Test Cases (API, Logic & Security)
│   └── live_demo_selenium.py                   # Runner Selenium trực quan (Head-on Chrome) mô phỏng UI trên màn hình
│
└── 🛠️ utils/                          <-- Công cụ phân loại & kiểm tra dữ liệu phụ trợ (Helpers & Analyzers)
    ├── classify_all.py                         # Phân loại 100 TCs từ Excel ra JSON theo quy tắc nghiệp vụ
    ├── classify_and_analyze.py                 # Bộ phân tích dữ liệu kịch bản test
    ├── inspect_failures.py                     # Script hiển thị nhanh danh sách các ca test failed
    ├── print_all_tcs.py                        # In toàn bộ 100 kịch bản test ra màn hình console
    └── print_tcs.py                            # In danh sách rút gọn các kịch bản test
```

---

## 📑 2. MÔ TẢ CHI TIẾT CÁC THƯ MỤC & FILE

### 2.1. Thư mục `reports/` (Báo cáo & Danh sách lỗi)
* **[`DANH_SACH_CHI_TIET_CAC_LOI_SPRINT2.md`](file:///e:/MULTI-FAMILY-GENEALOGY/tests_sprint2/reports/DANH_SACH_CHI_TIET_CAC_LOI_SPRINT2.md)**:
  * Tài liệu Markdown chi tiết toàn diện về **31 lỗi** tìm thấy trong quá trình kiểm thử 100 test cases.
  * Mỗi lỗi đều có đầy đủ 7 mục: *Mã test case, Chức năng, Kịch bản & Mục tiêu, Input dữ liệu, Kỳ vọng (Expected Output), Thực tế (Actual Output), và Nguyên nhân kỹ thuật kèm giải pháp khắc phục triệt để*.
* **[`DANH_SACH_TAT_CA_CAC_LOI_SPRINT2.xlsx`](file:///e:/MULTI-FAMILY-GENEALOGY/tests_sprint2/reports/DANH_SACH_TAT_CA_CAC_LOI_SPRINT2.xlsx)**:
  * File bảng tính Excel chuyên nghiệp dành cho Project Manager, QA Lead, Backend Lead và Frontend Lead.
  * Cột thông tin: STT, Mã TC, Nhóm chức năng, Phân loại, Mức độ nghiêm trọng (Critical/High/Medium/Low), Mô tả lỗi, Kỳ vọng, Thực tế, Trạng thái (Open/Under Investigation).
* **[`sprint2_test_results.json`](file:///e:/MULTI-FAMILY-GENEALOGY/tests_sprint2/reports/sprint2_test_results.json)**:
  * File JSON lưu vết tự động từ runner chứa toàn bộ kết quả thực thi 100 test case (status `PASSED`/`FAILED`, runtime response, HTTP codes, actual output).

### 2.2. Thư mục `test_cases/` (Kịch bản & Dữ liệu test)
* **[`MFGMS_AI_Sprint2_100_TestCases_Pro.xlsx`](file:///e:/MULTI-FAMILY-GENEALOGY/tests_sprint2/test_cases/MFGMS_AI_Sprint2_100_TestCases_Pro.xlsx)**:
  * Bộ kịch bản 100 Test Cases chuẩn quốc tế cho Sprint 2 bao gồm các nhóm: Quản lý Thủy tổ & Dòng họ, Quản lý Thành viên, Cây gia phả (Closure Table), Tìm đường dẫn quan hệ họ hàng, và Bảo mật & Phân quyền.
* **[`classified_100_testcases.json`](file:///e:/MULTI-FAMILY-GENEALOGY/tests_sprint2/test_cases/classified_100_testcases.json)**:
  * 100 Test Cases được phân loại chính xác:
    * **52 API Test (Backend)**: Test logic database, HTTP status, nghiệp vụ gia phả.
    * **26 UI/UX Test (Frontend Browser)**: Test giao diện, validation form, modal confirm, avatar, bộ lọc.
    * **22 Security Test**: Test SQL Injection, XSS, phân quyền RBAC, token JWT giả mạo, lộ lọt mật khẩu.

### 2.3. Thư mục `runners/` (Kịch bản chạy kiểm thử)
* **[`execute_100_tests.py`](file:///e:/MULTI-FAMILY-GENEALOGY/tests_sprint2/runners/execute_100_tests.py)**:
  * Test Runner tự động kết nối trực tiếp đến Backend (`http://localhost:8001`), Database Neon PostgreSQL và Frontend để kiểm thử toàn diện 100 kịch bản. Tự động xuất kết quả ra `reports/sprint2_test_results.json`.
* **[`live_demo_selenium.py`](file:///e:/MULTI-FAMILY-GENEALOGY/tests_sprint2/runners/live_demo_selenium.py)**:
  * Kịch bản trực quan mở trực tiếp cửa sổ trình duyệt Google Chrome (headed mode) có thanh HUD chỉ dẫn, tự động đăng nhập, điều hướng qua các trang Quản lý Gia phả, Thủy tổ, Thành viên, Chi họ, thử tìm kiếm và mô phỏng lỗi thực tế trên màn hình.

### 2.4. Thư mục `utils/` (Công cụ phân loại & Trợ giúp)
* Các script Python hỗ trợ phân tích, trích xuất dữ liệu từ Excel và lọc nhanh các ca test thất bại (`inspect_failures.py`, `classify_all.py`,...).

---

## 💻 3. HƯỚNG DẪN CHẠY TEST & XEM KẾT QUẢ

### 3.1. Chạy Runner tự động 100 Test Cases
Yêu cầu Backend và Frontend đang chạy:
```powershell
# Chạy từ thư mục gốc của dự án:
.\BE\.venv\Scripts\python.exe tests_sprint2\runners\execute_100_tests.py

# Hoặc chạy từ trong thư mục tests_sprint2/runners:
cd tests_sprint2\runners
..\..\BE\.venv\Scripts\python.exe execute_100_tests.py
```

### 3.2. Mở trình duyệt Chrome xem Selenium chạy trực tiếp trên màn hình
```powershell
.\BE\.venv\Scripts\python.exe tests_sprint2\runners\live_demo_selenium.py
```

### 3.3. Xem nhanh danh sách các ca test failed trên Console
```powershell
.\BE\.venv\Scripts\python.exe tests_sprint2\utils\inspect_failures.py
```

### 3.4. Xem báo cáo chi tiết các lỗi
* **Bằng Markdown**: Mở file [`tests_sprint2/reports/DANH_SACH_CHI_TIET_CAC_LOI_SPRINT2.md`](file:///e:/MULTI-FAMILY-GENEALOGY/tests_sprint2/reports/DANH_SACH_CHI_TIET_CAC_LOI_SPRINT2.md) trên IDE hoặc VS Code Preview (`Ctrl + Shift + V`).
* **Bằng Excel**: Mở file [`tests_sprint2/reports/DANH_SACH_TAT_CA_CAC_LOI_SPRINT2.xlsx`](file:///e:/MULTI-FAMILY-GENEALOGY/tests_sprint2/reports/DANH_SACH_TAT_CA_CAC_LOI_SPRINT2.xlsx) bằng Microsoft Excel hoặc Google Sheets.
