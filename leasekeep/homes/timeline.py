"""The home timeline: every stewardship event from acquisition to resale."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import groupby

from django.urls import reverse
from django.utils import timezone

from leasekeep.billing.models import Payment
from leasekeep.formulas.engine import long_date, money

from .models import (
    CapitalImprovement,
    Home,
    OccupancyCheck,
    RefinanceRequest,
)


@dataclass
class Event:
    on: date
    kind: str  # css modifier and icon name
    title: str
    detail: str = ""
    badge: str = ""
    tone: str = "neutral"  # neutral | good | warn | bad | info
    url: str = ""
    order: int = 50


@dataclass
class YearGroup:
    year: int
    events: list[Event]


IMPROVEMENT_TONES = {
    CapitalImprovement.Status.APPROVED: "good",
    CapitalImprovement.Status.REQUESTED: "warn",
    CapitalImprovement.Status.DENIED: "bad",
    CapitalImprovement.Status.WITHDRAWN: "neutral",
}
OCCUPANCY_TONES = {
    OccupancyCheck.Result.COMPLIANT: "good",
    OccupancyCheck.Result.WAIVED: "neutral",
    OccupancyCheck.Result.PENDING: "warn",
    OccupancyCheck.Result.SUBMITTED: "info",
    OccupancyCheck.Result.NON_COMPLIANT: "bad",
}
REFINANCE_TONES = {
    RefinanceRequest.Status.APPROVED: "good",
    RefinanceRequest.Status.APPROVED_WITH_CONDITIONS: "good",
    RefinanceRequest.Status.SUBMITTED: "warn",
    RefinanceRequest.Status.UNDER_REVIEW: "warn",
    RefinanceRequest.Status.DENIED: "bad",
    RefinanceRequest.Status.WITHDRAWN: "neutral",
}


def build_events(home: Home, *, today: date | None = None, for_owner: bool = False) -> list[Event]:
    today = today or timezone.localdate()
    events: list[Event] = []

    if home.acquired_on:
        events.append(
            Event(
                home.acquired_on, "land", "Land acquired by the CLT", "Placed in trust permanently.", order=0
            )
        )

    for subsidy in home.subsidies.all():
        detail = subsidy.program_name or subsidy.get_kind_display()
        if subsidy.affordability_ends_on:
            detail += f" · affordability period to {subsidy.affordability_ends_on:%b %Y}"
        events.append(
            Event(
                subsidy.funded_on,
                "subsidy",
                f"{money(subsidy.amount)} {subsidy.get_source_display()} subsidy",
                detail,
                order=5,
            )
        )

    ownerships = (
        home.ownerships.select_related("household", "formula")
        .prefetch_related("improvements", "occupancy_checks", "refinances")
        .order_by("purchase_date")
    )
    for ownership in ownerships:
        hh = ownership.household
        purchase_detail = f"Formula: {ownership.formula.name}"
        if ownership.initial_appraised_value:
            gap = ownership.initial_appraised_value - ownership.purchase_price
            purchase_detail = (
                f"Market value {money(ownership.initial_appraised_value)} · "
                f"{money(gap)} below market · {purchase_detail}"
            )
        events.append(
            Event(
                ownership.purchase_date,
                "purchase",
                f"{hh.name} bought the home for {money(ownership.purchase_price)}",
                purchase_detail,
                tone="info",
                url="" if for_owner else reverse("homes:formula", args=[ownership.pk]),
                order=10,
            )
        )
        lease = ownership.lease_or_none
        if lease is not None:
            events.append(
                Event(
                    lease.start_date,
                    "lease",
                    f"{lease.term_years}-year ground lease {lease.lease_number} signed",
                    f"Lease fee {money(lease.monthly_fee)}/month · runs to {lease.expires_on:%b %Y}",
                    url="" if for_owner else reverse("billing:ledger", args=[lease.pk]),
                    order=11,
                )
            )
            events.extend(_fee_years(lease, today, for_owner))

        for item in ownership.improvements.all():
            when = item.completed_on or item.created_at.date()
            if item.status == CapitalImprovement.Status.APPROVED and item.approved_credit is not None:
                title = f"Improvement credited: {item.title}"
                detail = f"{money(item.approved_credit)} credit"
                if item.useful_life_years:
                    detail += f", depreciates over {item.useful_life_years} years"
            else:
                title = f"Improvement {item.get_status_display().lower()}: {item.title}"
                detail = f"{money(item.requested_amount)} requested"
            events.append(
                Event(
                    when,
                    "improvement",
                    title,
                    detail,
                    badge=item.get_status_display(),
                    tone=IMPROVEMENT_TONES.get(item.status, "neutral"),
                    url="" if for_owner else reverse("homes:improvement_review", args=[item.pk]),
                    order=30,
                )
            )

        for check in ownership.occupancy_checks.all():
            when = check.completed_on or check.due_date
            detail = check.get_method_display() if check.method else f"Due {long_date(check.due_date)}"
            events.append(
                Event(
                    when,
                    "occupancy",
                    f"{check.year} owner-occupancy check",
                    detail,
                    badge=check.get_result_display(),
                    tone="bad" if check.is_overdue else OCCUPANCY_TONES.get(check.result, "neutral"),
                    url="" if for_owner else reverse("homes:occupancy_record", args=[check.pk]),
                    order=40,
                )
            )

        for refi in ownership.refinances.all():
            when = refi.decided_on or refi.created_at.date()
            events.append(
                Event(
                    when,
                    "refinance",
                    f"Refinance with {refi.lender}",
                    f"{money(refi.loan_amount)} loan · {refi.get_purpose_display()}",
                    badge=refi.get_status_display(),
                    tone=REFINANCE_TONES.get(refi.status, "neutral"),
                    url="" if for_owner else reverse("homes:refinance_review", args=[refi.pk]),
                    order=45,
                )
            )

        if ownership.sale_date:
            detail = ""
            if ownership.formula_price_at_sale:
                detail = f"Formula price {money(ownership.formula_price_at_sale)}"
            if ownership.appraised_value_at_sale:
                detail += f" · market value {money(ownership.appraised_value_at_sale)}"
            if ownership.sale_price:
                gain = ownership.sale_price - ownership.purchase_price
                detail += f" · seller gained {money(gain)}"
            events.append(
                Event(
                    ownership.sale_date,
                    "resale",
                    f"{hh.name} sold the home for {money(ownership.sale_price or Decimal(0))}",
                    detail.strip(" ·"),
                    tone="info",
                    order=90,
                )
            )

    for appraisal in home.appraisals.all():
        events.append(
            Event(
                appraisal.effective_date,
                "appraisal",
                f"Appraised at {money(appraisal.value)}",
                appraisal.get_purpose_display()
                + (f" · {appraisal.appraiser}" if appraisal.appraiser else ""),
                order=8,
            )
        )
    return sorted(events, key=lambda e: (e.on, e.order))


def _fee_years(lease, today: date, for_owner: bool) -> list[Event]:
    """One summary event per year of lease fees rather than one per payment."""
    billed: dict[int, Decimal] = defaultdict(Decimal)
    months: dict[int, int] = defaultdict(int)
    paid: dict[int, Decimal] = defaultdict(Decimal)
    for charge in lease.charges.filter(waived=False):
        billed[charge.due_date.year] += charge.amount
        months[charge.due_date.year] += 1
    for payment in lease.payments.filter(status=Payment.Status.SUCCEEDED):
        paid[payment.received_on.year] += payment.amount
    events = []
    for year in sorted(set(billed) | set(paid)):
        end = date(year, 12, 31)
        if lease.ended_on and lease.ended_on.year == year:
            end = lease.ended_on
        if year == today.year:
            end = min(end, today)
        shortfall = billed[year] - paid[year]
        tone = "good" if shortfall <= 0 else ("warn" if shortfall <= lease.monthly_fee * 2 else "bad")
        detail = f"{money(paid[year])} paid of {money(billed[year])} billed"
        if months[year]:
            detail += f" ({months[year]} month{'s' if months[year] != 1 else ''})"
        events.append(
            Event(
                end,
                "fees",
                f"{year} lease fees",
                detail,
                badge="Paid in full" if shortfall <= 0 else f"{money(shortfall)} unpaid",
                tone=tone,
                url="" if for_owner else reverse("billing:ledger", args=[lease.pk]),
                order=20,
            )
        )
    return events


def group_by_year(events: list[Event], *, newest_first: bool = False) -> list[YearGroup]:
    ordered = sorted(events, key=lambda e: (e.on, e.order), reverse=newest_first)
    return [
        YearGroup(year=year, events=list(items)) for year, items in groupby(ordered, key=lambda e: e.on.year)
    ]
