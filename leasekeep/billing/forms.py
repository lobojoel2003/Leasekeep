from decimal import Decimal

from django import forms
from django.utils import timezone

from leasekeep.homes.forms import DateInput

from .models import LeaseCharge, Payment


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ["amount", "received_on", "method", "reference", "notes"]
        widgets = {"received_on": DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Online methods are recorded by Stripe; staff record offline payments.
        self.fields["method"].choices = [
            c for c in Payment.Method.choices if c[0] not in (Payment.Method.CARD,)
        ]


class ChargeForm(forms.ModelForm):
    class Meta:
        model = LeaseCharge
        fields = ["kind", "amount", "due_date", "description"]
        widgets = {"due_date": DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kind"].choices = [
            c for c in LeaseCharge.Kind.choices if c[0] != LeaseCharge.Kind.LEASE_FEE
        ]
        self.fields["due_date"].initial = timezone.localdate()


class GenerateChargesForm(forms.Form):
    month = forms.DateField(
        widget=forms.DateInput(attrs={"type": "month"}, format="%Y-%m"),
        input_formats=["%Y-%m", "%Y-%m-%d"],
        help_text="Creates this month's lease fee for every active lease. Safe to run twice.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["month"].initial = timezone.localdate().replace(day=1)


class PortalPaymentForm(forms.Form):
    amount = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("1.00"),
        max_value=Decimal("10000.00"),
        widget=forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}),
    )
