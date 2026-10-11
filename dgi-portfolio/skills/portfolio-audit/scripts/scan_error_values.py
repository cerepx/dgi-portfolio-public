#!/usr/bin/env python3
"""Report cells whose *displayed* value is a spreadsheet error.

WHY THIS IS SEPARATE FROM audit_formulas.py
-------------------------------------------
`audit_formulas.py` opens the workbook with `data_only=False`, so a formula
cell hands it the formula text, never the result. `#REF!`, `#N/A` and `#NAME?`
live in the *cached result*, so its `check_formula_errors` can only ever catch
an error typed in as a literal. On a workbook rebuilt from a bridge snapshot it
is structurally blind: every formula cell holds a formula.

The snapshot carries `displayValues` precisely so that blind spot can be
covered. This script reads them and nothing else.

Do not fold this into audit_formulas.py -- that script's contract is that it
works on any .xlsx, and display values are not available there.

A note on false negatives: `=IFERROR(SPARKLINE(...), "N/A")` displays the
string `N/A`, not `#N/A`, so a caught error looks identical to a deliberate
"not applicable" marker. Those are reported separately, as suspicions rather
than findings, because in this sheet `N/A` is also the intentional marker for
every DGI-only column on the non-DGI rows.

USAGE
-----
    python3 scan_error_values.py sheet-snapshot.json
    python3 scan_error_values.py sheet-snapshot.json --json
"""

import argparse
import json
import sys

# Real spreadsheet errors. These can only appear as a computed result.
ERROR_MARKERS = ("#REF!", "#N/A", "#NAME?", "#VALUE!", "#DIV/0!", "#ERROR!",
                 "#NUM!", "#NULL!")

# Not errors, but worth surfacing: a formula still resolving, or a value that
# an IFERROR turned into a friendly string.
SUSPECT_EXACT = ("N/A", "Loading...", "#GETTING_DATA")


def column_letter(index):
    """0-based column index -> A, Z, AA."""
    letters = ""
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def scan(snapshot):
    errors, suspects = [], []

    for name, sheet in snapshot["sheets"].items():
        display = sheet.get("displayValues") or []
        formulas = sheet.get("formulas") or []

        for r, row in enumerate(display):
            for c, value in enumerate(row):
                if not isinstance(value, str) or not value.strip():
                    continue
                text = value.strip()
                cell = "%s%d" % (column_letter(c), r + 1)

                formula = ""
                if r < len(formulas) and c < len(formulas[r]):
                    formula = (formulas[r][c] or "").strip()

                hit = {"sheet": name, "cell": cell, "value": text,
                       "formula": formula[:120]}

                if any(marker in text for marker in ERROR_MARKERS):
                    errors.append(hit)
                elif text in SUSPECT_EXACT and formula:
                    # Only interesting when a formula produced it. A typed
                    # "N/A" is the sheet's deliberate not-applicable marker.
                    suspects.append(hit)

    return errors, suspects


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("snapshot")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    with open(args.snapshot, encoding="utf-8") as fh:
        snapshot = json.load(fh)

    errors, suspects = scan(snapshot)

    if args.json:
        print(json.dumps({"errors": errors, "suspects": suspects}, indent=1))
        return 1 if errors else 0

    print("=" * 78)
    print("ERROR-VALUE SCAN - %s, snapshot %s"
          % (snapshot.get("spreadsheet", "?"), snapshot.get("fetched_at", "?")))
    print("=" * 78)
    print("ERRORS: %d   SUSPECT: %d\n" % (len(errors), len(suspects)))

    for label, rows in (("ERRORS", errors), ("SUSPECT", suspects)):
        if not rows:
            continue
        print("--- %s %s" % (label, "-" * (74 - len(label))))
        for hit in rows:
            print("  %s!%s = %s" % (hit["sheet"], hit["cell"], hit["value"]))
            if hit["formula"]:
                print("      %s" % hit["formula"])
        print()

    if not errors:
        print("No cell in the snapshot displays a spreadsheet error.")
    print("=" * 78)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
