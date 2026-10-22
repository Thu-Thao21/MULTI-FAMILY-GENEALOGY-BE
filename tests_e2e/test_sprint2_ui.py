import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def test_business_plans_page(driver, base_url):
    """Sprint 2: Test Service Packages / Business Plans page."""
    driver.get(f"{base_url}/public/business-plans")
    WebDriverWait(driver, 10).until(
        lambda d: len(d.find_elements(By.TAG_NAME, "h1")) > 0 or len(d.find_elements(By.TAG_NAME, "h2")) > 0
    )
    # Check for plan/package elements or cards
    page_text = driver.page_source
    assert "gói" in page_text.lower() or "dịch vụ" in page_text.lower() or "plan" in page_text.lower()

def test_business_registration_wizard(driver, base_url):
    """Sprint 2: Test Clan registration wizard form."""
    driver.get(f"{base_url}/public/business-register")
    WebDriverWait(driver, 10).until(
        lambda d: len(d.find_elements(By.TAG_NAME, "input")) > 0
    )
    inputs = driver.find_elements(By.TAG_NAME, "input")
    assert len(inputs) > 0

def test_business_track_page(driver, base_url):
    """Sprint 2: Test Registration tracking status page."""
    driver.get(f"{base_url}/public/business-register/track")
    WebDriverWait(driver, 10).until(
        lambda d: len(d.find_elements(By.TAG_NAME, "input")) > 0 or len(d.find_elements(By.TAG_NAME, "button")) > 0
    )
    page_text = driver.page_source
    assert "tra cứu" in page_text.lower() or "hồ sơ" in page_text.lower() or "mã" in page_text.lower()
