# AAPL — Apple Inc. — DGI analysis

**Date:** 2026-10-10 · **Price:** $336.64 (FMP `profile-symbol`) · **Fiscal year ends:** September (FY2025 closed 2025-09-27)
**Run through:** `company-analysis` skill, installed v0.11.9, all six methods. Not held.

## Verdict

**Fails the strategy: criterion 3 is in the `NO` band.** 5Y DGR on the latest complete fiscal year
(FY2021 $0.85 → FY2026 $1.06, Tiingo `divCash`) is **4.51%**, below the 5% floor for a low-yield payer,
and growth is decelerating at every horizon (1y 3.9% < 3y 4.1% < 5y 4.5% < 10y 6.9%). The other nine
criteria score **19/27**. The first version of this report (2026-10-10) read 5Y DGR as 5.11% because
it stopped at FY2025: the FY2026 10-K is not filed, so EDGAR has no FY2026 dividend yet. The
dripinvesting figure, 4.7%, was the more current one. Other points lost: yield (0.32%, below the
S&P 500), EPS and FCF consistency. The dividend itself is not at risk: FCF payout ~16%.
**Valuation: all five mean-reversion methods put fair value at $83-$165 against $336.64**, but the
business re-rated structurally from hardware to services, so mean reversion is the weakest
assumption in this report.

## Step 0b result

Ordinary us-gaap filer. Every concept resolved; no IFRS note and no per-share-class note.

## Data handling

1. **Two splits in the window: 7:1 (2014-06-09) and 4:1 (2020-08-31).** Every as-filed per-share
   figure was scaled by `split_factor_by_filing_date`, keyed on its `filed` date. FY2010-2011 were
   filed before the 7:1 split (factor 1/28), FY2012-2017 between the splits (factor 0.25), and
   FY2018 onward after both (factor 1.0). Keying on the fiscal year would have rescaled FY2018 and
   FY2019, which are already post-split, by 0.25. The adjusted EPS series is smooth through both
   splits (FY2017 $2.30 → FY2018 $2.98).
2. **Share counts need the inverse factor.** `shares_diluted` as filed jumps from 5.25bn (FY2017)
   to 20.0bn (FY2018). That is the 4:1 split, not issuance; dividing by the same factor gives a count
   that falls every year from FY2013 to FY2025. The skill documents the factor only for per-share
   figures — see BACKLOG item 29.
3. **`operating_cash_flow` has an interior gap at FY2014.** FCF trend and the P/OpCF and P/FCF means
   skip that year.
4. **`interest_expense` is stale after FY2023**, because Apple stopped tagging it. Interest coverage
   is reported through FY2023 only.
5. **Balance sheet at fiscal year end.** FY2024 and FY2025 equity and debt come from comparatives in
   a 10-Q filed 2026-07-31, at the September balance-sheet date (FY2024 equity $56.95bn, matching the
   10-K). This is the item 26 fix working on a second filer.
6. **The FY2026 10-K is not filed yet.** Corrected 2026-10-11: criterion 3 now uses FY2026 dividends
   from Tiingo `divCash` (the daily series `price_annual_averages` already fetches), summed by
   ex-date over October-September. That is $0.26 + $0.26 + $0.27 + $0.27 = $1.06. Fiscal 2026 closed in September 2026; the 10-K is due around
   the end of October. FY2026 prices are complete but have no fundamentals to pair with, so every
   current multiple uses FY2025. That overstates today's multiples against trailing twelve months.

## Scoring

| # | Criterion | Points | Evidence |
|---|---|---|---|
| 1 | Growth years | 2 | 13 consecutive FY increases FY2013-FY2025. The dividend was reinstated in FY2012 (partial year); the 1987-1995 dividend was suspended. Cross-check: dripinvesting `Contender` |
| 2 | Yield vs S&P 500 | 1 | $1.08 annualised ($0.27 quarterly) / $336.64 = 0.32%. The S&P 500 is ~1% (proxy: SPY trailing 0.98%). Under 1x on any plausible index figure |
| 3 | DGR (low-yield bucket) | **NO** | 5Y 4.51% (FY2021 $0.85 → FY2026 $1.06; FY2026 from Tiingo `divCash`, which matches EDGAR exactly on FY2018-FY2025). Decelerating: 1y 3.9%, 3y 4.1%, 10y 6.9%. On FY2025, the latest year in EDGAR, it read 5.11% (1 point) |
| 4 | EPS + payout | 1 | Trend growing (3); 3 GAAP declines in 10y — FY2016, FY2019, FY2024 (1); payout 13.7% FY2025 (3). FY2024 normalised for the EU tax charge leaves 2 declines → 2 |
| 5 | FCF + payout | 1 | 10y FCF CAGR 3.5% (2); 5 declines — FY2016, 2017, 2019, 2023, 2025 (1); FCF payout 15.6% FY2025 (3) |
| 6 | Debt to capital | 2 | 55.2% FY2025, down from a 68.5% peak (FY2022), up from 20.6% (FY2014). Gross debt $90.7bn; coverage 29x (FY2023, last tagged) |
| 7 | ROE | 3 | 152% FY2025, inflated by buybacks shrinking equity. ROIC approximation NI/(debt+equity) 68%: still > 25% |
| 8 | Operating margin | 3 | 32.0% FY2025, rising from 24.1% (FY2020) |
| 9 | Share count | 3 | Split-adjusted diluted shares 23.17bn (FY2015) → 15.00bn (FY2025), -35%, down every year |
| 10 | Credit rating | 3 | Moody's Aaa, stable outlook (affirmed Nov 2024). S&P AA+ (not confirmed by search). 30-year default probability 0.07-0.29% |
| | **Total** | **19/27 + `NO`** | Criterion 3 disqualifies; 20/27 with normalised FY2024 EPS. Not averaged into a /30 total |

## Dividend safety

The dividend costs ~$15.4bn a year against ~$99bn of FCF; the earnings payout is 14% and the FCF
payout 16%. A cut would take an earnings collapse of more than 80%. The real constraint is the other
way round: dividends plus buybacks were 107% of FCF in FY2025 ($90.7bn of buybacks), funded partly by
drawing down the net cash position. The dividend is a small and deliberately slow-growing part of
capital return. Raises run at ~4% a year, and that, not safety, is the DGI problem.

Through 2020 the dividend still rose (FY2020 +6%). There is no 2008-09 record: no dividend was paid
then.

## Valuation

Prices: `price_annual_averages`, fiscal years ending September; `verification` = `consistent`.
FY2011 (truncated) and FY2027 (in progress) were excluded; FY2026 has no fundamentals yet. Single,
uncorroborated price source (Tiingo).

| Method | 15y window (FY2012-2025) | 10y window (FY2016-2025) | Applicable | Note |
|---|---|---|---|---|
| Dividend Yield (Weiss) | $83 | — | yes, weakly | hist. yield 1.29% (FY2013-2025) vs 0.32%; ratio 4.03, guard not hit |
| Historical P/E | $145 | $165 | yes | hist. 19.4x / 22.2x vs current 45.1x (FY2025 EPS $7.46) |
| Historical P/EBIT | $140 | $163 | yes | 15.8x / 18.4x vs 38.0x |
| Historical P/OpCF | $120 | $136 | yes | 16.2x / 18.3x vs 45.3x; FY2014 gap skipped |
| Historical P/FCF | $125 | $137 | yes | 19.0x / 20.8x vs 51.1x |
| Gordon Growth | $19-$28 | | **no** | r = 9%, g = 3-5%. Inapplicable to a 0.3% yielder that returns most cash through buybacks |

**Average (5 methods, 15y): $123. Range $83-$145.** With 10y multiples: $137, range $83-$165.
**Target at a 12% margin: ~$108-$120. Current $336.64, ~2.5-2.7x the estimate.**

Every method points the same way, so the spread is not the issue. **The assumption is.** In
FY2012-2016 Apple traded at 11-15x as a hardware cycle business; since 2020 it has traded at 25-35x as
a services platform with a 32% operating margin. A mean that includes the old company reads the
new one as artificially expensive. Even against the 10y means alone the price is about twice the
estimate. Current multiples use FY2025 earnings and will fall when FY2026 is filed.

## Risks

1. **DGR stays in `NO`.** It is already there at 4.5% on FY2026. Leaving it needs FY2027 above
   $1.14 (5% a year on FY2022 $0.90), i.e. a raise of ~8% or more in May 2027 against ~4% lately.
   Monitor: the May raise.
2. **Services regulation.** App Store fees and the Google search payment carry the margin expansion.
   Monitor: Services gross margin and the outcome of the DOJ remedy and EU DMA cases.
3. **China and supply chain.** Greater China revenue and tariff exposure. Monitor: segment revenue in
   each 10-Q and the gross margin guidance.

## What's next

- **FY2026 Q4 results and 10-K, around the end of October 2026** (date unverified): rerun the
  valuation with FY2026 fundamentals, then check FCF and whether buybacks still exceed FCF.
- **Dividend raise with fiscal Q2 results, early May 2027:** the size of the raise decides criterion 3.

