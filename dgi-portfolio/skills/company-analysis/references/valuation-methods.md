# Price valuation - 6 methods

From *"Cum analizez o companie"* (Dividende.blog).

Shared assumption behind all six: **over the long run the market tends to value a
company correctly, so multiples revert to their historical mean.** The author's
line: *"if you ask me which is the best method, I will tell you to use all of
them."*

No method is guaranteed. Every output is "possibly overvalued / possibly
undervalued", never "it is worth X".

---

## Price source: `price_annual_averages`

**Unblocked 2026-08-18.** The `dgi-prices` MCP tool (`price_annual_averages`)
returns split-adjusted annual average close prices, reduced from a daily Tiingo
series on the host so the ~3,800 daily rows never reach the conversation. One
call per ticker; set `fiscal_year_end_month` for filers that do not close in
December (INTU closes in July) so the average lines up with the EDGAR fiscal
year it is paired against.

Three things every response carries, and all three are mandatory to check
before using the numbers:

- **`incomplete_years`** — exclude every year listed here from any historical
  mean. It splits "still in progress" (the current year, before the fiscal
  year end) from "truncated by the start of the window" (the oldest year, if
  the 10-15 year lookback starts mid-year). Averaging an in-progress year into
  a 15-year mean drags the mean toward today's price — this was a real bug,
  fixed in v0.5.1, and the exclusion is what fixes it, not just the bar count.
- **`verification.verdict`** — must read `consistent`. It checks the
  split-only series against Tiingo's own `adjClose`; if it does not say
  `consistent`, do not report a valuation from that ticker's series until the
  discrepancy is understood.
- **`split_factor_by_filing_date`** — multiply an AS-FILED per-share figure
  from `edgar_financials` (EPS, EBIT/share, OpCF/share, FCF/share, and the
  dividend per share the Weiss model divides by) by this before dividing a
  price by it. For the dividend, also read `quality.per_payment_rate` first:
  in the years it lists, the figure is one payment, not the year's total. **Key it on the figure's `filed` date, which
  `edgar_financials` returns per year, NOT on the fiscal year.** Take the first
  table row whose `filed_before` is later than that date and use its `factor`;
  no row matches means `1.0`.

  Two ways to get this wrong, and both are the same size — the full split
  ratio:

  1. **Skipping it.** MA, V, KO and NEE all split inside the window.
  2. **Keying it on the year.** EDGAR restates the last few years in every
     10-K, so the fact that wins for a year is usually filed about three years
     later and the 2-3 years before a split are ALREADY post-split. Rescaling
     them again gave MA 2013 a P/E of 240 instead of 24. This is not
     hypothetical — it was the shipped behaviour until 2026-08-29. See BACKLOG
     item 16.

**`source_note` on every response says this is a single, uncorroborated
source.** Yahoo and Stooq were tried and dropped — both sit behind an anti-bot
wall from a normal connection — so there is no second price provider behind
this one. `verification` checks internal consistency (our arithmetic against
Tiingo's own adjusted close), not a second source; it cannot catch an error
Tiingo itself made. Carry that caveat into any report built on these prices.

---

## When the core assumption breaks

Mean reversion assumes today's business is comparable to the one from 10-15 years
ago. That fails when:

- The company moved from growth into structural decline (`MO`, tobacco).
- A major spin-off changed the perimeter (`T`, `GE`, `JNJ`/Kenvue).
- The business model changed fundamentally.
- A rate regime shift permanently reset sector multiples (utilities, REITs after
  2022).

In these cases all five mean-based methods read artificially cheap, because the
average includes years of a company that no longer exists. **Say so explicitly**,
then shorten the window to 5-7 years or rely only on Gordon Growth.

---

## 1. Dividend Yield Model (Geraldine Weiss)

From *"Dividends Don't Lie"*. The author's preferred method for long-history
dividend payers.

Steps:

1. Call `price_annual_averages` for 10-15 years of annual average prices (see
   *Price source* above). Exclude any year listed in `incomplete_years`.
2. The tool already computed the average price for each complete year.
3. For each year: `yield = total dividend paid that year / average price`.
   `price_dividends` gives that total per fiscal year on the same share basis
   as the prices, so no split factor applies. Exclude its `incomplete_years`
   and any confirmed `outsized_payments` first.
4. Average those 10-15 yields into the `historical yield`.

```
Estimated price = Current price / (historical yield / current yield)
```

**Mandatory denominator guard:** if `historical yield / current yield < 0.8`, use
`0.8`. A large recent dividend increase otherwise distorts the result.

Worked example from the article: current yield 3.5%, historical yield 4%, price
$100. `100 / (0.04 / 0.035) = $87.50` - possibly overvalued by $12.50.

Applicability: best method for Champions and Contenders with a stable, rising
dividend. Unusable if the dividend was cut or frozen inside the window, because
the average loses meaning.

## 2. Historical P/E

1. For each of the last 10-15 years: `P/E = average annual price / (as-filed
   EPS x split factor)`. Get the factor by looking that year's `filed` date
   (from `edgar_financials`) up in `split_factor_by_filing_date` (from
   `price_annual_averages`). **The lookup key is the filing date, not the
   year** — see *Price source* above for why that distinction is worth this
   much ink.
2. Average them into the `historical P/E`.
3. `current P/E = current price / last reported EPS`.

```
Estimated price = Current price / (current P/E / historical P/E)
```

**Denominator guard:** if `current P/E / historical P/E` is below 0, use `1.5`
(equivalent to cutting the current price by about 33%). Negative EPS otherwise
produces absurd values.

Worked example from the article: current P/E 8, historical P/E 12, price $100.
`100 / (8/12) = $150` - possibly undervalued by $50.

Trap: use **normalised** EPS if the latest year carried large exceptional items
(litigation, impairment, gains on asset sales). A single distorted year moves the
estimate by tens of percent. Check the gap between GAAP and adjusted EPS and state
which you used.

## 3. Historical P/EBIT

Identical to method 2 with `EBIT per share` instead of EPS.

```
Estimated price = Current price / (current P/EBIT / historical P/EBIT)
```

Same guard: below 0, use `1.5`.

Why in addition to P/E: EBIT sits before interest and taxes, so it strips out
changes in capital structure and effective tax rate. Particularly useful after tax
reforms (US 2017) that moved EPS without changing the business.

## 4. Historical P/Operating Cash Flow

```
Estimated price = Current price / (current P/OpCF / historical P/OpCF)
```

Guard: below 0, use `1.5`.

More stable than P/E because OpCF is unaffected by non-cash depreciation and
amortisation. **The reference method for REITs** and capital-intensive companies,
where EPS is systematically distorted by depreciation.

## 5. Historical P/Free Cash Flow

```
Estimated price = Current price / (current P/FCF / historical P/FCF)
```

Guard: below 0, use `1.5`.

The most conservative multiple - FCF also subtracts capex. Companies in a heavy
investment cycle (utilities building capacity) look expensive here even when the
investment is rational. Check whether capex is growth or maintenance before
concluding.

## 6. Gordon Growth Model

Simplified variant of the Dividend Discount Model.

```
Value = D1 / (r - g)
```

- `D1` = expected dividend over the next 12 months
- `r` = required rate of return (typically 8-10%; use the same value across every
  company you compare, otherwise the comparison is meaningless)
- `g` = perpetual dividend growth rate

Mandatory constraints:

- `g` must be **strictly less** than `r`, or the formula returns negative or
  infinite values.
- `g` cannot durably exceed nominal GDP growth - use 2-5%, not the 5-year DGR. No
  company grows 12% a year forever.
- Extremely sensitive: at `r = 9%`, moving `g` from 3% to 4% raises the value by
  about 20%. Report a **range** across 2-3 values of `g`, never a single number.

Applicability: mature companies with a predictable dividend only. Unusable for
high or irregular growth.

---

## Discounted Cash Flow - why it is excluded

The author considers DCF the most popular method and still dislikes it: too many
assumptions, and the numbers swing too much. *"A single 1% and the price nearly
doubles."*

His own worked example, from the article, using the moneychimp calculator:

| Input | Run A | Run B |
|---|---|---|
| EPS (last 12 months) | $6.62 | $6.62 |
| Growth, next 5 years | 15% | 15% |
| Terminal growth thereafter | **8%** | **9%** |
| Discount rate | 10% | 10% |
| **Stock value per share** | **$484.35** | **$939.07** |

One percentage point on terminal growth moved the valuation by 94%. That is the
whole argument.

Nobody knows what a company looks like in 3-5 years. The author's compromise: if
DCF is needed, use a simple calculator
(`moneychimp.com/articles/valuation/dcf.htm`) for a rough figure rather than a
complex model that merely hides the arbitrariness of the assumptions.

**Do not include DCF in the average of the six** unless the user explicitly asks.
If they do, report a sensitivity range, never a point estimate.

---

## Synthesis

1. Compute all six estimates. Skip inapplicable methods and **say which and why**
   - never fill a gap with an invented value.
2. Average the applicable methods.
3. **Report the dispersion.** Min, max, spread. If estimates run from $60 to $180,
   an average of $120 is not an estimate, it is an illusion of precision. Say so
   directly and explain which methods diverge and why.
4. Apply the safety margin: **target price = estimated price x 0.85 to x 0.90**
   (10-15% below the estimate).
5. Compare against the current price and report the gap in percent.

The author's caveat, worth keeping: there is no point haggling over a few dollars
if you are holding the company long term and the outlook is good. The safety
margin is a guide, not a mechanical gate.

## Reporting format

| Method | Estimate | Applicable | Note |
|---|---|---|---|
| Dividend Yield Model | $87.50 | yes | historical yield 4.0% (2011-2025) |
| Historical P/E | $150.00 | yes | normalised EPS, 2023 impairment excluded |
| Historical P/EBIT | $111.00 | yes | |
| Historical P/OpCF | $98.00 | yes | |
| Historical P/FCF | - | no | FCF negative 2022-2023, capex cycle |
| Gordon Growth | $95 - $112 | yes | r = 9%, g = 3-4% |

**Average (5 applicable methods): $110. Range: $87 - $150.**
**Target price at 12% margin: $97. Current price: $104.**

The $63 spread between lowest and highest comes from the divergence between P/E
(suggesting undervaluation) and the Dividend Yield Model (suggesting
overvaluation) - a sign that yield compressed faster than the P/E did, meaning the
price rose faster than the dividend.
