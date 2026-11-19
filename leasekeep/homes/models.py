from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

MONEY = {"max_digits": 12, "decimal_places": 2}
POSITIVE = [MinValueValidator(Decimal("0.01"))]
NON_NEGATIVE = [MinValueValidator(Decimal("0"))]
UPLOAD_TYPES = FileExtensionValidator(["pdf", "png", "jpg", "jpeg", "heic", "webp", "doc", "docx"])


def validate_upload_size(file) -> None:
    limit = settings.LEASEKEEP_MAX_UPLOAD_MB * 1024 * 1024
    if file.size > limit:
        raise ValidationError(f"Files must be {settings.LEASEKEEP_MAX_UPLOAD_MB} MB or smaller.")


class Home(models.Model):
    class HomeType(models.TextChoices):
        SINGLE_FAMILY = "single_family", "Single-family house"
        TOWNHOUSE = "townhouse", "Townhouse"
        CONDO = "condo", "Condominium"
        DUPLEX = "duplex", "Duplex unit"
        MANUFACTURED = "manufactured", "Manufactured home"
        COOP = "coop", "Limited-equity co-op unit"

    class Tenure(models.TextChoices):
        GROUND_LEASE = "ground_lease", "Ground lease (CLT owns the land)"
        DEED_RESTRICTED = "deed_restricted", "Deed-restricted (covenant)"

    address_line1 = models.CharField("Street address", max_length=200)
    address_line2 = models.CharField("Unit / apt.", max_length=100, blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2, help_text="Two-letter state code.")
    postal_code = models.CharField("ZIP code", max_length=10)
    parcel_id = models.CharField("Parcel ID", max_length=60, blank=True)
    home_type = models.CharField(max_length=20, choices=HomeType.choices, default=HomeType.SINGLE_FAMILY)
    tenure = models.CharField(max_length=20, choices=Tenure.choices, default=Tenure.GROUND_LEASE)
    bedrooms = models.PositiveSmallIntegerField(default=2)
    bathrooms = models.DecimalField(max_digits=3, decimal_places=1, default=Decimal("1.0"))
    square_feet = models.PositiveIntegerField(null=True, blank=True)
    year_built = models.PositiveSmallIntegerField(null=True, blank=True)
    acquired_on = models.DateField("Date the CLT acquired the land", null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["address_line1", "address_line2"]

    def __str__(self) -> str:
        return self.street

    def get_absolute_url(self) -> str:
        return reverse("homes:detail", args=[self.pk])

    @property
    def street(self) -> str:
        return f"{self.address_line1}, {self.address_line2}" if self.address_line2 else self.address_line1

    @property
    def full_address(self) -> str:
        return f"{self.street}, {self.city}, {self.state} {self.postal_code}"

    @property
    def current_ownership(self) -> Ownership | None:
        cached = getattr(self, "_current_ownership", None)
        if cached is not None:
            return cached
        ownership = (
            self.ownerships.filter(status=Ownership.Status.ACTIVE)
            .select_related("household", "formula", "formula__index_series")
            .order_by("-purchase_date")
            .first()
        )
        self._current_ownership = ownership
        return ownership

    def latest_appraisal(self, on: date | None = None) -> Appraisal | None:
        qs = self.appraisals.all()
        if on is not None:
            qs = qs.filter(effective_date__lte=on)
        return qs.order_by("-effective_date", "-pk").first()

    @property
    def status_label(self) -> str:
        return "Occupied" if self.current_ownership else "Vacant / in resale"


class Household(models.Model):
    class Race(models.TextChoices):
        # HUD IDIS beneficiary race categories.
        WHITE = "white", "White"
        BLACK = "black", "Black/African American"
        ASIAN = "asian", "Asian"
        AIAN = "aian", "American Indian/Alaskan Native"
        NHPI = "nhpi", "Native Hawaiian/Other Pacific Islander"
        AIAN_WHITE = "aian_white", "American Indian/Alaskan Native & White"
        ASIAN_WHITE = "asian_white", "Asian & White"
        BLACK_WHITE = "black_white", "Black/African American & White"
        AIAN_BLACK = "aian_black", "American Indian/Alaskan Native & Black/African American"
        OTHER_MULTI = "other_multi", "Other multi-racial"
        NOT_REPORTED = "not_reported", "Not reported"

    name = models.CharField(
        max_length=160, help_text="How staff refer to the household, e.g. “Rivera household”."
    )
    primary_contact = models.CharField(max_length=120)
    co_owners = models.CharField(max_length=255, blank=True, help_text="Other people on title.")
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    mailing_address = models.CharField(
        max_length=255, blank=True, help_text="Only if different from the home's address."
    )
    household_size = models.PositiveSmallIntegerField(default=1)
    annual_income_at_purchase = models.DecimalField(**MONEY, null=True, blank=True, validators=NON_NEGATIVE)
    ami_percent_at_purchase = models.DecimalField(
        "Income as % of AMI at purchase",
        max_digits=5,
        decimal_places=1,
        null=True,
        blank=True,
        validators=NON_NEGATIVE,
    )
    race = models.CharField(max_length=20, choices=Race.choices, default=Race.NOT_REPORTED)
    hispanic = models.BooleanField("Hispanic or Latino", null=True, blank=True)
    female_head_of_household = models.BooleanField(null=True, blank=True)
    portal_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="household",
        help_text="Login used by this household for the owner portal.",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("homes:household_detail", args=[self.pk])

    @property
    def income_category(self) -> str:
        """HUD income band used in HOME/CDBG reporting."""
        pct = self.ami_percent_at_purchase
        if pct is None:
            return "Not reported"
        if pct <= 30:
            return "0–30% AMI"
        if pct <= 50:
            return "31–50% AMI"
        if pct <= 60:
            return "51–60% AMI"
        if pct <= 80:
            return "61–80% AMI"
        return "Over 80% AMI"

    @property
    def active_ownership(self) -> Ownership | None:
        return (
            self.ownerships.filter(status=Ownership.Status.ACTIVE)
            .select_related("home", "formula")
            .order_by("-purchase_date")
            .first()
        )


class Ownership(models.Model):
    """One household's tenure in one home, from purchase to resale."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SOLD = "sold", "Sold (resale complete)"
        TERMINATED = "terminated", "Terminated"

    home = models.ForeignKey(Home, on_delete=models.PROTECT, related_name="ownerships")
    household = models.ForeignKey(Household, on_delete=models.PROTECT, related_name="ownerships")
    formula = models.ForeignKey("formulas.ResaleFormula", on_delete=models.PROTECT, related_name="ownerships")
    purchase_date = models.DateField()
    purchase_price = models.DecimalField(**MONEY, validators=POSITIVE)
    initial_appraised_value = models.DecimalField(
        "Appraised market value at purchase",
        **MONEY,
        null=True,
        blank=True,
        validators=POSITIVE,
        help_text="Unrestricted market value. Required for appraisal-based formulas.",
    )
    index_value_at_purchase = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        null=True,
        blank=True,
        validators=POSITIVE,
        help_text="Leave blank to look it up from the formula's index series.",
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    sale_date = models.DateField(null=True, blank=True)
    sale_price = models.DecimalField(**MONEY, null=True, blank=True, validators=POSITIVE)
    formula_price_at_sale = models.DecimalField(**MONEY, null=True, blank=True)
    appraised_value_at_sale = models.DecimalField(**MONEY, null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-purchase_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["home"],
                condition=models.Q(status="active"),
                name="one_active_ownership_per_home",
            )
        ]

    def __str__(self) -> str:
        return f"{self.household} at {self.home}"

    def get_absolute_url(self) -> str:
        return reverse("homes:formula", args=[self.pk])

    def clean(self) -> None:
        if self.sale_date and self.sale_date < self.purchase_date:
            raise ValidationError({"sale_date": "Sale date can't be before the purchase date."})

    @property
    def is_active(self) -> bool:
        return self.status == self.Status.ACTIVE

    @property
    def lease_or_none(self) -> GroundLease | None:
        try:
            return self.lease
        except GroundLease.DoesNotExist:
            return None

    @property
    def years_owned(self) -> Decimal:
        from leasekeep.formulas.engine import years_between

        end = self.sale_date or timezone.localdate()
        return years_between(self.purchase_date, end)


class GroundLease(models.Model):
    ownership = models.OneToOneField(Ownership, on_delete=models.CASCADE, related_name="lease")
    lease_number = models.CharField(max_length=40, unique=True)
    start_date = models.DateField()
    term_years = models.PositiveSmallIntegerField(default=99)
    monthly_fee = models.DecimalField(
        "Monthly ground lease fee", max_digits=8, decimal_places=2, validators=NON_NEGATIVE
    )
    recording_reference = models.CharField(
        max_length=80, blank=True, help_text="Book/page or instrument number at the registry."
    )
    recorded_on = models.DateField(null=True, blank=True)
    document = models.FileField(
        upload_to="leases/%Y/",
        blank=True,
        validators=[UPLOAD_TYPES, validate_upload_size],
        help_text="Signed lease (PDF).",
    )
    ended_on = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["lease_number"]

    def __str__(self) -> str:
        return f"Lease {self.lease_number}"

    def get_absolute_url(self) -> str:
        return reverse("billing:ledger", args=[self.pk])

    @property
    def home(self) -> Home:
        return self.ownership.home

    @property
    def household(self) -> Household:
        return self.ownership.household

    @property
    def expires_on(self) -> date:
        start = self.start_date
        try:
            return start.replace(year=start.year + self.term_years)
        except ValueError:  # 29 February
            return start.replace(year=start.year + self.term_years, day=28)

    @property
    def is_active(self) -> bool:
        return self.ended_on is None and self.ownership.is_active


class Appraisal(models.Model):
    class Purpose(models.TextChoices):
        PURCHASE = "purchase", "At purchase"
        RESALE = "resale", "For resale"
        REFINANCE = "refinance", "For refinance"
        PORTFOLIO = "portfolio", "Portfolio review"
        ASSESSMENT = "assessment", "Tax assessment"

    home = models.ForeignKey(Home, on_delete=models.CASCADE, related_name="appraisals")
    effective_date = models.DateField()
    value = models.DecimalField(**MONEY, validators=POSITIVE)
    purpose = models.CharField(max_length=12, choices=Purpose.choices, default=Purpose.PORTFOLIO)
    appraiser = models.CharField(max_length=160, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-effective_date"]

    def __str__(self) -> str:
        return f"{self.home} appraised {self.effective_date}"


class CapitalImprovement(models.Model):
    class Category(models.TextChoices):
        ROOF = "roof", "Roof"
        HVAC = "hvac", "Heating / cooling"
        ENERGY = "energy", "Energy efficiency / solar"
        KITCHEN = "kitchen", "Kitchen"
        BATH = "bath", "Bathroom"
        ACCESSIBILITY = "accessibility", "Accessibility"
        ADDITION = "addition", "Addition / finished space"
        STRUCTURAL = "structural", "Foundation / structural"
        WINDOWS = "windows", "Windows / doors"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        APPROVED = "approved", "Approved"
        DENIED = "denied", "Denied"
        WITHDRAWN = "withdrawn", "Withdrawn"

    ownership = models.ForeignKey(Ownership, on_delete=models.CASCADE, related_name="improvements")
    title = models.CharField(max_length=160)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)
    description = models.TextField(blank=True)
    contractor = models.CharField(max_length=160, blank=True)
    requested_amount = models.DecimalField(**MONEY, validators=POSITIVE)
    completed_on = models.DateField(null=True, blank=True)
    receipt = models.FileField(
        upload_to="improvements/%Y/",
        blank=True,
        validators=[UPLOAD_TYPES, validate_upload_size],
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.REQUESTED)
    approved_credit = models.DecimalField(**MONEY, null=True, blank=True, validators=NON_NEGATIVE)
    useful_life_years = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Credit depreciates to zero over this many years. Leave blank for full credit.",
    )
    decided_on = models.DateField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    decision_notes = models.TextField(blank=True)
    submitted_by_owner = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self) -> str:
        return reverse("homes:improvement_review", args=[self.pk])

    @property
    def is_credited(self) -> bool:
        return (
            self.status == self.Status.APPROVED
            and self.approved_credit is not None
            and self.completed_on is not None
        )


class OccupancyCheck(models.Model):
    class Method(models.TextChoices):
        SELF_CERTIFICATION = "self_certification", "Owner self-certification"
        SITE_VISIT = "site_visit", "Site visit"
        DOCUMENT_REVIEW = "document_review", "Document review (ID, tax return)"
        UTILITY_RECORDS = "utility_records", "Utility / mail records"

    class Result(models.TextChoices):
        PENDING = "pending", "Pending"
        SUBMITTED = "submitted", "Owner submitted, awaiting review"
        COMPLIANT = "compliant", "Owner-occupied"
        NON_COMPLIANT = "non_compliant", "Not owner-occupied"
        WAIVED = "waived", "Waived (approved absence)"

    ownership = models.ForeignKey(Ownership, on_delete=models.CASCADE, related_name="occupancy_checks")
    year = models.PositiveSmallIntegerField()
    due_date = models.DateField()
    result = models.CharField(max_length=16, choices=Result.choices, default=Result.PENDING)
    method = models.CharField(max_length=20, choices=Method.choices, blank=True)
    completed_on = models.DateField(null=True, blank=True)
    owner_statement = models.TextField(blank=True)
    owner_signed_name = models.CharField(max_length=160, blank=True)
    owner_submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-year", "ownership__home__address_line1"]
        constraints = [models.UniqueConstraint(fields=["ownership", "year"], name="one_check_per_year")]

    def __str__(self) -> str:
        return f"{self.year} occupancy check — {self.ownership.home}"

    @property
    def is_open(self) -> bool:
        return self.result in {self.Result.PENDING, self.Result.SUBMITTED}

    @property
    def is_overdue(self) -> bool:
        return self.result == self.Result.PENDING and self.due_date < timezone.localdate()


class RefinanceRequest(models.Model):
    class Purpose(models.TextChoices):
        RATE_TERM = "rate_term", "Lower rate or change term"
        CASH_OUT = "cash_out", "Cash-out"
        IMPROVEMENT = "improvement", "Finance home improvements"
        DEBT = "debt", "Debt consolidation"
        HELOC = "heloc", "Home equity line of credit"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        UNDER_REVIEW = "under_review", "Under review"
        APPROVED = "approved", "Approved"
        APPROVED_WITH_CONDITIONS = "conditional", "Approved with conditions"
        DENIED = "denied", "Denied"
        WITHDRAWN = "withdrawn", "Withdrawn"

    OPEN_STATUSES = (Status.SUBMITTED, Status.UNDER_REVIEW)

    ownership = models.ForeignKey(Ownership, on_delete=models.CASCADE, related_name="refinances")
    lender = models.CharField(max_length=160)
    loan_amount = models.DecimalField("New loan amount", **MONEY, validators=POSITIVE)
    existing_balance = models.DecimalField(
        "Current mortgage balance", **MONEY, null=True, blank=True, validators=NON_NEGATIVE
    )
    interest_rate = models.DecimalField(
        "Interest rate (%)", max_digits=5, decimal_places=3, null=True, blank=True
    )
    term_years = models.PositiveSmallIntegerField(null=True, blank=True)
    purpose = models.CharField(max_length=12, choices=Purpose.choices, default=Purpose.RATE_TERM)
    explanation = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SUBMITTED)
    formula_price_at_review = models.DecimalField(**MONEY, null=True, blank=True)
    max_allowed_loan = models.DecimalField(**MONEY, null=True, blank=True)
    conditions = models.TextField(blank=True)
    decided_on = models.DateField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    submitted_by_owner = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Refinance with {self.lender} — {self.ownership.home}"

    def get_absolute_url(self) -> str:
        return reverse("homes:refinance_review", args=[self.pk])

    @property
    def is_open(self) -> bool:
        return self.status in self.OPEN_STATUSES

    @property
    def cash_out(self) -> Decimal | None:
        if self.existing_balance is None:
            return None
        return self.loan_amount - self.existing_balance

    @property
    def ltv_percent(self) -> Decimal | None:
        if not self.formula_price_at_review:
            return None
        return (self.loan_amount / self.formula_price_at_review * 100).quantize(Decimal("0.1"))

    @property
    def within_policy(self) -> bool | None:
        if self.max_allowed_loan is None:
            return None
        return self.loan_amount <= self.max_allowed_loan


HOME_RULE_2025_EFFECTIVE = date(2025, 4, 20)
HOME_THRESHOLDS_2025 = (Decimal("25000"), Decimal("50000"))
HOME_THRESHOLDS_PRIOR = (Decimal("15000"), Decimal("40000"))


class Subsidy(models.Model):
    class Source(models.TextChoices):
        HOME = "home", "HUD HOME"
        CDBG = "cdbg", "HUD CDBG"
        HTF = "htf", "National Housing Trust Fund"
        STATE = "state", "State housing funds"
        LOCAL = "local", "City / county funds"
        PRIVATE = "private", "Private / philanthropic"
        OTHER = "other", "Other"

    class Kind(models.TextChoices):
        RETAINED = "retained", "Subsidy retained in the home (stays for future buyers)"
        BUYER = "buyer", "Direct buyer assistance"
        DEVELOPMENT = "development", "Development / rehab subsidy"

    home = models.ForeignKey(Home, on_delete=models.CASCADE, related_name="subsidies")
    source = models.CharField(max_length=10, choices=Source.choices)
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.RETAINED)
    program_name = models.CharField(max_length=160, blank=True)
    amount = models.DecimalField(**MONEY, validators=POSITIVE)
    funded_on = models.DateField(
        "Committed / funded on",
        help_text="For HOME funds, the commitment date decides which affordability rule applies.",
    )
    idis_activity_id = models.CharField("IDIS activity ID", max_length=40, blank=True)
    affordability_years_override = models.PositiveSmallIntegerField(
        "Affordability period (years)",
        null=True,
        blank=True,
        help_text="Leave blank to use the HOME minimum (24 CFR 92.254) or none for other sources. "
        "Enter a value if your written agreement requires a longer period.",
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-funded_on"]
        verbose_name_plural = "subsidies"

    def __str__(self) -> str:
        return f"{self.get_source_display()} — {self.home}"

    @property
    def affordability_years(self) -> int | None:
        """Minimum HOME homeownership affordability period, 24 CFR 92.254(a)(4).

        The 2025 HOME final rule raised the per-unit thresholds for funds committed
        on or after its effective date (April 20, 2025): under $25,000 → 5 years,
        $25,000–$50,000 → 10 years, over $50,000 → 15 years. Earlier commitments
        keep the prior thresholds ($15,000 and $40,000).
        """
        if self.affordability_years_override:
            return self.affordability_years_override
        if self.source != self.Source.HOME:
            return None
        low, high = (
            HOME_THRESHOLDS_2025 if self.funded_on >= HOME_RULE_2025_EFFECTIVE else HOME_THRESHOLDS_PRIOR
        )
        if self.amount < low:
            return 5
        if self.amount <= high:
            return 10
        return 15

    @property
    def affordability_ends_on(self) -> date | None:
        years = self.affordability_years
        if years is None:
            return None
        start = self.funded_on
        try:
            return start.replace(year=start.year + years)
        except ValueError:
            return start.replace(year=start.year + years, day=28)
