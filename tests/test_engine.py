"""Unit tests for the resale formula engine.

The first group of tests reproduces worked examples published by community land
trusts, HUD and evaluators. Each test cites its source. Where a publication
rounds an intermediate figure differently from Leasekeep, the test asserts
Leasekeep's exact result and says how the published figure was rounded.
"""

from datetime import date
from decimal import Decimal as D

import pytest

from leasekeep.formulas import engine
from leasekeep.formulas.engine import (
    Compounding,
    Depreciation,
    FormulaConfig,
    FormulaError,
    FormulaInputs,
    FormulaKind,
    ImprovementCredit,
    Rounding,
    calculate,
)


def appraisal(share="0.25", **kw):
    return FormulaConfig(kind=FormulaKind.APPRAISAL, owner_share=D(share), **kw)


def indexed(**kw):
    return FormulaConfig(kind=FormulaKind.INDEXED, index_name="HUD AMI", **kw)


def fixed(rate, compounding=Compounding.COMPOUND, **kw):
    return FormulaConfig(kind=FormulaKind.FIXED_RATE, annual_rate=D(rate), compounding=compounding, **kw)


# ---------------------------------------------------------------------------
# Published examples: appraisal-based (shared appreciation) formulas
# ---------------------------------------------------------------------------


def test_hud_homefires_appraisal_based_example():
    """HUD HOMEfires Vol. 15 No. 1 (Jan 2020), “Appraisal-Based Resale Formulas”.

    “Fair Return on Investment: $75,000 x .25 = $18,750
     Resale Price: $150,000 + $18,750 = $168,750”
    HUD notes that no separate improvement credit is added because the resale
    appraisal already reflects improvements.
    """
    result = calculate(
        appraisal(include_improvements=False),
        FormulaInputs(
            purchase_price=D("150000"),
            purchase_date=date(2010, 1, 1),
            valuation_date=date(2020, 1, 1),
            initial_appraised_value=D("200000"),
            current_appraised_value=D("275000"),
        ),
    )
    assert result.price == D("168750.00")
    labels = {s.label: s.value for s in result.steps}
    assert labels["Change in appraised value"] == D("75000.00")
    assert labels["Homeowner's share of the change"] == D("18750.00")


def test_champlain_housing_trust_single_family_scaled_share():
    """Champlain Housing Trust single-family formula, from the Urban Institute's
    “Shared Equity Homeownership Evaluation: Case Study of Champlain Housing
    Trust” (Temkin, Theodos & Price, 2010).

    Price $100,000 on a home appraised at $200,000 (owner paid 50% of value);
    appreciates to $300,000: “$100,000 + [50% × 25% × $100,000] = $112,500”.
    """
    result = calculate(
        appraisal(scale_by_purchase_ratio=True),
        FormulaInputs(
            purchase_price=D("100000"),
            purchase_date=date(2000, 6, 1),
            valuation_date=date(2008, 6, 1),
            initial_appraised_value=D("200000"),
            current_appraised_value=D("300000"),
        ),
    )
    assert result.price == D("112500.00")
    ratio = next(s for s in result.steps if s.label == "Homeowner's share of the initial value")
    assert ratio.value == D("0.5")


@pytest.mark.parametrize(
    ("initial", "price", "current", "expected"),
    [
        # 2021 deck: appraisal $200K, $40K subsidy → price $160K; reappraised at $240K → $170K.
        ("200000", "160000", "240000", "170000.00"),
        # Jan 2025 deck: appraisal $220K, $60K subsidy → $160K; reappraised at $300K → $180K.
        ("220000", "160000", "300000", "180000.00"),
    ],
)
def test_champlain_housing_trust_legislative_testimony(initial, price, current, expected):
    """Champlain Housing Trust testimony to the Vermont House (Chris Donnelly,
    2021 and January 2025): the seller's price is the appraisal minus the
    original subsidy minus 75% of market appreciation, i.e. the purchase price
    plus 25% of appreciation."""
    result = calculate(
        appraisal(),
        FormulaInputs(
            purchase_price=D(price),
            purchase_date=date(2015, 1, 1),
            valuation_date=date(2024, 1, 1),
            initial_appraised_value=D(initial),
            current_appraised_value=D(current),
        ),
    )
    assert result.price == D(expected)


def test_cpah_scaled_share_with_depreciated_roof_credit():
    """Community Partners for Affordable Housing (Highland Park, IL).

    Initial appraisal $300,000, price $180,000 (investment ratio 60%), appraisal
    $350,000 after 10 years, shared appreciation factor 15%. A $6,000 roof added
    in year 4, depreciated straight-line over 15 years, is worth $3,600 after
    year 10. Formula price $188,100: $180,000 + $4,500 + $3,600.
    """
    result = calculate(
        appraisal("0.15", scale_by_purchase_ratio=True),
        FormulaInputs(
            purchase_price=D("180000"),
            purchase_date=date(2010, 1, 1),
            valuation_date=date(2020, 1, 1),
            initial_appraised_value=D("300000"),
            current_appraised_value=D("350000"),
            improvements=(ImprovementCredit("Roof", D("6000"), date(2014, 1, 1), useful_life_years=15),),
        ),
    )
    assert result.base_price == D("184500.00")
    assert result.improvement_credit == D("3600.00")
    assert result.price == D("188100.00")
    assert not result.capped


def test_flagstaff_clt_program_example():
    """City of Flagstaff Community Land Trust Program resale formula sheet:
    “$180,000 + [($293,201 - $180,000) x 25%] = $208,300”."""
    result = calculate(
        appraisal(),
        FormulaInputs(
            purchase_price=D("180000"),
            purchase_date=date(2012, 1, 1),
            valuation_date=date(2022, 1, 1),
            initial_appraised_value=D("180000"),
            current_appraised_value=D("293201"),
        ),
    )
    assert result.base_price == D("208300.25")
    assert result.price == D("208300.00")  # rounded to the nearest dollar


def test_one_roof_community_housing_example():
    """One Roof Community Housing (Duluth, MN) CLT FAQ: price $185,000,
    appraised $225,000 at purchase and $305,000 at resale;
    “.25 x $80,000=$20,000”, resale price $205,000."""
    result = calculate(
        appraisal(),
        FormulaInputs(
            purchase_price=D("185000"),
            purchase_date=date(2014, 5, 1),
            valuation_date=date(2023, 5, 1),
            initial_appraised_value=D("225000"),
            current_appraised_value=D("305000"),
        ),
    )
    assert result.price == D("205000.00")


# ---------------------------------------------------------------------------
# Published examples: indexed formulas
# ---------------------------------------------------------------------------


def test_housing_land_trust_of_the_north_bay_ami_index():
    """Housing Land Trust of the North Bay sample resale: 4-person 100% AMI
    $82,600 (2014) → $93,300 (2019) on a $300,000 price gives a maximum sales
    price of $338,861.99. Matching it requires the unrounded index ratio."""
    result = calculate(
        indexed(rounding=Rounding.CENT, cap_at_appraised_value=False),
        FormulaInputs(
            purchase_price=D("300000"),
            purchase_date=date(2014, 4, 1),
            valuation_date=date(2019, 4, 1),
            index_at_purchase=D("82600"),
            index_at_valuation=D("93300"),
        ),
    )
    assert result.price == D("338861.99")


def test_san_francisco_bmr_ami_repricing():
    """San Francisco MOHCD “Guidelines for Repricing BMR Units” (2010):
    $298,000 price, AMI $64,080 → $69,200, new price $321,810 (before the
    allowance for sales commission, which Leasekeep does not add)."""
    result = calculate(
        indexed(cap_at_appraised_value=False),
        FormulaInputs(
            purchase_price=D("298000"),
            purchase_date=date(2001, 1, 31),
            valuation_date=date(2007, 5, 15),
            index_at_purchase=D("64080"),
            index_at_valuation=D("69200"),
        ),
    )
    assert result.price == D("321810.00")


# ---------------------------------------------------------------------------
# Published examples: fixed-rate formulas
# ---------------------------------------------------------------------------


def test_big_river_clt_compounded_rate():
    """Big River CLT resale formula page: 1.5% compounded annually for 7 years
    on $350,000 → maximum resale $388,446."""
    result = calculate(
        fixed("0.015", cap_at_appraised_value=False),
        FormulaInputs(D("350000"), date(2017, 1, 1), date(2024, 1, 1)),
    )
    assert result.price == D("388446.00")


def test_homestead_clt_compounded_rate():
    """Homestead CLT (Seattle), formula since January 2020: “$200,000 + 1.5%
    compounding annually” = $221,968 over seven years. Homestead truncates;
    Leasekeep keeps cents when rounding is set to the nearest cent."""
    result = calculate(
        fixed("0.015", rounding=Rounding.CENT, cap_at_appraised_value=False),
        FormulaInputs(D("200000"), date(2020, 1, 1), date(2027, 1, 1)),
    )
    assert result.price == D("221968.98")


def test_houston_clt_simple_rate():
    """Houston CLT presentation to H-GAC (Sept 2019): 1.25% simple on a
    $75,115 initial price is $79,810 at year 5. (Houston rounds each five-year
    step, so its later figures run $1–2 above exact simple interest.)"""
    config = fixed("0.0125", Compounding.SIMPLE, cap_at_appraised_value=False)
    year5 = calculate(config, FormulaInputs(D("75115"), date(2019, 1, 1), date(2024, 1, 1)))
    year10 = calculate(config, FormulaInputs(D("75115"), date(2019, 1, 1), date(2029, 1, 1)))
    assert year5.price == D("79810.00")
    assert year10.price == D("84504.00")  # published $84,505 after step rounding


def test_ut_austin_toolkit_two_percent_simple():
    """UT Austin Entrepreneurship & Community Development Clinic CLT toolkit
    (2018): a home priced at $100,000 is $102,000 a year later and $104,000
    after two years at 2% simple."""
    config = fixed("0.02", Compounding.SIMPLE, cap_at_appraised_value=False)
    assert calculate(config, FormulaInputs(D("100000"), date(2018, 1, 1), date(2019, 1, 1))).price == D(
        "102000.00"
    )
    assert calculate(config, FormulaInputs(D("100000"), date(2018, 1, 1), date(2020, 1, 1))).price == D(
        "104000.00"
    )


# ---------------------------------------------------------------------------
# Behaviour
# ---------------------------------------------------------------------------


def test_cap_at_appraised_value_applies_lesser_of_formula_and_market():
    """2011 CLT Network model ground lease §10.9: price is the lesser of the
    appraised value and the formula price."""
    result = calculate(
        indexed(),
        FormulaInputs(
            purchase_price=D("150000"),
            purchase_date=date(2016, 1, 1),
            valuation_date=date(2026, 1, 1),
            index_at_purchase=D("70000"),
            index_at_valuation=D("100000"),
            current_appraised_value=D("190000"),
        ),
    )
    assert result.uncapped_price == D("214285.71")
    assert result.capped
    assert result.price == D("190000.00")
    assert any(s.label == "Capped at appraised value" for s in result.steps)


def test_cap_warns_when_no_appraisal_on_file():
    result = calculate(fixed("0.02"), FormulaInputs(D("100000"), date(2020, 1, 1), date(2021, 1, 1)))
    assert not result.capped
    assert "No current appraisal" in result.warnings[0]


def test_losses_are_shared_unless_purchase_price_protected():
    inputs = FormulaInputs(
        purchase_price=D("150000"),
        purchase_date=date(2006, 1, 1),
        valuation_date=date(2011, 1, 1),
        initial_appraised_value=D("220000"),
        current_appraised_value=D("180000"),
    )
    shared = calculate(appraisal(), inputs)
    assert shared.price == D("140000.00")  # bears 25% of the $40,000 decline
    protected = calculate(appraisal(protect_purchase_price=True), inputs)
    assert protected.price == D("150000.00")
    assert any(s.label == "Purchase price protection" for s in protected.steps)


def test_indexed_price_can_fall_with_the_index():
    result = calculate(
        indexed(cap_at_appraised_value=False),
        FormulaInputs(
            D("100000"),
            date(2009, 1, 1),
            date(2011, 1, 1),
            index_at_purchase=D("80000"),
            index_at_valuation=D("76000"),
        ),
    )
    assert result.price == D("95000.00")


def test_fixed_rate_prorates_by_complete_months():
    config = fixed("0.02", Compounding.SIMPLE, cap_at_appraised_value=False, rounding=Rounding.CENT)
    result = calculate(config, FormulaInputs(D("120000"), date(2020, 3, 15), date(2022, 9, 14)))
    # 29 complete months (the 30th is one day short) = 2.41667 years.
    assert result.years_held == D(29) / D(12)
    assert result.price == D("125800.00")


def test_fixed_rate_whole_years_only():
    config = fixed("0.02", Compounding.SIMPLE, prorate_partial_years=False, cap_at_appraised_value=False)
    result = calculate(config, FormulaInputs(D("120000"), date(2020, 3, 15), date(2022, 9, 14)))
    assert result.years_held == D(2)
    assert result.price == D("124800.00")


def test_improvements_full_credit_without_depreciation():
    config = fixed("0", depreciation=Depreciation.NONE, cap_at_appraised_value=False)
    result = calculate(
        config,
        FormulaInputs(
            D("100000"),
            date(2015, 1, 1),
            date(2025, 1, 1),
            improvements=(ImprovementCredit("Furnace", D("8000"), date(2016, 1, 1), useful_life_years=10),),
        ),
    )
    assert result.improvement_credit == D("8000.00")
    assert result.price == D("108000.00")


def test_improvement_fully_depreciated_after_useful_life():
    result = calculate(
        fixed("0", cap_at_appraised_value=False),
        FormulaInputs(
            D("100000"),
            date(2000, 1, 1),
            date(2025, 1, 1),
            improvements=(
                ImprovementCredit("Water heater", D("1500"), date(2005, 1, 1), useful_life_years=12),
            ),
        ),
    )
    assert result.improvement_credit == D("0.00")
    step = next(s for s in result.steps if s.label.startswith("Improvement credit"))
    assert "fully depreciated" in step.expression


def test_future_improvement_is_not_credited_and_warns():
    result = calculate(
        fixed("0", cap_at_appraised_value=False),
        FormulaInputs(
            D("100000"),
            date(2020, 1, 1),
            date(2022, 1, 1),
            improvements=(ImprovementCredit("Deck", D("5000"), date(2023, 6, 1)),),
        ),
    )
    assert result.improvement_credit == D("0.00")
    assert any("Deck" in w for w in result.warnings)


def test_improvements_ignored_when_formula_excludes_them():
    result = calculate(
        appraisal(include_improvements=False),
        FormulaInputs(
            D("100000"),
            date(2020, 1, 1),
            date(2022, 1, 1),
            initial_appraised_value=D("150000"),
            current_appraised_value=D("170000"),
            improvements=(ImprovementCredit("Kitchen", D("20000"), date(2021, 1, 1)),),
        ),
    )
    assert result.improvement_credit == D("0")
    assert result.price == D("105000.00")


@pytest.mark.parametrize(
    ("rounding", "expected"),
    [(Rounding.CENT, "128443.62"), (Rounding.DOLLAR, "128444.00"), (Rounding.HUNDRED, "128400.00")],
)
def test_rounding_modes(rounding, expected):
    config = fixed("0.02", rounding=rounding, cap_at_appraised_value=False)
    result = calculate(config, FormulaInputs(D("123456"), date(2020, 1, 1), date(2022, 1, 1)))
    assert result.price == D(expected)


def test_worksheet_is_reproducible_step_by_step():
    """Every money line is rounded to the cent before it feeds the next line."""
    result = calculate(
        appraisal(),
        FormulaInputs(
            D("150000"),
            date(2016, 3, 14),
            date(2026, 11, 19),
            initial_appraised_value=D("200000.33"),
            current_appraised_value=D("265000.99"),
        ),
    )
    steps = {s.label: s.value for s in result.steps}
    assert steps["Base formula price"] == D("150000.00") + steps["Homeowner's share of the change"]
    assert all(s.value == s.value.quantize(D("0.01")) for s in result.steps if s.unit == "money")
    assert result.steps[-1].label == "Formula price" and result.steps[-1].total


@pytest.mark.parametrize(
    ("config", "inputs", "message"),
    [
        (appraisal(), FormulaInputs(D("0"), date(2020, 1, 1), date(2021, 1, 1)), "greater than zero"),
        (
            fixed("0.02"),
            FormulaInputs(D("1"), date(2021, 1, 1), date(2020, 1, 1)),
            "before the purchase date",
        ),
        (
            appraisal(),
            FormulaInputs(D("1"), date(2020, 1, 1), date(2021, 1, 1)),
            "appraised value at purchase",
        ),
        (
            appraisal(),
            FormulaInputs(D("1"), date(2020, 1, 1), date(2021, 1, 1), initial_appraised_value=D("2")),
            "current appraisal",
        ),
        (indexed(), FormulaInputs(D("1"), date(2020, 1, 1), date(2021, 1, 1)), "HUD AMI values"),
        (
            indexed(),
            FormulaInputs(
                D("1"),
                date(2020, 1, 1),
                date(2021, 1, 1),
                index_at_purchase=D("-1"),
                index_at_valuation=D("2"),
            ),
            "greater than zero",
        ),
        (
            appraisal(),
            FormulaInputs(D("1"), date(2020, 1, 1), date(2021, 1, 1), current_appraised_value=D("0")),
            "greater than zero",
        ),
    ],
)
def test_invalid_inputs_raise_clear_errors(config, inputs, message):
    with pytest.raises(FormulaError, match=message):
        calculate(config, inputs)


def test_invalid_config_is_rejected():
    with pytest.raises(FormulaError):
        appraisal("1.5")
    with pytest.raises(FormulaError):
        fixed("0.5")


def test_describe_reads_plainly():
    assert engine.describe(appraisal()).startswith("The homeowner receives what they paid plus 25% of")
    assert "proportional" in engine.describe(appraisal(scale_by_purchase_ratio=True))
    assert "HUD AMI" in engine.describe(indexed())
    text = engine.describe(
        fixed("0.015", Compounding.SIMPLE, protect_purchase_price=True, depreciation=Depreciation.NONE)
    )
    assert "1.5% a year (simple)" in text
    assert "never falls below" in text
    assert "depreciated" not in text
    assert engine.describe(fixed("0.02", include_improvements=False, cap_at_appraised_value=False)).endswith(
        "(compounded)."
    )


@pytest.mark.parametrize(
    ("start", "end", "months"),
    [
        (date(2020, 1, 31), date(2020, 2, 29), 0),
        (date(2020, 1, 15), date(2020, 2, 15), 1),
        (date(2020, 1, 15), date(2030, 1, 14), 119),
        (date(2020, 5, 1), date(2020, 4, 1), 0),
    ],
)
def test_complete_months(start, end, months):
    assert engine.complete_months(start, end) == months


def test_formatting_helpers():
    assert engine.money(D("-1234.5")) == "−$1,234.50"
    assert engine.percent(D("0.0125")) == "1.25%"
    assert engine.percent(D("0.25")) == "25%"
    assert engine.long_date(date(2026, 3, 5)) == "Mar 5, 2026"
    step = engine.Step("x", "y", D("0.5"), unit="percent")
    assert step.display_value == "50%"
    assert engine.Step("x", "y", D("2.5"), unit="years").display_value == "2.50 yrs"
    assert engine.Step("x", "y", D("1.23456789"), unit="factor").display_value == "× 1.234568"
    assert engine.Step("x", "y", D("7"), unit="count").display_value == "7"


def test_owner_gain():
    result = calculate(
        fixed("0.02", Compounding.SIMPLE, cap_at_appraised_value=False),
        FormulaInputs(D("100000"), date(2020, 1, 1), date(2025, 1, 1)),
    )
    assert result.owner_gain == D("10000.00")
