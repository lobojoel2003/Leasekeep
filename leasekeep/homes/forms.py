from __future__ import annotations

from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm
from django.utils import timezone

from leasekeep.core.models import Organization
from leasekeep.formulas.models import ResaleFormula

from .models import (
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


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, attrs=None, format="%Y-%m-%d"):
        super().__init__(attrs=attrs, format=format)


def date_widgets(*names: str) -> dict[str, forms.Widget]:
    return {name: DateInput() for name in names}


def money_field(label: str, *, required: bool = True, help_text: str = "") -> forms.DecimalField:
    return forms.DecimalField(
        label=label,
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
        required=required,
        help_text=help_text,
        widget=forms.NumberInput(attrs={"step": "0.01", "inputmode": "decimal"}),
    )


class HomeForm(forms.ModelForm):
    class Meta:
        model = Home
        fields = [
            "address_line1",
            "address_line2",
            "city",
            "state",
            "postal_code",
            "parcel_id",
            "home_type",
            "tenure",
            "bedrooms",
            "bathrooms",
            "square_feet",
            "year_built",
            "acquired_on",
            "notes",
        ]
        widgets = {**date_widgets("acquired_on"), "notes": forms.Textarea(attrs={"rows": 3})}

    def clean_state(self):
        return self.cleaned_data["state"].upper()


class HouseholdForm(forms.ModelForm):
    class Meta:
        model = Household
        fields = [
            "name",
            "primary_contact",
            "co_owners",
            "email",
            "phone",
            "mailing_address",
            "household_size",
            "annual_income_at_purchase",
            "ami_percent_at_purchase",
            "race",
            "hispanic",
            "female_head_of_household",
            "notes",
        ]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class OwnershipForm(forms.ModelForm):
    """A household buying a home from the CLT, with its ground lease."""

    lease_number = forms.CharField(max_length=40)
    monthly_fee = forms.DecimalField(
        label="Monthly ground lease fee", max_digits=8, decimal_places=2, min_value=Decimal("0")
    )
    term_years = forms.IntegerField(initial=99, min_value=1, max_value=199)
    recording_reference = forms.CharField(max_length=80, required=False)
    lease_document = forms.FileField(required=False, help_text="Signed lease (PDF), optional.")

    class Meta:
        model = Ownership
        fields = [
            "household",
            "formula",
            "purchase_date",
            "purchase_price",
            "initial_appraised_value",
            "index_value_at_purchase",
            "notes",
        ]
        widgets = {**date_widgets("purchase_date"), "notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, home: Home, **kwargs):
        super().__init__(*args, **kwargs)
        self.home = home
        self.fields["formula"].queryset = ResaleFormula.objects.filter(is_active=True)
        self.fields["monthly_fee"].initial = Organization.current().default_monthly_lease_fee
        self.fields["purchase_date"].initial = timezone.localdate()

    def clean(self):
        data = super().clean()
        if self.home.current_ownership is not None:
            raise forms.ValidationError("This home already has an active ownership. Record a resale instead.")
        formula = data.get("formula")
        if formula and formula.kind == "appraisal" and not data.get("initial_appraised_value"):
            self.add_error(
                "initial_appraised_value", "Appraisal-based formulas need the market value at purchase."
            )
        number = data.get("lease_number")
        if number and GroundLease.objects.filter(lease_number=number).exists():
            self.add_error("lease_number", "Another lease already uses this number.")
        return data


class AppraisalForm(forms.ModelForm):
    class Meta:
        model = Appraisal
        fields = ["effective_date", "value", "purpose", "appraiser", "notes"]
        widgets = {**date_widgets("effective_date"), "notes": forms.Textarea(attrs={"rows": 2})}


class SubsidyForm(forms.ModelForm):
    class Meta:
        model = Subsidy
        fields = [
            "source",
            "kind",
            "program_name",
            "amount",
            "funded_on",
            "idis_activity_id",
            "affordability_years_override",
            "notes",
        ]
        widgets = {**date_widgets("funded_on"), "notes": forms.Textarea(attrs={"rows": 2})}


class ImprovementForm(forms.ModelForm):
    """Staff entering an improvement on a homeowner's behalf."""

    class Meta:
        model = CapitalImprovement
        fields = [
            "title",
            "category",
            "description",
            "contractor",
            "requested_amount",
            "completed_on",
            "receipt",
        ]
        widgets = {**date_widgets("completed_on"), "description": forms.Textarea(attrs={"rows": 3})}


class ImprovementDecisionForm(forms.ModelForm):
    decision = forms.ChoiceField(
        choices=[
            (CapitalImprovement.Status.APPROVED, "Approve"),
            (CapitalImprovement.Status.DENIED, "Deny"),
            (CapitalImprovement.Status.REQUESTED, "Keep open"),
        ],
        widget=forms.RadioSelect,
    )

    class Meta:
        model = CapitalImprovement
        fields = ["approved_credit", "useful_life_years", "completed_on", "decision_notes"]
        widgets = {**date_widgets("completed_on"), "decision_notes": forms.Textarea(attrs={"rows": 3})}
        labels = {"decision_notes": "Notes to the homeowner"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["decision"].initial = self.instance.status
        if self.instance.approved_credit is None:
            self.fields["approved_credit"].initial = self.instance.requested_amount

    def clean(self):
        data = super().clean()
        if data.get("decision") == CapitalImprovement.Status.APPROVED:
            if data.get("approved_credit") is None:
                self.add_error("approved_credit", "Enter the credit to approve.")
            if not data.get("completed_on"):
                self.add_error(
                    "completed_on", "Credits count once the work is complete. Enter the completion date."
                )
        return data


class OccupancyRecordForm(forms.ModelForm):
    class Meta:
        model = OccupancyCheck
        fields = ["result", "method", "completed_on", "notes"]
        widgets = {**date_widgets("completed_on"), "notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.completed_on:
            self.fields["completed_on"].initial = timezone.localdate()

    def clean(self):
        data = super().clean()
        result = data.get("result")
        closed = {
            OccupancyCheck.Result.COMPLIANT,
            OccupancyCheck.Result.NON_COMPLIANT,
            OccupancyCheck.Result.WAIVED,
        }
        if result in closed and not data.get("completed_on"):
            self.add_error("completed_on", "Enter the date this check was completed.")
        if result in (OccupancyCheck.Result.COMPLIANT, OccupancyCheck.Result.NON_COMPLIANT) and not data.get(
            "method"
        ):
            self.add_error("method", "How was occupancy verified?")
        return data


class RefinanceForm(forms.ModelForm):
    class Meta:
        model = RefinanceRequest
        fields = [
            "lender",
            "loan_amount",
            "existing_balance",
            "interest_rate",
            "term_years",
            "purpose",
            "explanation",
        ]
        widgets = {"explanation": forms.Textarea(attrs={"rows": 3})}


class RefinanceDecisionForm(forms.ModelForm):
    class Meta:
        model = RefinanceRequest
        fields = ["status", "conditions"]
        widgets = {"conditions": forms.Textarea(attrs={"rows": 3})}
        labels = {"conditions": "Conditions or reasons (shared with the homeowner)"}


class ResaleForm(forms.Form):
    sale_date = forms.DateField(widget=DateInput())
    appraised_value = money_field("Appraised market value at sale")
    appraiser = forms.CharField(max_length=160, required=False)
    sale_price = money_field("Sale price", help_text="Normally the formula price, or less.")
    buyer = forms.ModelChoiceField(
        queryset=Household.objects.none(),
        label="Buying household",
        help_text="Add the household first if it isn't listed.",
    )
    formula = forms.ModelChoiceField(
        queryset=ResaleFormula.objects.filter(is_active=True), label="Buyer's resale formula"
    )
    lease_number = forms.CharField(max_length=40, label="New lease number")
    monthly_fee = forms.DecimalField(
        max_digits=8, decimal_places=2, min_value=Decimal("0"), label="Buyer's monthly lease fee"
    )
    allow_above_formula = forms.BooleanField(
        required=False,
        label="The board approved a price above the formula price",
    )
    notes = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)

    def __init__(self, *args, ownership: Ownership, **kwargs):
        super().__init__(*args, **kwargs)
        self.ownership = ownership
        self.fields["buyer"].queryset = Household.objects.exclude(pk=ownership.household_id).exclude(
            ownerships__status=Ownership.Status.ACTIVE
        )
        self.fields["formula"].initial = ownership.formula_id
        lease = ownership.lease_or_none
        self.fields["monthly_fee"].initial = (
            lease.monthly_fee if lease else Organization.current().default_monthly_lease_fee
        )
        self.fields["sale_date"].initial = timezone.localdate()

    def clean_lease_number(self):
        number = self.cleaned_data["lease_number"]
        if GroundLease.objects.filter(lease_number=number).exists():
            raise forms.ValidationError("Another lease already uses this number.")
        return number


class WhatIfForm(forms.Form):
    on = forms.DateField(label="Valuation date", required=False, widget=DateInput())
    appraised_value = forms.DecimalField(
        label="Appraised value",
        required=False,
        min_value=Decimal("1"),
        max_digits=12,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"step": "1000", "placeholder": "Use appraisal on file"}),
    )
    index_value = forms.DecimalField(
        label="Index value",
        required=False,
        min_value=Decimal("0.0001"),
        max_digits=14,
        decimal_places=4,
        widget=forms.NumberInput(attrs={"step": "any", "placeholder": "Use index on file"}),
    )


class PortalInviteForm(forms.Form):
    email = forms.EmailField(help_text="We'll email a link to set a password.")

    def __init__(self, *args, household: Household, **kwargs):
        super().__init__(*args, **kwargs)
        self.household = household
        self.fields["email"].initial = household.email

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        user_model = get_user_model()
        existing = user_model.objects.filter(email__iexact=email).first()
        if existing is not None:
            linked = getattr(existing, "household", None)
            if existing.is_staff or (linked is not None and linked.pk != self.household.pk):
                raise forms.ValidationError("That email already belongs to another account.")
        return email


class PortalInviteResetForm(PasswordResetForm):
    """Password-reset email that also reaches invited users who have no password yet."""

    def get_users(self, email):
        return get_user_model()._default_manager.filter(email__iexact=email, is_active=True)
