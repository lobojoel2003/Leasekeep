"""CSV exports: HUD/HOME compliance, portfolio valuation, aging and payments.

Column names follow the vocabulary HUD uses in IDIS beneficiary reporting and
HOME monitoring so the files can be pasted into a participating jurisdiction's
workbook with little rework. They are not an official HUD format.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from datetime import date
from decimal import Decimal

from django.db.models import Prefetch, Sum

from leasekeep.billing.models import Payment
from leasekeep.billing.services import aging_report
from leasekeep.homes.models import Home, OccupancyCheck, Ownership, Subsidy
from leasekeep.homes.services import quote

from .metrics import BoardReport, portfolio_valuation


def to_csv(header: Sequence[str], rows: Iterable[Sequence]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    for row in rows:
        writer.writerow(["" if v is None else _cell(v) for v in row])
    return buffer.getvalue()


def _cell(value):
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return "Y" if value else "N"
    return value


def _yn(value: bool | None) -> str:
    if value is None:
        return "Not reported"
    return "Y" if value else "N"


HOME_HEADER = [
    "Address",
    "City",
    "State",
    "ZIP",
    "Parcel ID",
    "IDIS activity ID",
    "HOME funds",
    "All subsidy",
    "Subsidy funded on",
    "Affordability period (years)",
    "Affordability period ends",
    "Within affordability period",
    "Resale restriction",
    "Current owner household",
    "Purchase date",
    "Purchase price",
    "Household size",
    "Annual income at purchase",
    "Income % of AMI at purchase",
    "Income category",
    "Race",
    "Hispanic or Latino",
    "Female head of household",
    "Last occupancy check (year)",
    "Last occupancy result",
    "Principal residence verified",
    "Current formula price",
    "Latest appraised value",
]


def home_compliance_rows(on: date) -> list[list]:
    homes = (
        Home.objects.filter(subsidies__source=Subsidy.Source.HOME)
        .distinct()
        .prefetch_related(
            "subsidies",
            Prefetch(
                "ownerships",
                queryset=Ownership.objects.filter(status=Ownership.Status.ACTIVE).select_related(
                    "household", "formula__index_series"
                ),
                to_attr="active",
            ),
        )
        .order_by("address_line1")
    )
    rows = []
    for home in homes:
        subsidies = list(home.subsidies.all())
        home_funds = [s for s in subsidies if s.source == Subsidy.Source.HOME]
        primary = max(home_funds, key=lambda s: s.affordability_ends_on or s.funded_on)
        ownership = home.active[0] if home.active else None
        hh = ownership.household if ownership else None
        check = (
            ownership.occupancy_checks.exclude(result=OccupancyCheck.Result.PENDING).order_by("-year").first()
            if ownership
            else None
        )
        pq = quote(ownership, on) if ownership else None
        ends = primary.affordability_ends_on
        rows.append(
            [
                home.street,
                home.city,
                home.state,
                home.postal_code,
                home.parcel_id,
                ", ".join(s.idis_activity_id for s in home_funds if s.idis_activity_id),
                sum((s.amount for s in home_funds), Decimal(0)),
                sum((s.amount for s in subsidies), Decimal(0)),
                primary.funded_on,
                primary.affordability_years,
                ends,
                _yn(ends >= on) if ends else "",
                "CLT ground lease with resale formula"
                if home.tenure == Home.Tenure.GROUND_LEASE
                else "Deed restriction with resale formula",
                hh.name if hh else "Vacant",
                ownership.purchase_date if ownership else None,
                ownership.purchase_price if ownership else None,
                hh.household_size if hh else None,
                hh.annual_income_at_purchase if hh else None,
                hh.ami_percent_at_purchase if hh else None,
                hh.income_category if hh else "",
                hh.get_race_display() if hh else "",
                _yn(hh.hispanic) if hh else "",
                _yn(hh.female_head_of_household) if hh else "",
                check.year if check else None,
                check.get_result_display() if check else "No check on file",
                _yn(check.result == OccupancyCheck.Result.COMPLIANT) if check else "N",
                pq.price if pq and pq.ok else None,
                pq.market_value if pq else None,
            ]
        )
    return rows


VALUATION_HEADER = [
    "Address",
    "Household",
    "Formula",
    "Purchase date",
    "Purchase price",
    "Years owned",
    "Improvement credits",
    "Formula price",
    "Latest appraised value",
    "Appraisal date",
    "Affordability preserved",
    "Capped at appraisal",
    "Note",
]


def valuation_rows(on: date) -> list[list]:
    rows = []
    for pq in sorted(portfolio_valuation(on).quotes, key=lambda q: q.ownership.home.address_line1):
        o = pq.ownership
        r = pq.result
        rows.append(
            [
                o.home.street,
                o.household.name,
                o.formula.name,
                o.purchase_date,
                o.purchase_price,
                f"{r.years_held:.2f}" if r else "",
                r.improvement_credit if r else None,
                r.price if r else None,
                pq.market_value,
                pq.appraisal.effective_date if pq.appraisal else None,
                pq.affordability_gap,
                r.capped if r else None,
                pq.error or "; ".join(r.warnings if r else []),
            ]
        )
    return rows


AGING_HEADER = [
    "Lease",
    "Address",
    "Household",
    "0–30 days",
    "31–60 days",
    "61–90 days",
    "Over 90 days",
    "Total",
]


def aging_rows(on: date) -> list[list]:
    return [
        [
            row.lease.lease_number,
            row.lease.home.street,
            row.lease.household.name,
            row.current,
            row.days_30,
            row.days_60,
            row.days_90,
            row.total,
        ]
        for row in aging_report(on).rows
    ]


PAYMENTS_HEADER = ["Received", "Lease", "Address", "Household", "Amount", "Method", "Status", "Reference"]


def payment_rows(start: date, end: date) -> list[list]:
    payments = (
        Payment.objects.filter(received_on__gte=start, received_on__lte=end)
        .select_related("lease__ownership__home", "lease__ownership__household")
        .order_by("received_on", "pk")
    )
    return [
        [
            p.received_on,
            p.lease.lease_number,
            p.lease.home.street,
            p.lease.household.name,
            p.amount,
            p.get_method_display(),
            p.get_status_display(),
            p.reference,
        ]
        for p in payments
    ]


def payments_total(start: date, end: date) -> Decimal:
    return Payment.objects.filter(
        received_on__gte=start, received_on__lte=end, status=Payment.Status.SUCCEEDED
    ).aggregate(t=Sum("amount"))["t"] or Decimal(0)


def board_report_rows(report: BoardReport) -> list[list]:
    rate = report.collection_rate
    occ_rate = report.occupancy_rate
    rows = [
        ["Fiscal year", f"FY{report.fiscal_year}", f"{report.start.isoformat()} to {report.end.isoformat()}"],
        ["Homes in portfolio", report.homes, ""],
        ["Homes with an active homeowner", report.active_ownerships, ""],
        ["New homeowners this year", report.new_ownerships, ""],
        ["Resales completed", len(report.resales), ""],
        ["Equity gained by sellers", report.resale_seller_gain, "Sale price minus purchase price"],
        ["Affordability kept at resale", report.resale_affordability_kept, "Market value minus sale price"],
        ["Lease fees billed", report.billed, ""],
        ["Lease fees collected", report.collected, ""],
        ["Collection rate", f"{rate}%" if rate is not None else "", ""],
        ["Lease fees outstanding at year end", report.receivable_end, ""],
        ["Occupancy checks", report.occupancy["total"], f"Calendar year {report.occupancy_year}"],
        ["Confirmed owner-occupied", report.occupancy["compliant"], ""],
        ["Not owner-occupied", report.occupancy["non_compliant"], ""],
        ["Occupancy compliance rate", f"{occ_rate}%" if occ_rate is not None else "", ""],
        ["Improvement requests received", report.improvements_received, ""],
        [
            "Improvement credits approved",
            report.improvement_credits,
            f"{report.improvements_approved} approvals",
        ],
        ["Refinance requests", report.refinances["received"], ""],
        ["Refinances approved", report.refinances["approved"], ""],
        ["Refinances denied", report.refinances["denied"], ""],
        ["Public subsidy retained in homes", report.subsidy_total, ""],
        ["Portfolio formula value", report.valuation.total_formula, ""],
        ["Portfolio market value", report.valuation.total_market, ""],
        ["Affordability preserved (market − formula)", report.valuation.affordability_preserved, ""],
    ]
    rows += [
        [f"Households at {band}", n, "Active homeowners, income at purchase"]
        for band, n in report.income_bands
    ]
    return rows
