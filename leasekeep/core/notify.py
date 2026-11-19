"""Email notifications. Failures are logged, never raised to the person using the app."""

import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def _send(subject: str, body: str, recipients: list[str]) -> bool:
    recipients = [r for r in recipients if r]
    if not recipients:
        return False
    try:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, recipients)
    except Exception:
        logger.exception("Could not send notification %r", subject)
        return False
    return True


def notify_staff(subject: str, body: str) -> bool:
    return _send(f"[Leasekeep] {subject}", body, [settings.LEASEKEEP_STAFF_NOTIFICATION_EMAIL])


def notify_household(household, subject: str, body: str) -> bool:
    email = household.email or (household.portal_user.email if household.portal_user else "")
    return _send(subject, body, [email])
