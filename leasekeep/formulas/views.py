from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from leasekeep.core.auth import staff_required
from leasekeep.homes.models import Ownership

from . import engine
from .forms import IndexSeriesForm, IndexValueForm, PreviewForm, ResaleFormulaForm
from .models import IndexSeries, ResaleFormula


@staff_required
def formula_list(request):
    formulas = ResaleFormula.objects.select_related("index_series").annotate(
        active_homes=Count("ownerships", filter=Q(ownerships__status=Ownership.Status.ACTIVE))
    )
    return render(
        request,
        "formulas/formula_list.html",
        {"formulas": formulas, "series": IndexSeries.objects.annotate(n=Count("values"))},
    )


@staff_required
def formula_detail(request, pk):
    formula = get_object_or_404(ResaleFormula.objects.select_related("index_series"), pk=pk)
    today = timezone.localdate()
    initial = {
        "purchase_price": Decimal("150000"),
        "purchase_date": date(today.year - 10, today.month, 1),
        "valuation_date": today,
        "initial_appraised_value": Decimal("200000"),
        "current_appraised_value": Decimal("280000"),
    }
    if formula.index_series_id:
        then = formula.index_series.value_on(initial["purchase_date"])
        now = formula.index_series.value_on(today)
        initial["index_at_purchase"] = then.value if then else None
        initial["index_at_valuation"] = now.value if now else None
    form = PreviewForm(request.GET or None, initial=initial)
    data = form.cleaned_data if form.is_valid() else dict(initial)
    result, error = None, ""
    try:
        improvements = ()
        if data.get("improvement_credit"):
            improvements = (
                engine.ImprovementCredit("Improvements", data["improvement_credit"], data["purchase_date"]),
            )
        result = engine.calculate(
            formula.to_config(),
            engine.FormulaInputs(
                purchase_price=data["purchase_price"],
                purchase_date=data["purchase_date"],
                valuation_date=data["valuation_date"],
                initial_appraised_value=data.get("initial_appraised_value"),
                current_appraised_value=data.get("current_appraised_value"),
                index_at_purchase=data.get("index_at_purchase"),
                index_at_valuation=data.get("index_at_valuation"),
                improvements=improvements,
            ),
        )
    except (engine.FormulaError, KeyError, TypeError) as exc:
        error = str(exc) if isinstance(exc, engine.FormulaError) else "Fill in every field to preview."
    ownerships = formula.ownerships.filter(status=Ownership.Status.ACTIVE).select_related("home", "household")
    return render(
        request,
        "formulas/formula_detail.html",
        {"formula": formula, "form": form, "result": result, "error": error, "ownerships": ownerships},
    )


@staff_required
def formula_create(request):
    form = ResaleFormulaForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        formula = form.save()
        messages.success(request, f"Formula “{formula}” created.")
        return redirect(formula)
    return render(request, "formulas/formula_form.html", {"form": form, "title": "New resale formula"})


@staff_required
def formula_edit(request, pk):
    formula = get_object_or_404(ResaleFormula, pk=pk)
    in_use = formula.ownerships.exists()
    form = ResaleFormulaForm(request.POST or None, instance=formula)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Formula saved.")
        return redirect(formula)
    return render(
        request,
        "formulas/formula_form.html",
        {"form": form, "title": f"Edit {formula}", "formula": formula, "in_use": in_use},
    )


@staff_required
def series_create(request):
    form = IndexSeriesForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        series = form.save()
        messages.success(request, f"Index “{series}” created. Add its published values next.")
        return redirect("formulas:series", pk=series.pk)
    return render(
        request,
        "homes/form.html",
        {"form": form, "title": "New index series", "back": reverse("formulas:list")},
    )


@staff_required
def series_detail(request, pk):
    series = get_object_or_404(IndexSeries, pk=pk)
    form = IndexValueForm(request.POST or None, series=series)
    if request.method == "POST" and form.is_valid():
        value = form.save(commit=False)
        value.series = series
        value.save()
        messages.success(
            request, f"Added {series.short_name} value for {engine.long_date(value.effective_date)}."
        )
        return redirect("formulas:series", pk=series.pk)
    values = list(series.values.order_by("effective_date"))
    rows = []
    for i, v in enumerate(values):
        prev = values[i - 1] if i else None
        change = ((v.value / prev.value - 1) * 100).quantize(Decimal("0.1")) if prev else None
        rows.append((v, change))
    rows.reverse()
    return render(
        request,
        "formulas/series_detail.html",
        {"series": series, "rows": rows, "form": form, "formulas": series.formulas.all()},
    )
