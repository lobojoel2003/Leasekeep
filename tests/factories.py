"""Small helpers for building test records without a factory library."""

from __future__ import annotations

import itertools
from datetime import date
from decimal import Decimal as D

from django.contrib.auth import get_user_model

from leasekeep.formulas.models import IndexSeries, IndexValue, ResaleFormula
from leasekeep.homes.models import Appraisal, GroundLease, Home, Household, Ownership

_seq = itertools.count(1)


def user(*, staff=False, **kw):
    n = next(_seq)
    defaults = {"username": f"user{n}", "email": f"user{n}@example.org", "is_staff": staff}
    defaults.update(kw)
    u = get_user_model().objects.create_user(password="pw-123456!", **defaults)
    return u


def formula(kind="appraisal", **kw):
    n = next(_seq)
    defaults = {"name": f"Formula {n}", "kind": kind}
    if kind == "indexed" and "index_series" not in kw:
        kw["index_series"] = series()
    defaults.update(kw)
    return ResaleFormula.objects.create(**defaults)


def series(values=None, **kw):
    n = next(_seq)
    s = IndexSeries.objects.create(
        name=kw.pop("name", f"AMI {n}"), short_name=kw.pop("short_name", "HUD AMI"), **kw
    )
    for when, value in (values or {date(2015, 4, 1): "70000", date(2025, 4, 1): "100000"}).items():
        IndexValue.objects.create(series=s, effective_date=when, value=D(value))
    return s


def home(**kw):
    n = next(_seq)
    defaults = {
        "address_line1": f"{n} Test Street",
        "city": "Riverbend",
        "state": "OR",
        "postal_code": "97999",
    }
    defaults.update(kw)
    return Home.objects.create(**defaults)


def household(**kw):
    n = next(_seq)
    defaults = {"name": f"Household {n}", "primary_contact": f"Person {n}", "email": f"hh{n}@example.org"}
    defaults.update(kw)
    return Household.objects.create(**defaults)


def ownership(
    *,
    home_obj=None,
    household_obj=None,
    formula_obj=None,
    purchase_date=date(2016, 1, 1),
    price="150000",
    appraised="200000",
    fee="35.00",
    lease=True,
    **kw,
):
    o = Ownership.objects.create(
        home=home_obj or home(),
        household=household_obj or household(),
        formula=formula_obj or formula(),
        purchase_date=purchase_date,
        purchase_price=D(price),
        initial_appraised_value=D(appraised) if appraised else None,
        **kw,
    )
    if lease:
        GroundLease.objects.create(
            ownership=o, lease_number=f"L-{next(_seq):04d}", start_date=purchase_date, monthly_fee=D(fee)
        )
    return o


def appraisal(home_obj, value, on, **kw):
    return Appraisal.objects.create(home=home_obj, value=D(value), effective_date=on, **kw)
