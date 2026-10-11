# INTU — Intuit Inc. — DGI analysis

**Date:** 2026-10-11 · **Price:** $302.75 (FMP `profile-symbol`, 2026-10-11) · **Fiscal year ends:** July
**Run through:** `company-analysis` skill, Step 0b branch 3 (ordinary filer: every concept resolved in EDGAR)

## Verdict

**23/30 — solid (> 20), with one boundary call.** Criterion 1 scores 3 on an *effective* streak of
15 (14 complete fiscal years plus the +15% raise to $1.38 that went ex on 2026-10-08); on complete
years alone it is 2 and the total is 22. It loses points on yield (1.82%, under 2x the S&P 500),
one EPS and one FCF decline in ten years, ROE just under 25% (24.0%), a credit rating of A / A3
and a share count that rose over the decade (265m → 277m, acquisitions paid in stock). **The
dividend is not at risk: FCF payout 15.5% (FY2026), EPS payout 29%.**

**Valuation: the mean-reversion methods say $378-$770 (15-year average $645) against $302.75,
and that number should not be trusted at face value.** The stock fell from $785 to $255 within
FY2026 on fears that AI tax tools erode TurboTax. If that re-rating is permanent, every
historical multiple overstates fair value. Even restricted to the pre-premium years FY2012-2017
the methods average $492, and the Weiss model, which the denominator guard caps, gives $378.

## Data

- **Statements:** `edgar_financials`, all concepts resolved. `quality` flags:
  `dividend_per_share_declared` and `dividends_paid` carry `zero_values: [2011]` (pre-dividend
  year; the first dividend was declared in FY2012), so every DGR and streak starts at FY2012.
  `short_term_debt` (`LongTermDebtCurrent`) has interior gaps and is **not used**: `LongTermDebt`
  already includes the current portion (FY2026 7,669 = 6,420 noncurrent + 1,249 current).
- **Dividends:** EDGAR `dividend_per_share_declared` and `price_dividends` agree exactly for
  FY2012-FY2026, 4 payments a year, no `outsized_payments`. FY2027 is incomplete (one payment).
- **Prices:** `price_annual_averages`, `fiscal_year_end_month = 7`, FY2012-FY2026 complete,
  FY2027 excluded as incomplete. `verification` = `consistent`. **No split in the window**, so no
  split factor applies. Single, uncorroborated price source (Tiingo).
- **Credit rating:** June 2026 notes offering (FWP on EDGAR): S&P A stable, Moody's A3 stable.
- **S&P 500 yield:** no reliable index figure found for October 2026; proxy SPY trailing 0.98%,
  range ~1.0-1.2% as in the V and AAPL analyses.
- **Not used:** dripinvesting CSV (none in the folder). FMP statements (gated).

| FY | DPS | EPS dil. | FCF ($m) | Op. margin | Debt/cap | Diluted shares (m) | Avg price |
|---|---|---|---|---|---|---|---|
| 2016 | 1.20 | 3.69 | 1,044 | 26.5% | 24.6% | 265 | 99.40 |
| 2017 | 1.36 | 3.78 | 1,497 | 27.3% | 20.5% | 261 | 119.89 |
| 2018 | 1.56 | 5.09 | 2,074 | 25.9% | 12.1% | 261 | 169.03 |
| 2019 | 1.88 | 5.89 | 2,248 | 27.3% | 9.3% | 264 | 232.71 |
| 2020 | 2.12 | 6.92 | 2,355 | 28.3% | 28.5% | 264 | 272.28 |
| 2021 | 2.36 | 7.56 | 3,197 | 26.0% | 17.1% | 273 | 388.27 |
| 2022 | 2.72 | 7.28 | 3,732 | 20.2% | 29.6% | 284 | 513.56 |
| 2023 | 3.12 | 8.42 | 4,836 | 21.9% | 26.2% | 283 | 425.01 |
| 2024 | 3.60 | 10.43 | 4,693 | 22.3% | 24.7% | 284 | 591.99 |
| 2025 | 4.16 | 13.67 | 6,123 | 26.1% | 23.3% | 283 | 650.17 |
| 2026 | 4.80 | 16.46 | 8,663 | 27.4% | 28.8% | 277 | 511.98 |

FCF = `NetCashProvidedByUsedInOperatingActivities` − `PaymentsToAcquirePropertyPlantAndEquipment`.
Capitalised software (`PaymentsToDevelopSoftware`, $46m FY2026) is not subtracted; it moves
nothing at this scale.

## The business

Intuit sells software that keeps the books and files the taxes of US households and small
businesses. Four segments: Global Business Solutions (QuickBooks, payroll, payments, Mailchimp),
Consumer (TurboTax), Credit Karma (a free credit-score app paid by lenders for referrals) and
ProTax (software for tax professionals). Most revenue is subscription or per-filing.

The advantage is **switching cost plus data**. A small business's ledger, payroll history and
accountant workflow all live in QuickBooks, and moving them is painful and risky. TurboTax has
carried a brand and prior-year-return lock-in. Credit Karma and TurboTax share a customer base of
tens of millions, which feeds cross-selling.

What must stay true: QuickBooks remains the default ledger for US small businesses; TurboTax keeps
enough of its paying users that price cuts do not hollow out the Consumer segment; the AI agents
that threaten tax filing are something Intuit builds into its products rather than something that
routes around them.

Shareholder friendliness: a dividend raised every year since its 2011 initiation, at a steady
~15% a year; heavy buybacks ($5.4bn in FY2026, $7.9bn authorised). Against that, stock-based
compensation runs at $2.06bn a year, so a large part of the buyback only offsets dilution, and
FY2026's buyback was done at an average price far above today's.

## Scoring

| # | Criterion | Pts | Evidence |
|---|---|---|---|
| 1 | Growth streak | 3 | 14 consecutive raises over complete fiscal years (FY2013-FY2026, $0.60 → $4.80), the figure verified in BACKLOG item 2. FY2027 quarterly raised $1.20 → $1.38 (+15%), already paid ex 2026-10-08: **effective streak 15**. Boundary call, stated: on complete years it is 2 points |
| 2 | Yield vs S&P 500 | 2 | $5.52 / $302.75 = 1.82%, 1.5-1.9x an S&P 500 yield of ~1.0-1.2%. **Low-yield bucket (< 2%)**; at ~$276 it would cross 2% |
| 3 | DGR (low-yield bucket) | 3 | 5Y 15.3% (FY2021-2026). 1Y 15.4%, 3Y 15.4%, 10Y 14.9%, FY2027 raise 15.0%. No deceleration |
| 4 | EPS + payout | 2 | Trend growing (3.69 → 16.46, FY2016-2026): 3. One decline in ten years (FY2022, 7.56 → 7.28): 2. Payout 4.80 / 16.46 = 29%: 3. Lowest = 2 |
| 5 | FCF + payout | 2 | Trend growing (1.50bn → 8.66bn, FY2017-2026): 3. One decline (FY2024, 4.84bn → 4.69bn): 2. FCF payout 1,347 / 8,663 = 15.5% (FY2025: 19.4%): 3. Lowest = 2 |
| 6 | Debt to capital | 3 | 7.67bn / (7.67bn + 18.99bn) = 28.8% (FY2026). Range 23-30% since the FY2022 acquisitions, up from 25.7% a year earlier. Interest coverage 5,884 / 256 = 23x. **Near the 30% line** |
| 7 | ROE | 2 | 4,566 / 18,992 = 24.0% (FY2026), rising from 12.6% (FY2022). Equity is heavy with goodwill from Credit Karma and Mailchimp, which depresses ROE |
| 8 | Operating margin | 3 | 5,884 / 21,448 = 27.4% (FY2026), 20-28% every year of the decade; recovering since the FY2022 trough of 20.2% |
| 9 | Share count | 1 | Diluted 265m (FY2016) → 277m (FY2026): increasing over the decade, from stock paid for Credit Karma (FY2021) and Mailchimp (FY2022). Falling since FY2022 (284m → 277m), not yet enough to call a pattern |
| 10 | Credit rating | 2 | S&P A stable, Moody's A3 stable (June 2026). Split rating: Moody's A3 is the A- equivalent, which the model treats as BBB in practice |
| | **Total** | **23/30** | **Solid.** 22/30 if the FY2027 raise is not counted toward the streak |

## Dividend safety

- **Payout:** 29% of GAAP EPS, 15.5% of FCF (FY2026). After subtracting stock-based compensation
  as if it were cash (8,663 − 2,056 = 6,607), the payout is still 20%.
- **Coverage:** dividends of $1.35bn against FCF of $8.66bn. FY2026 operating cash flow rose 42%,
  more than earnings; on FY2025 FCF the payout is 19.4%, so the safety does not depend on one year.
- **Recessions:** no dividend existed in 2008-09. In FY2020 (COVID, a tax deadline pushed to July)
  the dividend rose 12.8%.
- **What a cut would take:** FCF falling by more than 80%. Nothing in the filings points that way.
  The realistic risk is not a cut but **slower raises**: below 13% a year, criterion 3 drops to
  2 points, and buybacks compete for the same cash.

## Valuation

Window FY2012-FY2026 (15 complete fiscal years, Aug-Jul). FY2027 excluded as incomplete. Current
per-share figures on FY2026 and the FY2026 diluted count (277m).

| Method | Estimate | Applicable | Note |
|---|---|---|---|
| Dividend Yield Model | $378 | yes | historical yield 0.88% vs current 1.82%; ratio 0.48 → **guard 0.8 binds** |
| Historical P/E | $679 | yes | current 18.4x vs 15y mean 33.9x (FY2015 GAAP EPS 1.28 inflates the mean; excluding it: $641) |
| Historical P/EBIT | $660 | yes | current 14.3x vs mean 31.1x |
| Historical P/OpCF | $740 | yes | current 9.5x vs mean 23.2x |
| Historical P/FCF | $770 | yes | current 9.7x vs mean 24.6x. On FY2025 FCF/share (P/FCF 14.0x) it would be ~$530 |
| Gordon Growth | $92-$138 | **no** | r = 9%, g = 3-5%, D1 $5.52. Inapplicable to a 15% dividend grower yielding 1.8% |

**Average (5 methods): $645. Range $378-$770**, a $392 spread. The Weiss figure is set by the
guard, not by the data: the current yield is twice the historical one because the price
halved, not because the dividend jumped.

**Sensitivity, because the core assumption is in doubt.** FY2018-FY2025 multiples (P/E 33-70)
priced a growth premium the market has now withdrawn. Restricting the means to the pre-premium
years FY2012-FY2017 gives P/E $545, P/EBIT $446, P/OpCF $514, P/FCF $579, Weiss $378: **average
$492, range $378-$579.** With 10-year means (FY2017-2026) the average rises to $726.

**Target at a 12% margin:** $568 on the 15-year average, $433 on the pre-premium sensitivity,
$333 on Weiss alone. **Current $302.75** sits below all three.

**Structural-break warning.** All five mean-reversion methods assume today's Intuit is comparable
to the Intuit of 2012-2025. The 2026 sell-off is a bet that it is not: that AI agents turn tax
filing into a commodity and squeeze TurboTax's pricing. If that bet is right, these estimates are
too high by an amount no historical window can measure. The current multiples (P/FCF 9.7x, below
any year since FY2012) price exactly that.

## Risks — three thesis-breakers

1. **AI commoditises tax filing.** TurboTax is ~25% of revenue and operating income, and Intuit
   is already cutting prices to win back users. *Monitor:* Consumer segment revenue and TurboTax
   units in the Q3 report (May 2027), after the tax season.
2. **Growth slows into the dividend.** FY2027 guidance is 9-10% revenue growth, down from 14%.
   *Monitor:* the August 2027 raise. Below 13% moves criterion 3 to 2 points; below 9% to 1.
3. **Capital allocation turns against shareholders.** $5.4bn of FY2026 buybacks at prices well
   above today's, debt up to $7.7bn, SBC at $2.06bn. *Monitor:* debt to capital above 30%
   (criterion 6 drops), and whether the diluted count keeps falling once SBC is netted.

## What's next

- **Q1 FY2027 results:** historically late November (date not confirmed). Check the reaffirmed
  FY2027 guidance ($23.3-23.5bn revenue).
- **Q3 FY2027 results (May 2027):** the tax-season verdict on TurboTax pricing and units.
- **Q4 FY2027 results (late August 2027):** the next dividend raise is announced with them.

