# Validation rules

What `scripts/audit_formulas.py` checks, why, and how to add a rule.

## Severities

| Level | Means | Example |
|---|---|---|
| `CRITICAL` | A reported number is wrong **right now** | a `SUM` that omits positions |
| `SERIOUS` | Will break, or actively misleads | a label contradicting its formula |
| `WARNING` | Fragile, needs manual verification | hardcoded payment frequency |
| `INFO` | Observation, no action | a check that requires live data |

Exit code is 1 if any `CRITICAL` exists, otherwise 0.

## Design principles

**Deterministic only.** No LLM inference. Every finding must be reproducible from
the file plus the config, so the same input always yields the same report.

**Evidence or nothing.** Each finding quotes the actual cell content or a concrete
figure. A finding the user cannot verify against their sheet has no place in the
report.

**Aggregate, do not spam.** A rule that fires per row across every position
produces seventeen findings and an unreadable report. Collect and emit one finding
naming the affected cells. The frequency and tax checks both do this.

**Prove, do not accuse.** Where the data cannot distinguish between causes, say the
data cannot distinguish. See check 7.

---

## 1. Dead Google formulas

Detects `__xludf.DUMMYFUNCTION` and Apps Script functions (`get[A-Z]\w*\(`).

When a Google Sheet is exported to `.xlsx`, `GOOGLEFINANCE`, `SPARKLINE`,
`IMPORTHTML`, `IMPORTXML`, `IMPORTRANGE`, `QUERY` and `IMAGE` have no Excel
equivalent. Google replaces them with
`=IFERROR(__xludf.DUMMYFUNCTION("original formula as text"), last_known_value)`.

Practical consequence: the file looks plausible and complete, but every price is
frozen at export time. An audit that treats those values as current produces a
confident, wrong report.

Apps Script functions have a nastier failure mode: if the scraped source changes
structure, the function returns the last good value or a blank **with no visible
error**. The price stays frozen for months. Recommend a last-updated timestamp so
staleness is detectable.

## 2. Total row range consistency

For each row in `total_rows`:

- **2a.** Extract every `SUM(Xn:Xm)`. Differing `m` across columns is `CRITICAL` -
  columns describing the same positions must cover the same rows, otherwise income
  is computed over one set and value over another.
- **2b.** Any `SUM` ending before the last DGI row is `CRITICAL`, listing the
  excluded positions by ticker.
- **2c.** A `SUM` on a column flagged `dgi_only_aggregate` that reaches into the
  non-DGI block is `CRITICAL`. Tracking-only positions must not leak into dividend
  reporting.
- **2d.** Any cell in the total row that is neither a formula nor a label (short
  text without spaces) is `SERIOUS`. Typically a ticker jotted down and forgotten.

The recommended range always ends one row past the last data row, giving a buffer
so inserting a position does not reintroduce the bug.

## 3. Non-DGI separator label

Verifies `blocks.separator.cell` still contains `expected_label`.

That label is the only in-sheet documentation that the rows below are tracking-only.
If someone deletes it, the distinction survives only in this config file - and the
next person to open the sheet sees empty dividend cells and assumes missing data.

The real fix is an explicit `DGI` TRUE/FALSE column, which the finding recommends.
A text label plus hardcoded row numbers is documentation; a column is data.

## 4. Non-DGI isolation

For every column flagged `dgi_only`, checks that non-DGI rows carry the
`unavailable_marker` (`N/A`), empty, or zero.

**This check exists to prevent a false positive, not just to find errors.** Empty
dividend cells on `PLTR`, `META`, `SXR8` and `BVBETF` are intentional. Without
this rule, a naive "missing data" check would flag them every run and train the
user to ignore the report.

When isolation is clean the check emits `INFO` confirming it, so the user can see
the rule ran and agreed with their intent.

## 5. Weight denominators

Two sub-checks on columns with `expected_sum: 1.0`:

**5a. Shape consistency.** Normalise the denominator of each formula (replacing
column letters with `@`) and group. More than one group is `CRITICAL`.

A different denominator on a few rows is almost always a patch for a broken `SUM`
elsewhere. If two bases are genuinely needed, that is two columns - not two formula
shapes in one column.

**5b. Self-exclusion.** A non-DGI row whose weight divides by a total that stops
before its own row is `CRITICAL`. The position is missing from its own denominator,
so its weight is overstated and the column cannot sum to 100%.

This is a subtler bug than 5a because each individual formula looks correct in
isolation. Only the interaction between the formula and the range of the total
reveals it.

## 6. Dividend tax factor by year

Detects the leading multiplier in the dividends-received column and compares it
against `dividend_tax.brackets`.

Finding `legacy_net_factor` (0.90) applied to a cumulative total is `CRITICAL`,
because payments received from 2026 are taxed at 16% and are therefore overstated
by 6.67%.

The fix text deliberately warns **against** the obvious correction. Replacing 0.90
with 0.84 wholesale retroactively re-taxes 2024-2025 income and understates what
was actually received. The factor belongs per payment, by year of receipt - and a
flat string carries no dates, which is what makes it impossible rather than merely
inconvenient.

An unrecognised factor (matching no configured bracket) is `WARNING`.

Full background in `tax-treatment.md`.

## 7. Dividend history shape

Extracts the numbers from the payment string and compares against the median.
Outliers above `2.5x` or below `0.4x` are `SERIOUS`.

The wording is deliberately cautious. A flat string `0.9*(a+b+c)` stores no payment
date and no share count at the time of payment, so it is **impossible** to
determine whether an outlier is a special dividend, a raise, or the effect of
buying more shares. Do not claim it is a special dividend - claim the data cannot
tell you, which is the actual problem.

Concrete consequence worth stating: **DGR cannot be computed from the user's own
data**, so criterion 3 of the scoring model - the one the author calls the most
important pillar of the strategy - depends on an external source for as long as the
column stays in this shape.

When no outliers are found the check still emits `INFO`, because the absence of
dates remains a blocker regardless.

## 8. Hardcoded payment frequency

Detects `=M*<n>*D` in the annual income column and aggregates across positions.

The frequency assumption breaks for: REITs paying monthly (`O`), companies that
change frequency, special-dividend payers, and any company that just raised.

Framed around the asymmetry: a missed raise understates income, a missed cut
overstates it, and the cut is the dangerous one because a cut is the only sell
signal in the strategy.

## 9. Mislabeled columns

Driven by `mislabeled: true` in the config, not by heuristics - guessing from
column names produces too many false positives.

Known case: column `K` is named "Div Yield" but computes `N/(H+S)`, which is
**Yield on Cost**. The difference is not cosmetic:

- *Yield on Cost* - what your invested money returns. Rises as the company raises
  its dividend. Good for measuring progress.
- *Dividend Yield* - `N/F`, the return at today's price. The only one relevant to a
  buy decision and to criterion 2 of the scoring model.

A 6% YoC on a company yielding 2.5% today is not a buying opportunity - but the
wrong label suggests it is.

## 10. Duplicate and malformed tickers

Duplicates are `CRITICAL` (the position is counted twice in totals and weights).
Surrounding whitespace is `WARNING` (`VLOOKUP` and API calls fail).

## 11. Sector misclassification

Compares the sector column against `expected_sectors` in the config. Any mismatch
is `CRITICAL`, because sector concentration checks and any sector pie chart are
wrong by that position's weight.

Config-driven rather than API-driven so the check stays deterministic and runs
offline. Keep `expected_sectors` in sync when adding positions.

Why this matters more than it looks: GICS moved data processing and payment
companies from Information Technology to Financials in 2023. A sheet built before
that still carries the old labels, and nothing in the spreadsheet flags it. Two of
the current holdings were affected.

## 12. Formula errors

`#REF!`, `#DIV/0!`, `#VALUE!`, `#NAME?`, `#NUM!`, `#N/A`, `#NULL!`, `#SPILL!`,
`#CALC!` - excluding matches inside a `DUMMYFUNCTION`, which are text rather than
real errors, and requiring the cell to be a formula.

## 13. Fragile fixed-row references

Emitted from the sheet spec's `note` field.

Known case, `Evolutie`: `H2=B55`, `H3=B109`, `H4=B163` tie annual deposits to
absolute rows. Insert a row in the weekly area and every annual total silently
points at a different year. `SUMIFS` on a year column fixes it permanently.

## 14. Type consistency within a column

Flags columns declared as formulas that mix formulas and literal values. `WARNING`,
because a literal does not update when its inputs change.

Found in practice on the fees and dividends columns, where later rows were typed as
plain numbers while earlier ones are formulas.

## 15. The per-payment sheet (`Dividends received`)

The sheet that feeds every dividend aggregate. Added 2026-08-01, after it went
a week with no coverage, during which a batch of literal writes broke an
ARRAYFORMULA spill and only a human re-read caught it.

| Finding | Severity | Fires when |
|---|---|---|
| Spill broken | `CRITICAL` | a configured anchor (`spill_anchors`, F2/G2/H2) is **empty** while cells below carry values. The column has silently emptied |
| Config or sheet stale | `CRITICAL` | the anchor holds a **literal**. That is a broken spill or a column made manual on purpose (`F2`, item 5), and the sheet alone cannot tell which. The fix says to settle it first and **never** to clear the column |
| Formula inside a spill | `SERIOUS` | a formula written below an anchor blocks the spill |
| Sheet empty | `SERIOUS` | no payment rows, yet the sheet is configured as the source |
| Unknown payment type | `SERIOUS` | a type outside the configured vocabulary |
| Bad date | `SERIOUS` | a missing or impossible payment date |
| Unknown ticker | `WARNING` | a ticker absent from the positions sheet |

New payment rows get the `manual_columns` only (A:E and I), never the spilled
ones. Missing payments are not this check's job; `check_missing_dividends.py`,
step 5 of `/audit-live`, compares the sheet against IBKR Flex.

---

## Adding a rule

1. Write `check_<name>(workbook, config, report)`.
2. Call `report.add(severity, sheet, cell, title, evidence, fix)`.
   - `evidence` must contain the actual cell content or a concrete figure.
   - `fix` must be specific and actionable, never "check the formula".
3. Append the function to the `CHECKS` list. Exceptions are caught per check, so a
   crashing rule does not abort the audit - it degrades to an `INFO` finding.
4. Prefer config-driven thresholds over constants in the code, so the rule can be
   tuned without editing Python.

## Deliberately not checked

- **Price correctness** - requires live data, cannot be derived from structure.
- **Average cost correctness** - the average cost column holds purchase prices
  hardcoded as a sum. Verifying it requires parsing the transaction journal, and
  the `Jurnal` sheet has an irregular format. Candidate for a later version.
- **FX rate consistency** - `Evolutie!L:M` pull EUR:USD and RON:USD through
  `GOOGLEFINANCE`, dead in the export.
- **Concentration limits** - needs evaluated values, so it belongs in the live
  Google Sheets path, not the `.xlsx`.
- **Allocation rules** - subjective, not the job of a deterministic validator.
