"""Lease fee billing: generating monthly charges, ledgers and aging."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from leasekeep.core.models import Organization
from leasekeep.homes.models import GroundLease, Ownership

from .models import LeaseCharge, Payment

ZERO = Decimal("0.00")


def month_start(value: date) -> date:
    return value.replace(day=1)


def add_months(value: date, months: int) -> date:
    index = value.year * 12 + (value.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def month_end(value: date) -> date:
    return add_months(month_start(value), 1) - timedelta(days=1)


def months_in_range(start: date, end: date) -> list[date]:
    months = []
    current = month_start(start)
    while current <= month_start(end):
        months.append(current)
        current = add_months(current, 1)
    return months


def first_billable_month(lease: GroundLease) -> date:
    """Fees start the month the lease begins if it begins on the 1st, else the next month."""
    start = lease.start_date
    return start if start.day == 1 else add_months(start, 1)


def active_leases():
    return GroundLease.objects.filter(
        ended_on__isnull=True, ownership__status=Ownership.Status.ACTIVE
    ).select_related("ownership__home", "ownership__household")


@transaction.atomic
def generate_charges(months: Iterable[date], *, leases: Iterable[GroundLease] | None = None) -> int:
    """Create the monthly lease fee for each lease and month given. Idempotent."""
    org = Organization.current()
    leases = list(leases) if leases is not None else list(active_leases())
    created = 0
    for period in sorted({month_start(m) for m in months}):
        due = period.replace(day=org.lease_fee_due_day)
        for lease in leases:
            if lease.monthly_fee <= 0 or period < first_billable_month(lease):
                continue
            if lease.ended_on and period > lease.ended_on:
                continue
            _, was_created = LeaseCharge.objects.get_or_create(
                lease=lease,
                period=period,
                kind=LeaseCharge.Kind.LEASE_FEE,
                defaults={"amount": lease.monthly_fee, "due_date": due},
            )
            created += int(was_created)
    return created


# ---------------------------------------------------------------------------
# Ledgers
# ---------------------------------------------------------------------------


@dataclass
class ChargeLine:
    charge: LeaseCharge
    paid: Decimal = ZERO
    grace_days: int = 0
    today: date | None = None

    @property
    def outstanding(self) -> Decimal:
        return ZERO if self.charge.waived else self.charge.amount - self.paid

    @property
    def status(self) -> str:
        if self.charge.waived:
            return "waived"
        if self.outstanding <= 0:
            return "paid"
        if self.paid > 0:
            return "partial"
        today = self.today or timezone.localdate()
        if self.charge.due_date + timedelta(days=self.grace_days) < today:
            return "late"
        return "due"


@dataclass
class Ledger:
    lease: GroundLease
    lines: list[ChargeLine] = field(default_factory=list)
    payments: list[Payment] = field(default_factory=list)
    total_billed: Decimal = ZERO
    total_paid: Decimal = ZERO
    pending: Decimal = ZERO

    @property
    def balance(self) -> Decimal:
        return self.total_billed - self.total_paid

    @property
    def credit(self) -> Decimal:
        return max(ZERO, -self.balance)

    @property
    def covered_by_pending(self) -> bool:
        """A bank transfer in flight already covers the whole balance."""
        return self.balance > 0 and self.pending >= self.balance

    @property
    def unpaid_lines(self) -> list[ChargeLine]:
        return [line for line in self.lines if line.outstanding > 0]

    @property
    def overdue_amount(self) -> Decimal:
        return sum((ln.outstanding for ln in self.lines if ln.status == "late"), ZERO)

    @property
    def oldest_unpaid(self) -> ChargeLine | None:
        unpaid = self.unpaid_lines
        return unpaid[0] if unpaid else None

    @property
    def months_behind(self) -> int:
        return sum(1 for ln in self.lines if ln.status == "late")


def build_ledger(lease: GroundLease) -> Ledger:
    """Apply received payments to charges oldest-first (FIFO)."""
    charges = list(lease.charges.order_by("due_date", "pk"))
    payments = list(lease.payments.order_by("-received_on", "-pk"))
    received = [p for p in payments if p.status == Payment.Status.SUCCEEDED]
    pool = sum((p.amount for p in received), ZERO)
    ledger = Ledger(lease=lease, payments=payments)
    ledger.total_paid = pool
    grace = Organization.current().grace_period_days
    today = timezone.localdate()
    ledger.pending = sum(
        (p.amount for p in payments if p.status in (Payment.Status.PENDING, Payment.Status.PROCESSING)),
        ZERO,
    )
    for charge in charges:
        line = ChargeLine(charge, grace_days=grace, today=today)
        if not charge.waived:
            ledger.total_billed += charge.amount
            applied = min(pool, charge.amount)
            line.paid = applied
            pool -= applied
        ledger.lines.append(line)
    return ledger


def balance_for(lease: GroundLease) -> Decimal:
    billed = lease.charges.filter(waived=False).aggregate(t=Sum("amount"))["t"] or ZERO
    paid = lease.payments.filter(status=Payment.Status.SUCCEEDED).aggregate(t=Sum("amount"))["t"] or ZERO
    return billed - paid


@dataclass
class AgingRow:
    lease: GroundLease
    ledger: Ledger
    current: Decimal = ZERO
    days_30: Decimal = ZERO
    days_60: Decimal = ZERO
    days_90: Decimal = ZERO

    @property
    def total(self) -> Decimal:
        return self.current + self.days_30 + self.days_60 + self.days_90


@dataclass
class AgingReport:
    rows: list[AgingRow]
    as_of: date

    def _sum(self, attr: str) -> Decimal:
        return sum((getattr(r, attr) for r in self.rows), ZERO)

    @property
    def totals(self) -> dict[str, Decimal]:
        return {k: self._sum(k) for k in ("current", "days_30", "days_60", "days_90", "total")}


def aging_report(as_of: date | None = None, *, leases=None) -> AgingReport:
    """Outstanding balances bucketed by days past due."""
    as_of = as_of or timezone.localdate()
    if leases is None:
        leases = GroundLease.objects.filter(charges__isnull=False).distinct()
    rows = []
    for lease in leases.select_related("ownership__home", "ownership__household"):
        ledger = build_ledger(lease)
        if ledger.balance <= 0:
            continue
        row = AgingRow(lease=lease, ledger=ledger)
        for line in ledger.unpaid_lines:
            days = (as_of - line.charge.due_date).days
            if days <= 30:
                row.current += line.outstanding
            elif days <= 60:
                row.days_30 += line.outstanding
            elif days <= 90:
                row.days_60 += line.outstanding
            else:
                row.days_90 += line.outstanding
        rows.append(row)
    rows.sort(key=lambda r: (-r.days_90, -r.days_60, -r.total))
    return AgingReport(rows=rows, as_of=as_of)


def collected_between(start: date, end: date) -> Decimal:
    return (
        Payment.objects.filter(
            status=Payment.Status.SUCCEEDED, received_on__gte=start, received_on__lte=end
        ).aggregate(t=Sum("amount"))["t"]
        or ZERO
    )


def billed_between(start: date, end: date) -> Decimal:
    return (
        LeaseCharge.objects.filter(waived=False, due_date__gte=start, due_date__lte=end).aggregate(
            t=Sum("amount")
        )["t"]
        or ZERO
    )


def monthly_collections(months: int = 12, *, end: date | None = None) -> list[dict]:
    """Billed vs collected for each of the last ``months`` months (oldest first)."""
    end = month_start(end or timezone.localdate())
    series = []
    for offset in range(months - 1, -1, -1):
        start = add_months(end, -offset)
        stop = month_end(start)
        series.append(
            {
                "month": start,
                "billed": billed_between(start, stop),
                "collected": collected_between(start, stop),
            }
        )
    return series
