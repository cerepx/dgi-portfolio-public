---
name: company-analysis
description: >
  This skill should be used when the user asks to "analyze [ticker]",
  "score this company", "DGI analysis", "is [ticker] a buy", "check the
  dividend for [ticker]", "how safe is the dividend", "what score does
  [ticker] get", or - in Romanian - "analizeaza [ticker]", "analiza
  companie", "e bun [ticker] de cumparat", "ce scor are [ticker]",
  "verifica dividendul la [ticker]", "cat de sigur e dividendul". Also
  triggers on any request for a dividend-growth-investing assessment
  covering financials, valuation, competitive position, risks, earnings or
  dividend safety. Applies the Dividende.blog 10-criteria scoring system
  (max 30 points, floor 10) plus six price valuation methods.
metadata:
  version: "0.2.0"
---

# Company analysis - dividend growth investing

Assess a company through a DGI lens: how safe the dividend is, how likely it is to
grow, and whether today's price is worth paying.

Conversation with the user is in Romanian. Everything written to disk - reports,
code, file names - is in English.

## What makes this different from generic stock analysis

Three differences that change the conclusions:

1. **The dividend is the thesis, not a bonus.** A weak quarter is not a sell
   signal. The only sell signal is imminent danger of a dividend cut.
2. **Cash flow beats earnings.** A good accountant can make the balance sheet look
   good. They cannot invent the cash the dividend is paid from. When EPS and FCF
   disagree, FCF is right.
3. **Price is a separate decision from quality.** The best company in the world
   bought too expensively delivers poor returns. Score and valuation are reported
   separately and never blended into one number.

## Step 0 - is this even a DGI position

Read `${CLAUDE_PLUGIN_ROOT}/config/portfolio.json` first.

If the ticker sits in `blocks.non_dgi` (`PLTR`, `META`, `SXR8`, `BVBETF`), the
10-criteria scoring **does not apply**. These are tracking-only positions - some
pay no dividend, others pay one with no DGI history worth scoring. Their empty
dividend cells are intentional.

For a non-DGI position, report: price, position value, cost, profit, weight in the
total portfolio, and the business in brief. Then say plainly that DGI scoring does
not apply and why. Do not fabricate a score by treating a missing dividend as a
1-point criterion - that produces a meaningless 10/30.

If the user asks to score a non-DGI holding anyway, ask whether they want to move
it into the DGI block first, since scoring it implies it belongs to the strategy.

## Step 0b - can EDGAR answer for this filer at all

**Check this before the cascade, not after.** BACKLOG items 11 and 17. Both
failures below produce a confident-looking low score if you walk the whole
analysis first and only then discover the source was empty.

Make one `edgar_financials` call for a cheap concept and **read the `note` on
an empty series**. It now names which of three situations you are in:

**1. "No us-gaap facts at all" - a foreign private issuer filing under IFRS.**
BCS (Barclays) is the measured case: `edgar_lookup` resolves it, prices work,
and every single `edgar_financials` concept comes back empty because the filer
publishes only `ifrs-full` facts. There is **no alternate tag to find**;
`edgar_tags` will show you 476 IFRS tags that this plugin cannot read.

**Stop and say so.** Do NOT walk the cascade applying "unavailable, score 0,
report the reduced maximum" - that yields something like `12/21`, which reads
as a weak company and actually means an absent source. Report: the ticker is in
scope (it is US-listed), the business in brief, the price data that does work,
and that the 10-criteria score **cannot be computed from EDGAR**, naming IFRS
as the reason. Offer the corroboration path item 2 used for growth streaks if
the user wants to proceed by hand.

**2. "reports per-share figures only per share class" - V (Visa).** The us-gaap
facts are there, but `EarningsPerShare*` and every weighted-average share count
are reported per share class, and SEC `companyfacts` omits dimensioned facts.
`net_income` and `revenue` resolve normally.

Here the **10-criteria score still works**. The per-share figures come from
**`av_financials`** (`dgi-alphavantage`, since v0.13.0): `shares_outstanding`
for the count, and `eps_from_net_income` (GAAP; V FY2025 $10.20) for EPS. The
count is already on today's split basis, so it takes **no** split factor. Take
EBIT, OpCF and FCF from EDGAR as usual and divide them by that count; then
methods 2-5 run. **Read `quality.count_basis_suspect` first**: V's FY2011-2012
counts are on another basis, so the window starts at FY2013. **Never use
`eps_reported`**: it is street EPS (V FY2025 11.47). Say in the report that the share count came from Alpha Vantage. Without
a key in `~/.dgi/alphavantage.json`, fall back to the old rule: score the
company, and say the historical multiples are unavailable rather than
producing four of six methods.

**3. An ordinary missing tag.** Only here is `edgar_tags` worth running, and
only a `us-gaap:` tag can be passed back to `edgar_financials`. This is the ZTS
case from 2026-08-01, and it is the one that gets fixed by finding the tag.

## Step 1 - one ticker at a time

If the user gives several tickers, or asks to "analyse the portfolio", **do not
analyse everything**. List them, say each full analysis is substantial, and ask
which to start with. Use `AskUserQuestion`.

If the ticker is in the portfolio, read its row: shares, average cost, dividends
received, growth years, weight. An existing position changes the question from
"worth buying?" to "worth holding, adding, or trimming?".

## Step 2 - data

**Read `references/data-sources.md` before the first API call.** It carries the
`edgar_financials` concept and the arithmetic for every criterion, the measured
boundary of what FMP still serves, and the FMP-to-GICS sector translation.
Working from memory here produces wrong concept names and calls into a wall.

The six facts that shape every analysis:

1. **`dgi-edgar` is the source for financial statements, not FMP.** Changed
   2026-08-01. The `edgar_financials` tool returns annual series straight from
   SEC XBRL filings: free, no key, and the full filed history rather than a
   five-year window. Ask only for the concepts you need; it returns a few dozen
   numbers, never the raw payload.
2. **FMP gates fundamentals PER SYMBOL and cannot be relied on.** Measured
   2026-08-01 across a 17-ticker sample: `income-statement` returned HTTP 200 for
   only **KO, JNJ, ABBV, V** and HTTP **402** for the other thirteen, including
   ZTS. The `statements`, `analyst` and `discountedCashFlow` tool families are
   denied outright through the connector. `company` / `profile-symbol` and
   `quote` still work, so FMP survives only as a price and profile source.
   **Never plan an analysis around FMP statements.**
3. **XBRL tag mapping is per company, and an empty series has THREE causes.**
   `edgar_financials` ranks every `(tag, unit)` pair in the chain and reports
   the tag AND unit it used. An empty series is not automatically a tag outside
   the chain - read its `note`, which distinguishes an IFRS filer, figures
   reported only per share class, and an ordinary missing tag. **Only the third
   is worth hunting**; see Step 0b. Call `edgar_tags` with a substring for that
   case, then use the raw tag directly. ZTS
   needed exactly this for `dividends_paid` and does not report
   `OperatingIncomeLoss` at all, so EBIT had to be derived as pretax income plus
   interest expense.
4. **FMP's sector names are not GICS.** Translate through `fmp_sector_to_gics` in
   the config before comparing with the sheet.
5. **dripinvesting.org is now the cross-check, not the primary source, for
   dividend history.** `dividend_per_share_declared` from EDGAR gives the
   declared rate per year from the filings, which resolves the growth streak and
   DGR from primary source. Three traps in the CSV, all verified: `Stock Type`
   is a bucket that cannot score a Contender on criterion 1; its prices are
   unreliable, one off by 52%; and **`DGR` can be plain wrong** - it reported
   ZTS at `DGR 1Y -19.3%` when the filings show **+13.0%**.
   **Never take a price, yield or valuation input from that file, and never let
   a negative DGR from it disqualify a company without corroboration.**
   **`price_dividends` (`dgi-prices`) is the second dividend source**, added
   v0.12.0: the `divCash` on the same Tiingo daily rows as the prices, summed
   per fiscal year by ex-date, already split-adjusted. Use it to corroborate
   the EDGAR series; on AAPL it matched FY2018-FY2025 exactly. Use it instead
   of EDGAR in three cases: an IFRS filer (EDGAR has no dividend at all), a
   `per_payment_rate` filer (V), and **the newest fiscal year when its 10-K
   is not filed yet**. AAPL's 5Y DGR read 5.11% on EDGAR's FY2025 and 4.51%,
   in the `NO` band, on the FY2026 that only `price_dividends` had. **Score
   criterion 1 and 3 on the latest complete fiscal year either source has**,
   and say which one. Read its `quality` first: `outsized_payments` are
   possible specials (Tiingo does not mark them) and must be confirmed and
   excluded before any DGR. BCS 2013-09-19 shows $1.57 against ~$0.06
   payments around it.
6. **READ `quality` BEFORE USING ANY SERIES.** `edgar_financials` returns it
   only when a defect survives its choice of tag, so its presence always means
   something. Each key changes what you may compute:
   - `non_usd_unit` - the numerator is not USD. Every price here is USD, so any
     multiple against it is **wrong**, not approximate. Do not report one.
     Share counts (unit `shares`) are exempt: a count is never the numerator of
     a price multiple, so "not USD" says nothing about it.
   - `stale` - the filer stopped reporting this tag. A growth streak or DGR off
     it is wrong by exactly the missing years.
   - `interior_gaps` - years missing mid-series. A consecutive-years count
     across a gap is meaningless; say the streak cannot be confirmed rather
     than counting through it.
   - `zero_values` / `negative_values` - a growth ratio here is **undefined**,
     not imprecise. These are normally real (pre-dividend years, genuine loss
     years), so do not call them data errors: start the window after them, or
     say the metric cannot be computed. INTU, ZTS, QCOM, MO, MA, GPC and ARE
     all carry them.
   - `per_payment_rate` - on `dividend_per_share_declared` only. In the listed
     `years` the "annual" figure is ONE payment's rate, as the filer tagged it
     (V: 0.59 for a year that paid 2.36). Any yield, payout or Weiss input
     from it is wrong by the payment count: multiply by `payments_per_year`
     first. Growth ratios inside the listed years are fine; never across into
     an unlisted year, which is unproven rather than annual. The values are
     never rewritten - the flag is the fix (BACKLOG item 25).
   - `count_jumps` - on share counts only. A year where the count moves
     1.9x or more is a split, not issuance: counts are as filed, so AAPL reads
     5.25bn for FY2017 (filed before the 4:1 split) and 20.0bn for FY2018.
     **Per-share figures are MULTIPLIED by the split factor; a share count is
     DIVIDED by it**, keyed on the same `filed` date. Do this for criterion 9
     on every ticker with a split in the window, flagged or not: a 3:2 split
     stays under the threshold. For methods 3-5, divide the total (EBIT, OpCF,
     FCF) by the as-filed count, then multiply by the factor (BACKLOG item 29).

   `alternatives` lists the `(tag, unit)` candidates that lost. It exists so a
   choice is visible rather than assumed - worth a glance when `quality` is
   non-empty, because a shorter but cleaner series is sometimes the better
   input, and saying which one you used is part of the report.

Source order:

| What | Where |
|---|---|
| EPS, revenue, cash flow, capex, debt, equity, share count, dividends paid | `edgar_financials` |
| Declared dividend per share, growth streak, DGR | `edgar_financials` → `dividend_per_share_declared`, corroborated by `price_dividends` |
| Share count and GAAP EPS where EDGAR has none (V); a check on the EDGAR reader | `av_financials` (`dgi-alphavantage`): same SEC filings, so it corroborates our tag and date choice, never the filing. Read each concept's `note` |
| Dividends where EDGAR has none, or not yet | `price_dividends` (`dgi-prices`): IFRS filers, `per_payment_rate` filers, a fiscal year whose 10-K is not filed |
| A concept that came back empty | **Read its `note` first** — see Step 0b. Only an ordinary missing tag is worth hunting with `edgar_tags` |
| Sector, industry, current price, last dividend | `company` / `profile-symbol` |
| Chowder, payment frequency, DGR cross-check | dripinvesting screener CSV in the working folder |
| Next ex-date and pay date | dripinvesting monthly calendar |
| Credit rating and outlook, S&P 500 yield | `WebSearch` |
| Annual average prices for the valuation methods | `price_annual_averages` (`dgi-prices` MCP tool) - see step 5 |

**The screener CSV is a manual download.** The button on
<https://www.dripinvesting.org/stocks/> builds the file client-side, so there is
no URL to request. The user clicks it and drops the file in the working folder.
`web_fetch` on that page returns only the first ~66 of ~690 rows - the table
paginates in the browser, so never treat a fetch of it as the full list.

If no CSV is present, fall back to the per-stock page for the ticker being
analysed, which is fetchable and richer. Only if both are unavailable, take growth
years from the sheet's `Ani creștere` column and **flag it as unverified** - it is
hand-entered, and on 2026-07-31 it was three years stale for KO.

Rules:

- FMP is a **connector**. Discover its tools with `ToolSearch`; the server uuid in
  the tool names differs per installation, so never hardcode it. If no FMP tools
  appear, the connector is not connected - say so and fall back to `WebSearch` plus
  sec.gov with data marked unverified. Do not ask for an API key.
- **Never invent a figure.** If an indicator cannot be found, write "unavailable",
  score 0, and note that the maximum dropped. Report `18/27 (3 criteria without
  data)`, never `18/30`.
- **Report the window you actually used.** A 5-year average multiple is not the
  10-15 year mean the method specifies, and 5 years starting in 2021 is an unusual
  slice of market history to mean-revert against. Say it rather than presenting the
  number as if it were a long-run average.
- For any indicator deciding a 1 versus 3, verify in a second source. Dividend data
  differs between providers more often than expected.
- Record the period each figure refers to. "Payout ratio 58%" without a year is
  meaningless.
- Budget roughly **2-4 EDGAR calls, 1 FMP call and 2-4 searches** per company.
  **Ask `edgar_financials` for every concept you need in one call** - it takes a
  list, and one call for ten concepts costs the same round trip as one. Asking
  per concept is the main way to waste the budget. EDGAR has no daily quota (10
  req/sec per IP) and caches facts for 24h, so re-analysing the same company the
  same day costs no network at all.
- One ticker at a time. The reason is no longer a call quota - it is that a
  ten-year series per concept is a context cost, and the scoring needs the
  evidence visible while it reasons.

## Step 3 - understand the business before the numbers

Do not skip this and do not reduce it to a marketing sentence. From the 10-K,
*Business* and *Risk Factors*:

- What it sells, to whom, and how it makes money - explainable to a five-year-old.
  If you cannot, you have not understood it yet.
- Where the competitive advantage comes from and how long it lasts. Regulated
  monopoly, barrier to entry, brand, switching costs, network effect?
- Which conditions must stay true for the thesis to hold.
- Is it shareholder-friendly? Raises through recessions, buybacks at sensible
  prices, management compensation tied to results.
- The three things that would break the thesis.

If you cannot articulate the business clearly, **say so and stop**. A score on a
company you do not understand is false precision.

## Step 4 - scoring, 10 criteria, maximum 30

Read `references/scoring-model.md` for the exact thresholds. Two things that are
easy to get wrong:

- **The scale runs 10 to 30, not 0 to 30.** Every criterion awards at least 1
  point. Report the band, not just the number.
- **Criterion 3 is a matrix keyed to the yield bucket** from criterion 2, and it
  has a fourth `NO` row that is a hard reject, not zero points. Determine the yield
  bucket first. Getting the bucket wrong shifts the score by up to two points.

| # | Criterion |
|---|---|
| 1 | Consecutive years of dividend growth |
| 2 | Dividend yield vs S&P 500 |
| 3 | Dividend growth rate (matrix by yield bucket) |
| 4 | EPS and earnings payout ratio |
| 5 | Free cash flow and FCF payout ratio |
| 6 | Debt to total capital |
| 7 | Return on equity |
| 8 | Operating income margin |
| 9 | Share count |
| 10 | Credit rating |

Interpretation: **under 10** avoid. **10-20** acceptable with question marks that
must be named explicitly. **over 20** solid.

Criteria 4 and 5 score three dimensions each - trend, consistency, and payout
ratio. Score the lowest of the three; the weakest link governs dividend safety.
For REITs (for example `O`, `VICI`, `ARE`) use the REIT payout column,
which is part of the model, not an improvisation.

Present the score as a table with an evidence column - the concrete figure and year
justifying each point. A score without evidence is not verifiable.

## Step 5 - valuation, 6 methods

> **Unblocked 2026-08-18.** Methods 1 through 5 need **annual average prices
> over 10-15 years**, from the `dgi-prices` MCP tool's `price_annual_averages`
> - one call per ticker, set `fiscal_year_end_month` for filers that do not
> close in December (INTU closes in July).
>
> Three checks are mandatory before using the response, every time:
>
> - Exclude every year in `incomplete_years` from any historical mean - it
>   separates "still in progress" from "truncated by the start of the window".
>   Averaging the current, unfinished year into a 15-year mean drags the mean
>   toward today's price; this was a real bug (fixed in v0.5.1) and the
>   exclusion is what actually fixes it.
> - Require `verification.verdict == "consistent"`. If it is not, do not
>   report a valuation from that ticker's series.
> - Multiply an as-filed EDGAR per-share figure (EPS, EBIT/share, OpCF/share,
>   FCF/share, and **dividend per share** - for the Weiss yield and for any
>   growth streak or DGR that spans the split) by the right split factor
>   before dividing a price by it. V's 2014 dividend is filed at 0.40 and its
>   2015 at 0.12: a 4:1 split, not a 70% cut (item 25). **Key
>   it on that figure's `filed` date, which `edgar_financials` returns per
>   year - NEVER on the fiscal year.** Look the date up in
>   `split_factor_by_filing_date` from `price_annual_averages`. MA, V, KO and
>   NEE all carry a split inside the window; skipping the factor makes the
>   multiple wrong by the split ratio, and keying it on the year makes it wrong
>   by the same ratio in the OTHER direction, because EDGAR restates the last
>   few years and those figures are already post-split.
>
> **There is still no second price provider.** Yahoo and Stooq were both
> measured behind an anti-bot wall from a normal connection and removed;
> `verification` is an internal consistency check against Tiingo's own
> adjusted close, not a second source. State that every price-derived
> valuation rests on one uncorroborated source.
>
> Gordon Growth alone is still not a substitute for the other five - for a
> low-yield, high-growth payer it is the method the reference itself calls
> inapplicable. **A number from Gordon Growth alone is not a valuation.** On
> ZTS it read $36-56 against a $77 price, which is the method failing, not the
> stock being 50% overvalued. Now that prices are available, only skip a
> method and fall back toward Gordon Growth alone when that method's own
> applicability condition fails (e.g. a dividend cut inside the window) - not
> because the price series is unavailable, which is no longer the case.

Read `references/valuation-methods.md` for formulas, denominator guards and traps.

1. Dividend Yield Model (Geraldine Weiss)
2. Historical P/E
3. Historical P/EBIT
4. Historical P/Operating Cash Flow
5. Historical P/Free Cash Flow
6. Gordon Growth Model

All six assume **multiples revert to their historical mean.** That assumption fails
when the business changed structurally - a company that moved from growth to
decline does not return to its P/E from ten years ago, and every mean-based method
then reads artificially cheap. Name it explicitly when you suspect it.

Report the average **and the dispersion**. If estimates run from $60 to $180, an
average of $120 is not information, it is an illusion of precision. Say so.

Apply a 10-15% safety margin below the estimate for a buy target.

DCF is deliberately excluded from the six. The author's own worked example moves
the valuation from $484 to $939 on a single percentage point of terminal growth.
Mention it only if the user asks.

## Step 6 - report

Fixed order. The uncomfortable conclusion first, not on page three.

1. **Verdict, 2-3 sentences.** Score `X/30` with band, estimated price versus
   current price, and the main risk to the dividend. Any `NO` band or off-table
   value goes here regardless of the total.
2. **The business** - what it does, where the advantage comes from, how long it lasts.
3. **Scoring** - 10-criteria table with points, evidence figure, year.
4. **Dividend safety** - payout on EPS and on FCF, coverage, behaviour in
   recessions (2008-09, 2020), and what would have to happen for a cut.
5. **Valuation** - six methods, average, dispersion, target with margin.
6. **Risks** - the three thesis-breakers, each with an indicator to monitor.
7. **What's next** - next earnings date, likely raise announcement date, what to
   check at each.
8. **Position context** - if held: average cost, current yield on cost, weight, and
   whether adding would breach the concentration limits in the config.

If the user wants a file, use the `docx` or `pdf` skill. Otherwise answer in chat.

## Complementary skills

The `claude-for-financial-services` marketplace is installed and some of its
skills compose well here:

- `equity-research:initiating-coverage` - full institutional report when depth
  beyond this scoring is wanted
- `equity-research:thesis-tracker` - track the thesis on a position over time
- `equity-research:earnings-preview` - prepare before results
- `earnings-reviewer:audit-xls` - generic spreadsheet audit, complementary to
  `portfolio-audit` which is specialised on DGI rules

None of them supply market data - they are workflows. The data still comes from
`edgar_financials` for statements and FMP `quote` / `profile-symbol` for price
and profile.

## What this skill does not do

- **No buy or sell recommendations.** Present figures, score and a valuation range.
  The decision belongs to the user. Not a financial advisor - state it once,
  briefly, at the end.
- Never execute trades or propose to.
- Never adjust a score to reach a comfortable conclusion. If a holding scores
  11/30, that is the first sentence of the report.
