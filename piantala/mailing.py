from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from flask import current_app

from .models import PlatformSettings


class MailError(Exception):
    """Raised when Piantala cannot send one transactional email."""


def _sender_header(settings: PlatformSettings) -> str:
    """Return the RFC-compliant sender header value.

    Parameters:
        settings: Platform settings containing sender metadata.
    """
    if settings.mail_from_name:
        return f"{settings.mail_from_name} <{settings.mail_from_email}>"
    return settings.mail_from_email or ""


def send_email(*, to_email: str, subject: str, text_body: str) -> None:
    """Send one plain-text email using the configured SMTP server.

    Parameters:
        to_email: Recipient email address.
        subject: Email subject line.
        text_body: Plain-text email body.
    """
    settings = PlatformSettings.get_or_create()
    if not settings.smtp_is_configured:
        raise MailError("SMTP is not configured yet.")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = _sender_header(settings)
    message["To"] = to_email
    message.set_content(text_body)

    timeout = 20
    requires_auth = bool(settings.smtp_username) and settings.smtp_preset != "docker_mailpit"
    try:
        if settings.smtp_use_ssl:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(
                settings.smtp_host,
                settings.smtp_port,
                timeout=timeout,
                context=context,
            ) as client:
                if requires_auth:
                    client.login(settings.smtp_username, settings.smtp_password or "")
                client.send_message(message)
            return

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=timeout) as client:
            client.ehlo()
            if settings.smtp_use_tls:
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            if requires_auth:
                client.login(settings.smtp_username, settings.smtp_password or "")
            client.send_message(message)
    except OSError as exc:
        current_app.logger.exception("Could not send email to %s", to_email)
        raise MailError(f"Could not send email: {exc}") from exc
