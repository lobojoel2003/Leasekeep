from django.contrib import admin
from django.db import models

from .models import IndexSeries, IndexValue, ResaleFormula


class IndexValueInline(admin.TabularInline):
    model = IndexValue
    extra = 1


@admin.register(IndexSeries)
class IndexSeriesAdmin(admin.ModelAdmin):
    formfield_overrides = {models.URLField: {"assume_scheme": "https"}}
    list_display = ["name", "short_name", "kind"]
    inlines = [IndexValueInline]


@admin.register(ResaleFormula)
class ResaleFormulaAdmin(admin.ModelAdmin):
    list_display = ["name", "kind", "parameter_label", "is_active"]
    list_filter = ["kind", "is_active"]
    readonly_fields = ["summary"]
