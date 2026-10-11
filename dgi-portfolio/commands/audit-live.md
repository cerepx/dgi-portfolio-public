---
description: Audit the live Google Sheet — snapshot, rebuild, run the integrity checks
---

# Audit the live portfolio sheet

Run the full integrity audit against **ClaudePortofoliu as it is right now**,
not against a stale local export.

## Why this exists

`audit_formulas.py` needs an `.xlsx`. Every local export is dead: it lags the
sheet, may carry an obsolete column layout, and every `GOOGLEFINANCE`,
`SPARKLINE` and `IMPORTHTML` formula has been flattened into
`__xludf.DUMMYFUNCTION`. Auditing one describes a spreadsheet that no longer
exists.

So the data is pulled live through the bridge, rebuilt into a workbook that
holds real formulas, and audited from there.

## Steps

Do these in order. Do not skip step 1 even if a `sheet-snapshot.json` already
exists — an old snapshot is the exact problem this command was built to avoid.
Say so and re-take it.

**1. Take the snapshot.** Call the `bridge_snapshot` MCP tool with `out_path`
set to `sheet-snapshot.json` inside the user's working folder (absolute path).

This runs on the user's machine, which is the only place with a route to
`script.google.com` and a copy of the bridge token. It is read-only: it calls
`ping`, `structure` and `read` only, and does **not** require `ALLOW_WRITES`.
It returns a summary, never cell data — the cells go to the file.

If the tool is missing, the installed plugin predates it. Fall back to asking
the user to run:

```
python3 dgi-portfolio/skills/portfolio-audit/scripts/snapshot_fetch.py
```

**2. Rebuild the workbook.**

```
python3 -B dgi-portfolio/skills/portfolio-audit/scripts/snapshot_to_xlsx.py \
    sheet-snapshot.json -o live-audit.xlsx
```

**3. Run the integrity audit.**

```
python3 -B dgi-portfolio/skills/portfolio-audit/scripts/audit_formulas.py \
    live-audit.xlsx --config dgi-portfolio/config/portfolio.json
```

**4. Run the error-value scan.** Step 3 cannot see `#REF!` or `#N/A`: it reads
formulas, and errors live in cached results. This closes that blind spot and is
not optional.

```
python3 -B dgi-portfolio/skills/portfolio-audit/scripts/scan_error_values.py \
    sheet-snapshot.json
```

**5. Check for dividend payments missing from the sheet.** Steps 3-4 validate
what is already on `Dividends received`; neither can see a payment that was
never typed in at all. This step compares the sheet against Flex, which is an
independent source of what actually happened in the account.

```
python3 -B dgi-portfolio/skills/portfolio-audit/scripts/check_missing_dividends.py \
    sheet-snapshot.json flex-dividends.json
```

`flex-dividends.json` does not exist yet. Produce it with ONE tool call:

1. Call `flex_dividends` (from `dgi-ibkr-flex`) with three arguments:
   - `query`: **`"dividends"`**. It is required and has no default. Omitting it
     fails with a bare `ERROR: 'query'`, which reads like a bug and is not one.
     `flex_queries` lists the configured names if this ever changes.
   - `out_path`: `flex-dividends.json` inside the user's working folder, as an
     **absolute path**. The tool writes the rows to the file and returns only a
     count.
   - `include_withholding`: **`false`**. The tool defaults to `true`, and a
     Withholding Tax row shares the exact same `(year, month, ticker)` key as
     its own Dividends row. The script filters these out on its own now (a real
     run on 2026-08-22 caught a JNJ payment that was clearly on the sheet being
     reported "missing" because its withholding sibling consumed the match
     first), but there is no reason to pull 2-3x the rows just to filter them
     back out.

   **Never copy rows out of a tool response into a file by hand.** That is what
   `out_path` exists to prevent: the rows are amounts, pay dates and
   transaction ids, and one mistyped figure invents a missing payment or hides
   a real one. See BACKLOG item 19.

2. Run the script above against that file and the same `sheet-snapshot.json`
   from step 1.

If the `flex_dividends` tool is unreachable (DNS, disconnected app, missing
token) — this has happened before, see `BACKLOG.md` — say so and skip this
step rather than blocking the rest of the audit on it; the other four steps
do not depend on it.

**6. Report.** Group by severity. For every finding, state whether it is new,
already tracked in `BACKLOG.md`, or already resolved and therefore a stale
rule. Do not repeat known-and-accepted findings as if they were discoveries.
Report any rows from step 5 under their own heading — "Flex payments missing
from the sheet" — separate from the structural findings, since fixing them
means proposing new rows to add, not correcting an existing one.

## Rules

- **Read-only, all six steps.** Never propose a `bridge_write` from an audit.
  If something needs fixing — including a missing dividend row found in step
  5 — report it and let the user decide. Adding a missing row needs the same
  exact-diff, explicit-approval cycle as any other write; an audit finding is
  never itself the approval.
- **Always `python3 -B`.** Without it, every run leaves a `__pycache__` inside
  the user's working folder that the agent sandbox cannot delete.
- **Do not audit the local `.xlsx` files.** `Portofoliu.xlsx` is kept as an
  archive of the pre-migration state, not as an audit target. Its MD5 is
  recorded in `dgi-portfolio/README.md`; never write to it.
- Known findings the audit re-reports every run, all tracked in `BACKLOG.md` —
  mention them as known, do not re-litigate: `T13:T18` mixed formulas and
  literals (commissions, item 3), and `getYahooPrice` / `getBVBPrice` being
  Apps Script functions. `N14/N16/N17/N18` became formulas on 2026-10-11 and
  `Evolutie`'s fixed-row references were replaced by `SUMIFS` (item 4), so a
  finding on either is new, not known.
- **Any CRITICAL on `Dividends received` is real and urgent.** The spill-anchor
  check fires only when `F2`, `G2` or `H2` has stopped being an ARRAYFORMULA
  while values remain below it — that means the column has silently emptied for
  every earlier row and `MyShares` `Q` is understated right now. Report it
  first, before anything else in the run.
- The frequency finding is INFO when it verifies and **SERIOUS when it does
  not**. A SERIOUS one means annual income is wrong by the ratio of the two
  numbers; do not soften it.
