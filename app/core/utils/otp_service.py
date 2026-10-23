"""OTP service for verifying real Gmail addresses during registration."""

from __future__ import annotations

import logging
import os
import random
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, Set

from app.core.config import settings

logger = logging.getLogger("mfg.otp_service")

# In-memory storage for OTP verification: email -> {"code": "123456", "expires_at": timestamp}
_otp_cache: Dict[str, dict] = {}
# Set of verified emails that passed OTP
_verified_emails: Set[str] = set()

OTP_EXPIRY_SECONDS = 300  # 5 minutes


def generate_otp(email: str) -> str:
    """Generates a 6-digit OTP code and caches it for 5 minutes."""
    clean_email = email.strip().lower()
    code = f"{random.randint(100000, 999999)}"
    _otp_cache[clean_email] = {
        "code": code,
        "expires_at": time.time() + OTP_EXPIRY_SECONDS,
    }
    return code


def verify_otp(email: str, code: str) -> bool:
    """Verifies the provided OTP code for the given email."""
    clean_email = email.strip().lower()
    record = _otp_cache.get(clean_email)
    if not record:
        return False

    if time.time() > record["expires_at"]:
        _otp_cache.pop(clean_email, None)
        return False

    if record["code"] == code.strip():
        _otp_cache.pop(clean_email, None)
        _verified_emails.add(clean_email)
        return True

    return False


def is_email_verified(email: str) -> bool:
    """Checks if the email has been successfully verified via OTP."""
    return email.strip().lower() in _verified_emails


def send_otp_via_email(to_email: str, code: str) -> bool:
    """Sends OTP code to real Gmail using SMTP if configured, or logs to console."""
    clean_email = to_email.strip().lower()
    logger.info("==================================================")
    logger.info("[GMAIL OTP VERIFICATION] Email: %s | Mã OTP: %s", clean_email, code)
    logger.info("==================================================")

    smtp_user = (settings.SMTP_USER or os.getenv("SMTP_USER", "")).strip()
    smtp_password = (settings.SMTP_PASSWORD or os.getenv("SMTP_PASSWORD", "")).strip()
    smtp_host = (settings.SMTP_HOST or os.getenv("SMTP_HOST", "smtp.gmail.com")).strip()
    smtp_port = int(settings.SMTP_PORT or os.getenv("SMTP_PORT", 587))

    if smtp_user and smtp_password:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"[{code}] Mã xác thực đăng ký dòng họ - MFGMS"
            msg["From"] = f"MFGMS System <{smtp_user}>"
            msg["To"] = clean_email

            html_body = f"""
            <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
                <h2 style="color: #1e3a8a; text-align: center;">Xác Thực Địa Chỉ Gmail</h2>
                <p>Kính chào Quý đại diện dòng họ,</p>
                <p>Bạn đang thực hiện thủ tục đăng ký dòng họ trên Hệ thống Quản trị Gia phả MFGMS. Mã xác thực OTP của bạn là:</p>
                <div style="background: #f0fdf4; border: 2px dashed #16a34a; padding: 15px; text-align: center; font-size: 28px; font-weight: bold; letter-spacing: 6px; color: #15803d; margin: 20px 0; border-radius: 6px;">
                    {code}
                </div>
                <p style="color: #64748b; font-size: 14px;">Mã xác thực có hiệu lực trong vòng <strong>5 phút</strong>. Vui lòng không chia sẻ mã này cho bất kỳ ai.</p>
                <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 20px 0;" />
                <p style="color: #94a3b8; font-size: 12px; text-align: center;">Hệ thống Quản lý Gia phả Đa dòng họ MFGMS-AI</p>
            </div>
            """
            msg.attach(MIMEText(html_body, "html"))

            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                server.starttls()
                server.login(smtp_user, smtp_password)
                server.send_message(msg)

            logger.info("[GMAIL OTP] Successfully delivered OTP email to %s", clean_email)
            return True
        except Exception as e:
            logger.warning("[GMAIL OTP] Failed to send SMTP email: %s. OTP logged to console.", e)
            return False

    return True
