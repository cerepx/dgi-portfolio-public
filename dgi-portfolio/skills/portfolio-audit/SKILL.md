---
name: portfolio-audit
description: >
  This skill should be used when the user asks to "audit my portfolio",
  "check my portfolio sheet", "check my formulas", "find errors in my
  spreadsheet", "reconcile with the market", "are the numbers right", or -
  in Romanian - "auditeaza portofoliul", "verifica excelul", "sunt
  discrepante in excel", "verifica formulele", "reconciliaza cu bursa".
  Also triggers on any question about whether the numbers in their dividend
  portfolio spreadsheet are correct. Covers formula integrity, total and
  range consistency, DGI versus non-DGI separation, dividend tax year
  handling, reconciliation against live market data, and proposing (never
  applying) structural fixes.
---

# Dividend portfolio audit

Verify the integrity of the live portfolio sheet and reconcile it against the
market. Report. Change nothing without explicit consent for that specific batch.

Conversation with the user is in Romanian. Everything written to disk - code,
config, file names, reports - is in English.

## The rule that is never broken

**`ClaudePortofoliu` is the master and a critical report.** Any write requires
explicit consent for **that specific set of changes**, given **after** the
exact diff is shown.

- A general "yes" is never consent for later changes, and an audit finding is
  never itself approval.
- Never bundle safe changes with risky ones in a single consent request.
- **Never write to, and never audit, the local `.xlsx`.** It is a dead export:
  Google functions have become `__xludf.DUMMYFUNCTION`, and the layout is one
  column behind, so every check from `L` onward would be off by one.

## Step 0 - load context

Read `${CLAUDE_PLUGIN_ROOT}/config/portfolio.json`. It carries the column map,
the DGI and non-DGI blocks, the tax brackets, the expected sectors and the alert
thresholds. Without it, any validation is guesswork.

**The DGI / non-DGI distinction** is the most important structural fact about
the sheet:

- **DGI positions** feed every dividend aggregate: income, weight, yield, yield
  on cost, growth years, DGR, charts.
- **Non-DGI positions** (`PLTR`, `META`, `SXR8`, `BVBETF`, under the `C21`
  separator) are tracking only. Their dividend cells are deliberately `N/A`.
  Never report those empty cells as missing, and never offer to fill them.
- A dividend aggregate that reaches into the non-DGI block is `CRITICAL`. Value,
  cost and profit may include both; `dgi_only_aggregate` in the config says
  which column is which.
- A weight column must use **one** denominator throughout.
- **The `DGI` flag column (`AA`) is authoritative.** The row blocks in the
  config are a structural hint and drift when rows are inserted.

## Step 1 - structural validation: run `/audit-live`

Run the `/audit-live` command (`commands/audit-live.md`). It takes a live
`bridge_snapshot`, rebuilds it into a formula-level workbook, and then:
- runs `audit_formulas.py`, 15 deterministic checks;
- scans cached error values;
- compares the sheet against IBKR Flex for missing payments.

All six steps are read-only. Do not read a thousand rows by eye, and do not
infer errors from memory: findings must be reproducible.

- The checks are documented in `references/validation-rules.md`. Read it when
  the user asks why a finding was raised, or when adding a check.
- Exit code 1 means CRITICAL findings exist; say so in the first sentence.
- **Any CRITICAL on `Dividends received` is urgent.** A broken ARRAYFORMULA
  anchor in F2, G2 or H2 silently empties the column for every prior row.

## Step 2 - dividend tax by year of receipt

Read `references/tax-treatment.md` before saying anything about tax.

The Romanian dividend tax went from 10% to 16% on 1 January 2026. For a Romanian
resident holding US stock, the US withholds 10% and Romania taxes the gross with
a credit, so the total equals the Romanian rate: net factor `0.90` through 2025
and `0.84` from 2026.

The factor applies **per payment, by year of receipt**. `Dividends received`
does this: one row per payment, with the factor looked up from the year
(`G` = VLOOKUP on `K:L`). Check 6 verifies the brackets. **Applying 0.84 to a
cumulative figure is wrong**, because it re-taxes 2024-2025.

Tax questions themselves belong to the user's advisor. Do not research or
propose answers.

## Step 3 - reconcile with the market

DGI positions only, one at a time. Tag every number with its provenance: from
the sheet, from the provider, or computed.

| From the sheet | Against | Source | Alert when |
|---|---|---|---|
| Current price | current price | FMP `company` / `profile-symbol` | deviation > `price_deviation_alert_pct` |
| Dividend per share | latest regular payment | `price_dividends` `last_payments`, or Flex | any difference |
| Annual income | dividends paid over the last 12 months | `Dividends received`, Flex, `price_dividends` | deviation > `dividend_deviation_alert_pct` |
| Growth years | consecutive raises | `edgar_financials` `dividend_per_share_declared`, `price_dividends` | any difference |
| Sector | GICS | FMP `profile-symbol` through `fmp_sector_to_gics` | any difference |
| 52 week low / high | 52 week range | FMP `profile-symbol` `range` | deviation > 2% |

Where these sources stand:
- **FMP is a profile source only.** `quote` has been denied since 2026-08-22
  and `statements` for every symbol. Its tool names carry a per-installation
  uuid, so discover them with `ToolSearch`. If no FMP tool exists, say so; do
  not ask for an API key.
- **Statements come from `edgar_financials`, never FMP.** Detail is in
  `${CLAUDE_PLUGIN_ROOT}/skills/company-analysis/references/data-sources.md`.

Reporting rules:
- **Annual income matters most.** Column `O` is `current dividend x frequency x
  shares`, a hardcoded multiplier kept by decision. A missed raise understates
  income. A missed cut overstates it, and the cut is the dangerous one: it is
  the only sell signal in the strategy.
- Price differences below the threshold are normal (the sheet recalculates on
  open). Do not report them.
- **Sectors:** the validator checks them against `expected_sectors`. A new
  position needs its entry; a GICS reclassification needs it updated. Payment
  processors moved to Financials in 2023, for example.
- A ticker the provider does not know is reported as such. Non-US instruments
  (`SXR8.DE`, `BVBETF` on BVB) have no source here.

## Step 4 - report

Fixed structure, conclusion first:

1. **Verdict, one sentence.** How many critical errors, and whether total value
   or annual income is wrong right now.
2. **CRITICAL** - numbers wrong at this moment: cell, evidence, correct figure.
3. **SERIOUS** - will break or actively misleads.
4. **WARNING** - fragile, needs manual verification.
5. **Flex payments missing from the sheet**, under their own heading.
6. **Reconciliation** - ticker x indicator, deviations above threshold only.
7. **Proposed fixes** - numbered, each with cell, old value, new value and the
   effect on reported figures.

For every finding, say whether it is new, already tracked in `BACKLOG.md`, or a
stale rule. Do not re-announce known and accepted findings as discoveries.

## Step 5 - changes, only on explicit request

Do not volunteer changes at the end of an audit. When the user asks:

1. **Group by risk** and ask for consent separately per group:
   - *reversible, no effect on figures*: labels, notes;
   - *corrects figures*: ranges, denominators, sector labels;
   - *restructuring*: columns, formulas, new sheets.
2. **Show the exact diff first**: cell, old value or formula, new value or
   formula, and the numeric effect on totals.
3. **Values and formulas go through `bridge_write`.**
   - Re-check `ALLOW_WRITES` with `bridge_ping`.
   - The bridge takes a backup, logs the old values to `_DGI_Log`, and needs a
     stated reason.
   - On a timeout, **never retry blind**: `bridge_read` the cells first, since
     the write may already have landed.
   - New `Dividends received` rows get **A:E and I only**, never the spilled
     F/G/H.
4. **Formatting and structure go through the Google Sheets connector.** The
   bridge writes values only.
   - Run `bridge_backup` first, and show the exact request.
   - Get approval for that batch.
   - Record the write in `changesets/`: the connector logs nothing and ignores
     `ALLOW_WRITES`.
   - Prefer `PASTE_FORMAT` from an existing row.
5. **Verify after writing.** Read back the changed cells and confirm they match
   the prediction; report any difference immediately.

A readability reformat is never applied in place. Build a new sheet beside the
original, so the two can be compared.

## Already done or decided - do not recommend again

These used to be this skill's priority list and are settled:
- **Done:** the `DGI` flag column (`AA`).
- **Done:** per-payment rows in `Dividends received`.
- **Done:** the tax factor per year of receipt.
- **Done:** Yield on Cost (`K`) separated from Div Yield (`L`).
- **Decided:** column `O` keeps the hardcoded frequency. A counted frequency
  is less robust on thin history.
- **Decided:** no `refreshPrices()` trigger. `GOOGLEFINANCE` refreshes itself.

Recommend new structural work only from a current finding, not from this list.
