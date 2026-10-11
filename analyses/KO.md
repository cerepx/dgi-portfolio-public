# KO — The Coca-Cola Company

Analysed 2026-07-31 with `company-analysis`. **Score 20/30.** Valuation
recomputed 2026-08-18 with `price_annual_averages` — see *Valuation* below;
everything else on this page is unchanged from the original analysis.

## The FCF question — resolved

The apparent free-cash-flow collapse is **two separate one-offs in consecutive
years, not structural erosion.** The earlier working guess was half right and
incomplete:

| Year | Operating-cash outflow | What it was |
|---|---|---|
| 2024 | ~$6.0bn | IRS transfer-pricing litigation deposit |
| 2025 | $6.069bn | fairlife final contingent-consideration milestone, paid March 2025 |

FCF payout reported 176% (2024) and 166% (2025); adjusted for the two items,
**77.8% and 77.2%** — in line with 2022-23 (79.9%, 81.6%).

**The finding that survives the adjustment:** even normalised, FCF payout sits
above the 70% line, so criterion 5 scores 1 point either way, and the trend
across 2021-2025 is upward (64% → 77%). Coverage is real but thinning.

## Second warning, independent of the cash flow

**DGR is decelerating** — 5.43% (2024), 5.15% (2025), 3.92% (2026). The 2026
raise is the smallest in the five observable years. `incomeQuality`
(OCF / net income) fell 1.29 → 0.57 across the same window; part of that is the
one-offs, part is not.

## The contingent risk

The IRS case is on appeal, with up to **$14bn** of aggregate incremental tax and
interest exposure for 2010-2025 under the Tax Court methodology, on top of the
$6.0bn already deposited. Reserve was $529m as of 3 July 2026.

**An adverse ruling is the one event that would put the dividend in play.**

## Valuation — recomputed 2026-08-18, proper 14-year window

Superseded the 2026-07-31 5-year, ad-hoc-source figure below it. This run used
`price_annual_averages` (dgi-prices, v0.5.2) for the numerator and
`edgar_financials` for the denominators. `verification.verdict: consistent`.
`incomplete_years` excluded 2011 (window-truncated, 102 bars) and 2026 (in
progress) — 14 complete years, 2012-2025, inside the 10-15 spec.
The split factor is 1.0 for every year used, and this was **re-verified
2026-08-29 after BACKLOG item 16** found that the factor had been keyed on the
fiscal year instead of the EDGAR fact's filing date, which was wrong for the
2-3 years before any split. KO's 2:1 split was 2012-08-13 and the window starts
at 2012, whose fact was filed 2015-02-25 — after the split, so already on
today's basis. Both the old key and the corrected one give 1.0 for every year
in the average, so **this valuation is unaffected and its conclusion stands.**
Had the window reached back to 2010 or 2011 it would not have.
Current price **$88.74**, current indicated dividend **$2.08**.

**A real distortion turned up and had to be handled, not averaged blind:**

| Method | Needs a fix? | Why |
|---|---|---|
| P/E | **yes** | 2017 diluted EPS was $0.29 against ~$1.50 either side — the one-time hit from the 2017 US tax reform. Included raw, the historical P/E average comes out 34.3x and the method flips to "undervalued." Excluded, it is 25.2x and the method reads "overvalued," agreeing with the other four. **The raw number is presented only to show the size of the trap; the excluded figure is the one used in the average.** |
| P/OpCF, P/FCF | **yes** | The same 2024 IRS deposit (~$6.0bn) and 2025 fairlife milestone ($6.069bn) already identified above under *The FCF question* depress OpCF and FCF in exactly the two most recent years — which are also the years the *current* multiple is built from. Left raw, current P/OpCF hits 51.7x and current P/FCF hits 72.3x against historical averages in the low-to-mid 20s, and the method inverts to "70%+ undervalued," which is the cash-flow distortion, not the price. Both years are added back by the same amounts used in the FCF-payout adjustment above before computing the ratios. |
| P/EBIT | no | Operating income is unaffected by either distortion — this method is the clean cross-check the other two needed. |
| Dividend Yield (Weiss) | no | Dividend was never cut or frozen in the window. |

| Method | Estimate | Applicable | Note |
|---|---|---|---|
| 1. Dividend Yield Model | $67.42 | yes | historical yield 3.09% (2012-2025), current yield 2.34% |
| 2. Historical P/E | $76.48 | yes | 2017 excluded as a one-off (see above); raw-including-2017 figure was $104.23 and is not used |
| 3. Historical P/EBIT | $69.80 | yes | no adjustment needed |
| 4. Historical P/OpCF | $65.55 | yes | 2024/2025 one-offs added back; raw-distorted figure was $40.59 and is not used |
| 5. Historical P/FCF | $68.72 | yes | same two years adjusted; raw-distorted figure was $37.50 and is not used |
| 6. Gordon Growth | $34.67 - $52.00 | yes, input-wise | r = 9%, g = 3-5%. Numerically a clear outlier below the other five — plausible reading: r = 9% is aggressive against KO's ~2.3% yield plus mid-single-digit growth, not that the stock is 40%+ overvalued beyond what the other methods already say |

**Average of methods 1-5 (post-adjustment): $69.59. Range: $65.55 - $76.48.**
**Target price at 12% margin: ~$61.24. Current price: $88.74 — roughly 45%
above target, 27% above the average estimate.**

Gordon Growth is reported separately per its own convention and is not folded
into the five-method average; including it would widen the range to
$34.67-$76.48 without changing the direction of the conclusion, since every
method - adjusted or not - reads overvalued.

**This confirms, on a proper 14-year window with real prices, the same
direction the 2026-07-31 ad-hoc 5-year estimate found** (see below): KO reads
overvalued at $88.74, by a similar magnitude (~22-27% depending on which
average is used). The two estimates should not be expected to match exactly -
different windows, and the July estimate did not have this run's one-off
adjustments - but landing in the same range from an independent calculation is
the kind of corroboration this project doesn't otherwise have on the price
side (see `source_note`: single, uncorroborated price provider).

**Caveat that applies to every number above:** `price_annual_averages` has one
source, Tiingo, with no second provider. `verification` confirms internal
consistency (our split arithmetic against Tiingo's own adjusted close), not a
second source - it would not catch an error in Tiingo's own feed.

### Original valuation note, 2026-07-31 — superseded, kept for the comparison above

Computed over a **5-year window, not the 10-15 years the method specifies** —
state this whenever the figures are quoted.

Five mean-reversion methods cluster at **$67.90-$77.22, average $72.35**, against
a price of **$88.49** — roughly **22% above estimated fair value**. Gordon Growth
is a far-off outlier ($35-53 at r=9%) and was excluded from the average.

## What to watch

- Q3 2026 results
- The IRS appeal ruling
- The February 2027 raise — a fourth consecutive deceleration would change the
  DGR picture from "slowing" to "trend"

No decision taken. Not a recommendation.
