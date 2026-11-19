"""The homeowner portal: pay lease fees, request credits and approvals, see resale value."""

from __future__ import annotations

from decimal import Decimal

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from leasekeep.billing import services as billing
from leasekeep.billing import stripe_gateway
from leasekeep.billing.forms import PortalPaymentForm
from leasekeep.billing.models import Payment
from leasekeep.core.auth import owner_required
from leasekeep.core.models import Organization
from leasekeep.core.notify import notify_staff
from leasekeep.formulas.engine import money
from leasekeep.homes import services
from leasekeep.homes.models import OccupancyCheck, Ownership
from leasekeep.homes.timeline import build_events, group_by_year

from .forms import OwnerCertificationForm, OwnerImprovementForm, OwnerRefinanceForm


def _context(request) -> dict:
    household = request.household
    ownership: Ownership | None = household.active_ownership
    lease = ownership.lease_or_none if ownership else None
    return {
        "household": household,
        "ownership": ownership,
        "lease": lease,
        "home": ownership.home if ownership else None,
    }


def _require_ownership(request):
    ctx = _context(request)
    if ctx["ownership"] is None:
        messages.info(request, "There's no active home on your account right now.")
        return None
    return ctx


@owner_required
def home(request):
    ctx = _context(request)
    ownership = ctx["ownership"]
    if ownership is not None:
        ctx["quote"] = services.quote(ownership)
        if ctx["lease"]:
            ctx["ledger"] = billing.build_ledger(ctx["lease"])
        ctx["checks_due"] = ownership.occupancy_checks.filter(result=OccupancyCheck.Result.PENDING)
        ctx["improvements"] = ownership.improvements.all()[:5]
        ctx["refinances"] = ownership.refinances.all()[:3]
        ctx["years"] = group_by_year(build_events(ownership.home, for_owner=True), newest_first=True)
    return render(request, "portal/home.html", ctx)


@owner_required
def resale_value(request):
    ctx = _require_ownership(request)
    if ctx is None:
        return redirect("portal:home")
    ctx["quote"] = services.quote(ctx["ownership"])
    return render(request, "portal/resale_value.html", ctx)


@owner_required
def payments(request):
    ctx = _require_ownership(request)
    if ctx is None or ctx["lease"] is None:
        return redirect("portal:home")
    ledger = billing.build_ledger(ctx["lease"])
    ctx.update({"ledger": ledger, "lines": list(reversed(ledger.lines))[:36]})
    return render(request, "portal/payments.html", ctx)


@owner_required
def pay(request):
    ctx = _require_ownership(request)
    if ctx is None or ctx["lease"] is None:
        return redirect("portal:home")
    lease = ctx["lease"]
    balance = billing.balance_for(lease)
    suggested = balance if balance > 0 else lease.monthly_fee
    form = PortalPaymentForm(request.POST or None, initial={"amount": suggested})
    ctx.update({"form": form, "balance": balance, "enabled": stripe_gateway.is_configured()})
    if request.method == "POST" and form.is_valid():
        if not stripe_gateway.is_configured():
            messages.error(
                request, "Online payments aren't available yet. Please pay by check or contact the office."
            )
            return redirect("portal:pay")
        payment = Payment.objects.create(
            lease=lease,
            amount=form.cleaned_data["amount"],
            method=Payment.Method.ACH,
            status=Payment.Status.PENDING,
            received_on=timezone.localdate(),
            notes="Online payment",
        )
        success = request.build_absolute_uri(reverse("portal:pay_done")) + "?session_id={CHECKOUT_SESSION_ID}"
        cancel = request.build_absolute_uri(reverse("portal:pay"))
        try:
            session = stripe_gateway.create_checkout_session(
                payment, success_url=success, cancel_url=cancel, email=request.user.email
            )
        except Exception:
            payment.delete()
            messages.error(
                request, "We couldn't reach the payment processor. Please try again in a few minutes."
            )
            return redirect("portal:pay")
        return redirect(session["url"])
    return render(request, "portal/pay.html", ctx)


@owner_required
def pay_done(request):
    ctx = _context(request)
    session_id = request.GET.get("session_id", "")
    payment = None
    if session_id and ctx["lease"]:
        payment = Payment.objects.filter(lease=ctx["lease"], stripe_checkout_session_id=session_id).first()
    ctx["payment"] = payment
    return render(request, "portal/pay_done.html", ctx)


@owner_required
def improvement_new(request):
    ctx = _require_ownership(request)
    if ctx is None:
        return redirect("portal:home")
    form = OwnerImprovementForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)
        item.ownership = ctx["ownership"]
        item.submitted_by_owner = True
        item.save()
        notify_staff(
            f"Improvement credit request — {ctx['home']}",
            f"{ctx['household']} requested a credit for “{item.title}” ({money(item.requested_amount)}).\n"
            f"Review: {request.build_absolute_uri(item.get_absolute_url())}",
        )
        messages.success(request, "Thanks! Your request was sent. We'll let you know when it's reviewed.")
        return redirect("portal:home")
    ctx["form"] = form
    return render(
        request,
        "portal/form.html",
        {
            **ctx,
            "title": "Request an improvement credit",
            "multipart": True,
            "intro": "Capital improvements you make can raise your home's resale price. Tell us what you did "
            "and attach a receipt. Routine repairs and maintenance usually don't qualify.",
        },
    )


@owner_required
def certify(request, pk):
    ctx = _require_ownership(request)
    if ctx is None:
        return redirect("portal:home")
    check = get_object_or_404(OccupancyCheck, pk=pk, ownership=ctx["ownership"])
    if check.result != OccupancyCheck.Result.PENDING:
        messages.info(request, f"Your {check.year} certification is already on file.")
        return redirect("portal:home")
    form = OwnerCertificationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        check.result = OccupancyCheck.Result.SUBMITTED
        check.method = OccupancyCheck.Method.SELF_CERTIFICATION
        check.owner_statement = form.cleaned_data["statement"]
        check.owner_signed_name = form.cleaned_data["signed_name"]
        check.owner_submitted_at = timezone.now()
        check.save()
        notify_staff(
            f"Occupancy certification — {ctx['home']}",
            f"{ctx['household']} submitted their {check.year} owner-occupancy certification.",
        )
        messages.success(request, f"Thank you. Your {check.year} certification was submitted.")
        return redirect("portal:home")
    return render(
        request,
        "portal/form.html",
        {
            **ctx,
            "form": form,
            "title": f"{check.year} owner-occupancy certification",
            "intro": "Your ground lease asks you to live in your home as your primary residence. "
            "Each year we ask you to confirm it. This takes about a minute.",
        },
    )


@owner_required
def refinance_new(request):
    ctx = _require_ownership(request)
    if ctx is None:
        return redirect("portal:home")
    pq = services.quote(ctx["ownership"])
    form = OwnerRefinanceForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        refi = form.save(commit=False)
        refi.ownership = ctx["ownership"]
        refi.submitted_by_owner = True
        refi.save()
        services.evaluate_refinance(refi)
        notify_staff(
            f"Refinance request — {ctx['home']}",
            f"{ctx['household']} asked to refinance with {refi.lender} for {money(refi.loan_amount)}.\n"
            f"Review: {request.build_absolute_uri(refi.get_absolute_url())}",
        )
        messages.success(
            request, "Your refinance request was sent. Please don't close on the loan until we approve it."
        )
        return redirect("portal:home")
    limit = None
    if pq.price:
        limit = (pq.price * Organization.current().refinance_max_ltv_percent / 100).quantize(Decimal("1"))
    return render(
        request,
        "portal/form.html",
        {
            **ctx,
            "form": form,
            "title": "Ask to refinance",
            "intro": "Your ground lease requires the land trust's approval before you take out a new "
            "mortgage or home equity loan, so your home stays affordable and protected from foreclosure."
            + (f" Loans up to about {money(limit)} usually meet our policy." if limit else ""),
        },
    )
