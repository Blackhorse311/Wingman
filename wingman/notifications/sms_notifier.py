"""SMS notification sender via Google Fi email-to-SMS gateway."""

from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText

from wingman.config import NotificationConfig
from wingman.notifications.formatter import FormattedNotification

logger = logging.getLogger(__name__)


class SmsNotifier:
    """Sends SMS via carrier email-to-SMS gateway (Google Fi)."""

    def __init__(self, config: NotificationConfig) -> None:
        self.smtp_server = config.smtp_server
        self.smtp_port = config.smtp_port
        self.email = config.smtp_email
        self.password = config.smtp_password
        self.sms_gateway = config.sms_gateway

    def send(self, notification: FormattedNotification) -> bool:
        """Send an SMS notification via email gateway. Returns True on success."""
        if not self.email or not self.password or not self.sms_gateway:
            logger.warning("SMS notifier not configured, skipping")
            return False

        # SMS gateway only supports plain text, keep subject minimal
        msg = MIMEText(notification.text_body, "plain")
        msg["From"] = self.email
        msg["To"] = self.sms_gateway
        # Omit subject — SMS gateways often prepend it awkwardly

        try:
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.email, self.password)
                server.send_message(msg)
            logger.info("SMS sent to %s", self.sms_gateway)
            return True
        except smtplib.SMTPException as e:
            logger.error("Failed to send SMS: %s", e)
            return False
