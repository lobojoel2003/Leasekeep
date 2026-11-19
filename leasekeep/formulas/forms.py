from django import forms

from leasekeep.homes.forms import DateInput

from .models import IndexSeries, IndexValue, ResaleFormula


class ResaleFormulaForm(forms.ModelForm):
    class Meta:
        model = ResaleFormula
        fields = [
            "name",
            "kind",
            "owner_share_percent",
            "scale_by_purchase_ratio",
            "index_series",
            "annual_rate_percent",
            "compounding",
            "prorate_partial_years",
            "include_improvements",
            "improvement_depreciation",
            "protect_purchase_price",
            "cap_at_appraised_value",
            "rounding",
            "is_active",
            "description",
        ]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class IndexSeriesForm(forms.ModelForm):
    source_url = forms.URLField(label="Source URL", required=False, assume_scheme="https")

    class Meta:
        model = IndexSeries
        fields = ["name", "short_name", "kind", "source_url", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}


class IndexValueForm(forms.ModelForm):
    class Meta:
        model = IndexValue
        fields = ["effective_date", "value", "note"]
        widgets = {"effective_date": DateInput()}

    def __init__(self, *args, series: IndexSeries, **kwargs):
        super().__init__(*args, **kwargs)
        self.series = series

    def clean_effective_date(self):
        value = self.cleaned_data["effective_date"]
        if self.series.values.filter(effective_date=value).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("This series already has a value for that date.")
        return value


class PreviewForm(forms.Form):
    """Try a formula against hypothetical numbers, without saving anything."""

    purchase_price = forms.DecimalField(max_digits=12, decimal_places=2, min_value=1, initial=150000)
    purchase_date = forms.DateField(widget=DateInput())
    valuation_date = forms.DateField(widget=DateInput())
    initial_appraised_value = forms.DecimalField(
        label="Appraised value at purchase", max_digits=12, decimal_places=2, min_value=1, required=False
    )
    current_appraised_value = forms.DecimalField(
        label="Appraised value now", max_digits=12, decimal_places=2, min_value=1, required=False
    )
    index_at_purchase = forms.DecimalField(max_digits=14, decimal_places=4, min_value=0.0001, required=False)
    index_at_valuation = forms.DecimalField(
        label="Index now", max_digits=14, decimal_places=4, min_value=0.0001, required=False
    )
    improvement_credit = forms.DecimalField(
        label="Improvement credit", max_digits=12, decimal_places=2, min_value=0, required=False
    )
