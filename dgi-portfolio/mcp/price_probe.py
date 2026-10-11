#!/usr/bin/env python3
"""Diagnose the price source one layer at a time. Run this before blaming code.

Separates token, transport, parsing and verification, so a failure names its
own layer instead of arriving as one opaque traceback:

    1. Is a Tiingo token present?
    2. Does the API answer, and with how many rows?
    3. Are the splits the ones the filings show?
    4. Does our split arithmetic verify against Tiingo's own adjClose?

Usage, from the plugin root:

    python3 -B mcp/price_probe.py            # KO
    python3 -B mcp/price_probe.py MA V KO    # the acceptance set

MA, V and KO are the acceptance set because each has a split inside the window
(10:1 2014, 4:1 2015, 2:1 2012), and a split is what makes an adjustment error
visible. A quiet ticker would pass either way.

Read-only. Touches nothing but `~/.dgi/price-cache/`.
"""

import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import price_core  # noqa: E402

OK, BAD, NA = "  ok  ", " FAIL ", "  --  "


def line(status, label, detail=""):
    print("[%s] %-26s %s" % (status, label, detail))


def probe_token():
    print("\n--- token ---")
    try:
        price_core.tiingo_token()
    except price_core.PriceError as err:
        line(BAD, "tiingo token", str(err))
        return False
    line(OK, "tiingo token", "present (not printed)")
    return True


def probe_ticker(ticker):
    print("\n--- %s ---" % ticker.upper())

    try:
        data = price_core.fetch_tiingo(ticker, use_cache=False)
    except price_core.PriceError as err:
        line(BAD, "tiingo prices", str(err))
        return

    annual = price_core.annual_averages(data["bars"])
    line(OK, "tiingo prices",
         "%d rows, %d years" % (len(data["bars"]), len(annual)))

    splits = data["splits"]
    line(OK if splits else NA, "splits",
         ", ".join("%s %s" % (s["date"], s["label"]) for s in splits)
         or "none in window")

    factors = price_core.split_factors_by_year(splits, sorted(annual))
    adjusted = {y: f for y, f in factors.items() if f != 1.0}
    line(OK if adjusted else NA, "as-filed EPS factors",
         str(adjusted) if adjusted else "all 1.0 - no split in window")

    report = price_core.verify_split_arithmetic(data["bars"], splits)
    status = {True: OK, False: BAD, None: NA}[report["ok"]]
    line(status, "split verification",
         "%s, %d rows, dividend factor %.4f" % (
             report["verdict"], report.get("rows_checked", 0),
             report.get("dividend_factor", 0.0)))
    for problem in report.get("problems", []):
        print("       %s" % problem)

    years = sorted(annual)
    if years:
        first, last = years[0], years[-1]
        line(NA, "sample averages",
             "%d: %.2f   %d: %.2f" % (first, annual[first]["average"],
                                      last, annual[last]["average"]))


def main():
    tickers = sys.argv[1:] or ["KO"]
    print("Probing %s" % ", ".join(t.upper() for t in tickers))
    if not probe_token():
        return 1
    for ticker in tickers:
        probe_ticker(ticker)
    print("\nA `dividend_factor` near 1.00 for a long-time payer means the "
          "adjustment is not being applied - check before trusting a yield.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
