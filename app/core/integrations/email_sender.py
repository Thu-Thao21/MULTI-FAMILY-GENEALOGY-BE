"""Sending the temporary password and activation link to a new Owner (Mục E6) via Firebase and SMTP."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import json
import logging
import os
import smtplib
from typing import Literal, Protocol
import urllib.request
import urllib.error

from app.core.config import settings

logger = logging.getLogger("mfg.email_sender")

DeliveryStatus = Literal["QUEUED", "SENT", "FAILED", "BOUNCED"]


@dataclass(frozen=True)
class EmailDeliveryResult:
    """status is None when nothing was sent (the Noop sender)."""

    status: DeliveryStatus | None


class EmailSender(Protocol):
    async def send_owner_temporary_password(
        self,
        *,
        to_email: str,
        display_name: str,
        temporary_password: str,
        expires_at: datetime,
        clan_name: str | None = None,
        account_email: str | None = None,
    ) -> EmailDeliveryResult: ...


class SmtpEmailSender:
    """Sends the temporary password and login credentials to the Clan Owner via Firebase Auth
    and/or SMTP.
    """

    __slots__ = ()

    async def send_owner_temporary_password(
        self,
        *,
        to_email: str,
        display_name: str,
        temporary_password: str,
        expires_at: datetime,
        clan_name: str | None = None,
        account_email: str | None = None,
    ) -> EmailDeliveryResult:
        return await asyncio.to_thread(
            self._send_sync,
            to_email=to_email,
            display_name=display_name,
            temporary_password=temporary_password,
            expires_at=expires_at,
            clan_name=clan_name,
            account_email=account_email,
        )

    def _send_sync(
        self,
        *,
        to_email: str,
        display_name: str,
        temporary_password: str,
        expires_at: datetime,
        clan_name: str | None = None,
        account_email: str | None = None,
    ) -> EmailDeliveryResult:
        firebase_sent = False
        api_key = getattr(settings, "FIREBASE_API_KEY", os.getenv("FIREBASE_API_KEY", "AIzaSyBT-yyl7zQo_d8rZandALAWTdMvCYetLnQ"))
        if api_key:
            try:
                url = f"https://identitytoolkit.googleapis.com/v1/accounts:sendOobCode?key={api_key}"
                data = json.dumps({"requestType": "PASSWORD_RESET", "email": to_email}).encode("utf-8")
                req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    if resp.status == 200:
                        firebase_sent = True
                        logger.info("[EMAIL SENDER] Successfully sent Firebase activation/password link email to %s", to_email)
            except Exception as e:
                logger.warning("[EMAIL SENDER] Firebase sendOobCode notification for %s: %s", to_email, e)

        # Check SMTP configuration
        smtp_user = (settings.SMTP_USER or os.getenv("SMTP_USER", "")).strip()
        smtp_password = (settings.SMTP_PASSWORD or os.getenv("SMTP_PASSWORD", "")).strip()
        smtp_host = (settings.SMTP_HOST or os.getenv("SMTP_HOST", "smtp.gmail.com")).strip()
        port_val = settings.SMTP_PORT or os.getenv("SMTP_PORT", 587)
        try:
            smtp_port = int(port_val)
        except (ValueError, TypeError):
            smtp_port = 587

        frontend_url = getattr(settings, "FRONTEND_URL", os.getenv("FRONTEND_URL", "http://localhost:5173"))
        login_url = f"{frontend_url}/login"

        smtp_sent = False
        if smtp_password and smtp_user:
            try:
                msg = MIMEMultipart("alternative")
                family_str = f" cho {clan_name}" if clan_name else ""
                msg["Subject"] = f"🏛️ [Gia Phả Liên Họ] Thông tin tài khoản Quản trị dòng họ{family_str}"
                msg["From"] = f"Hệ thống Gia Phả Liên Họ <{smtp_user}>"
                msg["To"] = to_email

                login_account = account_email or to_email
                expires_str = expires_at.strftime("%H:%M ngày %d/%m/%Y (UTC)")

                html_content = f"""
                <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 620px; margin: 0 auto; padding: 25px; border: 1px solid #e2e8f0; border-radius: 12px; background-color: #ffffff; color: #1e293b;">
                    <div style="text-align: center; margin-bottom: 25px;">
                        <h1 style="color: #b45309; margin: 0; font-size: 24px; text-transform: uppercase; letter-spacing: 1px;">Hệ Thống Gia Phả Liên Họ</h1>
                        <p style="color: #64748b; font-size: 14px; margin-top: 5px;">Thông báo cấp tài khoản Quản trị không gian Dòng họ</p>
                    </div>
                    
                    <div style="background: linear-gradient(135deg, #fffbeb 0%, #fef3c7 100%); border-left: 4px solid #d97706; padding: 15px 20px; border-radius: 6px; margin-bottom: 20px;">
                        <p style="margin: 0; font-size: 15px; color: #92400e;">
                            Kính gửi Trưởng tộc / Người đại diện: <strong>{display_name}</strong>,<br>
                            Hồ sơ mở không gian số hóa gia phả{family_str} đã được <strong>Phê duyệt thành công</strong>!
                        </p>
                    </div>

                    <p style="font-size: 14px; line-height: 1.6; color: #334155;">
                        Dưới đây là thông tin tài khoản quản trị Trưởng tộc (Business Owner) được khởi tạo bởi ban quản trị hệ thống:
                    </p>

                    <div style="background-color: #f8fafc; border: 1px dashed #cbd5e1; border-radius: 8px; padding: 18px 20px; margin: 20px 0;">
                        <table style="width: 100%; font-size: 14px; border-collapse: collapse;">
                            <tr>
                                <td style="padding: 6px 0; color: #64748b; width: 160px;">Tài khoản đăng nhập:</td>
                                <td style="padding: 6px 0; font-weight: 600; color: #0f172a; font-size: 16px;">{login_account}</td>
                            </tr>
                            <tr>
                                <td style="padding: 6px 0; color: #64748b;">Mật khẩu tạm thời:</td>
                                <td style="padding: 6px 0; font-family: Consolas, monospace; font-size: 18px; font-weight: bold; color: #dc2626; letter-spacing: 1px;">
                                    {temporary_password}
                                </td>
                            </tr>
                            <tr>
                                <td style="padding: 6px 0; color: #64748b;">Thời hạn mật khẩu:</td>
                                <td style="padding: 6px 0; color: #d97706; font-size: 13px;">72 giờ (kết thúc lúc: {expires_str})</td>
                            </tr>
                        </table>
                    </div>

                    <div style="background-color: #eff6ff; border-radius: 6px; padding: 12px 16px; margin-bottom: 25px; font-size: 13px; color: #1e40af;">
                        ⚠️ <strong>Lưu ý bảo mật:</strong> Đây là mật khẩu tạm thời. Hệ thống sẽ yêu cầu bạn <strong>đổi mật khẩu mới</strong> ngay ở lần đăng nhập đầu tiên.
                    </div>

                    <div style="text-align: center; margin-bottom: 30px;">
                        <a href="{login_url}" style="background-color: #b45309; color: #ffffff; text-decoration: none; padding: 12px 30px; font-weight: 600; font-size: 15px; border-radius: 6px; display: inline-block;">
                            Đăng Nhập Quản Trị Dòng Họ →
                        </a>
                    </div>

                    <hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 20px 0;" />
                    <p style="color: #94a3b8; font-size: 12px; text-align: center; margin: 0;">
                        Email này được gửi tự động từ Ban quản trị Hệ thống Gia Phả Liên Họ.<br>
                        Nếu cần hỗ trợ kỹ thuật, vui lòng liên hệ ban quản trị hệ thống.
                    </p>
                </div>
                """

                msg.attach(MIMEText(html_content, "html", "utf-8"))

                with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
                    server.starttls()
                    server.login(smtp_user, smtp_password)
                    server.sendmail(smtp_user, [to_email], msg.as_string())

                smtp_sent = True
                logger.info("[EMAIL SENDER] Successfully sent branded SMTP email to %s (account: %s)", to_email, login_account)
            except Exception as e:
                logger.error("[EMAIL SENDER ERROR] Failed to send SMTP email to %s: %s", to_email, e)

        if firebase_sent or smtp_sent:
            return EmailDeliveryResult(status="SENT")

        logger.warning(
            "[EMAIL SENDER] Simulated account credentials dispatch for %s (account: %s). Temporary password: %s",
            to_email,
            login_account if 'login_account' in locals() else to_email,
            temporary_password,
        )
        return EmailDeliveryResult(status="FAILED")


class NoopEmailSender:
    """Sends nothing. Holds no state, so the password cannot be kept by accident."""

    __slots__ = ()

    async def send_owner_temporary_password(
        self,
        *,
        to_email: str,
        display_name: str,
        temporary_password: str,
        expires_at: datetime,
        clan_name: str | None = None,
        account_email: str | None = None,
    ) -> EmailDeliveryResult:
        return EmailDeliveryResult(status=None)



_sender: EmailSender = SmtpEmailSender()


def get_email_sender() -> EmailSender:
    """FastAPI dependency. Tests override it."""
    return _sender
