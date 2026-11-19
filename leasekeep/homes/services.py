"""Stewardship workflows: pricing, resales, occupancy checks and refinances."""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from leasekeep.core.models import Organization
from leasekeep.formulas import engine

from .models import (
    Appraisal,
    CapitalImprovement,
    GroundLease,
    Household,
    OccupancyCheck,
    Ownership,
    RefinanceRequest,
)

STALE_APPRAISAL_YEARS = 3


@dataclass
class Source:
    """Where an input to the formula came from, shown under the worksheet."""

    label: str
    value: str
    detail: str = ""


@dataclass
class PriceQuote:
    ownership: Ownership
    valuation_date: date
    result: engine.FormulaResult | None = None
    error: str = ""
    sources: list[Source] = field(default_factory=list)
    appraisal: Appraisal | None = None
    overridden: bool = False

    @property
    def ok(self) -> bool:
        return self.result is not None

    @property
    def price(self) -> Decimal | None:
        return self.result.price if self.result else None

    @property
    def market_value(self) -> Decimal | None:
        return self.appraisal.value if self.appraisal else None

    @property
    def appraisal_age_years(self) -> int | None:
        if self.appraisal is None:
            return None
        return (self.valuation_date - self.appraisal.effective_date).days // 365

    @property
    def stale_appraisal(self) -> bool:
        """True when the market value on file is more than three years old."""
        age = self.appraisal_age_years
        return age is not None and age >= STALE_APPRAISAL_YEARS and not self.overridden

    @property
    def affordability_gap(self) -> Decimal | None:
        """How far below market the formula keeps the home (the subsidy retained)."""
        if self.result is None or self.market_value is None:
            return None
        return self.market_value - self.result.price


def credited_improvements(ownership: Ownership) -> list[engine.ImprovementCredit]:
    items = ownership.improvements.filter(
        status=CapitalImprovement.Status.APPROVED,
        approved_credit__isnull=False,
        completed_on__isnull=False,
    ).order_by("completed_on")
    return [
        engine.ImprovementCredit(
            description=item.title,
            amount=item.approved_credit,
            completed_on=item.completed_on,
            useful_life_years=item.useful_life_years,
        )
        for item in items
    ]


def quote(
    ownership: Ownership,
    on: date | None = None,
    *,
    appraised_value: Decimal | None = None,
    index_value: Decimal | None = None,
) -> PriceQuote:
    """Compute the formula price for ``ownership`` on a date.

    ``appraised_value`` and ``index_value`` override what is on file, which is
    how the “what if” calculator works.
    """
    on = on or (ownership.sale_date if not ownership.is_active else None) or timezone.localdate()
    formula = ownership.formula
    config = formula.to_config()
    pq = PriceQuote(ownership=ownership, valuation_date=on)
    pq.overridden = appraised_value is not None or index_value is not None

    # Current market value: an override, or the latest appraisal on file.
    appraisal = ownership.home.latest_appraisal(on)
    current_value = None
    if appraised_value is not None:
        current_value = appraised_value
        pq.sources.append(
            Source("Current appraised value", engine.money(appraised_value), "Entered for this estimate")
        )
    elif appraisal is not None:
        current_value = appraisal.value
        pq.appraisal = appraisal
        detail = f"Appraisal effective {engine.long_date(appraisal.effective_date)}"
        if appraisal.appraiser:
            detail += f" by {appraisal.appraiser}"
        pq.sources.append(Source("Current appraised value", engine.money(appraisal.value), detail))
    if appraisal is not None and pq.appraisal is None:
        pq.appraisal = appraisal

    if ownership.initial_appraised_value:
        pq.sources.append(
            Source(
                "Appraised value at purchase",
                engine.money(ownership.initial_appraised_value),
                "From the ownership record",
            )
        )

    index_then = index_now = None
    if formula.kind == engine.FormulaKind.INDEXED and formula.index_series_id:
        series = formula.index_series
        if ownership.index_value_at_purchase:
            index_then = ownership.index_value_at_purchase
            pq.sources.append(
                Source(f"{series.short_name} at purchase", _num(index_then), "From the ownership record")
            )
        else:
            found = series.value_on(ownership.purchase_date)
            if found:
                index_then = found.value
                pq.sources.append(
                    Source(
                        f"{series.short_name} at purchase",
                        _num(found.value),
                        f"{series.name}, effective {engine.long_date(found.effective_date)}",
                    )
                )
        if index_value is not None:
            index_now = index_value
            pq.sources.append(
                Source(f"{series.short_name} now", _num(index_value), "Entered for this estimate")
            )
        else:
            found = series.value_on(on)
            if found:
                index_now = found.value
                pq.sources.append(
                    Source(
                        f"{series.short_name} now",
                        _num(found.value),
                        f"{series.name}, effective {engine.long_date(found.effective_date)}",
                    )
                )

    inputs = engine.FormulaInputs(
        purchase_price=ownership.purchase_price,
        purchase_date=ownership.purchase_date,
        valuation_date=on,
        initial_appraised_value=ownership.initial_appraised_value,
        current_appraised_value=current_value,
        index_at_purchase=index_then,
        index_at_valuation=index_now,
        improvements=tuple(credited_improvements(ownership)) if config.include_improvements else (),
    )
    try:
        pq.result = engine.calculate(config, inputs)
    except engine.FormulaError as exc:
        pq.error = str(exc)
    return pq


def _num(value: Decimal) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".") if value >= 1000 else f"{value.normalize():f}"


# ---------------------------------------------------------------------------
# Resale
# ---------------------------------------------------------------------------


class ResaleError(ValueError):
    pass


@dataclass
class ResaleResult:
    sold: Ownership
    new_ownership: Ownership
    new_lease: GroundLease
    formula_price: Decimal | None


@transaction.atomic
def record_resale(
    ownership: Ownership,
    *,
    sale_date: date,
    sale_price: Decimal,
    appraised_value: Decimal,
    buyer: Household,
    formula,
    lease_number: str,
    monthly_fee: Decimal,
    appraiser: str = "",
    allow_above_formula: bool = False,
    notes: str = "",
) -> ResaleResult:
    """Close the seller's ownership and open the buyer's, with a new ground lease."""
    if not ownership.is_active:
        raise ResaleError("This ownership has already ended.")
    if sale_date < ownership.purchase_date:
        raise ResaleError("The sale date can't be before the seller's purchase date.")
    if buyer.pk == ownership.household_id:
        raise ResaleError("The buyer must be a different household from the seller.")

    Appraisal.objects.create(
        home=ownership.home,
        effective_date=sale_date,
        value=appraised_value,
        purpose=Appraisal.Purpose.RESALE,
        appraiser=appraiser,
    )
    pq = quote(ownership, sale_date)
    if pq.price is not None and sale_price > pq.price and not allow_above_formula:
        raise ResaleError(
            f"The sale price is above the formula price of {engine.money(pq.price)}. "
            "Confirm the board-approved exception to continue."
        )

    ownership.status = Ownership.Status.SOLD
    ownership.sale_date = sale_date
    ownership.sale_price = sale_price
    ownership.formula_price_at_sale = pq.price
    ownership.appraised_value_at_sale = appraised_value
    ownership.save()
    lease = ownership.lease_or_none
    if lease is not None:
        lease.ended_on = sale_date
        lease.save(update_fields=["ended_on"])

    new_ownership = Ownership.objects.create(
        home=ownership.home,
        household=buyer,
        formula=formula,
        purchase_date=sale_date,
        purchase_price=sale_price,
        initial_appraised_value=appraised_value,
        notes=notes,
    )
    new_lease = GroundLease.objects.create(
        ownership=new_ownership,
        lease_number=lease_number,
        start_date=sale_date,
        monthly_fee=monthly_fee,
    )
    # Cancel any open checks and requests belonging to the seller.
    ownership.occupancy_checks.filter(result=OccupancyCheck.Result.PENDING).update(
        result=OccupancyCheck.Result.WAIVED, notes="Closed at resale."
    )
    ownership.refinances.filter(status__in=RefinanceRequest.OPEN_STATUSES).update(
        status=RefinanceRequest.Status.WITHDRAWN
    )
    ownership.improvements.filter(status=CapitalImprovement.Status.REQUESTED).update(
        status=CapitalImprovement.Status.WITHDRAWN
    )
    return ResaleResult(ownership, new_ownership, new_lease, pq.price)


# ---------------------------------------------------------------------------
# Occupancy checks
# ---------------------------------------------------------------------------


def occupancy_due_date(year: int) -> date:
    """Checks are due on the last day of the organization's chosen month."""
    month = Organization.current().occupancy_check_due_month
    return date(year, month, calendar.monthrange(year, month)[1])


@transaction.atomic
def schedule_occupancy_checks(year: int) -> int:
    """Create a pending check for every active ownership purchased before ``year``."""
    due = occupancy_due_date(year)
    created = 0
    for ownership in Ownership.objects.filter(
        status=Ownership.Status.ACTIVE, purchase_date__lt=date(year, 1, 1)
    ):
        _, was_created = OccupancyCheck.objects.get_or_create(
            ownership=ownership, year=year, defaults={"due_date": due}
        )
        created += int(was_created)
    return created


# ---------------------------------------------------------------------------
# Refinance review
# ---------------------------------------------------------------------------


def evaluate_refinance(request: RefinanceRequest, *, save: bool = True) -> PriceQuote:
    """Price the home and work out the largest loan the CLT's policy allows."""
    pq = quote(request.ownership)
    if pq.price is not None:
        ltv = Organization.current().refinance_max_ltv_percent
        request.formula_price_at_review = pq.price
        request.max_allowed_loan = engine.to_cents(pq.price * ltv / 100)
        if save:
            request.save(update_fields=["formula_price_at_review", "max_allowed_loan"])
    return pq
