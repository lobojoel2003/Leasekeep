from datetime import date
from decimal import Decimal, InvalidOperation

from django import template
from django.utils.html import format_html

from leasekeep.formulas import engine

register = template.Library()


@register.filter
def money(value, places: int = 2):
    """$1,234.56 — accepts Decimal, int, float or numeric strings."""
    if value is None or value == "":
        return "—"
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return value
    if int(places) == 0:
        amount = amount.quantize(Decimal("1"))
        sign = "−" if amount < 0 else ""
        return f"{sign}${abs(amount):,.0f}"
    return engine.money(amount)


@register.filter
def pct(value, places: int = 0):
    if value is None or value == "":
        return "—"
    return f"{Decimal(str(value)):.{int(places)}f}%"


@register.filter
def longdate(value):
    if not value:
        return "—"
    if not isinstance(value, date):
        return value
    return engine.long_date(value)


@register.simple_tag
def icon(name, size=""):
    css = f"icon icon--{size}" if size else "icon"
    return format_html('<svg class="{}" aria-hidden="true"><use href="#i-{}"></use></svg>', css, name)


@register.simple_tag
def status_pill(label, tone="neutral"):
    return format_html('<span class="pill pill--{}">{}</span>', tone, label)


@register.filter
def get_item(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def percent_of(part, whole):
    try:
        part, whole = Decimal(str(part)), Decimal(str(whole))
    except (InvalidOperation, ValueError):
        return 0
    if whole == 0:
        return 0
    return int(max(Decimal(0), min(Decimal(100), part / whole * 100)))
