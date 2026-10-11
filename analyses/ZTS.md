# ZTS — Zoetis Inc.

Analysed 2026-08-01 with `company-analysis`. **Score 23/30, "solid" band.**
Valuation deliberately not produced.

First end-to-end run of the skill, and the first ever on real data.

## Score

| # | Criterion | Pts | Evidence |
|---|---|---|---|
| 1 | Growth years | 2 | DPS rose every year 2015-2025 from SEC filings; Feb 2013 IPO caps the streak at 13 |
| 2 | Yield vs S&P | 3 | 2.74% vs 1.08% = **2.54x**, barely over the 2.5x line |
| 3 | DGR, medium bucket | 3 | DGR 5Y **19.0%** |
| 4 | EPS and payout | 3 | 1.65 to 6.02, **zero declines in 10 years**, payout 33.7% |
| 5 | FCF and payout | 1 | growth and 38.9% payout are fine, but **3 declines** (2019, 2022, 2025) |
| 6 | Debt to capital | 1 | **72.6%**, up from 57.9% in one year |
| 7 | ROE | 3 | 78.3% headline, **ROIC 21.5%** is the real figure |
| 8 | Operating margin | 3 | EBIT/revenue **37.8%**, rising from 28.5% in 2016 |
| 9 | Share count | 3 | 502M to 444M, down every single year |
| 10 | Credit rating | 1 | S&P **BBB** stable / Moody's **A3** stable; conservative reading taken |

Points lost on criteria 5, 6 and 10, plus criterion 1 capped by the IPO date.

## The finding that outranks the score: the 2025 balance sheet

Long-term debt 5.2bn to 9.0bn (**+73%**) while equity fell 4 770 to 3 415
(**−28%**), against a share count down only 2.4%. Debt to capital went 57.9% to
72.6% in a single year.

Interest coverage is still 16.1x, so this is a **leverage change to monitor, not
distress** — but the dividend now sits on materially more debt than in 2023.

## Three nuances that must travel with the score

- **DGR decelerates perfectly monotonically**: 1Y 13.0% < 3Y 14.6% < 5Y 19.0% <
  10Y 20.1%. The scoring model calls this the single most useful signal in the
  system.
- **ROE 78.3% is a capital-structure artefact**, not profitability — equity fell
  28%. ROIC 21.5% is the honest number.
- **The 2025 FCF "decline" is −0.65%**, essentially flat. Without it there are 2
  declines and criterion 5 scores 2 rather than 1. The point turns on a tenth of
  a percentage point; it was not rounded in the company's favour.

## Primary-source data

Diluted EPS straight from the filings, 13 years — the series FMP refuses to
serve for this symbol at all:

2013 1.01 · 2014 1.16 · 2015 0.68 · 2016 1.65 · 2017 1.75 · 2018 2.93 ·
2019 3.11 · 2020 3.42 · 2021 4.27 · 2022 4.49 · 2023 5.07 · 2024 5.47 ·
2025 6.02

One decline in thirteen years, in 2015. That is criterion 4's consistency
dimension answered with real data rather than a vendor's five-year window.

Two EDGAR tag notes specific to this filer: `dividends_paid` needed
`PaymentsOfOrdinaryDividends`, and ZTS does **not report `OperatingIncomeLoss`
at all**, so EBIT was derived as pretax income plus interest expense.

## Valuation — NOT produced, deliberately

Five of the six methods need annual average prices over 10-15 years, and no
price-history source exists. Gordon Growth alone gives $36-56 at r=9%, g=3-5%,
but it is the method the reference itself calls inapplicable to a low-yield,
high-growth payer — against a $77 price that reads as the method failing, not
the stock being 50% overvalued. **A number from Gordon Growth alone is not a
valuation.**

## Data correction this analysis produced

- **dripinvesting lists ZTS at `DGR 1Y` −19.3%. The filings show +13.0%.** No
  payment split reproduces −19.3%; a real cut would make the trailing total
  *higher* than four times the current rate, and it is lower. It also
  contradicts its own file (3Y +3.7%, 5Y +17.4%, 10Y +13.2%), and the specials
  explanation that covers AFG does not apply — ZTS shows `Payouts/Year` 4.
  Most likely a partial-year comparison. Mechanism unproven; the wrongness is not.
- **A growth-years figure of 14 and cannot be right.** ZTS listed
  February 2013, so 13 is the ceiling. Both are under 15, so the score does not
  change and no write was proposed.

