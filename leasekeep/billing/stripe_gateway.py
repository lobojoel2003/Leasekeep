"""Online lease fee payments through Stripe Checkout (card and ACH bank transfer).

Stripe is optional. Without ``STRIPE_SECRET_KEY`` the portal hides online
payment and staff record checks, cash and money orders by hand.

ACH (``us_bank_account``) payments settle a few days after checkout. They are
recorded as *processing* when checkout completes and become *received* when
Stripe sends ``checkout.session.async_payment_succeeded``.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal

import stripe
from django.conf import settings
from django.db import IntegrityError, transaction

from .models import Payment, StripeEvent

logger = logging.getLogger(__name__)


class PaymentsNotConfigured(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(settings.STRIPE_SECRET_KEY)


def to_minor_units(amount: Decimal) -> int:
    return int((amount * 100).quantize(Decimal("1")))


def create_checkout_session(payment: Payment, *, success_url: str, cancel_url: str, email: str = ""):
    if not is_configured():
        raise PaymentsNotConfigured("Online payments are not configured.")
    lease = payment.lease
    params = {
        "mode": "payment",
        "payment_method_types": settings.STRIPE_PAYMENT_METHOD_TYPES,
        "line_items": [
            {
                "quantity": 1,
                "price_data": {
                    "currency": settings.LEASEKEEP_CURRENCY,
                    "unit_amount": to_minor_units(payment.amount),
                    "product_data": {
                        "name": f"Ground lease fee — {lease.home.street}",
                        "description": f"Lease {lease.lease_number}",
                    },
                },
            }
        ],
        "client_reference_id": str(payment.pk),
        "metadata": {"payment_id": str(payment.pk), "lease_number": lease.lease_number},
        "payment_intent_data": {"metadata": {"payment_id": str(payment.pk)}},
        "success_url": success_url,
        "cancel_url": cancel_url,
    }
    if email:
        params["customer_email"] = email
    session = stripe.checkout.Session.create(api_key=settings.STRIPE_SECRET_KEY, **params)
    payment.stripe_checkout_session_id = session["id"]
    payment.save(update_fields=["stripe_checkout_session_id"])
    return session


def verify_event(payload: bytes, signature: str) -> dict:
    """Verify the webhook signature and return the event as plain dicts.

    Raises ``ValueError`` for malformed payloads and
    ``stripe.SignatureVerificationError`` for bad signatures.
    """
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise PaymentsNotConfigured("STRIPE_WEBHOOK_SECRET is not set.")
    stripe.Webhook.construct_event(payload, signature, settings.STRIPE_WEBHOOK_SECRET)
    return json.loads(payload)


def _payment_for(session) -> Payment | None:
    metadata = session.get("metadata") or {}
    payment_id = metadata.get("payment_id") or session.get("client_reference_id")
    qs = Payment.objects.select_for_update()
    payment = None
    if payment_id:
        payment = qs.filter(pk=payment_id).first()
    if payment is None and session.get("id"):
        payment = qs.filter(stripe_checkout_session_id=session["id"]).first()
    return payment


HANDLED = {
    "checkout.session.completed",
    "checkout.session.async_payment_succeeded",
    "checkout.session.async_payment_failed",
    "checkout.session.expired",
}


def handle_event(event: dict) -> str:
    """Apply a verified Stripe event. Returns a short description for logs and tests."""
    event_type = event["type"]
    if event_type not in HANDLED:
        return "ignored"
    with transaction.atomic():
        try:
            with transaction.atomic():
                StripeEvent.objects.create(event_id=event["id"], event_type=event_type)
        except IntegrityError:
            return "duplicate"
        session = event["data"]["object"]
        payment = _payment_for(session)
        if payment is None:
            logger.warning("Stripe event %s has no matching payment", event["id"])
            return "unmatched"
        if session.get("payment_intent"):
            payment.stripe_payment_intent_id = str(session["payment_intent"])

        if event_type == "checkout.session.completed":
            if session.get("payment_status") == "paid":
                # Bank debits never settle at checkout, so an immediate payment is a card.
                payment.status = Payment.Status.SUCCEEDED
                payment.method = Payment.Method.CARD
            else:
                # Bank debits are confirmed later by async_payment_succeeded.
                payment.status = Payment.Status.PROCESSING
                payment.method = Payment.Method.ACH
        elif event_type == "checkout.session.async_payment_succeeded":
            payment.status = Payment.Status.SUCCEEDED
            payment.method = Payment.Method.ACH
        elif event_type == "checkout.session.async_payment_failed":
            payment.status = Payment.Status.FAILED
            payment.notes = "Bank transfer failed."
        elif event_type == "checkout.session.expired":
            if payment.status == Payment.Status.PENDING:
                payment.delete()
                return "expired"
            return "ignored"
        payment.reference = payment.reference or (payment.stripe_payment_intent_id or session.get("id", ""))
        payment.save()
        return payment.status
