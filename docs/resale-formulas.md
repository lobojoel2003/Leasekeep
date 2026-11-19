# Resale formulas in Leasekeep

This page explains how Leasekeep computes formula prices and lists the published
worked examples its tests reproduce.

## How a price is computed

1. **Purchase price**: what the homeowner paid.
2. **Base formula price**, by formula type:
   - *Appraisal-based*: purchase price + share × (current appraisal − appraisal at purchase).
     With **scale by purchase price ÷ initial appraisal** turned on, the share applies only to
     the part of the home's value the homeowner paid for:
     purchase price + share × (purchase price ÷ initial appraisal) × (current − initial).
   - *Indexed*: purchase price × index now ÷ index at purchase. Index values come from an
     index series (for example HUD Area Median Income), using the value in effect on each
     date, or from an override on the ownership.
   - *Fixed rate*: purchase price × (1 + rate)^years (compound) or × (1 + rate × years)
     (simple). Years are complete months ÷ 12, or whole years only.
3. **Purchase price protection** (optional): the base price never falls below the purchase price.
4. **Capital improvement credits** (optional): each approved, completed improvement adds its
   credit, either in full or depreciated straight-line: credit × (1 − age ÷ useful life),
   never below zero. Improvements completed after the valuation date aren't credited.
5. **Market cap** (optional): the price is the lesser of the formula price and the current
   appraised value.
6. **Rounding** of the final price to the cent, dollar or $100.

Every money amount is rounded to the cent before it is used in the next step, and every step
is shown on the worksheet, so the result can be reproduced by hand. Ratios and growth factors
are kept at full precision. For indexed formulas this matters: published examples match only
when the unrounded ratio is used.

Which appraisal counts as "current"? The latest appraisal on file on or before the valuation
date. If it's more than three years old, the worksheet says so and suggests recording a new
one or entering a value in *What if…*.

## Published examples reproduced by the tests

All of these are in [`tests/test_engine.py`](../tests/test_engine.py).

### Appraisal-based

| Example | Inputs | Result |
|---|---|---|
| HUD *HOMEfires* Vol. 15 No. 1, "Appraisal-Based Resale Formulas" (January 2020) | price $150,000; appraisals $200,000 → $275,000; 25% | $150,000 + $75,000 × 0.25 = **$168,750** |
| Champlain Housing Trust, single-family (Urban Institute, *Shared Equity Homeownership Evaluation: Case Study of Champlain Housing Trust*, 2010) | price $100,000; appraisals $200,000 → $300,000; 25%, scaled by 50% | $100,000 + 50% × 25% × $100,000 = **$112,500** |
| Champlain Housing Trust, testimony to the Vermont House (2021) | appraisal $200,000; price $160,000; reappraised $240,000 | **$170,000** |
| Champlain Housing Trust, testimony to the Vermont House (January 2025) | appraisal $220,000; price $160,000; reappraised $300,000 | **$180,000** |
| Community Partners for Affordable Housing (Highland Park, IL) | price $180,000; appraisals $300,000 → $350,000 after 10 years; 15% scaled by 60%; $6,000 roof in year 4 over 15 years | $180,000 + $4,500 + $3,600 = **$188,100** |
| City of Flagstaff Community Land Trust Program | price $180,000; appraisals $180,000 → $293,201; 25% | **$208,300** |
| One Roof Community Housing (Duluth, MN) | price $185,000; appraisals $225,000 → $305,000; 25% | **$205,000** |

HUD notes that an appraisal-based formula usually shouldn't add a separate improvement credit,
because the resale appraisal already reflects improvements. Turn off **Credit capital
improvements** for such formulas.

### Indexed

| Example | Inputs | Result |
|---|---|---|
| Housing Land Trust of the North Bay, sample resale | price $300,000; 4-person AMI $82,600 → $93,300 | **$338,861.99** |
| San Francisco MOHCD, *Guidelines for Repricing BMR Units* (2010) | price $298,000; AMI $64,080 → $69,200 | **$321,810** (before a sales-commission allowance, which Leasekeep does not add) |

### Fixed rate

| Example | Inputs | Result |
|---|---|---|
| Big River CLT | $350,000; 1.5% compounded; 7 years | **$388,446** |
| Homestead CLT (Seattle), formula since 2020 | $200,000; 1.5% compounded; 7 years | **$221,968** published (truncated); Leasekeep: $221,968.98 |
| Houston CLT, presentation to H-GAC (2019) | $75,115; 1.25% simple | **$79,810** at year 5. Houston rounds each five-year step, so its year-10 figure ($84,505) is $1 above exact simple interest ($84,504). |
| UT Austin ECDC Clinic, *CLT Toolkit* (2018) | $100,000; 2% simple | **$102,000** after one year, **$104,000** after two |

## Choosing settings for your formula

- Read the resale section of your ground lease and copy it into the formula's description.
- When your lease changes for new buyers, create a **new** formula and leave the old one on
  existing ownerships. Editing a formula changes the price for every home that uses it.
- Most model ground leases (for example §10.9 of the 2011 CLT Network model) set the price at
  the **lesser** of the formula price and the appraised value: keep **cap at appraised value** on.
- Formulas that pass losses on to owners in a falling market are common. Turn on **protect
  purchase price** only if your lease guarantees the original price.
