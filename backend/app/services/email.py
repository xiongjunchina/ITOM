"""使用系统全局集成配置发送邮件。"""
import smtplib
from email.message import EmailMessage
from email.utils import formataddr
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.services.integrations import get_integration_config
from app.services.secrets_store import decrypt_secret


def send_initial_password_email(db: Session, recipient: str, display_name: str, username: str, password: str) -> None:
    cfg = get_integration_config(db).email_config or {}
    if not cfg.get("enabled") or not cfg.get("host") or not cfg.get("from_email"):
        raise AppError("SMTP_NOT_CONFIGURED", "邮件服务器未启用或配置不完整", 503)
    message = EmailMessage()
    message["Subject"] = "ITOM 系统初始密码"
    message["From"] = formataddr((cfg.get("from_name") or "ITOM", cfg["from_email"]))
    message["To"] = recipient
    message.set_content(
        f"{display_name or '您好'}：\n\n您的 ITOM 账号已开通。\n登录账号：{username}\n"
        f"初始密码：{password}\n\n请登录后尽快修改密码，请勿转发本邮件。\n"
    )
    try:
        with smtplib.SMTP(cfg["host"], int(cfg.get("port") or 587), timeout=15) as smtp:
            if cfg.get("use_tls", True): smtp.starttls()
            if cfg.get("username"): smtp.login(cfg["username"], decrypt_secret(cfg.get("password_encrypted")))
            smtp.send_message(message)
    except AppError:
        raise
    except Exception as exc:
        raise AppError("EMAIL_SEND_FAILED", "初始密码邮件发送失败，请检查邮件服务器配置", 502) from exc
