"""Every screen renders against the full Riverbend demo portfolio.

The demo is loaded once for this module (see ``conftest.demo``), so tests here
must only read.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from leasekeep.formulas.models import IndexSeries, ResaleFormula
from leasekeep.homes.models import CapitalImprovement, Home, OccupancyCheck, Ownership, RefinanceRequest
from tests.test_views import STAFF_URLS

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("demo")]


@pytest.fixture
def staff_client(client):
    client.force_login(get_user_model().objects.get(username="staff"))
    return client


@pytest.fixture
def rivera_client(client):
    client.force_login(get_user_model().objects.get(username="ana.rivera@riverbendclt.example"))
    return client


def test_every_staff_screen_renders_with_demo_data(staff_client):
    client = staff_client
    alder = Home.objects.get(address_line1="18 Alder Court")
    rivera = alder.current_ownership
    sold = alder.ownerships.get(status=Ownership.Status.SOLD)
    urls = [reverse(n) for n in STAFF_URLS] + [
        alder.get_absolute_url(),
        alder.get_absolute_url() + "?order=newest",
        reverse("homes:edit", args=[alder.pk]),
        reverse("homes:formula", args=[rivera.pk]),
        reverse("homes:formula", args=[rivera.pk]) + "?appraised_value=300000&on=2030-01-01",
        reverse("homes:formula", args=[sold.pk]),
        reverse("homes:resale", args=[rivera.pk]),
        reverse("homes:appraisal_create", args=[alder.pk]),
        reverse("homes:subsidy_create", args=[alder.pk]),
        reverse("homes:improvement_create", args=[rivera.pk]),
        reverse("homes:refinance_create", args=[rivera.pk]),
        reverse("homes:household_detail", args=[rivera.household.pk]),
        reverse("homes:household_edit", args=[rivera.household.pk]),
        reverse("billing:ledger", args=[rivera.lease.pk]),
        reverse("billing:payment_create", args=[rivera.lease.pk]),
        reverse("billing:charge_create", args=[rivera.lease.pk]),
        reverse("homes:list") + "?q=Alder&status=occupied",
        reverse("homes:list") + "?status=vacant",
        reverse("homes:households") + "?q=Rivera",
        reverse("homes:improvements") + "?status=all",
        reverse("homes:refinances") + "?show=all",
        reverse("homes:occupancy") + f"?year={timezone.localdate().year}&result=pending",
        reverse("reports:board") + "?fy=2024",
        reverse("reports:home_compliance") + "?format=html",
    ]
    urls += [i.get_absolute_url() for i in CapitalImprovement.objects.all()]
    urls += [r.get_absolute_url() for r in RefinanceRequest.objects.all()]
    urls += [reverse("homes:occupancy_record", args=[c.pk]) for c in OccupancyCheck.objects.all()[:5]]
    urls += [f.get_absolute_url() for f in ResaleFormula.objects.all()]
    urls += [reverse("formulas:edit", args=[f.pk]) for f in ResaleFormula.objects.all()]
    urls += [reverse("formulas:series", args=[s.pk]) for s in IndexSeries.objects.all()]
    for url in urls:
        response = client.get(url)
        assert response.status_code == 200, url
        assert b"Traceback" not in response.content
    vacant = Home.objects.get(address_line1="88 Meadow Lane")
    assert client.get(vacant.get_absolute_url()).status_code == 200
    assert client.get(reverse("homes:ownership_create", args=[vacant.pk])).status_code == 200
    # The resale page redirects for an ownership that has already ended.
    assert client.get(reverse("homes:resale", args=[sold.pk])).status_code == 302


def test_dashboard_numbers(staff_client):
    response = staff_client.get(reverse("core:dashboard"))
    data = response.context["data"]
    assert data.homes == 12 and data.occupied == 11
    assert data.valuation.errors == []
    assert data.valuation.affordability_preserved > 0
    assert len(response.context["chart"].groups) == 12
    assert response.context["work"]
    assert b"Affordability preserved" in response.content


def test_every_portal_screen_renders_with_demo_data(rivera_client):
    for name in [
        "portal:home",
        "portal:resale_value",
        "portal:payments",
        "portal:pay",
        "portal:pay_done",
        "portal:improvement_new",
        "portal:refinance_new",
    ]:
        response = rivera_client.get(reverse(name))
        assert response.status_code == 200, name
    home = rivera_client.get(reverse("portal:home"))
    assert home.context["quote"].ok
    assert home.context["ledger"].covered_by_pending
    assert b"payment is processing" in home.content


def test_reports_with_demo_data(staff_client):
    board = staff_client.get(reverse("reports:board"))
    report = board.context["report"]
    assert report.homes == 12
    assert report.occupancy_year <= timezone.localdate().year
    csv = staff_client.get(reverse("reports:home_compliance")).content.decode()
    assert csv.count("\n") == 1 + 5  # header + five HOME-assisted homes
    assert "88 Meadow Lane" in csv and ",Vacant," in csv
    resales = staff_client.get(reverse("reports:board"), {"fy": "2022"}).context["report"].resales
    assert [o.household.name for o in resales] == ["Bennett household"]
