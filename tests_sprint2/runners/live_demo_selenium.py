import time
import sys
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

sys.stdout.reconfigure(encoding='utf-8')

FE_URL = "http://localhost:5173"

def update_banner(driver, text):
    script = """
    let b = document.getElementById('selenium-hud-banner');
    if (!b) {
        b = document.createElement('div');
        b.id = 'selenium-hud-banner';
        b.style.position = 'fixed';
        b.style.top = '10px';
        b.style.left = '50%';
        b.style.transform = 'translateX(-50%)';
        b.style.backgroundColor = '#1e293b';
        b.style.color = '#38bdf8';
        b.style.border = '2px solid #38bdf8';
        b.style.borderRadius = '8px';
        b.style.padding = '12px 24px';
        b.style.fontSize = '17px';
        b.style.fontWeight = 'bold';
        b.style.boxShadow = '0 10px 25px rgba(0,0,0,0.5)';
        b.style.zIndex = '9999999';
        b.style.pointerEvents = 'none';
        b.style.transition = 'all 0.3s ease';
        document.body.appendChild(b);
    }
    b.innerHTML = arguments[0];
    """
    try:
        driver.execute_script(script, text)
    except Exception:
        pass

def highlight(driver, element, color="#ef4444"):
    try:
        driver.execute_script(f"""
            arguments[0].scrollIntoView({{behavior: 'smooth', block: 'center'}});
            arguments[0].style.outline = '4px solid {color}';
            arguments[0].style.boxShadow = '0 0 15px {color}';
            arguments[0].style.transition = 'all 0.3s ease';
        """, element)
    except Exception:
        pass

def unhighlight(driver, element):
    try:
        driver.execute_script("""
            arguments[0].style.outline = '';
            arguments[0].style.boxShadow = '';
        """, element)
    except Exception:
        pass

def slow_type(element, text, delay=0.06):
    for char in text:
        element.send_keys(char)
        time.sleep(delay)

def main():
    print("=" * 65)
    print(" 🚀 KHỞI ĐỘNG CỬA SỔ TRÌNH DUYỆT GOOGLE CHROME TRỰC TIẾP")
    print("=" * 65)
    
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # KHÔNG dùng headless để người dùng nhìn thấy cửa sổ trình duyệt thực tế
    
    driver = webdriver.Chrome(options=options)
    driver.implicitly_wait(6)

    try:
        # BƯỚC 1: TRANG CHỦ PUBLIC
        print("\n[1/6] 🌐 Điều hướng đến Trang Chủ Gia Phả Việt...")
        driver.get(f"{FE_URL}/public")
        time.sleep(1.5)
        update_banner(driver, "🤖 BƯỚC 1: TRANG CHỦ CÔNG KHAI - Xem tổng quan hệ thống")
        time.sleep(1.5)
        
        # Cuộn trang tự động
        for scroll_y in [400, 800, 1200, 0]:
            driver.execute_script(f"window.scrollTo({{top: {scroll_y}, behavior: 'smooth'}});")
            time.sleep(0.8)

        # BƯỚC 2: GÓI DỊCH VỤ DOANH NGHIỆP / DÒNG HỌ
        print("\n[2/6] 💳 Xem Gói Dịch Vụ / Business Plans...")
        update_banner(driver, "🤖 BƯỚC 2: Xem các Gói dịch vụ & Bảng giá dòng họ...")
        driver.get(f"{FE_URL}/public/business-plans")
        time.sleep(1.5)
        
        cards = driver.find_elements(By.CSS_SELECTOR, ".plan-card, [class*='card'], .border")
        for i, card in enumerate(cards[:3]):
            update_banner(driver, f"🤖 Đang kiểm tra Gói dịch vụ #{i+1}...")
            highlight(driver, card, "#10b981")
            time.sleep(1)
            unhighlight(driver, card)

        # BƯỚC 3: ĐĂNG KÝ THÀNH LẬP DÒNG HỌ (NHẬP LIỆU TỰ ĐỘNG)
        print("\n[3/6] ✍️ Tự động nhập Form Đăng Ký Dòng Họ...")
        driver.get(f"{FE_URL}/public/business-register")
        time.sleep(1.5)
        update_banner(driver, "🤖 BƯỚC 3: TỰ ĐỘNG NHẬP LIỆU FORM ĐĂNG KÝ DÒNG HỌ")
        time.sleep(1)

        inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='text'], input[type='email'], input[type='tel'], input:not([type='hidden'])")
        
        sample_data = [
            "Họ Nguyễn Đại Tộc",
            "Nguyễn Văn An",
            "nguyenan.daitoc@example.com",
            "0912345678",
            "Hà Nội",
        ]
        
        for idx, val in enumerate(sample_data):
            if idx < len(inputs):
                inp = inputs[idx]
                try:
                    update_banner(driver, f"🤖 Đang gõ trường #{idx+1}: <span style='color:#facc15'>{val}</span>")
                    highlight(driver, inp, "#f59e0b")
                    time.sleep(0.4)
                    inp.clear()
                    slow_type(inp, val, delay=0.05)
                    time.sleep(0.4)
                    unhighlight(driver, inp)
                except Exception as e:
                    print(f"Bỏ qua input {idx}: {e}")

        # BƯỚC 4: TRA CỨU HỒ SƠ
        print("\n[4/6] 🔍 Tra cứu tiến độ hồ sơ dòng họ...")
        driver.get(f"{FE_URL}/public/business-register/track")
        time.sleep(1.5)
        update_banner(driver, "🤖 BƯỚC 4: TRA CỨU TIẾN ĐỘ HỒ SƠ DÒNG HỌ")
        
        track_inputs = driver.find_elements(By.TAG_NAME, "input")
        if track_inputs:
            update_banner(driver, "🤖 Nhập mã hồ sơ: <span style='color:#facc15'>REG-2026-MFG-001</span>")
            highlight(driver, track_inputs[0], "#8b5cf6")
            time.sleep(0.5)
            slow_type(track_inputs[0], "REG-2026-MFG-001", delay=0.06)
            time.sleep(0.8)
            unhighlight(driver, track_inputs[0])

            buttons = driver.find_elements(By.TAG_NAME, "button")
            if buttons:
                update_banner(driver, "🤖 Bấm nút Tra Cứu...")
                highlight(driver, buttons[0], "#ec4899")
                time.sleep(0.8)
                buttons[0].click()
                time.sleep(1.5)
                unhighlight(driver, buttons[0])

        # BƯỚC 5: FAMILY ADMIN PREVIEW - CHUYỂN QUA CÁC TAB CHỨC NĂNG SPRINT 2
        print("\n[5/6] 🌳 Khám phá Family Admin (Chuyển Tab: Person, Quan hệ, Cây, Chi/Nhánh, Tra cứu)...")
        driver.get(f"{FE_URL}/family-admin-preview?view=overview")
        time.sleep(1.5)
        update_banner(driver, "🤖 BƯỚC 5: KHÁM PHÁ FAMILY ADMIN & PHẢ ĐỒ GIA PHẢ")
        time.sleep(1)

        tab_names = [
            ("members", "Tab Person - Danh Sách Thành Viên"),
            ("relations", "Tab Quan Hệ - Hôn Nhân & Huyết Thống"),
            ("branches", "Tab Chi/Nhánh - Quản Lý Các Phân Chi"),
            ("tree", "Tab Cây - Phả Đồ Gia Phả Trực Quan"),
            ("search", "Tab Tra Cứu - Tìm Kiếm Thành Viên"),
            ("exchange", "Tab Nhập Xuất - Xuất Dữ Liệu Excel"),
            ("audit", "Tab Nhật Ký - Ghi Vết Thao Tác Audit Log"),
        ]

        for tab_id, tab_label in tab_names:
            update_banner(driver, f"🤖 Chuyển sang: <span style='color:#38bdf8'>{tab_label}</span>")
            # Tìm nút tab tương ứng
            tab_btns = driver.find_elements(By.XPATH, f"//button[contains(text(), '{tab_label.split(' - ')[0].replace('Tab ', '')}') or contains(@class, '{tab_id}')]")
            if not tab_btns:
                driver.get(f"{FE_URL}/family-admin-preview?view={tab_id}")
            else:
                highlight(driver, tab_btns[0], "#38bdf8")
                time.sleep(0.6)
                tab_btns[0].click()
                unhighlight(driver, tab_btns[0])
            
            time.sleep(2)
            # Cuộn nhẹ trang để người dùng xem nội dung tab
            driver.execute_script("window.scrollBy({top: 250, behavior: 'smooth'});")
            time.sleep(1)
            driver.execute_script("window.scrollBy({top: -250, behavior: 'smooth'});")
            time.sleep(0.5)

        # BƯỚC 6: TRANG ĐĂNG NHẬP
        print("\n[6/6] 🔐 Chuyển sang Trang Đăng Nhập & Nhập Tài Khoản...")
        driver.get(f"{FE_URL}/login")
        time.sleep(1.5)
        update_banner(driver, "🤖 BƯỚC 6: FORM ĐĂNG NHẬP HỆ THỐNG")
        time.sleep(1)

        login_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='text'], input[type='email'], input[name='emailOrPhone'], #login-identifier")
        if login_inputs:
            update_banner(driver, "🤖 Nhập Email: <span style='color:#facc15'>thuthaor120608@gmail.com</span>")
            highlight(driver, login_inputs[0], "#f59e0b")
            time.sleep(0.5)
            login_inputs[0].clear()
            slow_type(login_inputs[0], "thuthaor120608@gmail.com", delay=0.06)
            unhighlight(driver, login_inputs[0])
            time.sleep(0.6)

        pw_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='password'], input[name='password']")
        if pw_inputs:
            update_banner(driver, "🤖 Nhập Mật khẩu: <span style='color:#facc15'>••••••••</span>")
            highlight(driver, pw_inputs[0], "#f59e0b")
            time.sleep(0.5)
            pw_inputs[0].clear()
            slow_type(pw_inputs[0], "Admin@2026", delay=0.06)
            unhighlight(driver, pw_inputs[0])
            time.sleep(0.8)

        update_banner(driver, "🎉 HOÀN THÀNH DEMO ĐIỀU KHIỂN TỰ ĐỘNG! Cửa sổ sẽ giữ mở thêm 5 giây...")
        print("\n✅ Hoàn thành toàn bộ kịch bản tự động điều khiển trình duyệt!")
        time.sleep(5)

    except Exception as e:
        print(f"\n❌ Lỗi trong quá trình điều khiển: {e}")
    finally:
        print("\nĐóng trình duyệt.")
        driver.quit()

if __name__ == '__main__':
    main()
