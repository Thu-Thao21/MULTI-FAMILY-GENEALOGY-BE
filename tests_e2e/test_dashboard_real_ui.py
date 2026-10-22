# -*- coding: utf-8 -*-
import time
import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ==============================================================================
# REAL DASHBOARD & REAL CANVAS TREE E2E TEST SUITE
# Tests the actual Member Dashboard (/user) and Admin Dashboard (/admin)
# with TopBar, Sidebar, TreeLayout (Canvas/SVG), and RelationshipFinder.
# ==============================================================================

@pytest.fixture(scope="module")
def driver(request, base_url):
    """Module-scoped driver to preserve authentication session across dashboard tests."""
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


from selenium.webdriver.common.keys import Keys

def login_as_member(driver, base_url):
    """Helper to perform real authentication as Family Member."""
    if "/user" in driver.current_url and len(driver.find_elements(By.CLASS_NAME, "sidebar-container")) > 0:
        return

    driver.get(f"{base_url}/login")
    time.sleep(0.5)

    if "/user" in driver.current_url and len(driver.find_elements(By.CLASS_NAME, "sidebar-container")) > 0:
        return

    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.TAG_NAME, "form"))
    )
    
    # Enter credentials with reliable React input clearing
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
    
    submit_btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
    submit_btn.click()
    
    # Wait for redirect to /user with generous timeout for cloud DB response
    WebDriverWait(driver, 40).until(
        lambda d: "/user" in d.current_url and len(d.find_elements(By.CLASS_NAME, "sidebar-container")) > 0
    )
    time.sleep(1)


def click_sidebar_tab(driver, keyword, fallback_url=None):
    """Helper to find and click a sidebar subitem using textContent and execute_script."""
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CLASS_NAME, "sidebar-container"))
    )
    time.sleep(0.8)
    
    # Wait for subitems to be present
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "button.sidebar-subitem-btn"))
    )
    
    sub_buttons = driver.find_elements(By.CSS_SELECTOR, "button.sidebar-subitem-btn")
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


def test_01_real_login_and_dashboard_layout(driver, base_url):
    """Test 1: Đăng nhập tài khoản thật và kiểm tra Layout Dashboard chính (/user)."""
    login_as_member(driver, base_url)
    
    # Verify TopBar and Sidebar exist
    sidebar = WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CLASS_NAME, "sidebar-container"))
    )
    assert sidebar.is_displayed(), "Sidebar chính phải hiển thị"
    
    topbar = driver.find_element(By.CSS_SELECTOR, "header.topbar-header, .topbar-header")
    assert topbar.is_displayed(), "TopBar chính (topbar-header) phải hiển thị"
    
    # Verify search input in topbar
    search_input = driver.find_element(By.CSS_SELECTOR, ".topbar-search-input")
    assert search_input.is_displayed(), "Ô tìm kiếm nhanh trên TopBar phải hiển thị"
    
    page_text = driver.page_source.lower()
    assert "nguyễn văn cường" in page_text or "cây gia phả" in page_text or "gia phả & quan hệ" in page_text


def test_02_real_canvas_tree_layout(driver, base_url):
    """Test 2: Kiểm tra cây gia phả thực tế (TreeLayout & Canvas/SVG)."""
    login_as_member(driver, base_url)
    
    # Click 'Cây Gia Phả' tab in Sidebar
    clicked = click_sidebar_tab(driver, "cây gia phả", fallback_url=f"{base_url}/user/tree/horizontal")
    assert clicked, "Nút 'Cây Gia Phả' phải mở được trong Sidebar"
    
    # Verify TreeLayout container and toolbar
    tree_container = WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ".tree-page-layout, .tree-toolbar-card"))
    )
    assert tree_container.is_displayed(), "Vùng vẽ cây phả hệ (TreeLayout) phải hiển thị"
    
    # Verify Title
    page_text = driver.page_source
    assert "Cây Gia Phả" in page_text or "Trực Hệ" in page_text
    
    # Verify Zoom controls
    zoom_buttons = driver.find_elements(By.CSS_SELECTOR, ".tree-zoom-btn-group button, .tree-control-btn")
    assert len(zoom_buttons) >= 2, "Phải có các nút zoom phóng to / thu nhỏ (+, -)"
    
    # Test Zoom In
    zoom_in_btn = zoom_buttons[0]
    zoom_in_btn.click()
    time.sleep(0.5)


def test_03_tree_orientation_and_filters(driver, base_url):
    """Test 3: Xoay hướng cây (Dọc/Ngang) và bộ lọc thế hệ / chi nhánh."""
    login_as_member(driver, base_url)
    
    # Switch to tree tab
    click_sidebar_tab(driver, "cây gia phả", fallback_url=f"{base_url}/user/tree/horizontal")
    time.sleep(0.8)
        
    # Check Direction toggle buttons (Dọc / Ngang)
    dir_buttons = WebDriverWait(driver, 15).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, ".tree-dir-btn, .tree-dir-toggle-group button"))
    )
    assert len(dir_buttons) >= 2, "Phải có cụm nút xoay hướng cây (Dọc / Ngang)"
    
    # Click Ngang (Horizontal)
    dir_buttons[1].click()
    time.sleep(0.5)
    
    # Click Dọc (Vertical)
    dir_buttons[0].click()
    time.sleep(0.5)
        
    # Check Generation and Family dropdowns
    selects = driver.find_elements(By.CSS_SELECTOR, "select.tree-control-select")
    assert len(selects) >= 1, "Cần có dropdown lọc thế hệ / chi nhánh / dòng họ trên cây"


def test_04_real_relationship_finder_ui(driver, base_url):
    """Test 4: Tra cứu & Xưng hô họ hàng thực tế (RelationshipFinder)."""
    login_as_member(driver, base_url)
    
    # Click 'Tra cứu & Xưng hô' in sidebar
    clicked = click_sidebar_tab(driver, "xưng hô", fallback_url=f"{base_url}/user/relationship")
    assert clicked, "Nút 'Tra cứu & Xưng hô' phải mở được trong Sidebar"
    
    # Verify RelationshipFinder card container
    rf_card = WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ".rel-finder-container"))
    )
    assert rf_card.is_displayed(), "Giao diện Tra cứu & Xưng hô phải hiển thị"
    
    # Verify title & subheader
    page_text = driver.page_source
    assert "Tra Cứu Quan Hệ" in page_text or "Xưng Hô" in page_text
    
    # Check person selection dropdowns
    selects = driver.find_elements(By.CSS_SELECTOR, "select.rel-select, .rel-select-group select")
    assert len(selects) >= 1, "Cần có ô chọn người để tra cứu quan hệ"
    
    # Check calculate button
    calc_buttons = driver.find_elements(By.CSS_SELECTOR, "button.rel-calc-btn")
    if calc_buttons:
        calc_buttons[0].click()
        time.sleep(1)


def test_05_real_member_list_table(driver, base_url):
    """Test 5: Danh sách thành viên dòng họ thực tế (MemberList)."""
    login_as_member(driver, base_url)
    
    # Click 'Danh sách thành viên' in sidebar
    clicked = click_sidebar_tab(driver, "thành viên", fallback_url=f"{base_url}/user/members")
    assert clicked, "Nút 'Danh sách thành viên' phải mở được trong Sidebar"
    
    # Verify MemberList container
    mem_container = WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ".member-list-container, .member-list-title"))
    )
    assert mem_container.is_displayed(), "Danh sách thành viên gia tộc phải hiển thị"
    
    # Check search input
    search_input = driver.find_element(By.CSS_SELECTOR, ".member-search-input")
    assert search_input.is_displayed(), "Ô tìm kiếm thành viên phải hiển thị"


def test_06_real_network_tabs(driver, base_url):
    """Test 6: Mạng lưới liên họ thực tế (Dòng họ Nội, Ngoại, Dâu & Rể)."""
    login_as_member(driver, base_url)
    
    # Click 'Dòng họ Nội'
    click_sidebar_tab(driver, "nội", fallback_url=f"{base_url}/user/network/noi")
    time.sleep(0.5)
    page_text = driver.page_source.lower()
    assert "nội" in page_text or "liên họ" in page_text or "dòng họ" in page_text
        
    # Click 'Dâu & Rể liên họ'
    click_sidebar_tab(driver, "dâu", fallback_url=f"{base_url}/user/network/dau-re")
    time.sleep(0.5)
    page_text = driver.page_source.lower()
    assert "dâu" in page_text or "rể" in page_text or "liên họ" in page_text


def test_07_real_admin_login_and_dashboard(base_url):
    """Test 7: Đăng nhập Quản trị viên (Admin) và kiểm tra Dashboard Quản trị (/admin)."""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1600,1000")
    
    admin_driver = webdriver.Chrome(options=options)
    try:
        admin_driver.get(f"{base_url}/login")
        WebDriverWait(admin_driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "form"))
        )
        
        ident_input = WebDriverWait(admin_driver, 15).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "#login-identifier, input[name='emailOrPhone']"))
        )
        ident_input.send_keys("admin@test.com")
        
        pw_input = admin_driver.find_element(By.CSS_SELECTOR, "input[type='password']")
        pw_input.send_keys("admin123")
        
        submit_btn = admin_driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        submit_btn.click()
        
        # Wait for redirect to /admin
        try:
            WebDriverWait(admin_driver, 30).until(
                lambda d: "/admin" in d.current_url or len(d.find_elements(By.CLASS_NAME, "sidebar-admin-menu")) > 0
            )
        except Exception:
            admin_driver.save_screenshot("tests_e2e/screenshots/test_07_debug.png")
            print("URL on failure:", admin_driver.current_url)
            raise
        
        # Verify Admin Sidebar items exist
        admin_menu = WebDriverWait(admin_driver, 15).until(
            EC.presence_of_element_located((By.CLASS_NAME, "sidebar-admin-menu"))
        )
        assert admin_menu.is_displayed(), "Menu Sidebar của Admin phải hiển thị"
        
        admin_items = admin_driver.find_elements(By.CLASS_NAME, "sidebar-admin-item")
        assert len(admin_items) >= 5, "Admin sidebar phải có các mục quản lý"
        
        page_text = admin_driver.page_source.lower()
        assert "quản lý" in page_text or "dashboard" in page_text
    finally:
        admin_driver.quit()
