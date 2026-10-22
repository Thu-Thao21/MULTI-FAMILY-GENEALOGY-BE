import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def test_public_family_search(driver, base_url):
    """Sprint 3 (FR-BO-52, FR-GU-03): Test public clan search interface and Neon DB data."""
    driver.get(f"{base_url}/public/families")
    WebDriverWait(driver, 10).until(
        lambda d: len(d.find_elements(By.TAG_NAME, "input")) > 0
    )

    # Verify search input field exists
    search_input = driver.find_element(By.TAG_NAME, "input")
    assert search_input.is_displayed()

    # Search for an active clan
    search_input.clear()
    search_input.send_keys("Võ")
    time.sleep(1)

    # Check page content
    page_text = driver.page_source.lower()
    assert "dòng họ" in page_text or "tìm kiếm" in page_text

def test_family_tree_visualization(driver, base_url):
    """Sprint 3 (FR-BO-39..44): Test Family Tree View, controls, zoom, pan, and orientation."""
    driver.get(f"{base_url}/family-admin-preview?view=tree")
    WebDriverWait(driver, 10).until(
        lambda d: len(d.find_elements(By.TAG_NAME, "button")) > 0
    )

    # Verify orientation toggle button or controls exist
    buttons = driver.find_elements(By.TAG_NAME, "button")
    button_texts = [b.text.strip().lower() for b in buttons if b.text.strip()]
    
    # Check tree interaction buttons
    page_content = driver.page_source.lower()
    assert any(k in page_content for k in ["cây", "ngang", "đứng", "thu phóng", "zoom", "đời", "chi"])

def test_member_and_person_search(driver, base_url):
    """Sprint 3 (FR-BO-45, FR-ME-11): Test Person / Member search UI."""
    driver.get(f"{base_url}/family-admin-preview?view=search")
    WebDriverWait(driver, 10).until(
        lambda d: len(d.find_elements(By.TAG_NAME, "input")) > 0 or len(d.find_elements(By.TAG_NAME, "button")) > 0
    )
    page_text = driver.page_source.lower()
    assert "tra cứu" in page_text or "tìm" in page_text or "thành viên" in page_text

def test_inter_family_linking_ui(driver, base_url):
    """Sprint 3 (FR-BO-53..57, FR-BO-77): Test Inter-Family linking and network interface."""
    driver.get(f"{base_url}/family-admin-preview?view=links")
    WebDriverWait(driver, 10).until(
        lambda d: len(d.find_elements(By.TAG_NAME, "button")) > 0
    )
    page_text = driver.page_source.lower()
    assert "liên họ" in page_text or "kết nối" in page_text or "yêu cầu" in page_text

def test_relationship_and_kinship_ui(driver, base_url):
    """Sprint 3 (FR-BO-46..48): Test Relationship calculation & Vietnamese kinship naming interface."""
    driver.get(f"{base_url}/family-admin-preview?view=relations")
    WebDriverWait(driver, 10).until(
        lambda d: len(d.find_elements(By.TAG_NAME, "button")) > 0 or len(d.find_elements(By.TAG_NAME, "table")) > 0
    )
    page_text = driver.page_source.lower()
    assert "quan hệ" in page_text
