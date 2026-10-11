# Data sources - what actually works

Empirically verified against a live FMP free-tier account on 2026-07-30. Not
guessed from documentation. Re-verify if the plan changes.

## How FMP is wired

FMP is a **connector**, not a bundled MCP server. The user connected it through the
app's connector directory, so the credential lives with the app and never reaches a
config file or the conversation.

This plugin deliberately ships **no `.mcp.json`**. An earlier version had one using
`${FMP_API_KEY}`, and it was actively harmful: it declared a second FMP server whose
env var is never set (macOS GUI apps do not read `~/.zshrc`), producing a broken
duplicate alongside the working connector. If a future version needs a bundled
server, verify it is not already available as a connector first.

Tool names are therefore `mcp__<server-uuid>__<toolName>`, where the uuid belongs to
the connected instance and changes per installation. **Never hardcode the uuid.**
Discover the tools with `ToolSearch` (query e.g. `financial dividends fundamentals`)
and use whatever names come back. The endpoint is always passed as the `endpoint`
parameter.

If no FMP tools are found, the connector is not connected. Say so and fall back to
`WebSearch` plus sec.gov, marking data as unverified at source. Do not ask for an
API key.

---

## FMP free tier - the boundary

### Works — verified 2026-08-01, and it is a short list

| Tool / endpoint | Gives |
|---|---|
| `company` / `profile-symbol` | `sector`, `industry`, `price`, `lastDividend`, `beta`, `marketCap`, `cik`, `description`, `ceo` |
| `quote` / `quote` | live price |
| `secFilings` / `search-by-symbol` | filing index. **Not re-tested since the gating was measured** — treat as unproven, and prefer `edgar_lookup` |

**That is all of it.** This table used to list five `statements` endpoints as
"the workhorse" while the Blocked table fifteen lines below listed the same tool
as denied. Following the first table was the fastest route to the wall.

For everything statement-derived — EPS, cash flow, capex, debt, equity, share
count, dividends paid, declared dividend per share — use **`edgar_financials`**.
See the field mapping below.

### Blocked

| Tool / endpoint | Consequence |
|---|---|
| `calendar` (**entire tool**) | no per-payment dividend history, no ex-dates, no earnings dates |
| `directory` (**entire tool**) | no sector or exchange reference lists |
| `statements` (**entire tool**) | denied through the connector for every symbol |
| `analyst` (**entire tool**) | no ratings, price targets or estimates |
| `discountedCashFlow` (**entire tool**) | denied |

### SUPERSEDED 2026-08-01: FMP is no longer the statements source

The old note here described a "hard 5-year cap" on `statements` and treated it
as the binding constraint. That is obsolete twice over, and both corrections
matter:

**1. FMP gates fundamentals per SYMBOL, not per endpoint.** Measured across this
portfolio with a direct `curl` on the user's own key: `income-statement`
returned HTTP 200 for **KO, JNJ, ABBV, V** and HTTP **402** for the other
thirteen, ZTS included. The 402 body says it plainly: *"This value set for
'symbol' is not available under your current subscription."* Four of seventeen
tickers tested. A five-year window was usable; four-of-seventeen coverage is not.

**2. Through the connector, `statements` is denied for every symbol**, including
KO, which the same key serves fine by curl. So the connector runs at a lower
tier than the user's own key. Upgrading the subscription would not fix it.

**The replacement is `dgi-edgar`, and it is strictly better than FMP ever was.**

| | FMP | SEC EDGAR XBRL |
|---|---|---|
| Cost | tiered, per-symbol gating | free |
| Key | yes | none, User-Agent only |
| History | 5 years | everything ever filed |
| Coverage | 4 of 17 tickers tested | every US SEC filer |
| Authority | vendor-normalised | the filing itself |

Where each criterion now gets its data:

| Needed by | Requirement | Source |
|---|---|---|
| Criterion 1 | consecutive years of dividend growth | `edgar_financials` → `dividend_per_share_declared`, primary source |
| Criterion 3 | DGR over 5 and 10 years | same series, computed as a CAGR; dripinvesting only as cross-check |
| Criterion 4 | no EPS decline in 10 years | `eps_diluted` - **solved**, 13 years available for ZTS |
| Criterion 5 | no FCF decline in 10 years | `operating_cash_flow` minus `capex` - **solved** |
| Criterion 6 | debt to total capital | `long_term_debt` + `short_term_debt` + `stockholders_equity` |
| Criterion 7 | ROE, ROIC | `net_income`, `stockholders_equity`, debt |
| Criterion 8 | operating margin | `operating_income` / `revenue`, or pretax + interest when the filer omits `OperatingIncomeLoss` |
| Criterion 9 | share count | `shares_diluted` |
| Criterion 10 | credit rating | `WebSearch` |
| Valuation 1-5 | 10-15 year average prices and multiples | **unblocked 2026-08-18** - `price_annual_averages` (`dgi-prices` MCP tool) |

**The price gap is closed.** `price_annual_averages` reduces a daily Tiingo
series to annual averages on the host, the same pattern as `dgi-edgar`, so the
~3,800-row daily series never reaches the conversation. One call per ticker.
Exclude every year in the response's `incomplete_years` from any historical
mean, check `verification.verdict == "consistent"` before using the series, and
apply the split factor before dividing a price by an as-filed EDGAR per-share
figure — looked up in `split_factor_by_filing_date` by that year's `filed`
date, never by the year itself. See `references/valuation-methods.md` for the full contract.
There is still no second price provider — Yahoo and Stooq were both walled by
anti-bot checks and removed — so report every price-derived valuation as
resting on a single, uncorroborated source.

**Report the window you actually used.** A "historical average P/E" over 5 years is
not the method the article describes, and 5 years starting in 2021 is an unusual
stretch of market history to mean-revert against. Say so rather than presenting the
number as if it were a 15-year mean.

---

## Field mapping per scoring criterion

**Rewritten 2026-08-01.** The previous version of this table routed eight
criteria to `metrics-ratios`, `key-metrics`, `income-statement` and
`cashflow-statement` — the exact FMP endpoints documented as DENIED twenty lines
above it. Following it produced a wall, not data. Every statement-derived figure
now comes from `edgar_financials` concepts.

### `quality` gates every criterion below

`edgar_financials` attaches `quality` only when a defect survives its ranking of
the candidate `(tag, unit)` pairs, so its presence is never noise. **Check it
before computing anything from the series**, and let it change the OUTPUT, not
just a footnote:

| Key | What it forbids |
|---|---|
| `non_usd_unit` | Any multiple against a USD price. The number would be wrong, not approximate — do not report one |
| `stale` | A growth streak or DGR; both are wrong by exactly the missing years |
| `interior_gaps` | A consecutive-years count across the gap. Say the streak cannot be confirmed |
| `zero_values`, `negative_values` | A growth ratio, which is **undefined** here rather than imprecise. Start the window after them or say so |
| `per_payment_rate` | Any yield, payout or Weiss input from the listed `years` without multiplying by `payments_per_year` - the figure is one payment, not the year (V). Also any growth ratio from a listed year into an unlisted one |
| `count_jumps` | Reading a share-count trend off the raw series. The jump is a split (AAPL FY2018 3.8x, NEE FY2018 4.0x, MA FY2011 9.8x): divide each year by its split factor first |

**Balance-sheet concepts are read at the filer's own fiscal year end** since
item 26 (v0.11.6). Before that, a September filer like V got the Dec 31
balance from its next fiscal year's first 10-Q, which put V's debt to capital
at 35.3% against a true 39.9%. Pairing a year's balance with that year's
income is now safe for non-December filers too.

These are normally real facts about the filer, not data errors — pre-dividend
years, loss years, tags the company retired. Reporting a criterion as
"unavailable, and here is why" beats a confident number computed through one of
them. `alternatives` shows the candidates that lost, so the choice is auditable
and a shorter cleaner series stays available.

**EDGAR gives raw filed values, not vendor-computed ratios.** FMP handed over
`debtToCapitalRatio` finished; EDGAR hands over debt and equity and the ratio is
yours to compute. That is the trade for coverage and for the filing being the
authority. The formula column below is the arithmetic, not a suggestion.

| # | Criterion | Concepts | Compute |
|---|---|---|---|
| 1 | Growth years | `dividend_per_share_declared`; `price_dividends` to corroborate and for the newest fiscal year | consecutive years of increase; cap at years since IPO |
| 2 | Dividend yield | FMP `quote` / `profile-symbol` (both still work) | `lastDividend / price`, or the sheet's column `L` |
| 2 | S&P 500 yield | `WebSearch` | - |
| 3 | DGR | `dividend_per_share_declared`; `price_dividends` for the newest fiscal year | CAGR over 5 and 10 years, ending on the latest complete fiscal year either source has; dripinvesting only as cross-check |
| 4 | EPS trend | `eps_diluted` | count declines over 10 years |
| 4 | Earnings payout | `dividend_per_share_declared`, `eps_diluted` | DPS / EPS |
| 5 | FCF trend | `operating_cash_flow`, `capex` | `OCF − capex`, count declines |
| 5 | FCF payout | `dividends_paid`, `operating_cash_flow`, `capex` | `abs(dividends_paid) / FCF` |
| 6 | Debt to capital | `long_term_debt`, `short_term_debt`, `stockholders_equity` | `debt / (debt + equity)` |
| 6 | Interest coverage | `operating_income`, `interest_expense` | `EBIT / interest` |
| 7 | ROE | `net_income`, `stockholders_equity` | `NI / equity` |
| 7 | ROIC (when ROE > 40%) | `net_income`, debt, `stockholders_equity` | `NI / (debt + equity)`, an approximation — say so |
| 8 | Operating margin | `operating_income`, `revenue` | `EBIT / revenue` - see below |
| 9 | Share count | `shares_diluted` | trend over 10 years, on today's basis: **divide** each year by the split factor for its `filed` date (the inverse of a per-share figure) |
| 9 | Buybacks | raw tag `PaymentsForRepurchaseOfCommonStock` | not in the alias list; use the raw tag |
| 10 | Credit rating | `WebSearch` | - |

`capex` and `dividends_paid` are filed as positive outflows by most filers and
negative by some. **Check the sign before subtracting** rather than assuming;
a sign error here flips FCF and is not visually obvious.

### Criterion 8: computing EBIT/revenue yourself

The old FMP problem — `ebitMargin` 36.8% versus `operatingProfitMargin` 28.7%
for KO FY2025, an 8 point gap between two vendor fields — **disappears with
EDGAR**, because you compute one number from filed `operating_income` and
`revenue` rather than choosing between two normalisations. Kept here because the
lesson survives: when two sources disagree by more than 5 points on a margin,
that gap is information about recurring non-operating items, not noise to pick a
winner from.

The EDGAR-specific difficulty is different: **some filers omit
`OperatingIncomeLoss` entirely.** The fallback is pretax income plus interest
expense. `edgar_financials` reports which tag actually resolved, so record it —
a margin computed from the fallback is not the same measurement as one from the
filed operating income, and the report should say which it used.

### Valuation field mapping — unblocked 2026-08-18, methods 1-5

**Do not use the table that used to be here.** It routed all five mean-reversion
methods to `metrics-ratios`, which is denied, and its per-year multiples were
built on fiscal year-end prices rather than the annual averages the method
specifies.

| Method | Needs | Source |
|---|---|---|
| 1. Dividend Yield Model | annual average price, annual dividend | `price_annual_averages` + `price_dividends` (same basis, no split factor) or `dividend_per_share_declared` x split factor |
| 2. Historical P/E | annual average price, `eps_diluted` x split factor by `filed` date | `price_annual_averages` + `edgar_financials` |
| 3. Historical P/EBIT | annual average price, `operating_income` / as-filed `shares_diluted`, then x split factor by `filed` date | `price_annual_averages` + `edgar_financials` |
| 4. Historical P/OpCF | annual average price, `operating_cash_flow` / as-filed `shares_diluted`, then x split factor by `filed` date | `price_annual_averages` + `edgar_financials` |
| 5. Historical P/FCF | annual average price, FCF / as-filed `shares_diluted`, then x split factor by `filed` date | `price_annual_averages` + `edgar_financials` |
| 6. Gordon Growth | current dividend, `r`, `g` | computable without prices, and alone it is not a valuation |

**All six denominators and the numerator are now available.** Call
`price_annual_averages` once per ticker (set `fiscal_year_end_month` for
non-December filers), exclude every year in `incomplete_years` from the
historical means, require `verification.verdict == "consistent"`, and multiply
each year's as-filed EDGAR per-share figure by its split factor before
dividing a price by it — looked up in `split_factor_by_filing_date` by that
year's `filed` date, **never by the year**. MA, V, KO and NEE all split inside
the window. Skipping the factor and keying it on the year are both wrong by the
full split ratio, in opposite directions. Do not substitute a 5-year window and call it a
historical average, and do not present Gordon Growth alone as a fair value:
it is the method notoriously inapplicable to low-yield, high-growth payers,
and it moved a ZTS estimate from $484 to $939 on one percentage point of
terminal growth. Report every price-derived estimate as resting on a single,
uncorroborated price source (see the note above).

---

## Alpha Vantage - `av_financials`, measured 2026-10-11

Free key in `~/.dgi/alphavantage.json`: 25 requests a day, 5 a minute, one
request per statement, a week of cache on the host.

| Function | Free key | History measured |
|---|---|---|
| `INCOME_STATEMENT`, `BALANCE_SHEET`, `CASH_FLOW` | yes | 20 annual years for AAPL and V (FY2006-2025), 17 for ZTS |
| `EARNINGS` | yes | annual EPS back to 1996 (AAPL) |
| `OVERVIEW` | **premium, refused** | - |

**What it is:** a second reader of the same SEC filings. On AAPL every figure
compared matched EDGAR to the dollar. Agreement proves our EDGAR tag and date
selection; it never proves the filing. **What it adds:** the share count for
Visa (1.966bn FY2025), which EDGAR cannot give.

Three traps, each reported in the response:

| Concept | Trap |
|---|---|
| `eps_reported` | **Street EPS, not GAAP**: V FY2025 11.47 against a GAAP 10.20. Use `eps_from_net_income` |
| `shares_outstanding` | Already split-adjusted (AAPL FY2017 21.007bn). **No** split factor |
| `short_term_debt` | Includes commercial paper (AAPL 22.4bn vs EDGAR 12.35bn). Do not mix sources in one debt ratio |
| `shares_outstanding` early years | Can be on another basis: V FY2011-2012 read 4.09bn and 3.86bn ($0.89 and $0.56 of net income per share against GAAP EPS of about $1.29 and $0.79). Flagged as `quality.count_basis_suspect` when net income / count falls outside 0.75-1.25x of the reported EPS. The same flag also fires on large one-off years (ZTS 2015 and 2017), where the count is fine and GAAP is not comparable with street EPS. Check every listed year |

`EARNINGS` also lists the year in progress as annual. It is flagged in
`incomplete_years`; exclude it.

---

## Sector taxonomy: FMP is not GICS

FMP uses its own sector names. The portfolio sheet uses GICS. A naive comparison
flags every row as a mismatch.

| FMP sector | GICS sector (used in the sheet) |
|---|---|
| Financial Services | Financials |
| Technology | Information Technology |
| Healthcare | Health Care |
| Consumer Cyclical | Consumer Discretionary |
| Consumer Defensive | Consumer Staples |
| Basic Materials | Materials |
| Communication Services | Communication Services |
| Real Estate | Real Estate |
| Utilities | Utilities |
| Industrials | Industrials |
| Energy | Energy |

Verified empirically only for `Financial Services` → `Financials` (MA returns
`sector: "Financial Services"`, `industry: "Financial - Credit Services"`). The
rest is inference from FMP's published sector list. Confirm a row before treating
a mismatch as an error.

The mapping lives in `config/portfolio.json` under `fmp_sector_to_gics`. Always
translate before comparing against the sheet's `Sector` column.

`industry` is often more useful than `sector` for peer comparison - `Financial -
Credit Services` distinguishes MA and V from banks and insurers, which matters for
the operating-margin sector median in criterion 8.

---

## dripinvesting.org - the CCC replacement

Verified 2026-07-31. This supersedes the old "Dividend Radar is email-gated, there
is no route" note, which was wrong: the gate applies to the emailed spreadsheet,
not to the public stock screener.

Three surfaces, different jobs:

### 1. Stock screener CSV - <https://www.dripinvesting.org/stocks/>

The full list, ~690 dividend payers. The page has a **"Download Dividend Stocks
CSV/Excel"** button. The download URL is generated client-side, so it cannot be
requested directly - the user clicks it once and drops the file in the working
folder. `web_fetch` on the page returns only the first ~66 rows, because the table
paginates in the browser. Do not mistake that for the whole file.

37 columns. The ones that matter, all of which FMP free cannot give:

| Column | Feeds |
|---|---|
| `Stock Type` | criterion 1, as a bucket - see the trap below |
| `DGR 1Y`, `DGR 3Y`, `DGR 5Y`, `DGR 10Y` | criterion 3, including the deceleration test |
| `Chowder Number` | the Chowder rule |
| `5Y Avg Yield` | context for criterion 2 |
| `Payouts/Year` | the real payment frequency, instead of the hardcoded x4 |
| `Ex-Date`, `Pay-Date` | next payment |
| `Debt/Capital`, `ROE`, `P/E`, `P/BV`, `PEG` | cross-checks against FMP |

**Trap - `Stock Type` is a bucket, not a year count.** King 50+, Champion 25-49,
Contender 10-24, Challenger 5-9. Criterion 1 scores at 15+ / 10-15 / under 10, so
**King, Champion and Challenger are unambiguous, and Contender is not** - the
bucket straddles the 15-year line. There is no exact-years column in the CSV.
Resolve a Contender from its individual history page (below), never by guessing
the middle of the bucket.

**Trap - the prices are unreliable.** Measured 2026-07-31 against live quotes: most
rows sat 5-15% below market, and QCOM was listed at $229.49 against an actual
$150.91. That is not staleness, it is wrong. **Use this file for DGR, Chowder,
Stock Type and frequency only. Never for price, yield or valuation.**

Parse it with:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/company-analysis/scripts/parse_dripinvesting.py" \
    screener stocks-YYYY-MM-DD.csv --tickers KO,MO
```

The script enforces both traps: it omits price and valuation columns unless
`--unsafe-prices` is passed, and it returns `UNRESOLVED` for a Contender instead of
inventing a year count. `--unresolved` lists exactly which holdings still need a
history page.

### 2. Per-stock history - `/stocks/<ticker>-dividend-history-calculator-returns/`

Roughly **20 years of individual payments**: ex-date, amount, yield at the time,
and the price. This is the single most valuable source in the whole plugin,
because it removes the constraints the 5-year FMP cap imposes:

- exact consecutive-growth streak for criterion 1, including Contenders
- DGR over any window, computed from real payments rather than a 4-year CAGR
- annual average price and annual dividend, which is what the **Dividend Yield
  Model (Weiss)** actually needs and what the 5-year FMP window could not support

Worked example, KO on 2026-07-31: DGR 1y 3.92%, 3y 4.83%, 5y 4.76%, 10y 4.24%,
15y 5.57%. The 4-year FMP CAGR had given 4.97% - enough to move criterion 3 across
the 5% threshold and change the total score by a point.

Fetch the page with the agent's own web tooling, save the text, then:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/company-analysis/scripts/parse_dripinvesting.py" \
    history ko-history.txt --ticker KO
```

The script does no HTTP of its own - deliberately, so there is one place where a
URL is fetched and the parser stays testable offline.

**The URL slug is not stable.** Two forms exist on the same site:
`/stocks/<t>-dividend-history-calculator-returns/` and
`/stocks/<t>-dividend-returns-history-calculator/`, and some tickers (ARE on
2026-07-31) return empty on both. Take the link from the screener CSV's HTML rather
than constructing it, and treat a miss as "resolve criterion 1 another way", not as
a reason to guess.

**Boundary handling, which decides real points.** The streak is counted over
complete calendar years, because a partial current year understates its total and
would look like a cut. But excluding it also hides a raise already declared, and a
company on 14 complete years that has raised again this year is on 15 - the line
between 2 and 3 points. The script compares the partial year on a per-payment basis
and reports the effective streak separately. Check that line before scoring anything
near 15.

### 3. Monthly calendar - `/dividend-calendar/`, `/dividend-calendar/<month>-<year>/`

Grouped by pay date, with ex-date, amount and yield per ticker. This is the
replacement for FMP's blocked `calendar` tool, and it is what the portfolio's
`Dividends received` sheet needs to move from month granularity to real pay dates.

### Specials are included, and that distorts DGR

dripinvesting's DGR counts total dividends paid, specials included. For AFG on
2026-07-31 that produced `DGR 1Y -23.7%`, `DGR 5Y -18.9%` against `DGR 10Y +12.7%`
- an artefact of shrinking special dividends, not a cut to the regular payout,
which went 0.80 to 0.88. `Payouts/Year` showed 6 for the same reason.

Where the user's `Dividends received` sheet tags payment type, **it is the better
source for any company that pays specials**, because it can separate them.

### A negative DGR 1Y can also be a partial-year artefact

Found 2026-08-01, and it is a *second* mechanism, not the specials one. ZTS on
the same file reads `DGR 1Y -19.3%` against `DGR 3Y +3.7%`, `DGR 5Y +17.4%`,
`DGR 10Y +13.2%`, with `Payouts/Year` **4** - so no specials are involved.

The regular payout actually rose, 0.50 to 0.53. Two independent facts prove it:
FMP's trailing-twelve-month total is 2.09, *below* four times the current 0.53,
which only happens on a raise; and 0.50 + 0.53 x 3 = 2.09 exactly. Three
payments at the new rate against four at the old gives -20.5%, close enough to
the reported -19.3% that an incomplete current year is the likely cause.

**Rule: never let a negative DGR disqualify a company on this file alone.**
Criterion 3 can push a name into the `NO` band, so corroborate first, with FMP's
trailing total or the per-stock history page. Cross-check `DGR 1Y` against
`3Y/5Y/10Y` - a single-year figure wildly out of line with the others is a
reporting artefact until proven otherwise.

### Reconstructing a raise from FMP's trailing total

Cheap, and it needs no history endpoint - which matters, since dividend history
is plan-blocked on FMP. `lastDividend` in `profile-symbol` is the trailing
twelve months, i.e. the sum of the last four payments. Given a per-payment rate
`r`, solve for how many payments happened at `r` and what the previous rate was:

    previous = (trailing - n x r) / (4 - n)   for n = 1, 2, 3

Usually several `n` fit arithmetically, so **this does not identify the raise on
its own** - use the CSV's `DGR 1Y` as an independent tiebreak and take the split
that agrees. Verified on MA (0.76 -> 0.87, +14.5%), V (0.59 -> 0.67, +13.6%) and
DPZ (1.74 -> 1.99, +14.4%), each agreeing with the CSV to within 0.3pp.

It also catches an annual figure typed into a per-payment field: `r x 4` then
lands nowhere near the trailing total. That is exactly the error that made MA
and V overstate annual income fourfold until 2026-07-31.

### Sure Dividend "Dividend Champions" xlsx - evaluated and dropped

A different product with a different format (Dividend Risk Score, analyst fair
value, `Years of Dividend Growth` as an exact number). Tested 2026-07-31 against
a 17-ticker portfolio and **deleted**: its 165 names are all 25+ year streaks, which is
exactly the set the CSV already resolves with certainty as King or Champion. It
contained none of the eight Contenders where the CSV is ambiguous. Zero
incremental coverage for criterion 1.

If it reappears, note that it disagreed with dripinvesting on ABBV - 54 years
versus Contender - because it counts Abbott's pre-2013 history. That is the
spin-off exception the scoring model already allows, not an error in either source.

---

## sec.gov for anything older than 5 years

The chosen fallback. It is also the article author's own method - he reads 10-Ks
going back at least 10 years rather than trusting aggregators.

Route: `secFilings` / `search-by-symbol` to get the filing index, then
`mcp__workspace__web_fetch` on the document URL. Or `statements` /
`financial-reports-form-10-k-json` with an explicit `year`, which may reach past
the 5-year window since the year is a parameter rather than a limit - untested,
worth trying before falling back to raw filings.

Slower per company, free, and authoritative. Use it for any figure that decides a
1-versus-3 score, and for the 10-year consistency tests in criteria 4 and 5.

---

## Call budget

**Rewritten 2026-08-01.** The old budget was four `statements` calls plus
`profile-symbol`. Three of those four are denied, so the figure it quoted — "5
FMP calls plus 2-4 searches" — described work that cannot be performed.

| Calls | For |
|---|---|
| 1 | `edgar_lookup` — ticker to CIK, and the cheapest test of whether the symbol files with the SEC at all |
| 1-2 | `edgar_financials` — ask for **every concept you need in one call**; the tool takes a list |
| 0-1 | `edgar_tags` — only when a concept came back empty |
| 1 | FMP `quote` or `profile-symbol` for the current price and last dividend |
| 2-4 | `WebSearch` for credit rating and S&P 500 yield |

So about **2-4 EDGAR calls, 1 FMP call and 2-4 searches per company.**

Three things changed in kind, not just in count:

- **No daily quota on EDGAR.** The limit is 10 requests/second per IP, which no
  conversational pace approaches. The old "free tier is rate-limited per day"
  constraint is gone.
- **Facts are cached 24h** under `~/.dgi/edgar-cache/`, so re-analysing the same
  company in the same day costs no network at all.
- **Batch the concepts.** `edgar_financials` accepts a list, and one call for ten
  concepts costs the same round trip as one concept. Asking per concept is the
  main way to waste the budget now.

Unchanged: **the skill analyses one ticker at a time.** The reason is no longer
a call quota — it is that a ten-year series per concept per company is a
context cost, and the scoring needs the evidence visible while it reasons.
