from django import forms

from leasekeep.homes.forms import DateInput
from leasekeep.homes.models import CapitalImprovement, RefinanceRequest


class OwnerImprovementForm(forms.ModelForm):
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
        widgets = {"completed_on": DateInput(), "description": forms.Textarea(attrs={"rows": 4})}
        labels = {
            "title": "What did you improve?",
            "requested_amount": "Cost of the work",
            "completed_on": "Date completed",
            "receipt": "Receipt or invoice",
        }
        help_texts = {
            "completed_on": "Leave blank if the work hasn't started yet. We can pre-approve it.",
            "receipt": "PDF or photo. You can also bring it to the office.",
        }


class OwnerCertificationForm(forms.Form):
    lives_here = forms.BooleanField(
        label="I confirm that this home is my primary residence and I have lived here for at least "
        "ten months of the past year.",
    )
    statement = forms.CharField(
        label="Anything we should know? (optional)",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    signed_name = forms.CharField(label="Type your full name to sign", max_length=160)


class OwnerRefinanceForm(forms.ModelForm):
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
        widgets = {"explanation": forms.Textarea(attrs={"rows": 4})}
        labels = {"explanation": "Tell us about the new loan"}
