from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Organization(models.Model):
    """The community land trust running this installation (a single row)."""

    name = models.CharField(max_length=200, default="Community Land Trust")
    short_name = models.CharField(
        max_length=40, blank=True, help_text="Used in the navigation bar, e.g. “Riverbend CLT”."
    )
    address = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)

    fiscal_year_start_month = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(12)],
        help_text="Month the fiscal year starts (1 = January, 7 = July). Used by board reports.",
    )
    default_monthly_lease_fee = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("35.00"))
    lease_fee_due_day = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(28)],
        help_text="Day of the month lease fees are due.",
    )
    grace_period_days = models.PositiveSmallIntegerField(
        default=15, help_text="Days after the due date before a fee counts as late."
    )
    refinance_max_ltv_percent = models.DecimalField(
        "Refinance maximum loan-to-formula-price (%)",
        max_digits=5,
        decimal_places=2,
        default=Decimal("90.00"),
        validators=[MinValueValidator(Decimal("1")), MaxValueValidator(Decimal("100"))],
        help_text="Largest mortgage the CLT will approve, as a percent of the current formula price.",
    )
    occupancy_check_due_month = models.PositiveSmallIntegerField(
        default=3,
        validators=[MinValueValidator(1), MaxValueValidator(12)],
        help_text="Month annual owner-occupancy certifications are due.",
    )
    portal_welcome = models.TextField(
        blank=True,
        help_text="Optional message shown at the top of every homeowner's portal page.",
    )

    class Meta:
        verbose_name = "organization settings"
        verbose_name_plural = "organization settings"

    def __str__(self) -> str:
        return self.name

    @property
    def display_name(self) -> str:
        return self.short_name or self.name

    @classmethod
    def current(cls) -> "Organization":
        org = cls.objects.order_by("pk").first()
        if org is None:
            org = cls.objects.create()
        return org
