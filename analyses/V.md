# V — Visa Inc. — DGI analysis

**Date:** 2026-10-04, valuation redone 2026-10-11 · **Price:** $385.45 (FMP `profile-symbol`, 2026-10-11) · **Fiscal year ends:** September
**Run through:** `company-analysis` skill, Step 0b branch 2 (per-share figures reported only per share class). The share count comes from `av_financials` (v0.13.0, BACKLOG item 31)

## Verdict

**24/30 — solid (> 20).** Criterion 9 is now confirmed from a reported share count (Alpha Vantage,
2.457bn FY2015 → 1.966bn FY2025, down every year), no longer derived. It loses points on yield (0.70%,
below the S&P 500) and on FCF consistency (4 declines in 10 years). The dividend is not at risk: FCF
payout ~22%. **Valuation, all five mean-reversion methods: $276-$373, average $321 against
$385.45** - about 20% above the historical-multiple estimate. The spread is moderate ($97), and every
method points the same way.

## Step 0b result

`eps_diluted` and `shares_diluted` came back empty with the per-share-class note (BACKLOG item 17).
`net_income`, `revenue`, `operating_income`, cash flow and balance-sheet concepts resolved normally.
Scoring proceeds. Since 2026-10-11, methods 2-5 run on `shares_outstanding` from `av_financials`.
That count is already split-adjusted, so no split factor applies. It checks against Visa's GAAP
diluted EPS: net income / count = 5.63 / 7.00 / 8.28 / 9.73 / 10.20 for FY2021-2025.

## Data corrections applied by hand

1. **`dividend_per_share_declared` is a quarterly rate, not an annual one.** Visa files an
   annual-duration fact (frame `CY2025`, 2024-10-01 to 2025-09-30) whose value, 0.59, is the
   per-quarter dividend. The winning tag `CommonStockDividendsPerShareCashPaid` also carries pre-2015
   values on the pre-split basis (0.33, 0.40 before the 4:1 split of 2015-03-19). FY2018 is missing
   because no single annual fact exists (0.195 in Q1, 0.21 thereafter). Annual DPS used below is
   quarterly rate x 4, split-adjusted, with FY2018 = 0.195 + 3 x 0.21.
2. **Balance-sheet values taken at the fiscal year end (Sept 30), not at Dec 31.** `edgar_financials`
   picks the `CY####Q4I` frame, which for a September filer is the Dec 31 balance from the next
   fiscal year's first 10-Q. Debt to capital reads 35.3% that way against 39.9% at fiscal year end.

| FY | Annual DPS | Avg price (FY) | Yield |
|---|---|---|---|
| 2013 | 0.33 | 41.51 | 0.795% |
| 2014 | 0.40 | 52.97 | 0.755% |
| 2015 | 0.48 | 66.37 | 0.723% |
| 2016 | 0.56 | 77.17 | 0.726% |
| 2017 | 0.66 | 90.18 | 0.732% |
| 2018 | 0.825 | 125.68 | 0.656% |
| 2019 | 1.00 | 156.20 | 0.640% |
| 2020 | 1.20 | 187.76 | 0.639% |
| 2021 | 1.28 | 219.63 | 0.583% |
| 2022 | 1.50 | 210.26 | 0.713% |
| 2023 | 1.80 | 223.35 | 0.806% |
| 2024 | 2.08 | 266.69 | 0.780% |
| 2025 | 2.36 | 333.23 | 0.708% |
| 2026 | 2.68 | 337.52 | 0.794% |

FY2026 DPS (0.67 quarterly) comes from the 2025-10-28 8-K and FMP `lastDividend`; the FY2026 10-K is
not filed yet.

## Scoring

| # | Criterion | Pts | Evidence |
|---|---|---|---|
| 1 | Growth years | 3 | EDGAR confirms increases FY2013 to FY2025, plus FY2026 (8-K) = 13; secondary source gives 18 since the 2008 IPO; the sheet says 17 |
| 2 | Yield vs S&P 500 | 1 | 2.68 / 385.45 = 0.70% (2026-10-11; 0.74% at $360.66 on 2026-10-04) against ~1.0-1.2% |
| 3 | DGR, low-yield bucket | 3 | 5y 15.9% (FY2021 to FY2026) |
| 4 | Earnings and payout | 2 | GAAP EPS (net income / Alpha Vantage count): 2 declines in 10 years (FY2016 2.48 from 2.58, FY2020 4.89 from 5.32). Payout 2.36 / 10.20 = 23.1% (FY2025) |
| 5 | FCF and FCF payout | 1 | Payout 21.5% (FY2025), but 4 declines in 10 years (2016, 2019, 2020, 2024) |
| 6 | Debt to capital | 2 | 39.9% at 2025-09-30; 32-40% since 2016 |
| 7 | ROE | 3 | 52.9% (FY2025); ROIC approx. 31.8%, rising from 18% in 2016 |
| 8 | Operating margin | 3 | 60.0% (FY2025), down from 64-66% in 2019-2024 |
| 9 | Share count | 3 | Alpha Vantage `shares_outstanding` 2.457bn (FY2015) → 1.966bn (FY2025), down every year. That confirms the earlier derivation (dividends paid / DPS). Buybacks $18.3bn in FY2025 |
| 10 | Credit rating | 3 | S&P AA- (affirmed April 2025), Moody's Aa3; outlook not found |

**Deceleration signal:** DGR 1y 13.6% < 3y 14.2% < 5y 15.9% < 10y 17.0%, strictly decreasing.

## Dividend safety

Payout ~23% of net income and ~22% of FCF. In FY2020 net income fell 10% and FCF 19% while the
dividend rose 20%. A cut would need a regulatory or litigation shock that takes cash flow below
~$5bn a year. The FCF declines are small (2019: -1.6%, 2024: -5%).

## Valuation

Redone 2026-10-11 with all six methods.
- **Prices:** `price_annual_averages`, fiscal years ending September; `verification` = `consistent`.
  A single, uncorroborated source (Tiingo).
- **Totals:** EDGAR (net income, operating income, OCF, capex).
- **Share count:** Alpha Vantage `shares_outstanding`, already split-adjusted.
- **Dividends:** `price_dividends`, on the same basis as the prices.
- **Window: FY2013-FY2025, 13 years.** Alpha Vantage's FY2011-2012 counts (4.09bn, 3.86bn) are on a
  different basis: net income over them gives $0.89 and $0.56 against GAAP EPS of about $1.29 and
  $0.79. From FY2013 they agree ($1.90).
- **Current multiples** use FY2025, because the FY2026 10-K is not filed yet (due mid-November).
  Against trailing twelve months they are somewhat overstated.

| Method | Estimate | Applicable | Note |
|---|---|---|---|
| Dividend Yield Model | $373 | yes | historical yield 0.718% (FY2013-FY2026) vs current 0.695% ($2.68 / $385.45); ratio 1.033, guard not triggered |
| Historical P/E | $304 | yes | mean 29.8x vs current 37.8x (FY2025 GAAP EPS $10.20); 10y mean 31.6x → $322 |
| Historical P/EBIT | $276 | yes | 22.6x vs 31.6x (EBIT/share $12.20); 10y → $298 |
| Historical P/OpCF | $325 | yes | 27.7x vs 32.9x (OpCF/share $11.73); 10y → $329 |
| Historical P/FCF | $328 | yes | 29.9x vs 35.1x (FCF/share $10.98); 10y → $329 |
| Gordon Growth | $46-$70 | no | r = 9%, g = 3-5%; inapplicable to a 13-16% dividend grower |

**Average (5 methods): $321. Range $276-$373** (13y window); about $330 with 10-year means.
**Target at a 12% margin: ~$283. Current $385.45, about 20% above the average estimate.**

- **The spread is moderate and the methods agree in direction.** Weiss sits highest because the yield
  has barely compressed: Visa raises its dividend about as fast as the price rises. P/EBIT sits lowest:
  FY2013-2015 multiples of 15-18x come from a smaller business before Visa Europe (2016).
- **Mean reversion holds better here than for AAPL.** The business model has not changed; it has
  scaled. Even so, the early years pull the means down, which is why the 10-year window reads $20-25
  higher.
- **Two data-quality notes:**
  - FY2012 net income ($2.1bn) is depressed by the litigation provision.
  - FY2013 OCF ($3.0bn) is depressed by the settlement payment, which inflates P/OpCF and P/FCF for
    that year (36x and 43x).
- **EDGAR and Alpha Vantage disagree on OCF for FY2017-2018** (9.317 / 12.941bn vs 9.208 / 12.713bn).
  EDGAR's figure is the one restated in later 10-Ks, and it is the one used here.

## Risks

1. **Interchange regulation** (Credit Card Competition Act, DoJ debit antitrust suit). Monitor:
   operating margin and net revenue yield.
2. **Interchange litigation.** The FY2025 margin dip likely reflects litigation provisions, not
   verified in this run. Monitor: provisions and escrow in the 10-K.
3. **Alternative rails** (instant payments, stablecoins). Monitor: payments volume growth.

## What's next

Q4 FY2026 results and the dividend announcement usually come at the end of October (date not
verified). Check whether the raise falls below 13% and the size of litigation provisions.

