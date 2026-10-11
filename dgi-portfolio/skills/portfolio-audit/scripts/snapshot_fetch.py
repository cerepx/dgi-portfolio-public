#!/usr/bin/env python3
"""Fetch a formula-level snapshot of the live Google Sheet into a JSON file.

WHY THIS EXISTS
---------------
`audit_formulas.py` reads an .xlsx. The only .xlsx files available locally are
dead exports from Google Sheets: they lag the live sheet, they carry the old
column layout, and every GOOGLEFINANCE / SPARKLINE / IMPORTHTML formula is
flattened into `__xludf.DUMMYFUNCTION`. Auditing them produces findings about a
spreadsheet that no longer exists.

This script closes that gap by reading the live sheet through the same Apps
Script bridge the MCP server uses, and writing the result to a JSON snapshot.
`snapshot_to_xlsx.py` then turns that snapshot into a workbook the existing
audit can consume unchanged.

WHERE IT RUNS
-------------
**On the user's machine, not in the agent sandbox.** The sandbox has no network
route to script.google.com (verified 2026-08-01: DNS fails and the proxy
returns 403). The bridge token also lives only on the host, in
`~/.dgi/sheet-bridge.json`. This script therefore reuses `call_bridge` from
`mcp/sheet_bridge_server.py` so there is exactly one copy of the transport and
one copy of the token-redaction logic.

READ-ONLY. It calls the `structure` and `read` actions only. It can never
write, and it does not need `ALLOW_WRITES`.

USAGE
-----
    python3 dgi-portfolio/skills/portfolio-audit/scripts/snapshot_fetch.py
    python3 ... snapshot_fetch.py --out sheet-snapshot.json --sheets MyShares

The snapshot lands next to the repo root by default. It contains formulas, raw
(unformatted) values and display values for every cell, which is more than the
audit needs -- the extra copies cost disk, not conversation context, and having
raw values is what lets the audit see real numbers instead of "$147.61".
"""

import argparse
import json
import sys
from pathlib import Path

# Importing sheet_bridge_server would otherwise drop a __pycache__ directory
# inside the repo. Files created that way are awkward to remove and are pure
# noise in a mounted working folder, so refuse to emit bytecode at all. This
# must be set before the import below, not after.
sys.dont_write_bytecode = True

# scripts -> portfolio-audit -> skills -> dgi-portfolio -> repo root.
# Same indexing convention audit_formulas.py uses for its default config path.
PLUGIN_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(__file__).resolve().parents[4]
MCP_DIR = PLUGIN_ROOT / "mcp"

sys.path.insert(0, str(MCP_DIR))

try:
    # sheet_bridge_server guards its MCP loop behind __main__, so importing it
    # costs nothing and gives us the single canonical copy of the transport,
    # the config loader and the token redaction. snapshot_core holds the read
    # loop, shared with the bridge_snapshot MCP tool so the two cannot drift.
    from sheet_bridge_server import call_bridge  # noqa: E402
    import snapshot_core  # noqa: E402
except ImportError as exc:  # pragma: no cover - depends on host layout
    sys.exit("Cannot import the bridge transport from %s: %s\n"
             "Run this script from inside the claude-dgi repo." % (MCP_DIR, exc))


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(REPO_ROOT / "sheet-snapshot.json"),
                        help="where to write the snapshot (default: repo root)")
    parser.add_argument("--sheets", nargs="*", default=None,
                        help="limit to these sheet names (default: all visible)")
    parser.add_argument("--max-rows", type=int,
                        default=snapshot_core.DEFAULT_MAX_ROWS,
                        help="safety cap on rows per sheet (default 400)")
    args = parser.parse_args()

    def progress(name, cell_range):
        print("reading %-32s %s" % (name, cell_range), file=sys.stderr)

    try:
        snapshot = snapshot_core.build_snapshot(
            call_bridge, sheets=args.sheets, max_rows=args.max_rows,
            progress=progress)
    except RuntimeError as exc:
        sys.exit(str(exc))

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, ensure_ascii=False, indent=1)

    total = sum(len(s["formulas"]) for s in snapshot["sheets"].values())
    print("\nwrote %s\n  %d sheets, %d rows, skipped %s"
          % (args.out, len(snapshot["sheets"]), total,
             ", ".join(snapshot["skipped"]) or "nothing"), file=sys.stderr)


if __name__ == "__main__":
    main()
