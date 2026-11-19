import io

import pytest
from django.core.management import call_command

from tests import factories


@pytest.fixture(autouse=True)
def _media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.STRIPE_SECRET_KEY = ""
    settings.STRIPE_WEBHOOK_SECRET = ""
    settings.LEASEKEEP_STAFF_NOTIFICATION_EMAIL = ""


@pytest.fixture
def staff_user(db):
    return factories.user(staff=True, first_name="Maya", last_name="Ellison")


@pytest.fixture
def staff_client(client, staff_user):
    client.force_login(staff_user)
    return client


@pytest.fixture
def owner(db):
    """A homeowner with a portal login, an active ownership and a ground lease."""
    u = factories.user(email="owner@example.org")
    hh = factories.household(portal_user=u, email="owner@example.org")
    o = factories.ownership(household_obj=hh)
    factories.appraisal(o.home, "260000", o.purchase_date.replace(year=2025))
    return o


@pytest.fixture
def owner_client(client, owner):
    client.force_login(owner.household.portal_user)
    return client


@pytest.fixture(scope="module")
def demo(django_db_setup, django_db_blocker):
    """The fictional Riverbend demo, loaded once per test module."""
    with django_db_blocker.unblock():
        call_command("seed_demo", "--with-users", stdout=io.StringIO())
        yield
        call_command("flush", "--no-input")
