"""Load a realistic, entirely fictional land trust so Leasekeep can be explored.

    python manage.py seed_demo --with-users

Creates “Riverbend Community Land Trust” with a dozen homes, three resale
formulas, an AMI index, fifteen years of lease fees, improvements, occupancy
checks, refinances, subsidies and one completed resale. Names, addresses and
numbers are invented. Index values are illustrative, not published HUD data.
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from leasekeep.billing.models import LeaseCharge, Payment
from leasekeep.billing.services import add_months, generate_charges, months_in_range
from leasekeep.core.models import Organization
from leasekeep.formulas.models import IndexSeries, IndexValue, ResaleFormula
from leasekeep.homes import services
from leasekeep.homes.models import (
    Appraisal,
    CapitalImprovement,
    GroundLease,
    Home,
    Household,
    OccupancyCheck,
    Ownership,
    RefinanceRequest,
    Subsidy,
)

DEMO_PASSWORD = "leasekeep-demo"  # noqa: S105 - documented demo credential

AMI = {
    2010: 62400,
    2011: 62900,
    2012: 63500,
    2013: 63100,
    2014: 64800,
    2015: 66200,
    2016: 68900,
    2017: 71500,
    2018: 74300,
    2019: 77800,
    2020: 80100,
    2021: 82600,
    2022: 89900,
    2023: 95300,
    2024: 98700,
    2025: 101900,
    2026: 104600,
}

# address, unit, type, beds, baths, sqft, built, parcel
HOMES = [
    ("18 Alder Court", "", "single_family", 3, "1.5", 1240, 1956, "R-0418-22"),
    ("42 Juniper Lane", "", "single_family", 2, "1.0", 980, 1949, "R-0552-07"),
    ("7 Heron Way", "", "townhouse", 3, "2.5", 1420, 2014, "R-1180-03"),
    ("1206 Willow Street", "Unit 3", "condo", 2, "1.0", 860, 2009, "C-2206-03"),
    ("55 Orchard Row", "", "single_family", 4, "2.0", 1610, 1972, "R-0731-15"),
    ("310 Cedar Street", "", "single_family", 3, "1.0", 1150, 1938, "R-0219-41"),
    ("91 Larkspur Drive", "", "townhouse", 2, "1.5", 1100, 2016, "R-1192-11"),
    ("23 Fernhill Road", "", "single_family", 3, "2.0", 1330, 1988, "R-0904-02"),
    ("640 River Road", "Unit B", "duplex", 2, "1.0", 920, 1961, "R-0611-19"),
    ("12 Quarry Lane", "", "manufactured", 3, "2.0", 1180, 2003, "R-1307-06"),
    ("5 Birch Terrace", "", "townhouse", 3, "2.5", 1390, 2024, "R-1450-01"),
    ("88 Meadow Lane", "", "single_family", 3, "1.5", 1210, 1964, "R-0377-28"),
]

# name, contact, co-owners, size, income, ami%, race, hispanic, female head, method
HOUSEHOLDS = {
    "Bennett": ("Bennett household", "Ruth Bennett", "", 2, "38400", "61.0", "white", False, True, "check"),
    "Rivera": (
        "Rivera household",
        "Ana Rivera",
        "Luis Rivera",
        4,
        "61200",
        "68.1",
        "white",
        True,
        False,
        "ach",
    ),
    "Okafor": (
        "Okafor household",
        "Chidi Okafor",
        "Ngozi Okafor",
        5,
        "54300",
        "71.2",
        "black",
        False,
        False,
        "ach",
    ),
    "Nguyen": ("Nguyen household", "Linh Nguyen", "", 3, "47900", "62.4", "asian", False, True, "ach"),
    "Halvorsen": (
        "Halvorsen household",
        "Kari Halvorsen",
        "Erik Halvorsen",
        2,
        "41800",
        "58.3",
        "white",
        False,
        False,
        "check",
    ),
    "Thompson": (
        "Thompson household",
        "Denise Thompson",
        "",
        3,
        "36900",
        "49.8",
        "black",
        False,
        True,
        "check",
    ),
    "Begay": (
        "Begay household",
        "Marcus Begay",
        "Tamsin Begay",
        4,
        "58800",
        "74.9",
        "aian",
        False,
        False,
        "ach",
    ),
    "Ahmed": (
        "Ahmed household",
        "Samira Ahmed",
        "Yusuf Ahmed",
        4,
        "63100",
        "77.6",
        "other_multi",
        False,
        False,
        "ach",
    ),
    "Delgado": (
        "Delgado household",
        "Rosa Delgado",
        "",
        2,
        "33200",
        "45.9",
        "white",
        True,
        True,
        "money_order",
    ),
    "Kowalski": (
        "Kowalski household",
        "Pete Kowalski",
        "Dana Kowalski",
        3,
        "44500",
        "66.0",
        "white",
        False,
        False,
        "check",
    ),
    "Park": (
        "Park household",
        "Jiwoo Park",
        "Min-jun Park",
        3,
        "70100",
        "79.2",
        "asian",
        False,
        False,
        "ach",
    ),
    "Whitfield": (
        "Whitfield household",
        "Gloria Whitfield",
        "",
        2,
        "45600",
        "63.7",
        "black",
        False,
        True,
        "check",
    ),
}


class Command(BaseCommand):
    help = "Load a fictional demo land trust (Riverbend Community Land Trust)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--with-users", action="store_true", help="Create demo staff and homeowner logins."
        )
        parser.add_argument(
            "--force", action="store_true", help="Load even if the database already has homes."
        )

    def handle(self, *args, with_users=False, force=False, **options):
        if Home.objects.exists() and not force:
            raise CommandError("This database already has homes. Use --force to add the demo data anyway.")
        self.rng = random.Random(2026)
        self.today = timezone.localdate()
        with transaction.atomic():
            self.build()
            if with_users:
                self.users()
        self.stdout.write(self.style.SUCCESS("Loaded Riverbend Community Land Trust demo data."))
        if with_users:
            self.stdout.write(f"  Staff:     staff / {DEMO_PASSWORD}")
            self.stdout.write(f"  Homeowner: ana.rivera@riverbendclt.example / {DEMO_PASSWORD}")

    # ------------------------------------------------------------------
    def build(self):
        org = Organization.current()
        org.name = "Riverbend Community Land Trust"
        org.short_name = "Riverbend CLT"
        org.address = "214 Mill Street, Riverbend, OR 97999"
        org.phone = "(541) 555-0142"
        org.email = "homes@riverbendclt.example"
        org.website = "https://riverbendclt.example"
        org.fiscal_year_start_month = 7
        org.default_monthly_lease_fee = D("40.00")
        org.grace_period_days = 15
        org.refinance_max_ltv_percent = D("90.00")
        org.occupancy_check_due_month = 3
        org.save()

        self.ami = IndexSeries.objects.create(
            name="HUD AMI — Riverbend metro, 4-person (demo values)",
            short_name="HUD AMI",
            kind=IndexSeries.Kind.AMI,
            source_url="https://www.huduser.gov/portal/datasets/il.html",
            notes="Illustrative values for the demo, not published HUD income limits.",
        )
        for year, value in AMI.items():
            if date(year, 4, 1) <= self.today:
                IndexValue.objects.create(series=self.ami, effective_date=date(year, 4, 1), value=D(value))

        self.shared = ResaleFormula.objects.create(
            name="Shared appreciation 25%",
            kind=ResaleFormula.Kind.APPRAISAL,
            owner_share_percent=D("25"),
            description="Ground lease §10.4. Homeowner receives the purchase price plus 25% of appraised "
            "appreciation and depreciated capital improvement credits, never more than market value.",
        )
        self.indexed = ResaleFormula.objects.create(
            name="AMI-indexed",
            kind=ResaleFormula.Kind.INDEXED,
            index_series=self.ami,
            description="Ground lease §10.4 (2016 form). Price follows HUD Area Median Income for a "
            "four-person household.",
        )
        self.fixed = ResaleFormula.objects.create(
            name="Fixed 2% compounding",
            kind=ResaleFormula.Kind.FIXED_RATE,
            annual_rate_percent=D("2.000"),
            compounding=ResaleFormula.Compounding.COMPOUND,
            protect_purchase_price=True,
            description="Ground lease §10.4 (2020 form) for townhomes in the Heron Way development.",
        )

        self.homes = {}
        for street, unit, kind, beds, baths, sqft, built, parcel in HOMES:
            self.homes[street] = Home.objects.create(
                address_line1=street,
                address_line2=unit,
                city="Riverbend",
                state="OR",
                postal_code="97999",
                parcel_id=parcel,
                home_type=kind,
                bedrooms=beds,
                bathrooms=D(baths),
                square_feet=sqft,
                year_built=built,
            )
        self.households = {}
        for key, (name, contact, co, size, income, ami, race, hisp, female, _method) in HOUSEHOLDS.items():
            slug = contact.lower().replace(" ", ".")
            self.households[key] = Household.objects.create(
                name=name,
                primary_contact=contact,
                co_owners=co,
                email=f"{slug}@riverbendclt.example",
                phone=f"(541) 555-{self.rng.randint(1000, 9999)}",
                household_size=size,
                annual_income_at_purchase=D(income),
                ami_percent_at_purchase=D(ami),
                race=race,
                hispanic=hisp,
                female_head_of_household=female,
            )

        # (home, household, formula, purchase date, price, appraised, fee, acquired, lease no.)
        plan = [
            (
                "42 Juniper Lane",
                "Okafor",
                self.shared,
                date(2013, 5, 17),
                "118000",
                "162000",
                "35",
                date(2012, 9, 4),
            ),
            (
                "7 Heron Way",
                "Nguyen",
                self.fixed,
                date(2020, 8, 28),
                "189000",
                "251000",
                "45",
                date(2019, 3, 12),
            ),
            (
                "1206 Willow Street",
                "Halvorsen",
                self.indexed,
                date(2016, 10, 3),
                "121500",
                "158000",
                "30",
                date(2016, 6, 1),
            ),
            (
                "55 Orchard Row",
                "Begay",
                self.shared,
                date(2015, 3, 20),
                "141000",
                "196000",
                "40",
                date(2014, 11, 18),
            ),
            (
                "310 Cedar Street",
                "Thompson",
                self.indexed,
                date(2017, 7, 14),
                "112000",
                "149000",
                "35",
                date(2011, 2, 9),
            ),
            (
                "91 Larkspur Drive",
                "Ahmed",
                self.fixed,
                date(2021, 4, 30),
                "198500",
                "262000",
                "45",
                date(2019, 3, 12),
            ),
            (
                "23 Fernhill Road",
                "Delgado",
                self.indexed,
                date(2018, 9, 7),
                "128000",
                "173500",
                "35",
                date(2018, 1, 22),
            ),
            (
                "640 River Road",
                "Kowalski",
                self.shared,
                date(2019, 6, 21),
                "104000",
                "151000",
                "30",
                date(2017, 8, 30),
            ),
            (
                "12 Quarry Lane",
                "Park",
                self.shared,
                date(2023, 2, 10),
                "96000",
                "138000",
                "30",
                date(2022, 5, 3),
            ),
            (
                "5 Birch Terrace",
                "Whitfield",
                self.fixed,
                date(2025, 9, 12),
                "214000",
                "289000",
                "45",
                date(2023, 4, 17),
            ),
        ]
        self.ownerships = {}
        for n, (street, key, formula, bought, price, appraised, fee, acquired) in enumerate(plan, start=1):
            home = self.homes[street]
            home.acquired_on = acquired
            home.save(update_fields=["acquired_on"])
            self.ownerships[key] = self.sell(
                home, key, formula, bought, price, appraised, fee, f"RCLT-{n + 100:03d}"
            )

        # The story home: first owner from 2012, resold in 2022.
        alder = self.homes["18 Alder Court"]
        alder.acquired_on = date(2011, 10, 3)
        alder.save(update_fields=["acquired_on"])
        Subsidy.objects.create(
            home=alder,
            source=Subsidy.Source.HOME,
            amount=D("35000"),
            funded_on=date(2012, 1, 18),
            program_name="Riverbend HOME homebuyer program",
            idis_activity_id="4471",
        )
        Subsidy.objects.create(
            home=alder,
            source=Subsidy.Source.PRIVATE,
            amount=D("9000"),
            funded_on=date(2012, 1, 18),
            program_name="Riverbend Community Foundation",
        )
        bennett = self.sell(
            alder, "Bennett", self.shared, date(2012, 4, 16), "132000", "176000", "35", "RCLT-001"
        )
        CapitalImprovement.objects.create(
            ownership=bennett,
            title="High-efficiency furnace",
            category=CapitalImprovement.Category.HVAC,
            requested_amount=D("6800"),
            contractor="Mill Creek Heating",
            completed_on=date(2016, 10, 21),
            status=CapitalImprovement.Status.APPROVED,
            approved_credit=D("6800"),
            useful_life_years=15,
            decided_on=date(2016, 11, 2),
            submitted_by_owner=True,
            created_at=self.at(date(2016, 10, 25)),
        )
        RefinanceRequest.objects.create(
            ownership=bennett,
            lender="Riverbend Community Credit Union",
            loan_amount=D("118500"),
            existing_balance=D("121300"),
            interest_rate=D("3.875"),
            term_years=30,
            purpose=RefinanceRequest.Purpose.RATE_TERM,
            status=RefinanceRequest.Status.APPROVED,
            formula_price_at_review=D("141250"),
            max_allowed_loan=D("127125"),
            decided_on=date(2015, 5, 12),
            created_at=self.at(date(2015, 4, 28)),
            submitted_by_owner=True,
        )
        self.history(bennett, until=date(2022, 6, 15))
        rivera_hh = self.households["Rivera"]
        sale_price = services.quote(bennett, date(2022, 6, 15), appraised_value=D("248000")).price
        resold = services.record_resale(
            bennett,
            sale_date=date(2022, 6, 15),
            sale_price=sale_price,
            appraised_value=D("248000"),
            appraiser="Cascade Valuation Group",
            buyer=rivera_hh,
            formula=self.shared,
            lease_number="RCLT-011",
            monthly_fee=D("40.00"),
            allow_above_formula=False,
        )
        self.ownerships["Rivera"] = resold.new_ownership

        # Vacant home in the pipeline, funded after the 2025 HOME rule took effect.
        meadow = self.homes["88 Meadow Lane"]
        meadow.acquired_on = self.today - timedelta(days=96)
        meadow.notes = (
            "Acquired from the city's scattered-site program. "
            "Rehab underway; marketing to buyers in the spring."
        )
        meadow.save()
        Subsidy.objects.create(
            home=meadow,
            source=Subsidy.Source.HOME,
            amount=D("52000"),
            funded_on=self.today - timedelta(days=110),
            program_name="Riverbend HOME homebuyer program",
            idis_activity_id="5203",
        )
        Appraisal.objects.create(
            home=meadow,
            effective_date=self.today - timedelta(days=90),
            value=D("296000"),
            purpose=Appraisal.Purpose.PORTFOLIO,
            appraiser="Cascade Valuation Group",
        )

        # More subsidy across the portfolio.
        Subsidy.objects.create(
            home=self.homes["42 Juniper Lane"],
            source=Subsidy.Source.HOME,
            amount=D("38000"),
            funded_on=date(2013, 3, 1),
            program_name="Riverbend HOME homebuyer program",
            idis_activity_id="4588",
        )
        Subsidy.objects.create(
            home=self.homes["310 Cedar Street"],
            source=Subsidy.Source.CDBG,
            amount=D("27500"),
            funded_on=date(2017, 5, 2),
            kind=Subsidy.Kind.DEVELOPMENT,
            program_name="Owner-occupied rehab",
        )
        Subsidy.objects.create(
            home=self.homes["7 Heron Way"],
            source=Subsidy.Source.STATE,
            amount=D("62000"),
            funded_on=date(2020, 6, 15),
            program_name="State homeownership development fund",
        )
        Subsidy.objects.create(
            home=self.homes["91 Larkspur Drive"],
            source=Subsidy.Source.STATE,
            amount=D("63500"),
            funded_on=date(2021, 3, 1),
            program_name="State homeownership development fund",
        )
        Subsidy.objects.create(
            home=self.homes["5 Birch Terrace"],
            source=Subsidy.Source.HOME,
            amount=D("45000"),
            funded_on=date(2025, 6, 2),
            program_name="Riverbend HOME homebuyer program",
            idis_activity_id="5117",
        )
        Subsidy.objects.create(
            home=self.homes["12 Quarry Lane"],
            source=Subsidy.Source.LOCAL,
            amount=D("42000"),
            funded_on=date(2022, 11, 1),
            program_name="City housing levy",
        )
        Subsidy.objects.create(
            home=self.homes["55 Orchard Row"],
            source=Subsidy.Source.HOME,
            amount=D("12500"),
            funded_on=date(2015, 1, 9),
            program_name="Riverbend HOME homebuyer program",
            idis_activity_id="4702",
        )

        for key, ownership in self.ownerships.items():
            if ownership.is_active:
                self.history(ownership, until=self.today, profile=key)

        self.portfolio_appraisals()
        self.improvements_and_requests()

    # ------------------------------------------------------------------
    def at(self, day: date, hour: int = 10) -> datetime:
        return timezone.make_aware(datetime.combine(day, time(hour, self.rng.randint(0, 59))))

    def sell(self, home, key, formula, bought, price, appraised, fee, lease_number):
        ownership = Ownership.objects.create(
            home=home,
            household=self.households[key],
            formula=formula,
            purchase_date=bought,
            purchase_price=D(price),
            initial_appraised_value=D(appraised),
        )
        GroundLease.objects.create(
            ownership=ownership,
            lease_number=lease_number,
            start_date=bought,
            monthly_fee=D(fee),
            recording_reference=f"Instr. {bought.year}-{self.rng.randint(10000, 99999)}",
            recorded_on=bought + timedelta(days=3),
        )
        Appraisal.objects.create(
            home=home,
            effective_date=bought - timedelta(days=21),
            value=D(appraised),
            purpose=Appraisal.Purpose.PURCHASE,
            appraiser="Cascade Valuation Group",
        )
        return ownership

    def history(self, ownership, *, until: date, profile: str = ""):
        """Lease fees and occupancy checks from purchase to ``until``."""
        lease = ownership.lease
        last_month = until.replace(day=1)
        generate_charges(months_in_range(ownership.purchase_date, last_month), leases=[lease])
        method = HOUSEHOLDS[ownership.household.name.split()[0]][-1]
        behind = {"Thompson": 3, "Kowalski": 5, "Delgado": 1}.get(profile, 0)
        charges = list(lease.charges.order_by("due_date"))
        cutoff = len(charges) - behind
        for i, charge in enumerate(charges):
            if i >= cutoff or charge.due_date > until:
                continue
            delay = self.rng.choice([0, 0, 0, 1, 2, 3, 5, 8, 12])
            if profile == "Thompson" and charge.due_date.year >= 2025:
                delay += 20
            received = min(charge.due_date + timedelta(days=delay), until)
            Payment.objects.create(
                lease=lease,
                amount=charge.amount,
                received_on=received,
                method=method if charge.due_date.year >= 2019 or method != "ach" else "check",
                status=Payment.Status.SUCCEEDED,
                reference=f"#{self.rng.randint(1000, 9999)}" if method in ("check", "money_order") else "",
            )
        if profile == "Rivera":
            latest = lease.payments.order_by("-received_on", "-pk").first()
            if latest is not None:
                latest.status = Payment.Status.PROCESSING
                latest.stripe_checkout_session_id = "cs_demo_processing"
                latest.save()
        # One small partial payment so the ledger shows partial status.
        if profile == "Kowalski":
            Payment.objects.create(
                lease=lease,
                amount=D("15.00"),
                received_on=until - timedelta(days=12),
                method=Payment.Method.CASH,
                status=Payment.Status.SUCCEEDED,
            )

        # Annual owner-occupancy checks.
        end_year = until.year
        for year in range(ownership.purchase_date.year + 1, end_year + 1):
            due = services.occupancy_due_date(year)
            check = OccupancyCheck(ownership=ownership, year=year, due_date=due)
            if due < until and (year < self.today.year or until < self.today):
                check.result = OccupancyCheck.Result.COMPLIANT
                check.method = self.rng.choice(
                    [OccupancyCheck.Method.SELF_CERTIFICATION] * 3 + [OccupancyCheck.Method.SITE_VISIT]
                )
                check.completed_on = due - timedelta(days=self.rng.randint(2, 40))
            elif year == self.today.year:
                if profile in ("Thompson",):
                    check.result = OccupancyCheck.Result.PENDING
                elif profile in ("Rivera", "Begay"):
                    check.result = OccupancyCheck.Result.SUBMITTED
                    check.method = OccupancyCheck.Method.SELF_CERTIFICATION
                    check.owner_signed_name = ownership.household.primary_contact
                    check.owner_submitted_at = self.at(due - timedelta(days=self.rng.randint(5, 20)))
                    check.owner_statement = "" if profile == "Begay" else "We're here year-round. Thanks!"
                else:
                    check.result = OccupancyCheck.Result.COMPLIANT
                    check.method = OccupancyCheck.Method.SELF_CERTIFICATION
                    check.completed_on = due - timedelta(days=self.rng.randint(2, 30))
            check.save()

    def portfolio_appraisals(self):
        values = {
            "18 Alder Court": "281000",
            "42 Juniper Lane": "268000",
            "7 Heron Way": "289000",
            "1206 Willow Street": "212000",
            "55 Orchard Row": "318000",
            "310 Cedar Street": "247000",
            "91 Larkspur Drive": "291000",
            "23 Fernhill Road": "259000",
            "640 River Road": "214000",
            "12 Quarry Lane": "171000",
        }
        when = date(2025, 9, 15) if date(2025, 9, 15) <= self.today else self.today
        for street, value in values.items():
            Appraisal.objects.create(
                home=self.homes[street],
                effective_date=when,
                value=D(value),
                purpose=Appraisal.Purpose.PORTFOLIO,
                appraiser="Cascade Valuation Group",
            )

    def improvements_and_requests(self):
        o = self.ownerships
        today = self.today
        CapitalImprovement.objects.create(
            ownership=o["Rivera"],
            title="Roof replacement",
            category=CapitalImprovement.Category.ROOF,
            requested_amount=D("14500"),
            contractor="Ridgeline Roofing",
            completed_on=date(2024, 5, 30),
            status=CapitalImprovement.Status.APPROVED,
            approved_credit=D("14500"),
            useful_life_years=25,
            decided_on=date(2024, 6, 11),
            submitted_by_owner=True,
            created_at=self.at(date(2024, 6, 3)),
        )
        CapitalImprovement.objects.create(
            ownership=o["Rivera"],
            title="Rooftop solar array",
            category=CapitalImprovement.Category.ENERGY,
            requested_amount=D("18200"),
            contractor="Sunbridge Solar",
            completed_on=today - timedelta(days=24),
            description="6.4 kW system with net metering. Invoice and city permit attached.",
            submitted_by_owner=True,
            created_at=self.at(today - timedelta(days=9)),
        )
        CapitalImprovement.objects.create(
            ownership=o["Okafor"],
            title="Basement bedroom egress window",
            category=CapitalImprovement.Category.ADDITION,
            requested_amount=D("9400"),
            completed_on=date(2019, 8, 14),
            status=CapitalImprovement.Status.APPROVED,
            approved_credit=D("8600"),
            useful_life_years=30,
            decided_on=date(2019, 9, 3),
            decision_notes="Credit excludes $800 of interior painting (maintenance).",
            created_at=self.at(date(2019, 8, 20)),
            submitted_by_owner=True,
        )
        CapitalImprovement.objects.create(
            ownership=o["Begay"],
            title="Kitchen remodel",
            category=CapitalImprovement.Category.KITCHEN,
            requested_amount=D("22800"),
            completed_on=date(2021, 3, 5),
            status=CapitalImprovement.Status.APPROVED,
            approved_credit=D("15000"),
            useful_life_years=20,
            decided_on=date(2021, 3, 22),
            decision_notes="Approved up to the $15,000 cap for kitchen remodels in our improvement policy.",
            created_at=self.at(date(2021, 3, 9)),
            submitted_by_owner=True,
        )
        CapitalImprovement.objects.create(
            ownership=o["Park"],
            title="Accessible entry ramp",
            category=CapitalImprovement.Category.ACCESSIBILITY,
            requested_amount=D("7400"),
            contractor="Able Access Builders",
            submitted_by_owner=True,
            description="Ramp and widened front door for our son's wheelchair. Work is scheduled next month.",
            created_at=self.at(today - timedelta(days=4)),
        )
        CapitalImprovement.objects.create(
            ownership=o["Halvorsen"],
            title="Hot tub",
            category=CapitalImprovement.Category.OTHER,
            requested_amount=D("6200"),
            completed_on=date(2022, 7, 1),
            status=CapitalImprovement.Status.DENIED,
            decided_on=date(2022, 7, 19),
            decision_notes="Luxury items aren't eligible under our improvement policy.",
            created_at=self.at(date(2022, 7, 6)),
            submitted_by_owner=True,
        )
        okafor = RefinanceRequest.objects.create(
            ownership=o["Okafor"],
            lender="Northfork Mortgage",
            loan_amount=D("146000"),
            existing_balance=D("88200"),
            interest_rate=D("6.250"),
            term_years=30,
            purpose=RefinanceRequest.Purpose.CASH_OUT,
            explanation="Consolidate a car loan and medical bills.",
            submitted_by_owner=True,
            created_at=self.at(today - timedelta(days=6)),
        )
        nguyen = RefinanceRequest.objects.create(
            ownership=o["Nguyen"],
            lender="Riverbend Community Credit Union",
            loan_amount=D("161000"),
            existing_balance=D("163900"),
            interest_rate=D("5.375"),
            term_years=25,
            purpose=RefinanceRequest.Purpose.RATE_TERM,
            submitted_by_owner=True,
            status=RefinanceRequest.Status.UNDER_REVIEW,
            created_at=self.at(today - timedelta(days=13)),
        )
        RefinanceRequest.objects.create(
            ownership=o["Begay"],
            lender="Cascade Federal",
            loan_amount=D("122000"),
            existing_balance=D("119400"),
            interest_rate=D("2.990"),
            term_years=30,
            purpose=RefinanceRequest.Purpose.RATE_TERM,
            status=RefinanceRequest.Status.APPROVED,
            decided_on=date(2021, 2, 8),
            submitted_by_owner=True,
            formula_price_at_review=D("163250"),
            max_allowed_loan=D("146925"),
            created_at=self.at(date(2021, 1, 25)),
        )
        for refi in (okafor, nguyen):
            services.evaluate_refinance(refi)

        # Late in the month, bill next month too so the demo looks current.
        if today.day >= 25:
            generate_charges([add_months(today.replace(day=1), 1)])
        LeaseCharge.objects.filter(
            lease__ownership__status=Ownership.Status.SOLD, due_date__gt=date(2022, 6, 15)
        ).delete()

    def users(self):
        user_model = get_user_model()
        staff, _ = user_model.objects.get_or_create(
            username="staff",
            defaults={
                "email": "staff@riverbendclt.example",
                "first_name": "Maya",
                "last_name": "Ellison",
                "is_staff": True,
                "is_superuser": True,
            },
        )
        staff.set_password(DEMO_PASSWORD)
        staff.save()
        owner, _ = user_model.objects.get_or_create(
            username="ana.rivera@riverbendclt.example",
            defaults={"email": "ana.rivera@riverbendclt.example", "first_name": "Ana", "last_name": "Rivera"},
        )
        owner.set_password(DEMO_PASSWORD)
        owner.save()
        rivera = self.households["Rivera"]
        rivera.portal_user = owner
        rivera.save(update_fields=["portal_user"])
