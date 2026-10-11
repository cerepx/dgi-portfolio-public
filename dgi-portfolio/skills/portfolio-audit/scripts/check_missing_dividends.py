#!/usr/bin/env python3
"""Find dividend payments visible in IBKR Flex but missing from the sheet.

WHY THIS IS SEPARATE FROM audit_formulas.py
--------------------------------------------
`audit_formulas.py` validates the *shape* of what is already on the sheet -
formulas, ranges, references. It has no way to know a payment happened at all
if no row was ever typed for it. This script closes that blind spot the other
direction: it does not check the sheet is internally consistent, it checks the
sheet against an external source of truth (Flex) for completeness.

A payment can exist in Flex
and have no row on the sheet at all. Not a bug - ordinary data-entry lag - but
worth automating so it does not depend on someone noticing by eye.

MATCHING KEY
------------
`(year, month, ticker)`, same key item 5 used to line up the two data sets.
Flex's `pay_date` is `YYYYMMDD`; the sheet's `Year`/`Month` are separate
columns. This is coarser than a date match on purpose - the sheet was never
guaranteed to record the exact IBKR pay date, only the year and month, so a
same-day requirement would produce false positives for real rows that are
just dated slightly differently.

Matching is by COUNT, not just by key presence: if Flex shows two ABBV
payments in the same month (rare, but IBKR can split a payment) and the sheet
only has one row for that key, the second is reported missing even though the
key "ABBV / 2026 / 8" exists once already. A `collections.Counter` seeded from
the sheet is decremented as Flex rows are consumed in order; a Flex row that
finds no remaining sheet credit is reported.

INPUTS
------
1. A `sheet-snapshot.json` from `bridge_snapshot` (same file `audit-live`
   already produces in step 1) - read for the `Dividends received` sheet's
   `Year`/`Month`/`Ticker` columns (A/B/C, i.e. index 0/1/2).
2. A JSON dump of the `flex_dividends` MCP tool's own output (the `{"cols":
   [...], "rows": [...]}` shape) - there is no file for this by default,
   since it is a live MCP call; save the tool result to a file first.

USAGE
-----
    python3 check_missing_dividends.py sheet-snapshot.json flex-dividends.json
    python3 check_missing_dividends.py sheet-snapshot.json flex-dividends.json --json

This is READ-ONLY. It never proposes or applies a bridge_write - it reports,
same as every other check in this skill. Adding a missing row is a separate,
explicit, per-batch approval step, same as any other sheet write.
"""

import argparse
import json
import sys
from collections import Counter

SHEET_NAME = "Dividends received"


def load_sheet_keys(snapshot):
    """Return a Counter of (year:int, month:int, ticker:str) from the sheet."""
    sheet = snapshot["sheets"].get(SHEET_NAME)
    if sheet is None:
        raise SystemExit("No '%s' sheet in this snapshot." % SHEET_NAME)

    rows = sheet.get("displayValues") or []
    keys = Counter()
    for row in rows[1:]:  # skip header
        if len(row) < 3:
            continue
        year_raw, month_raw, ticker = row[0], row[1], row[2]
        if not (year_raw and month_raw and ticker):
            continue
        try:
            year, month = int(float(year_raw)), int(float(month_raw))
        except ValueError:
            continue
        keys[(year, month, ticker.strip().upper())] += 1
    return keys


def load_flex_rows(flex_dump):
    """Return a list of dicts, one per flex_dividends row, in original order."""
    cols = flex_dump["cols"]
    idx = {name: i for i, name in enumerate(cols)}
    required = ("pay_date", "symbol", "amount")
    missing_cols = [c for c in required if c not in idx]
    if missing_cols:
        raise SystemExit("flex_dividends dump is missing columns: %s"
                          % ", ".join(missing_cols))

    out = []
    for row in flex_dump["rows"]:
        # Skip anything that isn't an actual dividend payment. flex_dividends
        # defaults to include_withholding=true, and a Withholding Tax row
        # shares the SAME (year, month, ticker) key as its own Dividends row -
        # left in, it silently eats the sheet's one matching credit and makes
        # the real Dividends row for that payment report as "missing" (caught
        # live 2026-08-22, first real /audit-live step-5 run: a JNJ payment
        # that was clearly on the sheet came back flagged, because its
        # Withholding Tax sibling consumed the match first). Filtering here,
        # not just documenting "pass include_withholding=false", makes this
        # safe regardless of how the caller invoked the tool.
        if "type" in idx and str(row[idx["type"]]).strip() != "Dividends":
            continue
        pay_date = str(row[idx["pay_date"]])
        if len(pay_date) != 8:
            continue
        year, month = int(pay_date[0:4]), int(pay_date[4:6])
        entry = {
            "pay_date": pay_date,
            "symbol": str(row[idx["symbol"]]).strip().upper(),
            "amount": row[idx["amount"]],
            "year": year,
            "month": month,
        }
        for extra in ("currency", "type", "transaction_id", "gross_per_share"):
            if extra in idx:
                entry[extra] = row[idx[extra]]
        out.append(entry)
    return out


def find_missing(sheet_keys, flex_rows):
    """Consume sheet_keys as flex_rows are matched; whatever is left over
    unmatched is reported missing. Does not mutate the caller's Counter."""
    remaining = Counter(sheet_keys)
    missing = []
    for entry in flex_rows:
        key = (entry["year"], entry["month"], entry["symbol"])
        if remaining[key] > 0:
            remaining[key] -= 1
        else:
            missing.append(entry)
    return missing


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("snapshot", help="sheet-snapshot.json from bridge_snapshot")
    parser.add_argument("flex_dump", help="saved flex_dividends tool output (JSON)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    with open(args.snapshot, encoding="utf-8") as fh:
        snapshot = json.load(fh)
    with open(args.flex_dump, encoding="utf-8") as fh:
        flex_dump = json.load(fh)

    sheet_keys = load_sheet_keys(snapshot)
    flex_rows = load_flex_rows(flex_dump)
    missing = find_missing(sheet_keys, flex_rows)

    if args.json:
        print(json.dumps({
            "sheet_rows": sum(sheet_keys.values()),
            "flex_rows": len(flex_rows),
            "missing": missing,
        }, indent=1))
        return 1 if missing else 0

    print("=" * 78)
    print("MISSING-DIVIDEND SCAN vs Flex - %d sheet rows, %d Flex rows"
          % (sum(sheet_keys.values()), len(flex_rows)))
    print("=" * 78)

    if not missing:
        print("Every Flex payment in this window has a matching sheet row.")
    else:
        print("%d Flex payment(s) have NO matching row in '%s':\n"
              % (len(missing), SHEET_NAME))
        for entry in missing:
            print("  %s  %-6s  %s %s  (%s)"
                  % (entry["pay_date"], entry["symbol"], entry["amount"],
                     entry.get("currency", ""), entry.get("type", "?")))
        print("\nThis is a completeness gap, not a sheet-integrity error - "
              "report it, do not write a fix without a separate explicit "
              "approval for the exact rows to add.")
    print("=" * 78)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
