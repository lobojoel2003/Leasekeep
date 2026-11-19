from __future__ import annotations

import logging

import stripe
from django.contrib import messages
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from leasekeep.core.auth import staff_required
from leasekeep.formulas.engine import money
from leasekeep.homes.models import GroundLease

from . import services, stripe_gateway
from .forms import ChargeForm, GenerateChargesForm, PaymentForm
from .models import LeaseCharge, Payment

logger = logging.getLogger(__name__)


@staff_required
def fee_overview(request):
    today = timezone.localdate()
    aging = services.aging_report(today)
    recent = Payment.objects.select_related("lease__ownership__home", "lease__ownership__household")[:12]
    leases = services.active_leases().order_by("ownership__home__address_line1")
    month = services.month_start(today)
    billed_this_month = set(
        LeaseCharge.objects.filter(period=month, kind=LeaseCharge.Kind.LEASE_FEE).values_list(
            "lease_id", flat=True
        )
    )
    missing = [lease for lease in leases if lease.pk not in billed_this_month and lease.monthly_fee > 0]
    return render(
        request,
        "billing/overview.html",
        {
            "aging": aging,
            "recent": recent,
            "lease_count": leases.count(),
            "missing": missing,
            "month": month,
            "generate_form": GenerateChargesForm(),
            "collected_month": services.collected_between(month, today),
        },
    )


@staff_required
@require_POST
def generate(request):
    form = GenerateChargesForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Choose a month to bill.")
        return redirect("billing:overview")
    month = services.month_start(form.cleaned_data["month"])
    created = services.generate_charges([month])
    if created:
        messages.success(
            request, f"Created {created} lease fee charge{'s' if created != 1 else ''} for {month:%B %Y}."
        )
    else:
        messages.info(request, f"Every active lease already has a {month:%B %Y} charge.")
    return redirect("billing:overview")


@staff_required
def ledger(request, pk):
    lease = get_object_or_404(
        GroundLease.objects.select_related("ownership__home", "ownership__household"), pk=pk
    )
    data = services.build_ledger(lease)
    lines = list(reversed(data.lines))
    return render(
        request,
        "billing/ledger.html",
        {"lease": lease, "ledger": data, "lines": lines, "home": lease.home},
    )


@staff_required
def payment_create(request, pk):
    lease = get_object_or_404(GroundLease.objects.select_related("ownership__home"), pk=pk)
    balance = services.balance_for(lease)
    form = PaymentForm(
        request.POST or None, initial={"amount": balance if balance > 0 else lease.monthly_fee}
    )
    if request.method == "POST" and form.is_valid():
        payment = form.save(commit=False)
        payment.lease = lease
        payment.status = Payment.Status.SUCCEEDED
        payment.recorded_by = request.user
        payment.save()
        messages.success(request, f"Recorded {money(payment.amount)} from {lease.household}.")
        return redirect("billing:ledger", pk=lease.pk)
    return render(
        request,
        "homes/form.html",
        {
            "form": form,
            "title": f"Record a payment: {lease.home}",
            "intro": f"Current balance {money(balance)}. Payments apply to the oldest unpaid charges first.",
            "back": lease.get_absolute_url(),
        },
    )


@staff_required
def charge_create(request, pk):
    lease = get_object_or_404(GroundLease.objects.select_related("ownership__home"), pk=pk)
    form = ChargeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        charge = form.save(commit=False)
        charge.lease = lease
        charge.period = services.month_start(charge.due_date)
        charge.save()
        messages.success(request, f"Added {charge.label} of {money(charge.amount)}.")
        return redirect("billing:ledger", pk=lease.pk)
    return render(
        request,
        "homes/form.html",
        {"form": form, "title": f"Add a charge: {lease.home}", "back": lease.get_absolute_url()},
    )


@staff_required
@require_POST
def charge_waive(request, pk):
    charge = get_object_or_404(LeaseCharge, pk=pk)
    charge.waived = not charge.waived
    charge.waived_reason = request.POST.get("reason", "")[:200] if charge.waived else ""
    charge.save(update_fields=["waived", "waived_reason"])
    messages.success(request, f"{charge.label} {'waived' if charge.waived else 'reinstated'}.")
    return redirect("billing:ledger", pk=charge.lease_id)


@csrf_exempt
@require_POST
def stripe_webhook(request):
    signature = request.headers.get("Stripe-Signature", "")
    try:
        event = stripe_gateway.verify_event(request.body, signature)
    except stripe_gateway.PaymentsNotConfigured:
        return HttpResponse("Webhook not configured", status=503)
    except (ValueError, stripe.SignatureVerificationError):
        return HttpResponseBadRequest("Invalid signature")
    outcome = stripe_gateway.handle_event(event)
    logger.info("Stripe %s %s: %s", event.get("type"), event.get("id"), outcome)
    return HttpResponse(outcome)
