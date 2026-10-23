import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from app.core.config import settings

logger = logging.getLogger(__name__)

def send_otp_email(to_email: str, otp_code: str) -> bool:
    """
    Sends OTP email to user's Gmail address via SMTP.
    Dynamic fallback to os.getenv if settings singleton was initialized prior to .env updates.
    """
    smtp_user = (settings.SMTP_USER or os.getenv("SMTP_USER", "")).strip()
    smtp_password = (settings.SMTP_PASSWORD or os.getenv("SMTP_PASSWORD", "")).strip()
    smtp_host = (settings.SMTP_HOST or os.getenv("SMTP_HOST", "smtp.gmail.com")).strip()
    
    port_val = settings.SMTP_PORT or os.getenv("SMTP_PORT", 587)
    try:
        smtp_port = int(port_val)
    except ValueError:
        smtp_port = 587

    if not smtp_password:
        logger.warning(
            f"[EMAIL SERVICE] SMTP_PASSWORD is not set in BE/.env. "
            f"Mã OTP {otp_code} chỉ hiển thị ở giao diện thử nghiệm."
        )
        print(f"\n[EMAIL SERVICE WARNING] SMTP_PASSWORD is empty in BE/.env!\n")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🔑 Mã OTP khôi phục mật khẩu: {otp_code}"
        msg["From"] = f"Hệ thống Gia phả Liên họ <{smtp_user}>"
        msg["To"] = to_email

        html_content = f"""
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e2e8f0; border-radius: 10px; background-color: #ffffff;">
            <h2 style="color: #2563eb; text-align: center;">HỆ THỐNG GIA PHẢ LIÊN HỌ</h2>
            <hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 20px 0;" />
            <p>Xin chào,</p>
            <p>Bạn đã yêu cầu khôi phục mật khẩu cho tài khoản <strong>{to_email}</strong>.</p>
            <p>Mã xác thực OTP của bạn là:</p>
            <div style="background-color: #f1f5f9; text-align: center; padding: 15px; border-radius: 8px; font-size: 32px; font-weight: bold; letter-spacing: 5px; color: #1e293b; margin: 20px 0;">
                {otp_code}
            </div>
            <p style="color: #64748b; font-size: 14px;">Mã OTP này có hiệu lực trong vòng <strong>10 phút</strong>. Vui lòng không chia sẻ mã này cho bất kỳ ai.</p>
            <hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 20px 0;" />
            <p style="color: #94a3b8; font-size: 12px; text-align: center;">Nếu bạn không thực hiện yêu cầu này, vui lòng bỏ qua email.</p>
        </div>
        """

        msg.attach(MIMEText(html_content, "html", "utf-8"))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, [to_email], msg.as_string())

        logger.info(f"[EMAIL SERVICE] Đã gửi thành công mã OTP tới Gmail: {to_email}")
        print(f"\n[EMAIL SERVICE SUCCESS] Da gui thanh cong ma OTP {otp_code} toi Gmail: {to_email}\n")
        return True
    except Exception as e:
        logger.error(f"[EMAIL SERVICE ERROR] Gửi email thất bại tới {to_email}: {e}")
        print(f"\n[EMAIL SERVICE ERROR] Gui email toi {to_email} thất bại: {e}\n")
        return False
