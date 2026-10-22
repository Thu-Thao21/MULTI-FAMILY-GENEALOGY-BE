import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def test_home_page_loads(driver, base_url):
    """Sprint 1: Test Home Page UI, navigation bar, and branding."""
    driver.get(f"{base_url}/")
    WebDriverWait(driver, 10).until(
        lambda d: "Gia Phả" in d.title or "Multi-Family" in d.title or len(d.find_elements(By.TAG_NAME, "h1")) > 0
    )
    assert len(driver.title) > 0
    # Check that navigation buttons or links exist
    nav_elements = driver.find_elements(By.CSS_SELECTOR, ".public-nav-item, button, a")
    assert len(nav_elements) > 0

def test_login_page_ui_and_validation(driver, base_url):
    """Sprint 1: Test Login form UI elements, inputs, and validations."""
    driver.get(f"{base_url}/login")
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.TAG_NAME, "form"))
    )

    # Verify input fields (FE uses #login-identifier / name='emailOrPhone' and password)
    email_inputs = driver.find_elements(
        By.CSS_SELECTOR, "#login-identifier, input[name='emailOrPhone'], input[type='email'], input[name='email']"
    )
    assert len(email_inputs) > 0, "Email/username input field must be present"

    password_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
    assert len(password_inputs) > 0, "Password input field must be present"

    # Verify submit button
    submit_buttons = driver.find_elements(By.CSS_SELECTOR, "button[type='submit']")
    assert len(submit_buttons) > 0, "Login submit button must be present"

def test_forgot_password_page(driver, base_url):
    """Sprint 1: Test Password Reset UI form."""
    driver.get(f"{base_url}/forgot-password")
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.TAG_NAME, "form"))
    )
    inputs = driver.find_elements(By.TAG_NAME, "input")
    assert len(inputs) > 0
