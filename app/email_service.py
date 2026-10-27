import smtplib
import ssl
from email.message import EmailMessage

from app.config import settings


def send_otp_email(recipient: str, code: str) -> None:
    if not settings.smtp_host or not settings.smtp_from_email:
        raise RuntimeError("SMTP_HOST and SMTP_FROM_EMAIL must be configured.")

    message = EmailMessage()
    message["Subject"] = "Your MOHERA verification code"
    message["From"] = settings.smtp_from_email
    message["To"] = recipient
    message.set_content(
        f"Your MOHERA verification code is {code}. "
        f"It expires in {settings.otp_expiration_minutes} minutes."
    )

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
        if settings.smtp_use_tls:
            server.starttls(context=ssl.create_default_context())
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)