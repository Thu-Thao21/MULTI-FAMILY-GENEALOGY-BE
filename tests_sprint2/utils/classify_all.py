import openpyxl
import json
import os

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SPRINT2_DIR = os.path.dirname(CURRENT_DIR)

def get_file_path(filename, subfolder="test_cases"):
    candidates = [
        os.path.join(SPRINT2_DIR, subfolder, filename),
        os.path.join(CURRENT_DIR, filename),
        filename
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return os.path.join(SPRINT2_DIR, subfolder, filename)

def classify_all():
    excel_path = get_file_path('MFGMS_AI_Sprint2_100_TestCases_Pro.xlsx')
    wb = openpyxl.load_workbook(excel_path)
    ws = wb['TestCases']
    
    test_cases = []
    
    # Explicit mapping or rules based on test ID and scenario:
    # Security Test: All TC_SEC_* cases (081-100) plus security/attack cases in other groups (TC_FAM_004, TC_FAM_006, TC_PER_020)
    # UI/UX Test: Browser-driven, UI rendering, form validation display, frontend warnings, drag/drop, buttons, responsive, modals
    # API Test: Backend logic, database state (Postgres), API status codes, Closure table calculations
    
    ui_ux_codes = {
        'TC_FAM_003', # Để trống trường bắt buộc -> Form bị chặn ở FE, message lỗi màu đỏ
        'TC_FAM_005', # Upload Logo >5MB -> Báo lỗi vượt quá dung lượng ở UI/FE
        'TC_FAM_008', # Cố gắng tạo Thủy tổ thứ 2 -> Nút bị disable trên UI
        'TC_PER_016', # Kiểm tra hiển thị mặc định bảng Person, skeleton loading
        'TC_PER_017', # Phân trang dữ liệu bấm sang trang 2
        'TC_PER_018', # Lọc tên có dấu tiếng Việt trên thanh tìm kiếm
        'TC_PER_019', # Lọc tổng hợp nhiều tiêu chí trên UI filter bar
        'TC_PER_022', # Thêm người có Ngày sinh tương lai -> Frontend chặn lưu
        'TC_PER_025', # Tuổi thọ > 150 -> Cảnh báo Modal Warning trên UI
        'TC_PER_027', # 29/02/2023 -> Form báo lỗi ngày tháng
        'TC_PER_030', # Sửa giới tính có vợ -> Cảnh báo confirm UI
        'TC_PER_031', # Bấm Ẩn -> Popup xác nhận UI
        'TC_PER_033', # Vào bộ lọc Đã ẩn -> Chọn Person -> Khôi phục
        'TC_PER_035', # Avatar mặc định / placeholder trên UI
        'TC_PER_036', # Bấm nút Xuất Excel -> Download file
        'TC_PER_038', # Xóa rỗng text Họ tên -> Bắt lỗi Require ở FE
        'TC_REL_041', # Thêm vợ chồng -> Hiển thị đường nối ngang trên cây UI
        'TC_REL_042', # Cùng giới tính -> Hiển thị cảnh báo UI
        'TC_REL_044', # Sửa Đã ly hôn -> Cây nét đứt hoặc có icon báo hiệu UI
        'TC_REL_046', # Tuổi kết hôn < 18 -> Cảnh báo UI
        'TC_REL_052', # Tạo mới popup Person Vợ ngay trong luồng tạo Hôn nhân UI
        'TC_REL_054', # Sắp xếp thứ tự vợ/chồng trên UI cây
        'TC_CLO_067', # UI hiển thị đúng anh lớn, em nhỏ: E -> D -> F
        'TC_CLO_077', # Gợi ý xưng hô tự động trên UI
        'TC_SEC_086', # Khách vãng lai vào nội bộ -> FE router guard đẩy về /login
        'TC_SEC_093', # Nhập pass và confirm pass lệch nhau -> Form FE báo lỗi
    }
    
    security_codes = {
        'TC_FAM_004', # XSS vào Lịch sử dòng họ
        'TC_FAM_006', # Đổi .exe thành .png upload (MIME spoofing attack)
        'TC_PER_020', # SQL Injection qua ô tìm kiếm
        'TC_PER_034', # Bypass soft delete, cố tình Hard Delete API
        'TC_SEC_081', # Session Timeout JWT
        'TC_SEC_082', # Invalid Token / Tampered JWT
        'TC_SEC_083', # Family Admin vs Trưởng tộc (RBAC)
        'TC_SEC_084', # IDOR sửa person họ khác
        'TC_SEC_085', # Bypass UI gọi API xóa person
        'TC_SEC_087', # Read-only data member gọi API sửa
        'TC_SEC_088', # Rate Limiting Brute Force
        'TC_SEC_089', # CORS Policy cross-origin
        'TC_SEC_090', # CSRF Protection
        'TC_SEC_091', # Sensitive data leakage (password hash)
        'TC_SEC_092', # Password Policy weak password
        'TC_SEC_094', # Account locked revocation
        'TC_SEC_095', # Horizontal privilege escalation
        'TC_SEC_096', # Data isolation private family
        'TC_SEC_097', # XSS Stored qua tên
        'TC_SEC_098', # Upload Shell .php/.js
        'TC_SEC_099', # Audit log quan trọng
        'TC_SEC_100', # Concurrency transaction ACID
    }

    for r in range(2, ws.max_row + 1):
        vals = [cell.value for cell in ws[r]]
        if not any(vals):
            continue
            
        code = (vals[1] or '').strip()
        category = (vals[0] or '').strip()
        feature = (vals[2] or '').strip()
        type_in_excel = (vals[3] or '').strip()
        scenario = (vals[4] or '').strip()
        input_action = (vals[5] or '').strip()
        expected = (vals[6] or '').strip()
        
        if code in security_codes or code.startswith('TC_SEC_') and code not in ui_ux_codes:
            classification = "Security Test"
        elif code in ui_ux_codes:
            classification = "UI/UX Test (Frontend Browser)"
        else:
            classification = "API Test (Backend)"
            
        test_cases.append({
            'index': r - 1,
            'code': code,
            'category': category,
            'feature': feature,
            'type_in_excel': type_in_excel,
            'scenario': scenario,
            'input_action': input_action,
            'expected': expected,
            'classification': classification
        })
        
    counts = {}
    for tc in test_cases:
        c = tc['classification']
        counts[c] = counts.get(c, 0) + 1
        
    print("Classifications count:", counts)
    
    out_path = get_file_path('classified_100_testcases.json', 'test_cases')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(test_cases, f, ensure_ascii=False, indent=2)
    print(f"Saved to: {out_path}")

if __name__ == '__main__':
    classify_all()
