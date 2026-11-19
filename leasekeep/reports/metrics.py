"""Portfolio metrics shared by the dashboard, board report and exports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from leasekeep.billing import services as billing
from leasekeep.billing.models import LeaseCharge, Payment
from leasekeep.core.models import Organization
from leasekeep.homes.models import (
    CapitalImprovement,
    Home,
    Household,
    OccupancyCheck,
    Ownership,
    RefinanceRequest,
    Subsidy,
)
from leasekeep.homes.services import PriceQuote, quote

ZERO = Decimal("0.00")


@dataclass
class PortfolioValuation:
    quotes: list[PriceQuote] = field(default_factory=list)

    @property
    def priced(self) -> list[PriceQuote]:
        return [q for q in self.quotes if q.ok]

    @property
    def total_formula(self) -> Decimal:
        return sum((q.price for q in self.priced), ZERO)

    @property
    def total_market(self) -> Decimal:
        return sum((q.market_value for q in self.priced if q.market_value is not None), ZERO)

    @property
    def affordability_preserved(self) -> Decimal:
        return sum((q.affordability_gap for q in self.priced if q.affordability_gap is not None), ZERO)

    @property
    def errors(self) -> list[PriceQuote]:
        return [q for q in self.quotes if not q.ok]


def portfolio_valuation(on: date | None = None) -> PortfolioValuation:
    ownerships = Ownership.objects.filter(status=Ownership.Status.ACTIVE).select_related(
        "home", "household", "formula", "formula__index_series"
    )
    return PortfolioValuation([quote(o, on) for o in ownerships])


def fiscal_year_bounds(year: int, org: Organization | None = None) -> tuple[date, date]:
    """Fiscal year ``year`` is the one that *ends* in ``year`` (FY2026 = Jul 2025–Jun 2026)."""
    org = org or Organization.current()
    month = org.fiscal_year_start_month
    if month == 1:
        return date(year, 1, 1), date(year, 12, 31)
    start = date(year - 1, month, 1)
    end = billing.add_months(start, 12)
    return start, date.fromordinal(end.toordinal() - 1)


def current_fiscal_year(today: date | None = None, org: Organization | None = None) -> int:
    today = today or timezone.localdate()
    org = org or Organization.current()
    month = org.fiscal_year_start_month
    if month == 1 or today.month < month:
        return today.year
    return today.year + 1


@dataclass
class Dashboard:
    homes: int
    occupied: int
    households_served: int
    receivable: Decimal
    collected_month: Decimal
    collected_ytd: Decimal
    collection_rate: Decimal | None
    late_accounts: int
    occupancy_year: int
    occupancy_total: int
    occupancy_done: int
    occupancy_overdue: int
    open_improvements: int
    open_refinances: int
    retained_subsidy: Decimal
    valuation: PortfolioValuation
    series: list[dict]
    aging: billing.AgingReport


def dashboard(today: date | None = None) -> Dashboard:
    today = today or timezone.localdate()
    year_start = date(today.year, 1, 1)
    month_start = billing.month_start(today)

    billed_total = LeaseCharge.objects.filter(waived=False).aggregate(t=Sum("amount"))["t"] or ZERO
    paid_total = (
        Payment.objects.filter(status=Payment.Status.SUCCEEDED).aggregate(t=Sum("amount"))["t"] or ZERO
    )
    series = billing.monthly_collections(12, end=today)
    billed_12 = sum((m["billed"] for m in series), ZERO)
    collected_12 = sum((m["collected"] for m in series), ZERO)
    aging = billing.aging_report(today)

    checks = OccupancyCheck.objects.filter(year=today.year)
    counts = checks.aggregate(
        total=Count("pk"),
        done=Count(
            "pk", filter=~Q(result__in=[OccupancyCheck.Result.PENDING, OccupancyCheck.Result.SUBMITTED])
        ),
        overdue=Count("pk", filter=Q(result=OccupancyCheck.Result.PENDING, due_date__lt=today)),
    )

    return Dashboard(
        homes=Home.objects.count(),
        occupied=Ownership.objects.filter(status=Ownership.Status.ACTIVE).count(),
        households_served=Household.objects.filter(ownerships__isnull=False).distinct().count(),
        receivable=max(ZERO, billed_total - paid_total),
        collected_month=billing.collected_between(month_start, today),
        collected_ytd=billing.collected_between(year_start, today),
        collection_rate=(collected_12 / billed_12 * 100).quantize(Decimal("0.1")) if billed_12 else None,
        late_accounts=sum(1 for row in aging.rows if row.days_30 + row.days_60 + row.days_90 > 0),
        occupancy_year=today.year,
        occupancy_total=counts["total"],
        occupancy_done=counts["done"],
        occupancy_overdue=counts["overdue"],
        open_improvements=CapitalImprovement.objects.filter(
            status=CapitalImprovement.Status.REQUESTED
        ).count(),
        open_refinances=RefinanceRequest.objects.filter(status__in=RefinanceRequest.OPEN_STATUSES).count(),
        retained_subsidy=Subsidy.objects.filter(kind=Subsidy.Kind.RETAINED).aggregate(t=Sum("amount"))["t"]
        or ZERO,
        valuation=portfolio_valuation(today),
        series=series,
        aging=aging,
    )


@dataclass
class BoardReport:
    fiscal_year: int
    occupancy_year: int
    start: date
    end: date
    homes: int
    homes_by_type: list[tuple[str, int]]
    active_ownerships: int
    new_ownerships: int
    resales: list[Ownership]
    billed: Decimal
    collected: Decimal
    receivable_end: Decimal
    aging: billing.AgingReport
    occupancy: dict[str, int]
    improvements_received: int
    improvements_approved: int
    improvement_credits: Decimal
    refinances: dict[str, int]
    subsidy_total: Decimal
    subsidy_by_source: list[tuple[str, Decimal]]
    income_bands: list[tuple[str, int]]
    valuation: PortfolioValuation

    @property
    def collection_rate(self) -> Decimal | None:
        if not self.billed:
            return None
        return (self.collected / self.billed * 100).quantize(Decimal("0.1"))

    @property
    def occupancy_rate(self) -> Decimal | None:
        closed = self.occupancy["compliant"] + self.occupancy["non_compliant"]
        if not closed:
            return None
        return (Decimal(self.occupancy["compliant"]) / closed * 100).quantize(Decimal("0.1"))

    @property
    def resale_seller_gain(self) -> Decimal:
        return sum(((o.sale_price or ZERO) - o.purchase_price for o in self.resales), ZERO)

    @property
    def resale_affordability_kept(self) -> Decimal:
        return sum(((o.appraised_value_at_sale or ZERO) - (o.sale_price or ZERO) for o in self.resales), ZERO)


def board_report(fiscal_year: int) -> BoardReport:
    org = Organization.current()
    start, end = fiscal_year_bounds(fiscal_year, org)
    as_of = min(end, timezone.localdate())

    resales = list(
        Ownership.objects.filter(sale_date__gte=start, sale_date__lte=end)
        .select_related("home", "household")
        .order_by("sale_date")
    )
    # Occupancy checks run on the calendar year: report the latest one inside this fiscal year.
    occupancy_year = min(end.year, as_of.year)
    occupancy_qs = OccupancyCheck.objects.filter(year=occupancy_year)
    occ = occupancy_qs.aggregate(
        total=Count("pk"),
        compliant=Count("pk", filter=Q(result=OccupancyCheck.Result.COMPLIANT)),
        non_compliant=Count("pk", filter=Q(result=OccupancyCheck.Result.NON_COMPLIANT)),
        waived=Count("pk", filter=Q(result=OccupancyCheck.Result.WAIVED)),
        open=Count(
            "pk", filter=Q(result__in=[OccupancyCheck.Result.PENDING, OccupancyCheck.Result.SUBMITTED])
        ),
    )
    improvements = CapitalImprovement.objects.filter(created_at__date__gte=start, created_at__date__lte=end)
    approved = CapitalImprovement.objects.filter(
        status=CapitalImprovement.Status.APPROVED, decided_on__gte=start, decided_on__lte=end
    )
    refis = RefinanceRequest.objects.filter(created_at__date__gte=start, created_at__date__lte=end)
    refi_counts = refis.aggregate(
        received=Count("pk"),
        approved=Count(
            "pk",
            filter=Q(
                status__in=[
                    RefinanceRequest.Status.APPROVED,
                    RefinanceRequest.Status.APPROVED_WITH_CONDITIONS,
                ]
            ),
        ),
        denied=Count("pk", filter=Q(status=RefinanceRequest.Status.DENIED)),
        open=Count("pk", filter=Q(status__in=RefinanceRequest.OPEN_STATUSES)),
    )

    type_labels = dict(Home.HomeType.choices)
    homes_by_type = [
        (type_labels.get(row["home_type"], row["home_type"]), row["n"])
        for row in Home.objects.values("home_type").annotate(n=Count("pk")).order_by("-n")
    ]
    source_labels = dict(Subsidy.Source.choices)
    subsidy_by_source = [
        (source_labels.get(row["source"], row["source"]), row["t"])
        for row in Subsidy.objects.values("source").annotate(t=Sum("amount")).order_by("-t")
    ]
    bands: dict[str, int] = {}
    for hh in Household.objects.filter(ownerships__status=Ownership.Status.ACTIVE).distinct():
        bands[hh.income_category] = bands.get(hh.income_category, 0) + 1
    band_order = ["0–30% AMI", "31–50% AMI", "51–60% AMI", "61–80% AMI", "Over 80% AMI", "Not reported"]
    income_bands = [(b, bands[b]) for b in band_order if b in bands]

    billed_to_end = (
        LeaseCharge.objects.filter(waived=False, due_date__lte=as_of).aggregate(t=Sum("amount"))["t"] or ZERO
    )
    paid_to_end = (
        Payment.objects.filter(status=Payment.Status.SUCCEEDED, received_on__lte=as_of).aggregate(
            t=Sum("amount")
        )["t"]
        or ZERO
    )

    return BoardReport(
        fiscal_year=fiscal_year,
        occupancy_year=occupancy_year,
        start=start,
        end=end,
        homes=Home.objects.count(),
        homes_by_type=homes_by_type,
        active_ownerships=Ownership.objects.filter(status=Ownership.Status.ACTIVE).count(),
        new_ownerships=Ownership.objects.filter(purchase_date__gte=start, purchase_date__lte=end).count(),
        resales=resales,
        billed=billing.billed_between(start, end),
        collected=billing.collected_between(start, end),
        receivable_end=max(ZERO, billed_to_end - paid_to_end),
        aging=billing.aging_report(as_of),
        occupancy=occ,
        improvements_received=improvements.count(),
        improvements_approved=approved.count(),
        improvement_credits=approved.aggregate(t=Sum("approved_credit"))["t"] or ZERO,
        refinances=refi_counts,
        subsidy_total=sum((amount for _, amount in subsidy_by_source), ZERO),
        subsidy_by_source=subsidy_by_source,
        income_bands=income_bands,
        valuation=portfolio_valuation(as_of),
    )
