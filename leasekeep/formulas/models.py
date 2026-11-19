from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse

from . import engine


class IndexSeries(models.Model):
    """A published index used by indexed formulas, e.g. HUD AMI for a metro area."""

    class Kind(models.TextChoices):
        AMI = "ami", "Area Median Income (HUD)"
        CPI = "cpi", "Consumer Price Index"
        OTHER = "other", "Other index"

    name = models.CharField(max_length=160, unique=True)
    short_name = models.CharField(
        max_length=40, help_text="Shown in the formula math, e.g. “HUD AMI” or “CPI-U”."
    )
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.AMI)
    source_url = models.URLField(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "index series"
        verbose_name_plural = "index series"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def value_on(self, on: date) -> IndexValue | None:
        """The value in effect on ``on``: the latest published on or before that date."""
        return self.values.filter(effective_date__lte=on).order_by("-effective_date").first()


class IndexValue(models.Model):
    series = models.ForeignKey(IndexSeries, on_delete=models.CASCADE, related_name="values")
    effective_date = models.DateField()
    value = models.DecimalField(
        max_digits=14, decimal_places=4, validators=[MinValueValidator(Decimal("0.0001"))]
    )
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["series", "-effective_date"]
        constraints = [
            models.UniqueConstraint(fields=["series", "effective_date"], name="unique_index_value_per_date")
        ]

    def __str__(self) -> str:
        return f"{self.series.short_name} {self.effective_date:%Y-%m-%d}: {self.value.normalize():f}"


class ResaleFormula(models.Model):
    """A CLT's resale formula, configurable without code changes."""

    class Kind(models.TextChoices):
        APPRAISAL = "appraisal", "Appraisal-based (shared appreciation)"
        INDEXED = "indexed", "Indexed (AMI or CPI)"
        FIXED_RATE = "fixed_rate", "Fixed rate"

    class Compounding(models.TextChoices):
        COMPOUND = "compound", "Compound"
        SIMPLE = "simple", "Simple"

    class Rounding(models.TextChoices):
        DOLLAR = "dollar", "Nearest dollar"
        CENT = "cent", "Nearest cent"
        HUNDRED = "hundred", "Nearest $100"

    class Depreciation(models.TextChoices):
        STRAIGHT_LINE = "straight_line", "Straight-line over useful life"
        NONE = "none", "No depreciation (full credit)"

    name = models.CharField(max_length=120, unique=True)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    description = models.TextField(
        blank=True, help_text="Internal notes, e.g. the ground lease section this implements."
    )

    owner_share_percent = models.DecimalField(
        "Homeowner share of appreciation (%)",
        max_digits=5,
        decimal_places=2,
        default=Decimal("25.00"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
        help_text="Appraisal-based formulas only.",
    )
    scale_by_purchase_ratio = models.BooleanField(
        "Scale by purchase price ÷ initial appraisal",
        default=False,
        help_text="Appraisal-based only. Apply the share only to the part of the home's value the "
        "homeowner paid for (e.g. Champlain Housing Trust single-family homes).",
    )
    index_series = models.ForeignKey(
        IndexSeries,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="formulas",
        help_text="Indexed formulas only.",
    )
    annual_rate_percent = models.DecimalField(
        "Annual rate (%)",
        max_digits=5,
        decimal_places=3,
        default=Decimal("2.000"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("25"))],
        help_text="Fixed-rate formulas only.",
    )
    compounding = models.CharField(max_length=10, choices=Compounding.choices, default=Compounding.COMPOUND)
    prorate_partial_years = models.BooleanField(
        default=True, help_text="Count partial years by complete months (fixed-rate formulas)."
    )
    protect_purchase_price = models.BooleanField(
        default=False, help_text="Never let the base price fall below the original purchase price."
    )
    cap_at_appraised_value = models.BooleanField(
        default=True, help_text="Never let the formula price exceed the current appraised value."
    )
    include_improvements = models.BooleanField("Credit capital improvements", default=True)
    improvement_depreciation = models.CharField(
        max_length=20,
        choices=Depreciation.choices,
        default=Depreciation.STRAIGHT_LINE,
    )
    rounding = models.CharField(max_length=10, choices=Rounding.choices, default=Rounding.DOLLAR)
    is_active = models.BooleanField(
        default=True, help_text="Inactive formulas stay on existing homes but can't be assigned."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "resale formula"

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("formulas:detail", args=[self.pk])

    def clean(self) -> None:
        if self.kind == engine.FormulaKind.INDEXED and self.index_series_id is None:
            raise ValidationError({"index_series": "Choose the index this formula follows."})

    def to_config(self) -> engine.FormulaConfig:
        return engine.FormulaConfig(
            kind=engine.FormulaKind(self.kind),
            owner_share=self.owner_share_percent / 100,
            scale_by_purchase_ratio=self.scale_by_purchase_ratio,
            annual_rate=self.annual_rate_percent / 100,
            compounding=engine.Compounding(self.compounding),
            prorate_partial_years=self.prorate_partial_years,
            index_name=self.index_series.short_name if self.index_series_id else "Index",
            protect_purchase_price=self.protect_purchase_price,
            cap_at_appraised_value=self.cap_at_appraised_value,
            include_improvements=self.include_improvements,
            depreciation=engine.Depreciation(self.improvement_depreciation),
            rounding=engine.Rounding(self.rounding),
        )

    @property
    def summary(self) -> str:
        return engine.describe(self.to_config())

    @property
    def parameter_label(self) -> str:
        if self.kind == engine.FormulaKind.APPRAISAL:
            return f"{engine.percent(self.owner_share_percent / 100)} of appreciation"
        if self.kind == engine.FormulaKind.INDEXED:
            return f"Follows {self.index_series.short_name if self.index_series_id else 'index'}"
        return f"{engine.percent(self.annual_rate_percent / 100)}/yr {self.get_compounding_display().lower()}"
