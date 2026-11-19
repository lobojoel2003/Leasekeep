import io
from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from leasekeep.core.models import Organization
from leasekeep.formulas.models import ResaleFormula
from leasekeep.homes import services
from leasekeep.homes.models import (
    Appraisal,
    CapitalImprovement,
    GroundLease,
    Household,
    OccupancyCheck,
    Ownership,
    RefinanceRequest,
    Subsidy,
)
from leasekeep.homes.timeline import build_events, group_by_year
from tests import factories

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("amount", "funded", "years"),
    [
        # Commitments before the 2025 HOME rule: $15,000 / $40,000 thresholds.
        ("14999.99", date(2020, 1, 1), 5),
        ("15000", date(2020, 1, 1), 10),
        ("40000", date(2020, 1, 1), 10),
        ("40000.01", date(2020, 1, 1), 15),
        # On or after April 20, 2025: $25,000 / $50,000 thresholds.
        ("20000", date(2025, 4, 19), 10),
        ("20000", date(2025, 4, 20), 5),
        ("45000", date(2025, 6, 1), 10),
        ("50000", date(2025, 6, 1), 10),
        ("50000.01", date(2025, 6, 1), 15),
    ],
)
def test_home_affordability_periods(amount, funded, years):
    subsidy = Subsidy(home=factories.home(), source=Subsidy.Source.HOME, amount=D(amount), funded_on=funded)
    assert subsidy.affordability_years == years
    assert subsidy.affordability_ends_on == funded.replace(year=funded.year + years)


def test_affordability_override_and_non_home_sources():
    h = factories.home()
    assert (
        Subsidy(
            home=h, source=Subsidy.Source.CDBG, amount=D("90000"), funded_on=date(2020, 1, 1)
        ).affordability_years
        is None
    )
    override = Subsidy(
        home=h,
        source=Subsidy.Source.LOCAL,
        amount=D("1"),
        funded_on=date(2020, 2, 29),
        affordability_years_override=30,
    )
    assert override.affordability_years == 30
    assert override.affordability_ends_on == date(2050, 2, 28)
    assert (
        Subsidy(
            home=h, source=Subsidy.Source.CDBG, amount=D("1"), funded_on=date(2020, 1, 1)
        ).affordability_ends_on
        is None
    )


@pytest.mark.parametrize(
    ("pct", "band"),
    [
        (None, "Not reported"),
        ("30", "0–30% AMI"),
        ("50", "31–50% AMI"),
        ("60", "51–60% AMI"),
        ("80", "61–80% AMI"),
        ("81", "Over 80% AMI"),
    ],
)
def test_income_category(pct, band):
    assert Household(ami_percent_at_purchase=D(pct) if pct else None).income_category == band


def test_lease_expiry_handles_leap_day():
    o = factories.ownership(purchase_date=date(2016, 2, 29))
    assert o.lease.expires_on == date(2115, 2, 28)
    o.lease.start_date = date(2020, 6, 1)
    assert o.lease.expires_on == date(2119, 6, 1)
    assert str(o.lease) == f"Lease {o.lease.lease_number}"
    assert o.lease.home == o.home and o.lease.household == o.household and o.lease.is_active


def test_organization_is_a_singleton():
    first = Organization.current()
    assert Organization.current().pk == first.pk
    assert first.display_name == first.name
    first.short_name = "RCLT"
    assert first.display_name == "RCLT"


def test_one_active_ownership_per_home():
    o = factories.ownership()
    with pytest.raises(Exception):  # noqa: B017 - IntegrityError from the constraint
        Ownership.objects.create(
            home=o.home,
            household=factories.household(),
            formula=o.formula,
            purchase_date=date(2020, 1, 1),
            purchase_price=D("1"),
        )


def test_ownership_clean_rejects_sale_before_purchase():
    o = factories.ownership()
    o.sale_date = o.purchase_date - timedelta(days=1)
    with pytest.raises(ValidationError):
        o.clean()


def test_home_properties():
    h = factories.home(address_line1="1206 Willow Street", address_line2="Unit 3")
    assert h.street == "1206 Willow Street, Unit 3"
    assert h.full_address.endswith("Riverbend, OR 97999")
    assert h.status_label == "Vacant / in resale"
    o = factories.ownership(home_obj=h)
    h = type(h).objects.get(pk=h.pk)
    assert h.current_ownership == o
    assert h.status_label == "Occupied"
    assert h.get_absolute_url() == f"/homes/{h.pk}/"


def test_index_series_value_on():
    s = factories.series({date(2020, 4, 1): "80000", date(2021, 4, 1): "82000"})
    assert s.value_on(date(2020, 3, 31)) is None
    assert s.value_on(date(2021, 3, 31)).value == D("80000")
    assert s.value_on(date(2030, 1, 1)).value == D("82000")
    assert "HUD AMI" in str(s.values.first())


def test_formula_model_config_and_labels():
    appraisal = factories.formula("appraisal", owner_share_percent=D("25"), scale_by_purchase_ratio=True)
    assert appraisal.to_config().owner_share == D("0.25")
    assert appraisal.parameter_label == "25% of appreciation"
    assert "proportional" in appraisal.summary
    fixed = factories.formula("fixed_rate", annual_rate_percent=D("1.5"), compounding="simple")
    assert fixed.parameter_label == "1.5%/yr simple"
    indexed = factories.formula("indexed")
    assert indexed.parameter_label == "Follows HUD AMI"
    assert indexed.to_config().index_name == "HUD AMI"
    broken = ResaleFormula(name="x", kind="indexed")
    with pytest.raises(ValidationError):
        broken.clean()


def test_refinance_properties():
    refi = RefinanceRequest(loan_amount=D("90000"), existing_balance=D("80000"))
    assert refi.cash_out == D("10000")
    assert refi.ltv_percent is None and refi.within_policy is None
    refi.formula_price_at_review = D("120000")
    refi.max_allowed_loan = D("108000")
    assert refi.ltv_percent == D("75.0")
    assert refi.within_policy is True
    assert RefinanceRequest(loan_amount=D("1")).cash_out is None


def test_occupancy_overdue():
    o = factories.ownership()
    check = OccupancyCheck.objects.create(ownership=o, year=2020, due_date=date(2020, 3, 31))
    assert check.is_overdue and check.is_open
    check.result = OccupancyCheck.Result.COMPLIANT
    assert not check.is_overdue and not check.is_open


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------


def test_quote_appraisal_formula_uses_latest_appraisal_and_credits():
    o = factories.ownership(formula_obj=factories.formula("appraisal", owner_share_percent=D("25")))
    factories.appraisal(o.home, "240000", date(2020, 1, 1), appraiser="Old")
    factories.appraisal(o.home, "280000", date(2024, 1, 1), appraiser="Cascade")
    CapitalImprovement.objects.create(
        ownership=o,
        title="Roof",
        requested_amount=D("10000"),
        approved_credit=D("10000"),
        completed_on=date(2021, 1, 1),
        status=CapitalImprovement.Status.APPROVED,
        useful_life_years=20,
    )
    CapitalImprovement.objects.create(ownership=o, title="Pending", requested_amount=D("5000"))
    pq = services.quote(o, date(2026, 1, 1))
    assert pq.ok
    assert pq.market_value == D("280000")
    # 150,000 + 25% × 80,000 + 10,000 × (1 − 5/20)
    assert pq.price == D("177500.00")
    assert pq.affordability_gap == D("102500.00")
    assert any("Cascade" in s.detail for s in pq.sources)
    assert not pq.stale_appraisal


def test_quote_flags_stale_appraisal_and_supports_overrides():
    o = factories.ownership()
    factories.appraisal(o.home, "230000", date(2017, 1, 1))
    pq = services.quote(o, date(2026, 1, 1))
    assert pq.stale_appraisal and pq.appraisal_age_years == 9
    what_if = services.quote(o, date(2026, 1, 1), appraised_value=D("300000"))
    assert what_if.overridden and not what_if.stale_appraisal
    assert what_if.price == D("175000.00")


def test_quote_indexed_formula_looks_up_index_values():
    s = factories.series({date(2015, 4, 1): "70000", date(2025, 4, 1): "105000"})
    o = factories.ownership(
        formula_obj=factories.formula("indexed", index_series=s, cap_at_appraised_value=False)
    )
    pq = services.quote(o, date(2026, 1, 1))
    assert pq.price == D("225000.00")
    o.index_value_at_purchase = D("75000")
    assert services.quote(o, date(2026, 1, 1)).price == D("210000.00")
    assert services.quote(o, date(2026, 1, 1), index_value=D("90000")).price == D("180000.00")


def test_quote_reports_missing_data_instead_of_crashing():
    o = factories.ownership(formula_obj=factories.formula("appraisal"))
    pq = services.quote(o, date(2026, 1, 1))
    assert not pq.ok
    assert "current appraisal" in pq.error
    assert pq.price is None and pq.affordability_gap is None


def test_record_resale_moves_the_home_to_the_buyer():
    o = factories.ownership(formula_obj=factories.formula("appraisal", owner_share_percent=D("25")))
    OccupancyCheck.objects.create(ownership=o, year=2026, due_date=date(2026, 3, 31))
    RefinanceRequest.objects.create(ownership=o, lender="Bank", loan_amount=D("1000"))
    CapitalImprovement.objects.create(ownership=o, title="Deck", requested_amount=D("1000"))
    buyer = factories.household()
    result = services.record_resale(
        o,
        sale_date=date(2026, 6, 1),
        sale_price=D("170000"),
        appraised_value=D("280000"),
        buyer=buyer,
        formula=o.formula,
        lease_number="NEW-1",
        monthly_fee=D("45"),
    )
    o.refresh_from_db()
    assert o.status == Ownership.Status.SOLD
    assert o.formula_price_at_sale == D("170000.00")
    assert o.lease.ended_on == date(2026, 6, 1)
    assert result.new_ownership.household == buyer
    assert result.new_ownership.initial_appraised_value == D("280000")
    assert result.new_lease.monthly_fee == D("45")
    assert Appraisal.objects.filter(home=o.home, purpose=Appraisal.Purpose.RESALE).count() == 1
    assert o.occupancy_checks.get().result == OccupancyCheck.Result.WAIVED
    assert o.refinances.get().status == RefinanceRequest.Status.WITHDRAWN
    assert o.improvements.get().status == CapitalImprovement.Status.WITHDRAWN


def test_record_resale_guards():
    o = factories.ownership(formula_obj=factories.formula("appraisal", owner_share_percent=D("25")))
    kwargs = {
        "sale_date": date(2026, 6, 1),
        "appraised_value": D("280000"),
        "buyer": factories.household(),
        "formula": o.formula,
        "lease_number": "N-1",
        "monthly_fee": D("40"),
    }
    with pytest.raises(services.ResaleError, match="above the formula price"):
        services.record_resale(o, sale_price=D("170001"), **kwargs)
    assert not Appraisal.objects.exists()  # rolled back
    with pytest.raises(services.ResaleError, match="different household"):
        services.record_resale(o, sale_price=D("1"), **{**kwargs, "buyer": o.household})
    with pytest.raises(services.ResaleError, match="before the seller"):
        services.record_resale(o, sale_price=D("1"), **{**kwargs, "sale_date": date(2000, 1, 1)})
    services.record_resale(o, sale_price=D("175000"), allow_above_formula=True, **kwargs)
    with pytest.raises(services.ResaleError, match="already ended"):
        services.record_resale(o, sale_price=D("1"), **{**kwargs, "lease_number": "N-2"})


def test_schedule_occupancy_checks_is_idempotent():
    org = Organization.current()
    org.occupancy_check_due_month = 2
    org.save()
    factories.ownership(purchase_date=date(2015, 1, 1))
    factories.ownership(purchase_date=date(2024, 6, 1))  # bought this year: first check next year
    assert services.schedule_occupancy_checks(2024) == 1
    assert services.schedule_occupancy_checks(2024) == 0
    assert OccupancyCheck.objects.get().due_date == date(2024, 2, 29)
    call_command("schedule_occupancy_checks", "--year", "2025", stdout=io.StringIO())
    assert OccupancyCheck.objects.filter(year=2025).count() == 2


def test_evaluate_refinance_applies_ltv_policy():
    o = factories.ownership(
        formula_obj=factories.formula("fixed_rate", annual_rate_percent=D("0"), cap_at_appraised_value=False)
    )
    refi = RefinanceRequest.objects.create(ownership=o, lender="Credit union", loan_amount=D("140000"))
    services.evaluate_refinance(refi)
    refi.refresh_from_db()
    assert refi.formula_price_at_review == D("150000.00")
    assert refi.max_allowed_loan == D("135000.00")
    assert refi.within_policy is False


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------


def test_timeline_tells_the_story_from_purchase_to_resale():
    h = factories.home(acquired_on=date(2011, 5, 1))
    Subsidy.objects.create(home=h, source=Subsidy.Source.HOME, amount=D("30000"), funded_on=date(2012, 1, 1))
    o = factories.ownership(home_obj=h, purchase_date=date(2012, 3, 1))
    from leasekeep.billing.models import Payment
    from leasekeep.billing.services import generate_charges, months_in_range

    generate_charges(months_in_range(date(2012, 3, 1), date(2013, 2, 1)), leases=[o.lease])
    Payment.objects.create(lease=o.lease, amount=D("35"), received_on=date(2012, 4, 2))
    CapitalImprovement.objects.create(
        ownership=o,
        title="Furnace",
        requested_amount=D("5000"),
        approved_credit=D("5000"),
        completed_on=date(2013, 1, 1),
        status=CapitalImprovement.Status.APPROVED,
        useful_life_years=15,
    )
    OccupancyCheck.objects.create(
        ownership=o,
        year=2013,
        due_date=date(2013, 3, 31),
        result="compliant",
        method="site_visit",
        completed_on=date(2013, 3, 2),
    )
    RefinanceRequest.objects.create(ownership=o, lender="Bank", loan_amount=D("100000"))
    services.record_resale(
        o,
        sale_date=date(2014, 1, 15),
        sale_price=D("150000"),
        appraised_value=D("205000"),
        buyer=factories.household(),
        formula=o.formula,
        lease_number="L-NEXT",
        monthly_fee=D("40"),
    )
    events = build_events(h, today=date(2014, 6, 1))
    kinds = [e.kind for e in events]
    for kind in (
        "land",
        "subsidy",
        "purchase",
        "lease",
        "fees",
        "improvement",
        "occupancy",
        "refinance",
        "resale",
        "appraisal",
    ):
        assert kind in kinds
    assert kinds.index("land") < kinds.index("purchase") < kinds.index("resale")
    fees_2012 = next(e for e in events if e.kind == "fees" and e.on.year == 2012)
    assert fees_2012.tone == "bad" and "unpaid" in fees_2012.badge
    owner_view = build_events(h, today=date(2014, 6, 1), for_owner=True)
    assert all(e.url == "" for e in owner_view)
    groups = group_by_year(events, newest_first=True)
    assert [g.year for g in groups] == sorted({e.on.year for e in events}, reverse=True)


def test_ground_lease_requires_unique_number():
    o = factories.ownership()
    with pytest.raises(Exception):  # noqa: B017
        GroundLease.objects.create(
            ownership=factories.ownership(lease=False),
            lease_number=o.lease.lease_number,
            start_date=date(2020, 1, 1),
            monthly_fee=D("1"),
        )


def test_seed_demo_refuses_to_overwrite_and_loads_with_force():
    factories.home()
    with pytest.raises(CommandError):
        call_command("seed_demo")
    call_command("seed_demo", "--force", "--with-users", stdout=io.StringIO())
    assert Ownership.objects.filter(status=Ownership.Status.SOLD).count() == 1
    rivera = Household.objects.get(name="Rivera household")
    assert rivera.portal_user is not None
    assert services.quote(rivera.active_ownership, timezone.localdate()).ok
