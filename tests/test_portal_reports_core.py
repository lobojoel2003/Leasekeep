import csv
import io
import json
from datetime import date
from decimal import Decimal as D

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory
from django.urls import reverse

from leasekeep.billing.models import Payment
from leasekeep.billing.services import generate_charges, months_in_range
from leasekeep.core import charts, errors
from leasekeep.core.context_processors import NavCounts
from leasekeep.core.models import Organization
from leasekeep.core.templatetags import leasekeep as tags
from leasekeep.homes.models import CapitalImprovement, OccupancyCheck, RefinanceRequest, Subsidy
from leasekeep.reports import metrics
from leasekeep.version import BuildInfo, get_build_info
from tests import factories

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Owner portal
# ---------------------------------------------------------------------------


def test_portal_home_shows_my_home_only(owner_client, owner):
    other = factories.ownership()
    response = owner_client.get(reverse("portal:home"))
    assert response.status_code == 200
    assert response.context["ownership"] == owner
    assert response.context["quote"].ok
    assert other.home.street.encode() not in response.content


def test_portal_without_an_active_home(client):
    hh = factories.household(portal_user=factories.user())
    client.force_login(hh.portal_user)
    assert b"no active home" in client.get(reverse("portal:home")).content
    for name in (
        "portal:resale_value",
        "portal:payments",
        "portal:pay",
        "portal:improvement_new",
        "portal:refinance_new",
    ):
        assert client.get(reverse(name))["Location"] == reverse("portal:home")


def test_owner_requests_an_improvement_credit(owner_client, owner, settings):
    settings.LEASEKEEP_STAFF_NOTIFICATION_EMAIL = "staff@example.org"
    receipt = SimpleUploadedFile("invoice.pdf", b"%PDF-1.4", content_type="application/pdf")
    response = owner_client.post(
        reverse("portal:improvement_new"),
        {
            "title": "Heat pump",
            "category": "hvac",
            "requested_amount": "9800",
            "completed_on": "2026-01-15",
            "receipt": receipt,
        },
    )
    assert response["Location"] == reverse("portal:home")
    item = CapitalImprovement.objects.get()
    assert item.ownership == owner and item.submitted_by_owner
    assert item.status == CapitalImprovement.Status.REQUESTED
    assert mail.outbox[0].to == ["staff@example.org"]
    assert "/improvements/" in mail.outbox[0].body


def test_owner_certifies_occupancy(owner_client, owner):
    check = OccupancyCheck.objects.create(ownership=owner, year=2026, due_date=date(2026, 3, 31))
    url = reverse("portal:certify", args=[check.pk])
    assert owner_client.get(url).status_code == 200
    response = owner_client.post(url, {"signed_name": "Pat Owner"})
    assert "lives_here" in response.context["form"].errors
    owner_client.post(url, {"lives_here": "on", "signed_name": "Pat Owner", "statement": "Home all year"})
    check.refresh_from_db()
    assert check.result == OccupancyCheck.Result.SUBMITTED
    assert check.owner_signed_name == "Pat Owner" and check.owner_submitted_at
    # A second visit says it's already on file.
    assert owner_client.get(url)["Location"] == reverse("portal:home")


def test_owner_cannot_touch_another_households_check(owner_client):
    other = factories.ownership()
    check = OccupancyCheck.objects.create(ownership=other, year=2026, due_date=date(2026, 3, 31))
    assert owner_client.get(reverse("portal:certify", args=[check.pk])).status_code == 404


def test_owner_asks_to_refinance(owner_client, owner):
    page = owner_client.get(reverse("portal:refinance_new"))
    assert b"usually meet our policy" in page.content
    owner_client.post(
        reverse("portal:refinance_new"),
        {"lender": "Credit union", "loan_amount": "120000", "purpose": "rate_term"},
    )
    refi = RefinanceRequest.objects.get()
    assert refi.submitted_by_owner and refi.max_allowed_loan is not None


def test_owner_resale_value_and_payment_history(owner_client, owner):
    generate_charges(months_in_range(date(2026, 1, 1), date(2026, 3, 1)), leases=[owner.lease])
    Payment.objects.create(lease=owner.lease, amount=D("35"), received_on=date(2026, 1, 3))
    resale = owner_client.get(reverse("portal:resale_value"))
    assert resale.context["quote"].ok
    assert b"Show the math" not in resale.content  # owners get the worksheet directly
    history = owner_client.get(reverse("portal:payments"))
    assert history.context["ledger"].balance == D("70.00")


def test_pay_without_online_payments(owner_client):
    page = owner_client.get(reverse("portal:pay"))
    assert b"aren't set up yet" in page.content
    response = owner_client.post(reverse("portal:pay"), {"amount": "35"})
    assert response["Location"] == reverse("portal:pay")
    assert not Payment.objects.exists()


def test_pay_online_redirects_to_stripe(owner_client, owner, settings, monkeypatch):
    settings.STRIPE_SECRET_KEY = "sk_test_x"
    monkeypatch.setattr(
        "leasekeep.billing.stripe_gateway.stripe.checkout.Session.create",
        lambda **kw: {"id": "cs_1", "url": "https://checkout.stripe.test/cs_1"},
    )
    response = owner_client.post(reverse("portal:pay"), {"amount": "35"})
    assert response["Location"] == "https://checkout.stripe.test/cs_1"
    payment = Payment.objects.get()
    assert payment.status == Payment.Status.PENDING and payment.stripe_checkout_session_id == "cs_1"
    done = owner_client.get(reverse("portal:pay_done"), {"session_id": "cs_1"})
    assert done.context["payment"] == payment
    assert b"processing" in done.content


def test_pay_online_handles_processor_errors(owner_client, settings, monkeypatch):
    settings.STRIPE_SECRET_KEY = "sk_test_x"

    def boom(**kw):
        raise RuntimeError("network down")

    monkeypatch.setattr("leasekeep.billing.stripe_gateway.stripe.checkout.Session.create", boom)
    response = owner_client.post(reverse("portal:pay"), {"amount": "35"})
    assert response["Location"] == reverse("portal:pay")
    assert not Payment.objects.exists()


def test_portal_welcome_message(owner_client):
    org = Organization.current()
    org.portal_welcome = "Office closed Friday."
    org.save()
    assert b"Office closed Friday." in owner_client.get(reverse("portal:home")).content


# ---------------------------------------------------------------------------
# Reports and exports
# ---------------------------------------------------------------------------


def rows_of(response):
    assert response["Content-Type"].startswith("text/csv")
    return list(csv.reader(io.StringIO(response.content.decode())))


def test_fiscal_years():
    org = Organization.current()
    assert metrics.fiscal_year_bounds(2026, org) == (date(2026, 1, 1), date(2026, 12, 31))
    assert metrics.current_fiscal_year(date(2026, 11, 19), org) == 2026
    org.fiscal_year_start_month = 7
    assert metrics.fiscal_year_bounds(2027, org) == (date(2026, 7, 1), date(2027, 6, 30))
    assert metrics.current_fiscal_year(date(2026, 11, 19), org) == 2027
    assert metrics.current_fiscal_year(date(2026, 6, 30), org) == 2026


def test_board_report_html_and_csv(staff_client):
    o = factories.ownership(purchase_date=date(2026, 1, 1))
    generate_charges(months_in_range(date(2026, 1, 1), date(2026, 3, 1)), leases=[o.lease])
    Payment.objects.create(lease=o.lease, amount=D("70"), received_on=date(2026, 2, 1))
    OccupancyCheck.objects.create(ownership=o, year=2026, due_date=date(2026, 3, 31), result="compliant")
    Subsidy.objects.create(home=o.home, source="home", amount=D("20000"), funded_on=date(2026, 1, 1))
    o.household.ami_percent_at_purchase = D("55")
    o.household.save()
    page = staff_client.get(reverse("reports:board"), {"fy": "2026"})
    report = page.context["report"]
    assert report.billed == D("105.00") and report.collected == D("70.00")
    assert report.collection_rate == D("66.7")
    assert report.occupancy_rate == D("100.0")
    assert report.income_bands == [("51–60% AMI", 1)]
    rows = rows_of(staff_client.get(reverse("reports:board"), {"fy": "2026", "format": "csv"}))
    assert rows[0] == ["Measure", "Value", "Notes"]
    assert ["Collection rate", "66.7%", ""] in rows
    assert staff_client.get(reverse("reports:board"), {"fy": "x"}).status_code == 200


def test_home_compliance_export(staff_client):
    o = factories.ownership(purchase_date=date(2026, 1, 1))
    o.household.ami_percent_at_purchase = D("48")
    o.household.hispanic = True
    o.household.save()
    Subsidy.objects.create(
        home=o.home, source="home", amount=D("30000"), funded_on=date(2025, 6, 1), idis_activity_id="77"
    )
    Subsidy.objects.create(home=o.home, source="local", amount=D("5000"), funded_on=date(2025, 6, 1))
    OccupancyCheck.objects.create(ownership=o, year=2026, due_date=date(2026, 3, 31), result="compliant")
    factories.ownership()  # not HOME-assisted, so not exported
    rows = rows_of(staff_client.get(reverse("reports:home_compliance"), {"on": "2026-06-01"}))
    header, data = rows[0], rows[1:]
    assert len(data) == 1
    row = dict(zip(header, data[0], strict=True))
    assert row["IDIS activity ID"] == "77"
    assert row["HOME funds"] == "30000.00" and row["All subsidy"] == "35000.00"
    assert row["Affordability period (years)"] == "10"
    assert row["Affordability period ends"] == "2035-06-01"
    assert row["Within affordability period"] == "Y"
    assert row["Income category"] == "31–50% AMI"
    assert row["Hispanic or Latino"] == "Y"
    assert row["Female head of household"] == "Not reported"
    assert row["Principal residence verified"] == "Y"
    html = staff_client.get(reverse("reports:home_compliance"), {"format": "html"})
    assert html.status_code == 200 and b"24 CFR 92.254" in html.content


def test_valuation_aging_and_payment_exports(staff_client):
    o = factories.ownership(purchase_date=date(2026, 1, 1), formula_obj=factories.formula("appraisal"))
    factories.appraisal(o.home, "260000", date(2026, 2, 1))
    generate_charges(months_in_range(date(2026, 1, 1), date(2026, 2, 1)), leases=[o.lease])
    Payment.objects.create(
        lease=o.lease, amount=D("35"), received_on=date(2026, 1, 5), method="check", reference="101"
    )
    valuation = rows_of(staff_client.get(reverse("reports:valuation"), {"on": "2026-06-01"}))
    assert valuation[1][7] == "165000.00" and valuation[1][10] == "95000.00"
    aging = rows_of(staff_client.get(reverse("reports:aging"), {"on": "2026-06-01"}))
    assert aging[1][-1] == "35.00"
    payments = rows_of(
        staff_client.get(reverse("reports:payments"), {"start": "2026-01-01", "end": "2026-12-31"})
    )
    assert payments[1][4:] == ["35.00", "Check", "Received", "101"]
    assert staff_client.get(reverse("reports:index")).status_code == 200


def test_valuation_export_reports_unpriceable_homes(staff_client):
    factories.ownership(formula_obj=factories.formula("appraisal"))
    rows = rows_of(staff_client.get(reverse("reports:valuation")))
    assert "current appraisal" in rows[1][-1]


# ---------------------------------------------------------------------------
# Core: health, version, charts, template helpers, errors
# ---------------------------------------------------------------------------


def test_healthz_reports_version_and_build(client, monkeypatch):
    monkeypatch.setenv("LEASEKEEP_BUILD_NUMBER", "42")
    monkeypatch.setenv("LEASEKEEP_GIT_SHA", "abcdef1234567890")
    get_build_info.cache_clear()
    try:
        data = json.loads(client.get("/healthz").content)
    finally:
        get_build_info.cache_clear()
    from leasekeep import __version__

    assert data["status"] == "ok" and data["database"] == "ok"
    assert data["version"] == __version__
    assert data["build_number"] == "42"
    assert data["git_sha"] == "abcdef1234567890"


def test_healthz_reports_database_failure(client, monkeypatch):
    def broken(*a, **kw):
        raise RuntimeError("db down")

    monkeypatch.setattr("leasekeep.core.views.connection.cursor", broken)
    response = client.get("/healthz")
    assert response.status_code == 503
    assert json.loads(response.content)["database"] == "unavailable"


def test_build_info_label_and_file(tmp_path, monkeypatch):
    info = BuildInfo(version="1.2.3", build_number="7", git_sha="0123456789", build_date="2026-11-19")
    assert info.label == "v1.2.3 · build 7 · 0123456"
    assert BuildInfo("1.0.0", "", "", "").label == "v1.0.0"
    path = tmp_path / "build_info.json"
    path.write_text(json.dumps({"build_number": "99", "git_sha": "feedface", "build_date": "2026-01-01"}))
    monkeypatch.setattr("leasekeep.version.BUILD_INFO_FILE", path)
    monkeypatch.delenv("LEASEKEEP_BUILD_NUMBER", raising=False)
    monkeypatch.delenv("LEASEKEEP_GIT_SHA", raising=False)
    get_build_info.cache_clear()
    try:
        assert get_build_info().build_number == "99"
        path.write_text("not json")
        get_build_info.cache_clear()
        assert get_build_info().build_number == "dev"
    finally:
        get_build_info.cache_clear()


def test_footer_shows_build(staff_client):
    assert get_build_info().label.encode() in staff_client.get(reverse("core:dashboard")).content


def test_charts_geometry():
    assert charts.nice_ceiling(0) == 1.0
    assert charts.nice_ceiling(430) == 500
    assert charts.nice_ceiling(2100) == 2500
    assert charts.compact(500) == "$500"
    assert charts.compact(25000) == "$25K"
    assert charts.compact(2_000_000) == "$2M"
    chart = charts.grouped_columns(
        [{"m": "Jan", "a": D("100"), "b": D("0")}, {"m": "Feb", "a": D("50"), "b": D("75")}],
        ["a", "b"],
        label_key="m",
    )
    assert len(chart.groups) == 2 and chart.plot_height == chart.baseline - chart.top
    jan = chart.groups[0]
    assert jan.bars[1].path == ""  # zero draws nothing
    assert jan.bars[0].path.startswith("M") and jan.tip.startswith("Jan|$100.00 a")
    assert all(b.x + 24 <= g.x + g.width for g in chart.groups for b in g.bars)


def test_template_filters():
    assert tags.money(None) == "—"
    assert tags.money("1234.5") == "$1,234.50"
    assert tags.money(D("-1234.5"), 0) == "−$1,234"
    assert tags.money("abc") == "abc"
    assert tags.pct(D("12.345"), 1) == "12.3%"
    assert tags.pct(None) == "—"
    assert tags.longdate(date(2026, 1, 2)) == "Jan 2, 2026"
    assert tags.longdate(None) == "—" and tags.longdate("x") == "x"
    assert tags.get_item({"a": 1}, "a") == 1 and tags.get_item(None, "a") is None
    assert tags.percent_of(5, 10) == 50 and tags.percent_of(5, 0) == 0 and tags.percent_of("x", 1) == 0
    assert tags.percent_of(20, 10) == 100
    assert 'href="#i-home"' in tags.icon("home", "sm")
    assert "pill--good" in tags.status_pill("Paid", "good")


def test_nav_counts():
    o = factories.ownership()
    CapitalImprovement.objects.create(ownership=o, title="x", requested_amount=D("1"))
    RefinanceRequest.objects.create(ownership=o, lender="x", loan_amount=D("1"))
    OccupancyCheck.objects.create(ownership=o, year=2026, due_date=date(2026, 3, 31), result="submitted")
    counts = NavCounts()
    assert (counts.improvements, counts.refinances, counts.occupancy) == (1, 1, 1)


def test_error_pages(client):
    request = RequestFactory().get("/")
    request.user = factories.user()
    assert errors.forbidden(request).status_code == 403
    assert errors.not_found(request).status_code == 404
    response = errors.server_error(request)
    assert response.status_code == 500 and b"Something went wrong" in response.content


def test_production_settings_require_secret_key(monkeypatch):
    import importlib

    from django.core.exceptions import ImproperlyConfigured

    import leasekeep.settings as live

    monkeypatch.setenv("LEASEKEEP_ENV", "production")
    monkeypatch.delenv("DJANGO_SECRET_KEY", raising=False)
    with pytest.raises(ImproperlyConfigured):
        importlib.reload(live)
    monkeypatch.setenv("DJANGO_SECRET_KEY", "x" * 50)
    monkeypatch.setenv("DJANGO_ALLOWED_HOSTS", "clt.example.org, www.clt.example.org")
    reloaded = importlib.reload(live)
    assert reloaded.DEBUG is False and reloaded.SESSION_COOKIE_SECURE
    assert reloaded.ALLOWED_HOSTS == ["clt.example.org", "www.clt.example.org", "localhost", "127.0.0.1"]
    assert "whitenoise.middleware.WhiteNoiseMiddleware" in reloaded.MIDDLEWARE
    monkeypatch.setenv("LEASEKEEP_ENV", "staging")
    with pytest.raises(ImproperlyConfigured):
        importlib.reload(live)
    monkeypatch.setenv("LEASEKEEP_ENV", "test")
    importlib.reload(live)
