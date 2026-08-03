"""Gmail SMTP delivery (app password; requires 2FA on the Google account)."""

import smtplib
from email.message import EmailMessage

from .config import Settings

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def send(settings: Settings, subject: str, text: str, html: str) -> None:
    if not settings.gmail_address or not settings.gmail_app_password:
        raise RuntimeError("GMAIL_ADDRESS / GMAIL_APP_PASSWORD not set")
    msg = EmailMessage()
    msg["From"] = settings.gmail_address
    msg["To"] = settings.digest_to or settings.gmail_address
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=60) as smtp:
        smtp.login(settings.gmail_address, settings.gmail_app_password)
        smtp.send_message(msg)
