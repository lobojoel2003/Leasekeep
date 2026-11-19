import hashlib
import hmac
import io
import json
import time
from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse
from django.utils import timezone

from leasekeep.billing import services, stripe_gateway
from leasekeep.billing.models import LeaseCharge, Payment, StripeEvent
from tests import factories

pytestmark = pytest.mark.django_db


def test_month_helpers():
    assert services.add_months(date(2026, 11, 19), 3) == date(2027, 2, 1)
    assert services.add_months(date(2026, 1, 31), -1) == date(2025, 12, 1)
    assert services.month_end(date(2028, 2, 10)) == date(2028, 2, 29)
    assert services.months_in_range(date(2026, 11, 5), date(2027, 1, 1)) == [
        date(2026, 11, 1),
        date(2026, 12, 1),
        date(2027, 1, 1),
    ]


def test_generate_charges_is_idempotent_and_starts_after_lease():
    mid_month = factories.ownership(purchase_date=date(2026, 3, 15))
    first_of_month = factories.ownership(purchase_date=date(2026, 3, 1))
    free = factories.ownership(purchase_date=date(2026, 1, 1), fee="0")
    months = services.months_in_range(date(2026, 1, 1), date(2026, 4, 1))
    assert services.generate_charges(months) == 2 + 1  # Mar+Apr, and Apr
    assert services.generate_charges(months) == 0
    assert mid_month.lease.charges.count() == 1
    assert first_of_month.lease.charges.count() == 2
    assert free.lease.charges.count() == 0
    charge = first_of_month.lease.charges.first()
    assert charge.due_date == date(2026, 3, 1)
    assert charge.label == "Lease fee — March 2026"


def test_generate_charges_skips_ended_leases():
    o = factories.ownership(purchase_date=date(2026, 1, 1))
    o.lease.ended_on = date(2026, 2, 10)
    o.lease.save()
    services.generate_charges(services.months_in_range(date(2026, 1, 1), date(2026, 4, 1)), leases=[o.lease])
    assert [c.period.month for c in o.lease.charges.all()] == [1, 2]
    assert list(services.active_leases()) == []


def test_ledger_applies_payments_oldest_first():
    o = factories.ownership(purchase_date=date(2026, 1, 1), fee="40")
    services.generate_charges(services.months_in_range(date(2026, 1, 1), date(2026, 4, 1)), leases=[o.lease])
    jan, feb, mar, apr = o.lease.charges.order_by("due_date")
    mar.waived = True
    mar.save()
    Payment.objects.create(lease=o.lease, amount=D("60"), received_on=date(2026, 2, 3))
    Payment.objects.create(
        lease=o.lease, amount=D("40"), received_on=date(2026, 4, 2), status=Payment.Status.PROCESSING
    )
    Payment.objects.create(
        lease=o.lease, amount=D("40"), received_on=date(2026, 4, 2), status=Payment.Status.FAILED
    )
    ledger = services.build_ledger(o.lease)
    status = {line.charge.pk: line.status for line in ledger.lines}
    assert status[jan.pk] == "paid"
    assert status[feb.pk] == "partial"
    assert status[mar.pk] == "waived"
    assert status[apr.pk] in {"late", "due"}
    assert ledger.total_billed == D("120.00")
    assert ledger.total_paid == D("60")
    assert ledger.balance == D("60.00")
    assert ledger.pending == D("40")
    assert not ledger.covered_by_pending
    assert ledger.oldest_unpaid.charge == feb
    assert services.balance_for(o.lease) == D("60.00")


def test_ledger_credit_and_pending_coverage():
    o = factories.ownership(purchase_date=date(2026, 1, 1), fee="40")
    services.generate_charges([date(2026, 1, 1)], leases=[o.lease])
    Payment.objects.create(
        lease=o.lease, amount=D("40"), received_on=date(2026, 1, 2), status=Payment.Status.PROCESSING
    )
    assert services.build_ledger(o.lease).covered_by_pending
    Payment.objects.create(lease=o.lease, amount=D("100"), received_on=date(2026, 1, 2))
    ledger = services.build_ledger(o.lease)
    assert ledger.credit == D("60.00")
    assert ledger.oldest_unpaid is None and ledger.months_behind == 0


def test_aging_buckets():
    today = timezone.localdate()
    o = factories.ownership(purchase_date=today - timedelta(days=400), fee="10")
    for days in (5, 45, 75, 200):
        LeaseCharge.objects.create(
            lease=o.lease,
            kind=LeaseCharge.Kind.ADJUSTMENT,
            period=today,
            due_date=today - timedelta(days=days),
            amount=D("10"),
        )
    paid = factories.ownership(fee="10")
    LeaseCharge.objects.create(
        lease=paid.lease, period=date(2026, 1, 1), due_date=date(2026, 1, 1), amount=D("10")
    )
    Payment.objects.create(lease=paid.lease, amount=D("10"))
    report = services.aging_report(today)
    assert len(report.rows) == 1
    row = report.rows[0]
    assert (row.current, row.days_30, row.days_60, row.days_90) == (D("10"), D("10"), D("10"), D("10"))
    assert report.totals["total"] == D("40")


def test_monthly_collections_series():
    o = factories.ownership(purchase_date=date(2025, 1, 1), fee="25")
    services.generate_charges(services.months_in_range(date(2026, 1, 1), date(2026, 3, 1)), leases=[o.lease])
    Payment.objects.create(lease=o.lease, amount=D("25"), received_on=date(2026, 3, 5))
    series = services.monthly_collections(3, end=date(2026, 3, 20))
    assert [row["month"] for row in series] == [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)]
    assert series[-1] == {"month": date(2026, 3, 1), "billed": D("25.00"), "collected": D("25.00")}


def test_generate_lease_charges_command():
    o = factories.ownership(purchase_date=date(2026, 1, 1))
    call_command("generate_lease_charges", "--from", "2026-01", "--month", "2026-03", stdout=io.StringIO())
    assert o.lease.charges.count() == 3
    with pytest.raises(CommandError):
        call_command("generate_lease_charges", "--month", "March")
    with pytest.raises(CommandError):
        call_command("generate_lease_charges", "--from", "2026-05", "--month", "2026-03")


# ---------------------------------------------------------------------------
# Stripe
# ---------------------------------------------------------------------------

SECRET = "whsec_test_secret"


def signed(client, payload: dict, secret=SECRET):
    body = json.dumps(payload)
    ts = int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
    return client.post(
        reverse("stripe_webhook"),
        data=body,
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE=f"t={ts},v1={sig}",
    )


def event(kind, payment, n=1, **session):
    obj = {
        "id": "cs_test_1",
        "metadata": {"payment_id": str(payment.pk)},
        "payment_intent": "pi_1",
        **session,
    }
    return {"id": f"evt_{kind}_{n}", "type": kind, "data": {"object": obj}}


@pytest.fixture
def pending_payment(settings):
    settings.STRIPE_WEBHOOK_SECRET = SECRET
    o = factories.ownership()
    return Payment.objects.create(
        lease=o.lease,
        amount=D("35"),
        status=Payment.Status.PENDING,
        method=Payment.Method.ACH,
        stripe_checkout_session_id="cs_test_1",
    )


def test_webhook_rejects_bad_signatures(client, pending_payment):
    response = signed(client, event("checkout.session.completed", pending_payment), secret="wrong")
    assert response.status_code == 400
    assert (
        client.post(reverse("stripe_webhook"), data="{}", content_type="application/json").status_code == 400
    )


def test_webhook_requires_configuration(client, settings):
    settings.STRIPE_WEBHOOK_SECRET = ""
    assert (
        client.post(reverse("stripe_webhook"), data="{}", content_type="application/json").status_code == 503
    )


def test_card_payment_succeeds_immediately(client, pending_payment):
    response = signed(client, event("checkout.session.completed", pending_payment, payment_status="paid"))
    assert response.status_code == 200
    pending_payment.refresh_from_db()
    assert pending_payment.status == Payment.Status.SUCCEEDED
    assert pending_payment.method == Payment.Method.CARD
    assert pending_payment.stripe_payment_intent_id == "pi_1"
    # Stripe retries deliveries; the second copy is ignored.
    assert (
        signed(client, event("checkout.session.completed", pending_payment, payment_status="paid")).content
        == b"duplicate"
    )


def test_bank_transfer_processes_then_settles(client, pending_payment):
    signed(client, event("checkout.session.completed", pending_payment, payment_status="unpaid"))
    pending_payment.refresh_from_db()
    assert pending_payment.status == Payment.Status.PROCESSING
    signed(client, event("checkout.session.async_payment_succeeded", pending_payment))
    pending_payment.refresh_from_db()
    assert pending_payment.status == Payment.Status.SUCCEEDED
    assert pending_payment.method == Payment.Method.ACH
    assert StripeEvent.objects.count() == 2


def test_bank_transfer_failure(client, pending_payment):
    signed(client, event("checkout.session.async_payment_failed", pending_payment))
    pending_payment.refresh_from_db()
    assert pending_payment.status == Payment.Status.FAILED


def test_expired_checkout_removes_pending_payment(client, pending_payment):
    assert signed(client, event("checkout.session.expired", pending_payment)).content == b"expired"
    assert not Payment.objects.exists()


def test_expired_after_completion_is_ignored(pending_payment):
    pending_payment.status = Payment.Status.SUCCEEDED
    pending_payment.save()
    assert stripe_gateway.handle_event(event("checkout.session.expired", pending_payment)) == "ignored"


def test_unmatched_and_unhandled_events(pending_payment):
    stray = {
        "id": "evt_x",
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_other", "metadata": {}}},
    }
    assert stripe_gateway.handle_event(stray) == "unmatched"
    assert (
        stripe_gateway.handle_event({"id": "evt_y", "type": "customer.created", "data": {"object": {}}})
        == "ignored"
    )


def test_payment_matched_by_session_id(pending_payment):
    evt = {
        "id": "evt_z",
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_test_1", "payment_status": "paid"}},
    }
    assert stripe_gateway.handle_event(evt) == "succeeded"


def test_create_checkout_session(monkeypatch, settings):
    settings.STRIPE_SECRET_KEY = "sk_test_123"
    o = factories.ownership()
    payment = Payment.objects.create(lease=o.lease, amount=D("35.50"), status=Payment.Status.PENDING)
    captured = {}

    def fake_create(**params):
        captured.update(params)
        return {"id": "cs_new", "url": "https://checkout.stripe.test/cs_new"}

    monkeypatch.setattr("stripe.checkout.Session.create", fake_create)
    session = stripe_gateway.create_checkout_session(
        payment, success_url="https://x/s", cancel_url="https://x/c", email="a@b.c"
    )
    assert session["url"].endswith("cs_new")
    assert captured["line_items"][0]["price_data"]["unit_amount"] == 3550
    assert captured["payment_method_types"] == ["us_bank_account", "card"]
    assert captured["customer_email"] == "a@b.c"
    payment.refresh_from_db()
    assert payment.stripe_checkout_session_id == "cs_new"


def test_checkout_requires_configuration():
    o = factories.ownership()
    payment = Payment.objects.create(lease=o.lease, amount=D("1"))
    with pytest.raises(stripe_gateway.PaymentsNotConfigured):
        stripe_gateway.create_checkout_session(payment, success_url="", cancel_url="")
