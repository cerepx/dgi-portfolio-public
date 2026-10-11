#!/usr/bin/env python3
"""
Parse dripinvesting.org data for the DGI scoring model.

Replaces parse_dividend_radar.py, which targeted the old CCC / Dividend Radar
spreadsheet. That file is no longer the source: dripinvesting publishes the same
information through a public screener, and the emailed spreadsheet the old script
expected is both harder to get and less complete.

Two subcommands, because there are two surfaces with different jobs:

  screener   parse the downloaded stock screener CSV
             (~690 rows: DGR 1/3/5/10Y, Chowder, Stock Type, payment frequency)

  history    parse a saved per-stock dividend history page
             (~20 years of individual payments: exact growth streak, DGR over
             any window, annual dividend and price for the Weiss model)

Both take a local file. Neither performs HTTP - the history page is fetched with
the agent's own web tooling and saved to disk first. Keeping network access out
of this script is deliberate: it stays testable offline and there is exactly one
place where a URL is fetched.

Usage:
    python3 parse_dripinvesting.py screener stocks-2026-07-31.csv --tickers KO,MO
    python3 parse_dripinvesting.py screener stocks-2026-07-31.csv --unresolved
    python3 parse_dripinvesting.py history ko-history.txt --ticker KO
    python3 parse_dripinvesting.py history ko-history.txt --ticker KO --json

Two guarantees this script makes, both learned by getting them wrong first:

1. It never emits a price, yield or valuation field from the screener CSV.
   Those columns are not merely stale - on 2026-07-31 QCOM was listed at $229.49
   against an actual $150.91, a 52% error. Pass --unsafe-prices if you have an
   independent reason to want them; it prints a warning to stderr every time.

2. It never converts a Stock Type bucket into a year count. Contender spans
   10-24 years and criterion 1 scores at 15+/10-15/under 10, so a Contender is
   reported as UNRESOLVED with a pointer to the history page, not guessed at.
"""

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

# Stock Type -> (min_years, max_years_or_None). dripinvesting's own definitions.
BUCKETS = {
    "King":       (50, None),
    "Champion":   (25, 49),
    "Contender":  (10, 24),
    "Challenger": (5, 9),
}

# Criterion 1 thresholds from references/scoring-model.md: 3 at 15+, 2 at 10-15,
# 1 under 10.
def criterion_1_from_bucket(stock_type):
    """
    Resolve criterion 1 from the bucket alone, or say plainly that it cannot be.
    Returns (points_or_None, explanation).
    """
    span = BUCKETS.get(stock_type)
    if span is None:
        return None, f"unknown Stock Type {stock_type!r}"
    low, high = span
    if low >= 15:
        return 3, f"{stock_type} means {low}+ years, above the 15-year threshold"
    if high is not None and high < 10:
        return 1, f"{stock_type} means {low}-{high} years, below 10"
    if high is not None and high < 15:
        return 2, f"{stock_type} means {low}-{high} years"
    # Contender: 10-24 straddles the 15-year line.
    return None, (f"{stock_type} spans {low}-{high} years, which straddles the "
                  "15-year threshold between 2 and 3 points - resolve from the "
                  "per-stock history page, do not guess")

# Screener columns this script will surface. Price, yield and valuation columns
# are deliberately absent - see the module docstring.
SAFE_FIELDS = [
    "Symbol", "Company", "Stock Type", "Sector", "Industry",
    "Current Div", "Payouts/Year", "Previous Div",
    "Ex-Date", "Pay-Date",
    "Chowder Number", "DGR 1Y", "DGR 3Y", "DGR 5Y", "DGR 10Y",
    "Debt/Capital", "ROE",
]
UNSAFE_FIELDS = [
    "Price", "Div Yield", "5Y Avg Yield", "Annualized",
    "FV (Peter Lynch)", "FV (Peter Lynch) %", "P/E", "P/BV", "PEG",
    "Low", "High", "TTR 1Y", "TTR 3Y",
]

PAYMENT_RE = re.compile(
    r"^\|\s*(\d{2})/(\d{2})/(\d{4})\s*\|"      # ex-date
    r"[^|]*\|"                                  # record/pay date, ignored
    r"\s*\$?([\d,]+\.?\d*)\s*\|"                # amount
    r"[^|]*\|"                                  # yield, ignored
    r"[^|]*\|"                                  # yield on cost, ignored
    r"\s*\$?([\d,]+\.?\d*)"                     # price
)


def to_float(text):
    if text is None:
        return None
    text = str(text).strip().replace("$", "").replace(",", "").replace("%", "")
    if text in ("", "-", "—", "n/a", "N/A"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


# ----------------------------------------------------------------- screener --

def cmd_screener(args):
    path = Path(args.file)
    if not path.exists():
        sys.exit(f"No such file: {path}")

    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = {r["Symbol"].strip(): r for r in csv.DictReader(fh) if r.get("Symbol")}

    if not rows:
        sys.exit("No rows with a Symbol column. Is this the screener CSV from "
                 "https://www.dripinvesting.org/stocks/ ?")

    fields = list(SAFE_FIELDS)
    if args.unsafe_prices:
        print("WARNING: emitting price and valuation columns from the screener "
              "CSV. These are unreliable - a 52% error was measured on "
              "2026-07-31. Do not use them for valuation.", file=sys.stderr)
        fields += UNSAFE_FIELDS

    wanted = [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else sorted(rows)

    out, missing = [], []
    for ticker in wanted:
        row = rows.get(ticker)
        if row is None:
            missing.append(ticker)
            continue
        rec = {f: row.get(f) for f in fields if f in row}
        pts, why = criterion_1_from_bucket(row.get("Stock Type", "").strip())
        rec["criterion_1_points"] = pts
        rec["criterion_1_note"] = why
        rec["history_page_needed"] = pts is None
        out.append(rec)

    if args.unresolved:
        out = [r for r in out if r["history_page_needed"]]

    result = {
        "source_file": path.name,
        "rows_in_file": len(rows),
        "returned": len(out),
        "not_found": missing,
        "price_fields_included": bool(args.unsafe_prices),
        "records": out,
    }

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print(f"{path.name}: {len(rows)} tickers in file\n")
    for r in out:
        pts = r["criterion_1_points"]
        flag = f"{pts} pts" if pts is not None else "UNRESOLVED"
        print(f"{r['Symbol']:<7} {r.get('Stock Type',''):<11} criterion 1: {flag}")
        print(f"        {r['criterion_1_note']}")
        print(f"        DGR 1Y {r.get('DGR 1Y','—'):>7}  3Y {r.get('DGR 3Y','—'):>7}"
              f"  5Y {r.get('DGR 5Y','—'):>7}  10Y {r.get('DGR 10Y','—'):>7}"
              f"   Chowder {r.get('Chowder Number','—')}")
        print(f"        div {r.get('Current Div','—')} x{r.get('Payouts/Year','—')}"
              f"/yr   ex {r.get('Ex-Date','—')}   pay {r.get('Pay-Date','—')}")
        print()
    if missing:
        print(f"Not in file: {', '.join(missing)}")
    unresolved = [r["Symbol"] for r in out if r["history_page_needed"]]
    if unresolved:
        print(f"\nNeed the history page to score criterion 1: {', '.join(unresolved)}")


# ------------------------------------------------------------------ history --

def parse_history(path):
    """Extract (year, month, amount, price) from a saved history page."""
    payments = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        m = PAYMENT_RE.match(line)
        if not m:
            continue
        month, _day, year, amount, price = m.groups()
        payments.append({
            "year": int(year),
            "month": int(month),
            "amount": to_float(amount),
            "price": to_float(price),
        })
    return payments


def annual_totals(payments):
    per_year = defaultdict(float)
    counts = defaultdict(int)
    prices = defaultdict(list)
    for p in payments:
        if p["amount"] is None:
            continue
        per_year[p["year"]] += p["amount"]
        counts[p["year"]] += 1
        if p["price"] is not None:
            prices[p["year"]].append(p["price"])
    return per_year, counts, prices


def growth_streak(per_year, counts):
    """
    Count consecutive years of dividend growth, using COMPLETE years only.

    A partial current year understates its total and would fake a cut, so the
    most recent year is excluded whenever it has fewer payments than the year
    before it.

    But excluding it also hides a raise that has already been declared, and that
    matters: a company on 14 complete years that raised again this year is on 15,
    which is the line between 2 and 3 points on criterion 1. So the partial year
    is compared on a PER-PAYMENT basis instead, and reported separately rather
    than folded into the count.

    Returns (streak, through_year, note, partial).
    `partial` is None, or a dict describing the excluded year.
    """
    years = sorted(per_year)
    if len(years) < 2:
        return 0, None, "not enough history", None

    note, partial = "", None
    last = years[-1]
    if counts[last] < counts.get(years[-2], 0):
        prev = years[-2]
        rate_now = per_year[last] / counts[last]
        rate_prev = per_year[prev] / counts[prev]
        partial = {
            "year": last,
            "payments_so_far": counts[last],
            "per_payment": round(rate_now, 4),
            "per_payment_prior_year": round(rate_prev, 4),
            "raised": rate_now > rate_prev,
        }
        note = (f"{last} excluded from the count as incomplete "
                f"({counts[last]} payments vs {counts[prev]})")
        years = years[:-1]

    streak = 0
    for i in range(len(years) - 1, 0, -1):
        if per_year[years[i]] > per_year[years[i - 1]]:
            streak += 1
        else:
            break
    return streak, (years[-1] if years else None), note, partial


def cagr(a, b, n):
    if not a or not b or a <= 0 or n <= 0:
        return None
    return ((b / a) ** (1 / n) - 1) * 100


def cmd_history(args):
    payments = parse_history(args.file)
    if not payments:
        sys.exit(f"No payment rows found in {args.file}. Expected lines shaped "
                 "like '| 06/15/2026 | 06/15/2026 | $0.530 | 2.57% | 2.62% | $80.91 |'")

    per_year, counts, prices = annual_totals(payments)
    streak, through, note, partial = growth_streak(per_year, counts)
    years = sorted(per_year)

    # A declared raise in the incomplete year extends the streak by one.
    effective = streak + 1 if (partial and partial["raised"]) else streak
    points = 3 if effective >= 15 else 2 if effective >= 10 else 1

    dgr = {}
    if through:
        for window in (1, 3, 5, 10, 15):
            base = through - window
            if base in per_year:
                dgr[f"{window}y"] = cagr(per_year[base], per_year[through], window)

    # Annual average price feeds the Weiss Dividend Yield Model.
    yearly = [{
        "year": y,
        "payments": counts[y],
        "dividend": round(per_year[y], 4),
        "avg_price": round(sum(prices[y]) / len(prices[y]), 2) if prices[y] else None,
    } for y in years]

    if args.json:
        print(json.dumps({
            "ticker": args.ticker,
            "source_file": Path(args.file).name,
            "payments_parsed": len(payments),
            "first_year": years[0],
            "last_year": years[-1],
            "growth_streak_complete_years": streak,
            "growth_streak_effective": effective,
            "criterion_1_points": points,
            "streak_counted_through": through,
            "streak_note": note,
            "incomplete_year": partial,
            "dgr_percent": {k: (round(v, 2) if v is not None else None)
                            for k, v in dgr.items()},
            "annual": yearly,
        }, indent=2))
        return

    label = args.ticker or Path(args.file).stem
    print(f"{label}: {len(payments)} payments parsed, {years[0]}-{years[-1]}\n")
    print(f"Consecutive years of dividend growth: {streak}  (complete years, through {through})")
    if note:
        print(f"  note: {note}")
    if partial:
        if partial["raised"]:
            print(f"  {partial['year']} pays {partial['per_payment']} per payment "
                  f"vs {partial['per_payment_prior_year']} - a raise is already "
                  f"declared, so the streak is effectively {effective}")
        else:
            print(f"  {partial['year']} pays {partial['per_payment']} per payment "
                  f"vs {partial['per_payment_prior_year']} - NO raise yet this year")
    print(f"  criterion 1: {points} points"
          f"{'  (boundary case - streak is 14 or 15)' if effective in (14, 15) else ''}\n")

    if dgr:
        print("DGR from actual payments:")
        for k in ("1y", "3y", "5y", "10y", "15y"):
            if k in dgr and dgr[k] is not None:
                print(f"  {k:>4}: {dgr[k]:6.2f}%")
        print()

    print(f"{'year':>6} {'pmts':>5} {'dividend':>10} {'avg price':>10}")
    for r in yearly[-args.years:]:
        px = f"{r['avg_price']:.2f}" if r["avg_price"] else "—"
        print(f"{r['year']:>6} {r['payments']:>5} {r['dividend']:>10.4f} {px:>10}")


# --------------------------------------------------------------------- main --

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    s = sub.add_parser("screener", help="parse the downloaded stock screener CSV")
    s.add_argument("file")
    s.add_argument("--tickers", help="comma separated; default is every row")
    s.add_argument("--unresolved", action="store_true",
                   help="only tickers whose criterion 1 needs the history page")
    s.add_argument("--unsafe-prices", action="store_true",
                   help="also emit price and valuation columns; they are unreliable")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_screener)

    h = sub.add_parser("history", help="parse a saved per-stock history page")
    h.add_argument("file")
    h.add_argument("--ticker", help="label for the report")
    h.add_argument("--years", type=int, default=25,
                   help="how many recent years to print (default 25)")
    h.add_argument("--json", action="store_true")
    h.set_defaults(func=cmd_history)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
