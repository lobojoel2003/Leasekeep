"""Resale formula engine.

This module is deliberately free of Django so it can be unit tested (and
audited) on its own. Every calculation returns the resulting price *and* the
ordered list of steps used to reach it, so the math can be shown to staff,
board members and homeowners exactly as it was computed.

Three families of formula are supported, matching the ones community land
trusts use in practice:

* **Appraisal-based** (shared appreciation): the purchase price plus a fixed
  share of the change in appraised market value between purchase and resale.
* **Indexed**: the purchase price multiplied by the change in an index,
  usually HUD Area Median Income (AMI) or the Consumer Price Index.
* **Fixed-rate**: the purchase price grown by a fixed annual percentage,
  either simple or compounded.

Any formula can add credits for approved capital improvements (optionally
depreciated straight-line over a useful life) and can be capped at the
current appraised value, so a formula price never exceeds the market.

Money is always :class:`decimal.Decimal`. Every money amount shown in a step is
rounded to the cent *before* it is used in the next step, so the visible
worksheet can be reproduced line by line with a calculator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext
from enum import StrEnum

CENT = Decimal("0.01")
ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")


class FormulaKind(StrEnum):
    APPRAISAL = "appraisal"
    INDEXED = "indexed"
    FIXED_RATE = "fixed_rate"


class Compounding(StrEnum):
    SIMPLE = "simple"
    COMPOUND = "compound"


class Rounding(StrEnum):
    CENT = "cent"
    DOLLAR = "dollar"
    HUNDRED = "hundred"


class Depreciation(StrEnum):
    NONE = "none"
    STRAIGHT_LINE = "straight_line"


class FormulaError(ValueError):
    """Raised when a formula cannot be evaluated with the inputs given."""


@dataclass(frozen=True)
class FormulaConfig:
    """How a CLT's resale formula is defined.

    Percentages are stored as fractions: ``owner_share=Decimal("0.25")`` means
    the homeowner keeps 25% of appreciation; ``annual_rate=Decimal("0.02")``
    means 2% a year.
    """

    kind: FormulaKind
    #: Appraisal-based: the homeowner's share of market appreciation (0–1).
    owner_share: Decimal = Decimal("0.25")
    #: Appraisal-based: apply the share only to the part of the initial value the
    #: homeowner paid for, i.e. multiply by purchase price ÷ initial appraisal.
    #: (Champlain Housing Trust single-family homes, CPAH and others do this.)
    scale_by_purchase_ratio: bool = False
    #: Fixed-rate: annual increase (0–1).
    annual_rate: Decimal = ZERO
    #: Fixed-rate: simple or compound growth.
    compounding: Compounding = Compounding.COMPOUND
    #: Count partial years by complete months. If False, only whole years count.
    prorate_partial_years: bool = True
    #: Indexed: a human name for the index, shown in the math ("HUD AMI").
    index_name: str = "Index"
    #: Never let the base price fall below what the homeowner paid.
    protect_purchase_price: bool = False
    #: Cap the final price at the current appraised value when one is known.
    cap_at_appraised_value: bool = True
    #: Add approved capital improvement credits.
    include_improvements: bool = True
    #: How improvement credits lose value over time.
    depreciation: Depreciation = Depreciation.STRAIGHT_LINE
    #: Rounding applied to the final price.
    rounding: Rounding = Rounding.DOLLAR

    def __post_init__(self) -> None:
        if not ZERO <= self.owner_share <= ONE:
            raise FormulaError("Owner share of appreciation must be between 0% and 100%.")
        if not ZERO <= self.annual_rate <= Decimal("0.25"):
            raise FormulaError("Annual rate must be between 0% and 25%.")


@dataclass(frozen=True)
class ImprovementCredit:
    """An approved capital improvement credit."""

    description: str
    amount: Decimal
    completed_on: date
    useful_life_years: int | None = None


@dataclass(frozen=True)
class FormulaInputs:
    """Facts about one ownership needed to price a resale."""

    purchase_price: Decimal
    purchase_date: date
    valuation_date: date
    initial_appraised_value: Decimal | None = None
    current_appraised_value: Decimal | None = None
    index_at_purchase: Decimal | None = None
    index_at_valuation: Decimal | None = None
    improvements: tuple[ImprovementCredit, ...] = ()


@dataclass(frozen=True)
class Step:
    """One line of the visible worksheet."""

    label: str
    expression: str
    value: Decimal
    #: How to display ``value``: ``money``, ``factor``, ``years`` or ``percent``.
    unit: str = "money"
    note: str = ""
    #: Emphasise this line (subtotals and the final price).
    total: bool = False

    @property
    def display_value(self) -> str:
        if self.unit == "money":
            return money(self.value)
        if self.unit == "factor":
            return f"× {self.value:.6f}"
        if self.unit == "years":
            return f"{self.value:.2f} yrs"
        if self.unit == "percent":
            return percent(self.value)
        return str(self.value)


@dataclass(frozen=True)
class FormulaResult:
    price: Decimal
    base_price: Decimal
    improvement_credit: Decimal
    uncapped_price: Decimal
    capped: bool
    years_held: Decimal
    steps: tuple[Step, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def owner_gain(self) -> Decimal:
        """How much more the homeowner receives than they paid, before costs."""
        return self.price - self.steps[0].value


# ---------------------------------------------------------------------------
# Formatting helpers (kept here so the engine's worksheet is self-contained)
# ---------------------------------------------------------------------------


def to_cents(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def money(value: Decimal) -> str:
    value = to_cents(value)
    sign = "−" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def percent(fraction: Decimal) -> str:
    pct = (fraction * HUNDRED).normalize()
    text = f"{pct:f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return f"{text}%"


def long_date(value: date) -> str:
    return f"{value:%b} {value.day}, {value.year}"


def complete_months(start: date, end: date) -> int:
    """Complete calendar months from ``start`` to ``end``."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(months, 0)


def years_between(start: date, end: date, *, prorate: bool = True) -> Decimal:
    """Years elapsed, counting partial years by complete months when ``prorate``."""
    months = complete_months(start, end)
    if not prorate:
        return Decimal(months // 12)
    with localcontext() as ctx:
        ctx.prec = 28
        return Decimal(months) / Decimal(12)


def apply_rounding(value: Decimal, rounding: Rounding) -> Decimal:
    if rounding == Rounding.CENT:
        return to_cents(value)
    if rounding == Rounding.DOLLAR:
        return value.quantize(ONE, rounding=ROUND_HALF_UP).quantize(CENT)
    return ((value / HUNDRED).quantize(ONE, rounding=ROUND_HALF_UP) * HUNDRED).quantize(CENT)


ROUNDING_LABELS = {
    Rounding.CENT: "nearest cent",
    Rounding.DOLLAR: "nearest dollar",
    Rounding.HUNDRED: "nearest $100",
}


# ---------------------------------------------------------------------------
# The calculation
# ---------------------------------------------------------------------------


def calculate(config: FormulaConfig, inputs: FormulaInputs) -> FormulaResult:
    """Price a resale under ``config`` and return the price with its worksheet."""
    _validate(inputs)
    steps: list[Step] = []
    warnings: list[str] = []

    purchase_price = to_cents(inputs.purchase_price)
    years = years_between(inputs.purchase_date, inputs.valuation_date, prorate=config.prorate_partial_years)
    steps.append(
        Step(
            "Purchase price",
            f"Paid by the homeowner on {long_date(inputs.purchase_date)}",
            purchase_price,
        )
    )

    if config.kind == FormulaKind.APPRAISAL:
        base = _appraisal_base(config, inputs, purchase_price, steps)
    elif config.kind == FormulaKind.INDEXED:
        base = _indexed_base(config, inputs, purchase_price, steps)
    elif config.kind == FormulaKind.FIXED_RATE:
        base = _fixed_rate_base(config, inputs, purchase_price, years, steps)
    else:  # pragma: no cover - guarded by the enum
        raise FormulaError(f"Unknown formula kind: {config.kind}")

    if config.protect_purchase_price and base < purchase_price:
        steps.append(
            Step(
                "Purchase price protection",
                f"Base price may not fall below the {money(purchase_price)} purchase price",
                purchase_price,
                total=True,
            )
        )
        base = purchase_price

    improvement_credit = ZERO
    if config.include_improvements:
        improvement_credit = _improvement_credits(config, inputs, steps, warnings)

    uncapped = to_cents(base + improvement_credit)
    if config.include_improvements and inputs.improvements:
        steps.append(
            Step(
                "Formula price before cap",
                f"{money(base)} base price + {money(improvement_credit)} improvement credits",
                uncapped,
                total=True,
            )
        )

    price = uncapped
    capped = False
    if config.cap_at_appraised_value:
        appraisal = inputs.current_appraised_value
        if appraisal is None:
            warnings.append("No current appraisal on file, so the market-value cap was not applied.")
        elif uncapped > appraisal:
            capped = True
            price = to_cents(appraisal)
            steps.append(
                Step(
                    "Capped at appraised value",
                    f"Lesser of {money(uncapped)} formula price and "
                    f"{money(appraisal)} current appraised value",
                    price,
                    total=True,
                )
            )

    final = apply_rounding(price, config.rounding)
    steps.append(
        Step(
            "Formula price",
            f"{money(price)} rounded to the {ROUNDING_LABELS[config.rounding]}",
            final,
            total=True,
        )
    )

    return FormulaResult(
        price=final,
        base_price=base,
        improvement_credit=improvement_credit,
        uncapped_price=uncapped,
        capped=capped,
        years_held=years,
        steps=tuple(steps),
        warnings=tuple(warnings),
    )


def _validate(inputs: FormulaInputs) -> None:
    if inputs.purchase_price <= 0:
        raise FormulaError("Purchase price must be greater than zero.")
    if inputs.valuation_date < inputs.purchase_date:
        raise FormulaError("The valuation date cannot be before the purchase date.")
    for name in ("initial_appraised_value", "current_appraised_value"):
        value = getattr(inputs, name)
        if value is not None and value <= 0:
            raise FormulaError(f"{name.replace('_', ' ').capitalize()} must be greater than zero.")
    for name in ("index_at_purchase", "index_at_valuation"):
        value = getattr(inputs, name)
        if value is not None and value <= 0:
            raise FormulaError(f"{name.replace('_', ' ').capitalize()} must be greater than zero.")


def _appraisal_base(
    config: FormulaConfig, inputs: FormulaInputs, purchase_price: Decimal, steps: list[Step]
) -> Decimal:
    if inputs.initial_appraised_value is None:
        raise FormulaError(
            "An appraisal-based formula needs the appraised value at purchase. "
            "Add it to the ownership record."
        )
    if inputs.current_appraised_value is None:
        raise FormulaError(
            "An appraisal-based formula needs a current appraisal. "
            "Record an appraisal or enter a value to price this home."
        )
    initial = to_cents(inputs.initial_appraised_value)
    current = to_cents(inputs.current_appraised_value)
    appreciation = current - initial
    steps.append(
        Step(
            "Change in appraised value",
            f"{money(current)} current appraisal − {money(initial)} appraisal at purchase",
            appreciation,
        )
    )
    if config.scale_by_purchase_ratio:
        with localcontext() as ctx:
            ctx.prec = 28
            ratio = purchase_price / initial
            share = to_cents(appreciation * config.owner_share * purchase_price / initial)
        steps.append(
            Step(
                "Homeowner's share of the initial value",
                f"{money(purchase_price)} purchase price ÷ {money(initial)} appraisal at purchase",
                ratio,
                unit="factor",
            )
        )
        expr = (
            f"{money(appreciation)} × {percent(config.owner_share)} × "
            f"({money(purchase_price)} ÷ {money(initial)})"
        )
    else:
        share = to_cents(appreciation * config.owner_share)
        expr = f"{money(appreciation)} × {percent(config.owner_share)}"
    steps.append(
        Step(
            "Homeowner's share of the change",
            expr,
            share,
            note="The rest of the change stays with the home to keep it affordable.",
        )
    )
    base = purchase_price + share
    steps.append(
        Step(
            "Base formula price",
            f"{money(purchase_price)} + {money(share)}",
            base,
            total=True,
        )
    )
    return base


def _indexed_base(
    config: FormulaConfig, inputs: FormulaInputs, purchase_price: Decimal, steps: list[Step]
) -> Decimal:
    if inputs.index_at_purchase is None or inputs.index_at_valuation is None:
        raise FormulaError(
            f"An indexed formula needs {config.index_name} values for the purchase date "
            "and the valuation date. Add them under Formulas → Indexes."
        )
    then = inputs.index_at_purchase
    now = inputs.index_at_valuation
    with localcontext() as ctx:
        ctx.prec = 28
        factor = now / then
        base = to_cents(purchase_price * now / then)
    steps.append(
        Step(
            f"Change in {config.index_name}",
            f"{_index(now)} now ÷ {_index(then)} at purchase",
            factor,
            unit="factor",
        )
    )
    steps.append(
        Step(
            "Base formula price",
            f"{money(purchase_price)} × {_index(now)} ÷ {_index(then)}",
            base,
            total=True,
        )
    )
    return base


def _fixed_rate_base(
    config: FormulaConfig,
    inputs: FormulaInputs,
    purchase_price: Decimal,
    years: Decimal,
    steps: list[Step],
) -> Decimal:
    months = complete_months(inputs.purchase_date, inputs.valuation_date)
    if config.prorate_partial_years:
        years_expr = f"{months} complete months ÷ 12"
    else:
        years_expr = f"{months} complete months, whole years only"
    steps.append(
        Step(
            "Time owned",
            f"{long_date(inputs.purchase_date)} → {long_date(inputs.valuation_date)} ({years_expr})",
            years,
            unit="years",
        )
    )
    rate = config.annual_rate
    with localcontext() as ctx:
        ctx.prec = 28
        if config.compounding == Compounding.COMPOUND:
            factor = (ONE + rate) ** years
            expr = f"(1 + {percent(rate)}) ^ {years:.4f}"
        else:
            factor = ONE + rate * years
            expr = f"1 + {percent(rate)} × {years:.4f}"
        base = to_cents(purchase_price * factor)
    steps.append(
        Step(
            "Growth factor",
            f"{expr} ({config.compounding.value} growth at {percent(rate)} a year)",
            factor,
            unit="factor",
        )
    )
    steps.append(
        Step(
            "Base formula price",
            f"{money(purchase_price)} × {factor:.6f}",
            base,
            total=True,
        )
    )
    return base


def _improvement_credits(
    config: FormulaConfig, inputs: FormulaInputs, steps: list[Step], warnings: list[str]
) -> Decimal:
    total = ZERO
    for item in sorted(inputs.improvements, key=lambda i: i.completed_on):
        amount = to_cents(item.amount)
        label = f"Improvement credit: {item.description}"
        if item.completed_on > inputs.valuation_date:
            warnings.append(
                f"“{item.description}” was completed after the valuation date and is not credited."
            )
            continue
        if (
            config.depreciation == Depreciation.STRAIGHT_LINE
            and item.useful_life_years
            and item.useful_life_years > 0
        ):
            age = years_between(item.completed_on, inputs.valuation_date, prorate=True)
            life = Decimal(item.useful_life_years)
            with localcontext() as ctx:
                ctx.prec = 28
                remaining = max(ZERO, ONE - age / life)
                credit = to_cents(amount * remaining)
            expr = f"{money(amount)} × (1 − {age:.2f} yrs ÷ {item.useful_life_years} yr useful life)"
            if remaining == ZERO:
                expr = f"{money(amount)} fully depreciated after {item.useful_life_years} years"
        else:
            credit = amount
            expr = f"{money(amount)} approved credit, completed {long_date(item.completed_on)}"
        steps.append(Step(label, expr, credit))
        total += credit
    return to_cents(total)


def _index(value: Decimal) -> str:
    """Format an index value: currency-like values get commas, others stay as-is."""
    if value >= 1000:
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return f"{value.normalize():f}"


def describe(config: FormulaConfig) -> str:
    """One plain-language sentence describing the formula, for owners and boards."""
    if config.kind == FormulaKind.APPRAISAL:
        portion = " their proportional part of" if config.scale_by_purchase_ratio else ""
        core = (
            f"The homeowner receives what they paid plus {percent(config.owner_share)} of"
            f"{portion} any change in the home's appraised value"
        )
    elif config.kind == FormulaKind.INDEXED:
        core = (
            f"The price the homeowner paid rises or falls with the {config.index_name} "
            "between purchase and resale"
        )
    else:
        how = "compounded" if config.compounding == Compounding.COMPOUND else "simple"
        core = f"The price the homeowner paid grows by {percent(config.annual_rate)} a year ({how})"
    parts = [core]
    if config.include_improvements:
        if config.depreciation == Depreciation.STRAIGHT_LINE:
            parts.append("plus credit for approved improvements, depreciated over their useful life")
        else:
            parts.append("plus credit for approved improvements")
    sentence = ", ".join(parts)
    if config.protect_purchase_price:
        sentence += ". It never falls below the original purchase price"
    if config.cap_at_appraised_value:
        sentence += ". It never exceeds the current appraised value"
    return sentence + "."
