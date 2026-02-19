"""Email notification sender via Gmail SMTP."""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from wingman.config import NotificationConfig
from wingman.notifications.formatter import FormattedNotification

logger = logging.getLogger(__name__)


class EmailNotifier:
    """Sends HTML email notifications via Gmail SMTP."""

    def __init__(self, config: NotificationConfig) -> None:
        self.smtp_server = config.smtp_server
        self.smtp_port = config.smtp_port
        self.email = config.smtp_email
        self.password = config.smtp_password
        self.recipient = config.recipient_email

    def send(self, notification: FormattedNotification) -> bool:
        """Send an email notification. Returns True on success."""
        if not self.email or not self.password or not self.recipient:
            logger.warning("Email notifier not configured, skipping")
            return False

        msg = MIMEMultipart("alternative")
        msg["Subject"] = notification.subject
        msg["From"] = self.email
        msg["To"] = self.recipient

        msg.attach(MIMEText(notification.text_body, "plain"))
        msg.attach(MIMEText(notification.html_body, "html"))

        try:
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.email, self.password)
                server.send_message(msg)
            logger.info("Email sent: %s", notification.subject)
            return True
        except smtplib.SMTPException as e:
            logger.error("Failed to send email: %s", e)
            return False
