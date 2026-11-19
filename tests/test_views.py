"""Staff screens, workflows and access control."""

from datetime import date
from decimal import Decimal as D

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from leasekeep.billing.models import LeaseCharge, Payment
from leasekeep.formulas.models import IndexSeries, ResaleFormula
from leasekeep.homes.models import (
    CapitalImprovement,
    Home,
    Household,
    RefinanceRequest,
    Subsidy,
)
from tests import factories

pytestmark = pytest.mark.django_db

STAFF_URLS = [
    "core:dashboard",
    "homes:list",
    "homes:create",
    "homes:households",
    "homes:household_create",
    "homes:improvements",
    "homes:occupancy",
    "homes:refinances",
    "billing:overview",
    "formulas:list",
    "formulas:create",
    "formulas:series_create",
    "reports:index",
    "reports:board",
]


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", STAFF_URLS)
def test_staff_pages_require_login(client, name):
    response = client.get(reverse(name))
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("login"))


@pytest.mark.parametrize("name", STAFF_URLS)
def test_homeowners_are_sent_to_the_portal(owner_client, name):
    response = owner_client.get(reverse(name))
    assert response.status_code == 302
    assert response["Location"] == reverse("portal:home")


def test_users_without_a_role_are_forbidden(client):
    client.force_login(factories.user())
    assert client.get(reverse("core:dashboard")).status_code == 403
    assert client.get(reverse("portal:home")).status_code == 403
    assert client.get(reverse("home")).status_code == 403


def test_root_routes_by_role(client, staff_user, owner):
    assert client.get("/")["Location"] == reverse("login")
    client.force_login(staff_user)
    assert client.get("/")["Location"] == reverse("core:dashboard")
    client.force_login(owner.household.portal_user)
    assert client.get("/")["Location"] == reverse("portal:home")


def test_staff_visiting_portal_go_to_dashboard(staff_client):
    assert staff_client.get(reverse("portal:home"))["Location"] == reverse("core:dashboard")


def test_login_with_email_or_username_and_logout(client):
    u = factories.user(username="maya", email="Maya@Example.org", staff=True)
    response = client.post(reverse("login"), {"username": "maya@example.org", "password": "pw-123456!"})
    assert response.status_code == 302
    assert client.get(reverse("core:dashboard")).status_code == 200
    client.post(reverse("logout"))
    assert client.get(reverse("core:dashboard")).status_code == 302
    assert client.post(reverse("login"), {"username": "MAYA", "password": "pw-123456!"}).status_code == 302
    client.post(reverse("logout"))
    assert (
        client.post(reverse("login"), {"username": "nobody@example.org", "password": "x"}).status_code == 200
    )
    assert client.post(reverse("login"), {"username": "maya", "password": "wrong"}).status_code == 200
    assert client.get(reverse("logout"))["Location"] == reverse("login")
    assert u.pk


def test_password_reset_pages(client):
    assert client.get(reverse("password_reset")).status_code == 200
    factories.user(email="reset@example.org")
    response = client.post(reverse("password_reset"), {"email": "reset@example.org"})
    assert response["Location"] == reverse("password_reset_done")
    assert len(mail.outbox) == 1
    assert client.get(reverse("password_reset_done")).status_code == 200
    assert client.get(reverse("password_reset_complete")).status_code == 200
    assert client.get(reverse("password_reset_confirm", args=["x", "y"])).status_code == 200


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------


def test_add_home_and_record_first_sale(staff_client):
    response = staff_client.post(
        reverse("homes:create"),
        {
            "address_line1": "9 New Street",
            "city": "Riverbend",
            "state": "or",
            "postal_code": "97999",
            "home_type": "single_family",
            "tenure": "ground_lease",
            "bedrooms": 3,
            "bathrooms": "1.5",
        },
    )
    home = Home.objects.get(address_line1="9 New Street")
    assert response["Location"] == home.get_absolute_url()
    assert home.state == "OR"
    hh = factories.household()
    f = factories.formula("appraisal")
    data = {
        "household": hh.pk,
        "formula": f.pk,
        "purchase_date": "2026-05-01",
        "purchase_price": "150000",
        "lease_number": "RCLT-900",
        "monthly_fee": "40",
        "term_years": 99,
    }
    response = staff_client.post(reverse("homes:ownership_create", args=[home.pk]), data)
    assert "initial_appraised_value" in response.context["form"].errors
    data["initial_appraised_value"] = "210000"
    data["lease_document"] = SimpleUploadedFile("lease.pdf", b"%PDF-1.4 test", content_type="application/pdf")
    response = staff_client.post(reverse("homes:ownership_create", args=[home.pk]), data)
    assert response.status_code == 302
    ownership = home.ownerships.get()
    assert ownership.lease.lease_number == "RCLT-900"
    assert ownership.lease.document.name.endswith(".pdf")
    # A second sale on an occupied home is refused.
    data["lease_number"] = "RCLT-901"
    response = staff_client.post(reverse("homes:ownership_create", args=[home.pk]), data)
    assert "already has an active ownership" in str(response.context["form"].non_field_errors())


def test_edit_home_appraisal_and_subsidy(staff_client):
    home = factories.home()
    data = {
        "address_line1": "Renamed",
        "city": "Riverbend",
        "state": "OR",
        "postal_code": "97999",
        "home_type": "condo",
        "tenure": "deed_restricted",
        "bedrooms": 1,
        "bathrooms": "1",
    }
    assert staff_client.post(reverse("homes:edit", args=[home.pk]), data).status_code == 302
    home.refresh_from_db()
    assert home.address_line1 == "Renamed"
    staff_client.post(
        reverse("homes:appraisal_create", args=[home.pk]),
        {"effective_date": "2026-01-02", "value": "250000", "purpose": "portfolio"},
    )
    assert home.appraisals.get().value == D("250000")
    staff_client.post(
        reverse("homes:subsidy_create", args=[home.pk]),
        {"source": "home", "kind": "retained", "amount": "30000", "funded_on": "2026-01-01"},
    )
    assert home.subsidies.get().affordability_years == 10


def test_formula_price_page_and_what_if(staff_client):
    o = factories.ownership(formula_obj=factories.formula("appraisal"))
    factories.appraisal(o.home, "260000", date(2025, 1, 1))
    response = staff_client.get(reverse("homes:formula", args=[o.pk]))
    assert response.context["quote"].price == D("165000.00")
    response = staff_client.get(reverse("homes:formula", args=[o.pk]), {"appraised_value": "280000"})
    assert response.context["quote"].price == D("170000.00")
    assert response.context["on_file"].price == D("165000.00")
    assert b"what-if estimate" in response.content


def test_resale_workflow(staff_client):
    o = factories.ownership(formula_obj=factories.formula("appraisal"))
    factories.appraisal(o.home, "260000", date(2025, 1, 1))
    buyer = factories.household()
    page = staff_client.get(reverse("homes:resale", args=[o.pk]))
    assert page.context["form"].fields["sale_price"].initial == D("165000.00")
    data = {
        "sale_date": "2026-06-01",
        "appraised_value": "260000",
        "sale_price": "999999",
        "buyer": buyer.pk,
        "formula": o.formula.pk,
        "lease_number": "R-2",
        "monthly_fee": "40",
    }
    response = staff_client.post(reverse("homes:resale", args=[o.pk]), data)
    assert "above the formula price" in str(response.context["form"].non_field_errors())
    data["sale_price"] = "165000"
    response = staff_client.post(reverse("homes:resale", args=[o.pk]), data)
    assert response["Location"] == o.home.get_absolute_url()
    assert o.home.current_ownership.household == buyer
    data["lease_number"] = "R-2"
    response = staff_client.post(reverse("homes:resale", args=[o.home.current_ownership.pk]), data)
    assert "lease_number" in response.context["form"].errors


def test_improvement_create_and_review(staff_client, settings):
    o = factories.ownership()
    receipt = SimpleUploadedFile("receipt.pdf", b"%PDF-1.4", content_type="application/pdf")
    response = staff_client.post(
        reverse("homes:improvement_create", args=[o.pk]),
        {"title": "New roof", "category": "roof", "requested_amount": "12000", "receipt": receipt},
    )
    item = CapitalImprovement.objects.get()
    assert response["Location"] == item.get_absolute_url()
    url = item.get_absolute_url()
    response = staff_client.post(url, {"decision": "approved", "approved_credit": "11000"})
    assert "completed_on" in response.context["form"].errors
    response = staff_client.post(
        url,
        {
            "decision": "approved",
            "approved_credit": "11000",
            "useful_life_years": 25,
            "completed_on": "2026-02-01",
            "decision_notes": "Approved.",
        },
    )
    assert response["Location"] == reverse("homes:improvements")
    item.refresh_from_db()
    assert item.is_credited and item.decided_by is not None
    assert "approved" in mail.outbox[0].subject
    assert staff_client.get(reverse("homes:improvements") + "?status=approved").context["items"][0] == item


def test_improvement_upload_validation(staff_client, settings):
    settings.LEASEKEEP_MAX_UPLOAD_MB = 0
    o = factories.ownership()
    big = SimpleUploadedFile("receipt.pdf", b"x" * 10, content_type="application/pdf")
    response = staff_client.post(
        reverse("homes:improvement_create", args=[o.pk]),
        {"title": "Roof", "category": "roof", "requested_amount": "1", "receipt": big},
    )
    assert "receipt" in response.context["form"].errors
    exe = SimpleUploadedFile("receipt.exe", b"x", content_type="application/octet-stream")
    response = staff_client.post(
        reverse("homes:improvement_create", args=[o.pk]),
        {"title": "Roof", "category": "roof", "requested_amount": "1", "receipt": exe},
    )
    assert "receipt" in response.context["form"].errors


def test_occupancy_schedule_and_record(staff_client):
    o = factories.ownership(purchase_date=date(2015, 1, 1))
    response = staff_client.post(reverse("homes:occupancy_schedule"), {"year": 2026})
    assert response["Location"].endswith("?year=2026")
    staff_client.post(reverse("homes:occupancy_schedule"), {"year": 2026})
    assert staff_client.post(reverse("homes:occupancy_schedule"), {"year": "x"}).status_code == 302
    check = o.occupancy_checks.get()
    url = reverse("homes:occupancy_record", args=[check.pk])
    response = staff_client.post(url, {"result": "compliant", "completed_on": "2026-03-01"})
    assert "method" in response.context["form"].errors
    response = staff_client.post(url, {"result": "compliant", "method": "site_visit", "completed_on": ""})
    assert "completed_on" in response.context["form"].errors
    staff_client.post(url, {"result": "compliant", "method": "site_visit", "completed_on": "2026-03-01"})
    check.refresh_from_db()
    assert check.result == "compliant" and check.reviewed_by is not None
    listing = staff_client.get(reverse("homes:occupancy"), {"year": "2026"})
    assert listing.context["summary"] == {"compliant": 1}
    assert staff_client.get(reverse("homes:occupancy"), {"year": "nope"}).status_code == 200


def test_refinance_create_and_decide(staff_client):
    o = factories.ownership(
        formula_obj=factories.formula("fixed_rate", annual_rate_percent=D("0"), cap_at_appraised_value=False)
    )
    staff_client.post(
        reverse("homes:refinance_create", args=[o.pk]),
        {"lender": "Credit Union", "loan_amount": "120000", "purpose": "rate_term"},
    )
    refi = RefinanceRequest.objects.get()
    assert refi.max_allowed_loan == D("135000.00") and refi.within_policy
    response = staff_client.get(refi.get_absolute_url())
    assert b"Within policy" in response.content
    staff_client.post(refi.get_absolute_url(), {"status": "conditional", "conditions": "No cash out."})
    refi.refresh_from_db()
    assert refi.status == "conditional" and refi.decided_on == timezone.localdate()
    assert "Approved with conditions" in mail.outbox[0].subject


def test_households_and_portal_invitation(staff_client):
    response = staff_client.post(
        reverse("homes:household_create") + "?next=/homes/",
        {"name": "Lee household", "primary_contact": "Sam Lee", "household_size": 2, "race": "not_reported"},
    )
    assert response["Location"] == "/homes/"
    hh = Household.objects.get(name="Lee household")
    staff_client.post(
        reverse("homes:household_edit", args=[hh.pk]),
        {"name": "Lee household", "primary_contact": "Sam Lee", "household_size": 3, "race": "asian"},
    )
    hh.refresh_from_db()
    assert hh.household_size == 3
    response = staff_client.post(
        reverse("homes:household_invite", args=[hh.pk]), {"email": "Sam@Example.org"}
    )
    assert response["Location"] == hh.get_absolute_url()
    hh.refresh_from_db()
    assert hh.portal_user.email == "sam@example.org"
    assert not hh.portal_user.has_usable_password()
    assert "homeowner portal" in mail.outbox[-1].subject
    assert "/accounts/reset/" in mail.outbox[-1].body
    # Re-sending to a new address updates the same login.
    staff_client.post(reverse("homes:household_invite", args=[hh.pk]), {"email": "sam.lee@example.org"})
    hh.refresh_from_db()
    assert hh.portal_user.email == "sam.lee@example.org"
    # An email that belongs to staff is refused.
    factories.user(email="boss@example.org", staff=True)
    staff_client.post(reverse("homes:household_invite", args=[hh.pk]), {"email": "boss@example.org"})
    hh.refresh_from_db()
    assert hh.portal_user.email == "sam.lee@example.org"
    assert staff_client.get(reverse("homes:households"), {"q": "Lee"}).context["page"].object_list[0] == hh


def test_lease_fee_workflows(staff_client):
    o = factories.ownership(purchase_date=date(2026, 1, 1), fee="40")
    response = staff_client.post(reverse("billing:generate"), {"month": "2026-02"})
    assert response["Location"] == reverse("billing:overview")
    staff_client.post(reverse("billing:generate"), {"month": "2026-02"})
    assert staff_client.post(reverse("billing:generate"), {"month": "bad"}).status_code == 302
    assert o.lease.charges.count() == 1
    staff_client.post(
        reverse("billing:charge_create", args=[o.lease.pk]),
        {"kind": "late_fee", "amount": "5", "due_date": "2026-02-20", "description": ""},
    )
    assert o.lease.charges.filter(kind=LeaseCharge.Kind.LATE_FEE).exists()
    response = staff_client.post(
        reverse("billing:payment_create", args=[o.lease.pk]),
        {"amount": "40", "received_on": "2026-02-03", "method": "check", "reference": "1042"},
    )
    assert response["Location"] == reverse("billing:ledger", args=[o.lease.pk])
    payment = Payment.objects.get()
    assert payment.status == Payment.Status.SUCCEEDED and payment.recorded_by is not None
    late = o.lease.charges.get(kind=LeaseCharge.Kind.LATE_FEE)
    staff_client.post(reverse("billing:charge_waive", args=[late.pk]), {"reason": "First time"})
    late.refresh_from_db()
    assert late.waived and late.waived_reason == "First time"
    staff_client.post(reverse("billing:charge_waive", args=[late.pk]))
    late.refresh_from_db()
    assert not late.waived
    ledger = staff_client.get(reverse("billing:ledger", args=[o.lease.pk]))
    assert ledger.context["ledger"].balance == D("5.00")
    overview = staff_client.get(reverse("billing:overview"))
    assert overview.status_code == 200


def test_formula_and_index_management(staff_client):
    response = staff_client.post(
        reverse("formulas:series_create"),
        {"name": "HUD AMI test", "short_name": "AMI", "kind": "ami", "source_url": "huduser.gov"},
    )
    series = IndexSeries.objects.get()
    assert series.source_url == "https://huduser.gov"
    url = reverse("formulas:series", args=[series.pk])
    assert response["Location"] == url
    staff_client.post(url, {"effective_date": "2020-04-01", "value": "80000"})
    staff_client.post(url, {"effective_date": "2021-04-01", "value": "84000"})
    duplicate = staff_client.post(url, {"effective_date": "2021-04-01", "value": "1"})
    assert "effective_date" in duplicate.context["form"].errors
    rows = staff_client.get(url).context["rows"]
    assert rows[0][1] == D("5.0")

    data = {
        "name": "Indexed",
        "kind": "indexed",
        "owner_share_percent": "25",
        "annual_rate_percent": "2",
        "compounding": "compound",
        "improvement_depreciation": "straight_line",
        "rounding": "dollar",
        "include_improvements": "on",
        "is_active": "on",
    }
    response = staff_client.post(reverse("formulas:create"), data)
    assert "index_series" in response.context["form"].errors
    data["index_series"] = series.pk
    response = staff_client.post(reverse("formulas:create"), data)
    formula = ResaleFormula.objects.get()
    assert response["Location"] == formula.get_absolute_url()
    detail = staff_client.get(formula.get_absolute_url())
    assert detail.context["result"] is None
    assert "needs AMI values" in detail.context["error"]  # no index value for the default purchase date
    preview = staff_client.get(
        formula.get_absolute_url(),
        {
            "purchase_price": "100000",
            "purchase_date": "2020-05-01",
            "valuation_date": "2021-05-01",
            "index_at_purchase": "80000",
            "index_at_valuation": "84000",
            "improvement_credit": "1000",
        },
    )
    assert preview.context["result"].price == D("106000.00")
    bad = staff_client.get(
        formula.get_absolute_url(),
        {"purchase_price": "100000", "purchase_date": "2020-05-01", "valuation_date": "2019-05-01"},
    )
    assert "before the purchase date" in bad.context["error"]
    data["name"] = "Indexed (renamed)"
    staff_client.post(reverse("formulas:edit", args=[formula.pk]), data)
    formula.refresh_from_db()
    assert formula.name == "Indexed (renamed)"
    assert staff_client.get(reverse("formulas:list")).context["formulas"][0].active_homes == 0


def test_subsidy_listed_on_home_page(staff_client):
    o = factories.ownership()
    Subsidy.objects.create(home=o.home, source="home", amount=D("10000"), funded_on=date(2020, 1, 1))
    response = staff_client.get(o.home.get_absolute_url())
    assert b"HUD HOME" in response.content
