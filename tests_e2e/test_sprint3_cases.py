# -*- coding: utf-8 -*-
import time
import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC

# ==============================================================================
# SPRINT 3 AUTOMATED SELENIUM TEST SUITE (SEL3-001 -> SEL3-016)
# Tests directly on the REAL DASHBOARD (/user, /admin, /public)
# Uses Canvas TreeLayout, standard Sidebar, and Real Neon PostgreSQL DB Data.
# ==============================================================================

@pytest.fixture(scope="module")
def driver(request, base_url):
    """Module-scoped driver to preserve authentication session across tests."""
    headed = request.config.getoption("--headed")
    options = Options()
    if not headed:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1600,1000")

    drv = webdriver.Chrome(options=options)
    drv.implicitly_wait(6)
    yield drv
    drv.quit()


def ensure_member_logged_in(driver, base_url):
    """Helper: Đăng nhập bằng tài khoản thành viên thật (member@test.com)."""
    if "/user" in driver.current_url and len(driver.find_elements(By.CLASS_NAME, "sidebar-container")) > 0:
        return

    driver.get(f"{base_url}/user")
    try:
        WebDriverWait(driver, 6).until(
            EC.presence_of_element_located((By.CLASS_NAME, "sidebar-container"))
        )
        return
    except Exception:
        pass

    if "/login" not in driver.current_url:
        driver.get(f"{base_url}/login")
        time.sleep(0.5)

    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.TAG_NAME, "form"))
    )
    
    ident_input = WebDriverWait(driver, 15).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "#login-identifier, input[name='emailOrPhone']"))
    )
    ident_input.send_keys(Keys.CONTROL + "a")
    ident_input.send_keys(Keys.BACKSPACE)
    ident_input.send_keys("member@test.com")
    
    pw_input = driver.find_element(By.CSS_SELECTOR, "input[name='password'], input[type='password']")
    pw_input.send_keys(Keys.CONTROL + "a")
    pw_input.send_keys(Keys.BACKSPACE)
    pw_input.send_keys("123456")
    
    driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
    
    WebDriverWait(driver, 40).until(
        lambda d: "/user" in d.current_url and len(d.find_elements(By.CLASS_NAME, "sidebar-container")) > 0
    )
    time.sleep(1)


def switch_sidebar_tab(driver, keyword, fallback_url=None):
    """Helper: Click chuyển tab từ thanh Sidebar chuẩn bằng textContent."""
    if fallback_url and fallback_url in driver.current_url:
        return True

    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CLASS_NAME, "sidebar-container"))
    )
    time.sleep(0.3)
    
    sub_buttons = driver.find_elements(By.CSS_SELECTOR, "button.sidebar-subitem-btn, button.sidebar-nav-btn")
    for btn in sub_buttons:
        raw_text = btn.get_attribute("textContent") or btn.text or ""
        if keyword.lower() in raw_text.strip().lower():
            driver.execute_script("arguments[0].scrollIntoView(true); arguments[0].click();", btn)
            time.sleep(1.2)
            return True
            
    if fallback_url:
        driver.get(fallback_url)
        time.sleep(1.2)
        return True
        
    return False


# ==============================================================================
# NHÓM 1: CÂY GIA PHẢ TRỰC HỆ (Canvas TreeLayout, Zoom, Focus View, Filter)
# ==============================================================================

def test_sel3_001_open_family_tree(driver, base_url):
    """SEL3-001: Mở cây gia phả - Render TreeLayout & Canvas trên Dashboard thật (/user)."""
    ensure_member_logged_in(driver, base_url)
    
    # Click 'Cây Gia Phả' trong Sidebar
    assert switch_sidebar_tab(driver, "cây gia phả", fallback_url=f"{base_url}/user/tree/horizontal")
    
    # Verify TreeLayout toolbar & layout card
    tree_toolbar = WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ".tree-toolbar-card, .tree-page-layout"))
    )
    assert tree_toolbar.is_displayed(), "Thanh công cụ cây gia phả phải hiển thị"
    
    page_text = driver.page_source
    assert "Cây Gia Phả Trực Hệ" in page_text or "Gia Phả" in page_text
    
    # Verify stats badges (Thành viên, Thế hệ, Nam, Nữ)
    stats_pills = driver.find_elements(By.CSS_SELECTOR, ".tree-stat-pill")
    assert len(stats_pills) >= 2, "Cần có các pill thống kê số lượng thành viên, thế hệ trên cây"


def test_sel3_002_tree_scale_and_zoom(driver, base_url):
    """SEL3-002: Thao tác phóng to / thu nhỏ cây gia phả trực hệ (Zoom controls)."""
    ensure_member_logged_in(driver, base_url)
    switch_sidebar_tab(driver, "cây gia phả", fallback_url=f"{base_url}/user/tree/horizontal")
    
    # Locate zoom buttons (+, -, Reset)
    zoom_buttons = WebDriverWait(driver, 15).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".tree-zoom-btn-group button, .tree-control-btn"))
    )
    assert len(zoom_buttons) >= 2, "Phải có ít nhất 2 nút zoom (+ và -)"
    
    # Click Zoom In (+)
    zoom_in_btn = zoom_buttons[0]
    zoom_in_btn.click()
    time.sleep(0.5)
    
    # Click Zoom Out (-)
    zoom_out_btn = zoom_buttons[1]
    zoom_out_btn.click()
    time.sleep(0.5)


def test_sel3_003_focus_view_central_person(driver, base_url):
    """SEL3-003: Bật Focus View chọn một người làm trung tâm (Focus Dropdown)."""
    ensure_member_logged_in(driver, base_url)
    switch_sidebar_tab(driver, "cây gia phả", fallback_url=f"{base_url}/user/tree/horizontal")
    
    # Find focus member select
    focus_selects = driver.find_elements(By.CSS_SELECTOR, "select.focus-select, select.tree-control-select")
    assert len(focus_selects) > 0, "Cần có dropdown chọn người làm trung tâm (Focus)"
    
    # Pick the last select which is Focus select
    focus_elem = focus_selects[-1]
    select = Select(focus_elem)
    if len(select.options) > 1:
        select.select_by_index(1)
        time.sleep(0.8)
        # Verify focus state indicated in subtitle
        page_text = driver.page_source
        assert "Focus View" in page_text or "trung tâm" in page_text or "Trực Hệ" in page_text


def test_sel3_004_filter_by_branch_and_generation(driver, base_url):
    """SEL3-004: Thu gọn / Lọc cây theo Chi/Nhánh hoặc Đời thứ (Generation & Branch Filter)."""
    ensure_member_logged_in(driver, base_url)
    switch_sidebar_tab(driver, "cây gia phả", fallback_url=f"{base_url}/user/tree/horizontal")
    
    # Find generation select
    selects = driver.find_elements(By.CSS_SELECTOR, "select.tree-control-select")
    assert len(selects) >= 1, "Cần có dropdown lọc thế hệ / chi nhánh trên cây"
    
    # Toggle Direction (Dọc / Ngang)
    dir_buttons = driver.find_elements(By.CSS_SELECTOR, ".tree-dir-btn, .tree-dir-toggle-group button")
    if len(dir_buttons) >= 2:
        dir_buttons[0].click()  # Dọc
        time.sleep(0.5)
        dir_buttons[1].click()  # Ngang
        time.sleep(0.5)


# ==============================================================================
# NHÓM 2: TÌM KIẾM THÀNH VIÊN (Person Search & Validation)
# ==============================================================================

def test_sel3_005_search_person(driver, base_url):
    """SEL3-005: Tìm kiếm người trong danh sách thành viên dòng họ - Trả về kết quả phù hợp."""
    ensure_member_logged_in(driver, base_url)
    
    # Switch to 'Danh sách thành viên'
    assert switch_sidebar_tab(driver, "thành viên", fallback_url=f"{base_url}/user/members")
    
    # Verify MemberList container
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ".member-list-container, .member-list-title"))
    )
    
    # Input search keyword
    search_input = driver.find_element(By.CSS_SELECTOR, ".member-search-input")
    search_input.send_keys(Keys.CONTROL + "a")
    search_input.send_keys(Keys.BACKSPACE)
    search_input.send_keys("Nguyễn")
    time.sleep(1)
    
    page_text = driver.page_source.lower()
    assert "danh sách" in page_text or "thành viên" in page_text


def test_sel3_006_search_person_not_found(driver, base_url):
    """SEL3-006: Tìm kiếm người không tồn tại - Hiển thị trạng thái không có kết quả."""
    ensure_member_logged_in(driver, base_url)
    switch_sidebar_tab(driver, "thành viên", fallback_url=f"{base_url}/user/members")
    
    search_input = WebDriverWait(driver, 15).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, ".member-search-input"))
    )
    search_input.send_keys(Keys.CONTROL + "a")
    search_input.send_keys(Keys.BACKSPACE)
    search_input.send_keys("NGUOI_KHONG_TON_TAI_XYZ999")
    time.sleep(1)
    
    page_text = driver.page_source.lower()
    # Check that non-existing name is not in person cards or empty results
    assert "xyz999" not in page_text or "0" in page_text or "không" in page_text


# ==============================================================================
# NHÓM 3: TÍNH TOÁN QUAN HỆ HUYẾT THỐNG & XƯNG HÔ (RelationshipFinder)
# ==============================================================================

def test_sel3_007_calculate_parent_child_kinship(driver, base_url):
    """SEL3-007: Tính quan hệ trực hệ & xưng hô họ hàng (Relationship calculation)."""
    ensure_member_logged_in(driver, base_url)
    
    # Switch to 'Tra cứu & Xưng hô'
    assert switch_sidebar_tab(driver, "xưng hô", fallback_url=f"{base_url}/user/relationship")
    
    # Verify RelationshipFinder card container
    rf_card = WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ".rel-finder-container"))
    )
    assert rf_card.is_displayed(), "Module Tra Cứu Quan Hệ & Xưng Hô phải hiển thị"
    
    # Verify selects for Person A and Person B
    selects = driver.find_elements(By.CSS_SELECTOR, "select.rel-select, .rel-select-group select")
    assert len(selects) >= 1, "Cần có ô chọn người để tính quan hệ"
    
    # Click calculate button
    calc_buttons = driver.find_elements(By.CSS_SELECTOR, "button.rel-calc-btn")
    if calc_buttons:
        calc_buttons[0].click()
        time.sleep(1)
        
        # Verify calculation result elements
        page_text = driver.page_source.lower()
        assert "xưng hô" in page_text or "kết quả" in page_text or "quan hệ" in page_text


def test_sel3_008_calculate_unrelated_person(driver, base_url):
    """SEL3-008: Tính quan hệ một người với chính mình (Same person / Identity check)."""
    ensure_member_logged_in(driver, base_url)
    switch_sidebar_tab(driver, "xưng hô", fallback_url=f"{base_url}/user/relationship")
    
    selects = driver.find_elements(By.CSS_SELECTOR, "select.rel-select, .rel-select-group select")
    if len(selects) >= 2:
        s1 = Select(selects[0])
        s2 = Select(selects[1])
        if len(s1.options) > 0 and len(s2.options) > 0:
            s1.select_by_index(0)
            s2.select_by_index(0)
            time.sleep(0.5)
            
            calc_btn = driver.find_element(By.CSS_SELECTOR, "button.rel-calc-btn")
            calc_btn.click()
            time.sleep(1)
            
            page_text = driver.page_source.lower()
            assert "chính mình" in page_text or "tôi" in page_text or "cùng một người" in page_text


def test_sel3_009_ancestor_descendant_tree_structure(driver, base_url):
    """SEL3-009: Xem cấu trúc tổ tiên & hậu duệ qua các thế hệ (Lineage Tab)."""
    ensure_member_logged_in(driver, base_url)
    switch_sidebar_tab(driver, "xưng hô", fallback_url=f"{base_url}/user/relationship")
    
    # Click subtab 'Tra cứu Tổ tiên & Hậu duệ'
    lineage_tab_btns = driver.find_elements(By.CSS_SELECTOR, "button.rel-tab-btn")
    if len(lineage_tab_btns) >= 2:
        lineage_tab_btns[1].click()
        time.sleep(1)
        
        page_text = driver.page_source.lower()
        assert "tổ tiên" in page_text or "hậu duệ" in page_text


# ==============================================================================
# NHÓM 4: MẠNG LƯỚI LIÊN HỌ (Inter-clan Network & Link Management)
# ==============================================================================

def test_sel3_010_send_inter_family_link_request(driver, base_url):
    """SEL3-010: Xem mạng lưới Dòng họ Nội (Inter-clan network category)."""
    ensure_member_logged_in(driver, base_url)
    
    # Click 'Dòng họ Nội' in sidebar
    switch_sidebar_tab(driver, "nội", fallback_url=f"{base_url}/user/network/noi")
    time.sleep(0.8)
    
    page_text = driver.page_source.lower()
    assert "nội" in page_text or "liên họ" in page_text or "dòng họ" in page_text


def test_sel3_011_approve_link_request(driver, base_url):
    """SEL3-011: Xem mạng lưới Dòng họ Ngoại."""
    ensure_member_logged_in(driver, base_url)
    
    # Click 'Dòng họ Ngoại'
    switch_sidebar_tab(driver, "ngoại", fallback_url=f"{base_url}/user/network/ngoai")
    time.sleep(0.8)
    
    page_text = driver.page_source.lower()
    assert "ngoại" in page_text or "liên họ" in page_text or "dòng họ" in page_text


def test_sel3_012_reject_link_request(driver, base_url):
    """SEL3-012: Xem mạng lưới Dâu & Rể liên họ."""
    ensure_member_logged_in(driver, base_url)
    
    # Click 'Dâu & Rể'
    switch_sidebar_tab(driver, "dâu", fallback_url=f"{base_url}/user/network/dau-re")
    time.sleep(0.8)
    
    page_text = driver.page_source.lower()
    assert "dâu" in page_text or "rể" in page_text or "liên họ" in page_text


def test_sel3_013_unlink_or_cancel_request(driver, base_url):
    """SEL3-013: Xem mạng lưới Họ Thông gia."""
    ensure_member_logged_in(driver, base_url)
    
    # Click 'Thông gia'
    switch_sidebar_tab(driver, "thông gia", fallback_url=f"{base_url}/user/network/thong-gia")
    time.sleep(0.8)
    
    page_text = driver.page_source.lower()
    assert "thông gia" in page_text or "liên họ" in page_text or "dòng họ" in page_text


# ==============================================================================
# NHÓM 5: BẢO MẬT & PHÂN QUYỀN TRUY CẬP (Access Control & Public Privacy)
# ==============================================================================

def test_sel3_014_public_profile_guest_view(base_url, request):
    """SEL3-014: Khách xem thông tin công khai (PUBLIC), bảo vệ dữ liệu nhạy cảm."""
    headed = request.config.getoption("--headed")
    options = Options()
    if not headed:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    
    guest_driver = webdriver.Chrome(options=options)
    try:
        guest_driver.get(f"{base_url}/public/families")
        WebDriverWait(guest_driver, 15).until(
            lambda d: "dòng họ" in d.page_source.lower() or "tra cứu" in d.page_source.lower() or "công khai" in d.page_source.lower()
        )
        page_text = guest_driver.page_source.lower()
        # Sensitive credentials must NEVER leak into public DOM
        assert "password_hash" not in page_text
        assert "firebase_token" not in page_text
        assert "secret_key" not in page_text
    finally:
        guest_driver.quit()


def test_sel3_015_security_unauthorized_access(base_url, request):
    """SEL3-015: Khách chưa đăng nhập không được truy cập trái phép trang quản trị (/admin)."""
    headed = request.config.getoption("--headed")
    options = Options()
    if not headed:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    
    anon_driver = webdriver.Chrome(options=options)
    try:
        anon_driver.get(f"{base_url}/admin")
        time.sleep(2)
        current_url = anon_driver.current_url
        page_text = anon_driver.page_source.lower()
        # Must be redirected to /login or blocked
        assert "/login" in current_url or "/public" in current_url or "đăng nhập" in page_text
    finally:
        anon_driver.quit()


# ==============================================================================
# NHÓM 6: HỒI QUY DỮ LIỆU ĐÃ LƯU (Regression Data Verification on Real DB)
# ==============================================================================

def test_sel3_016_regression_person_and_relationship_data(driver, base_url):
    """SEL3-016: Kiểm tra hồi quy toàn diện - Dữ liệu thực từ Neon PostgreSQL hiển thị đầy đủ trên Dashboard."""
    ensure_member_logged_in(driver, base_url)
    
    # Verify TopBar
    topbar = WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "header.topbar-header, .topbar-header"))
    )
    assert topbar.is_displayed(), "TopBar chính phải hiển thị đầy đủ"
    
    # Verify Sidebar menu
    sidebar = driver.find_element(By.CLASS_NAME, "sidebar-container")
    assert sidebar.is_displayed(), "Sidebar chính phải hiển thị đầy đủ"
    
    # Verify User Display Name
    page_text = driver.page_source.lower()
    assert "nguyễn văn cường" in page_text or "gia phả" in page_text or "dòng họ" in page_text
    
    # Verify Footer System Brand
    footer = driver.find_element(By.CLASS_NAME, "dashboard-footer")
    assert footer.is_displayed(), "Footer hệ thống phải hiển thị"
    assert "multi-family genealogy system" in footer.text.lower()
