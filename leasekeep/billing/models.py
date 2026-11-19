from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from leasekeep.homes.models import GroundLease

MONEY = {"max_digits": 10, "decimal_places": 2}


class LeaseCharge(models.Model):
    """A monthly ground lease fee (or other charge) billed to a lease."""

    class Kind(models.TextChoices):
        LEASE_FEE = "lease_fee", "Ground lease fee"
        LATE_FEE = "late_fee", "Late fee"
        ADJUSTMENT = "adjustment", "Adjustment"

    lease = models.ForeignKey(GroundLease, on_delete=models.CASCADE, related_name="charges")
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.LEASE_FEE)
    period = models.DateField(help_text="First day of the month this charge covers.")
    due_date = models.DateField()
    amount = models.DecimalField(**MONEY, validators=[MinValueValidator(Decimal("0.01"))])
    description = models.CharField(max_length=160, blank=True)
    waived = models.BooleanField(default=False)
    waived_reason = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["lease", "due_date", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["lease", "period"],
                condition=models.Q(kind="lease_fee"),
                name="one_lease_fee_per_month",
            )
        ]

    def __str__(self) -> str:
        return self.label

    @property
    def label(self) -> str:
        if self.description:
            return self.description
        if self.kind == self.Kind.LEASE_FEE:
            return f"Lease fee — {self.period:%B %Y}"
        return self.get_kind_display()


class Payment(models.Model):
    class Method(models.TextChoices):
        ACH = "ach", "Bank transfer (ACH)"
        CARD = "card", "Card"
        CHECK = "check", "Check"
        CASH = "cash", "Cash"
        MONEY_ORDER = "money_order", "Money order"
        PAYROLL = "payroll", "Payroll deduction / autopay"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing (bank transfer)"
        SUCCEEDED = "succeeded", "Received"
        FAILED = "failed", "Failed"
        REFUNDED = "refunded", "Refunded"

    lease = models.ForeignKey(GroundLease, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(**MONEY, validators=[MinValueValidator(Decimal("0.01"))])
    received_on = models.DateField(default=timezone.localdate)
    method = models.CharField(max_length=12, choices=Method.choices, default=Method.CHECK)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SUCCEEDED)
    reference = models.CharField(
        max_length=120, blank=True, help_text="Check number, confirmation code, etc."
    )
    stripe_checkout_session_id = models.CharField(max_length=255, blank=True, db_index=True)
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_on", "-pk"]

    def __str__(self) -> str:
        return f"${self.amount} on {self.received_on} ({self.get_status_display()})"

    @property
    def is_online(self) -> bool:
        return bool(self.stripe_checkout_session_id)


class StripeEvent(models.Model):
    """Webhook events already processed, so retries are idempotent."""

    event_id = models.CharField(max_length=255, unique=True)
    event_type = models.CharField(max_length=120)
    received_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.event_type} {self.event_id}"
