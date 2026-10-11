#!/usr/bin/env python3
"""dgi-prices - annual average share prices as MCP tools.

The fourth local server, and it exists for the same reason as `dgi-edgar`:

1. The agent sandbox has no route to arbitrary hosts.
2. **Response size.** A 15-year daily series is ~3,800 rows per ticker. The
   fetch happens here and only the annual averages go back - about fifteen
   numbers, plus the split events needed to use them correctly.

It closes the last hard gap in `company-analysis`. Every denominator for
valuation methods 1-5 was already solved by `dgi-edgar`; this is the numerator.

Reads a Tiingo token from `~/.dgi/prices.json`; it travels in an Authorization
header and never in a URL. Read-only otherwise: HTTP GETs plus a cache under
`~/.dgi/price-cache/`.

**Single source.** Yahoo and Stooq were built as cross-checks and removed on
2026-08-03 once both proved to be behind anti-bot walls - dead code that looks
live is worse than none. There is therefore no second opinion on these prices,
only the internal `verification`. Say so when a valuation depends on them.

THREE THINGS A CALLER MUST NOT SKIP
-----------------------------------
- `adjustment` is always `split_only`. If a future change makes it anything
  else, methods 1-5 are invalid until the change is understood.
- `split_factor_by_filing_date` is not decoration. EDGAR EPS is as-filed;
  these prices are split-adjusted. **Key it on the `filed` date that
  `edgar_financials` returns for that year, never on the year itself** - EDGAR
  restates recent years, so a year just before a split is often already
  post-split, and rescaling it again inflates the multiple by the full split
  ratio. It replaced `as_filed_eps_factor`, which was year-keyed and wrong.
- `verification.verdict` must read `consistent`. Anything else means the split
  arithmetic is suspect and no valuation should be reported from the series.
"""

import json
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import price_core  # noqa: E402

PROTOCOL_VERSION_FALLBACK = "2024-11-05"
SERVER_INFO = {"name": "dgi-prices", "version": "0.6.0"}

TOOLS = [
    {
        "name": "price_annual_averages",
        "description": (
            "Average share price per year over 10-15 years from Tiingo, "
            "reduced on this machine so the ~3,800-row daily series never "
            "reaches the conversation. This is the numerator for valuation "
            "methods 1-5 in company-analysis; every denominator comes from "
            "edgar_financials. Prices are SPLIT-adjusted only, never "
            "dividend-adjusted, and the split adjustment is COMPUTED here from "
            "raw close plus splitFactor - a dividend-adjusted series silently "
            "inflates historical yields and biases the Weiss estimate low. "
            "Also returns split events and, per year, the factor that puts "
            "AS-FILED EDGAR per-share figures on the same basis as these "
            "prices; ignoring that factor makes a historical P/E wrong by "
            "exactly the split ratio. Every response carries `verification`, "
            "which checks our split arithmetic against Tiingo's independent "
            "adjClose - if its verdict is not `consistent`, do not report a "
            "valuation from the series."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": (
                        "e.g. KO. US listings only - the same scope as "
                        "edgar_financials, which supplies every denominator "
                        "these prices pair with."),
                },
                "years": {
                    "type": "integer",
                    "default": 15,
                    "description": (
                        "Window length. The methodology asks for 10-15. Shorten "
                        "to 5-7 only when mean reversion is broken by a "
                        "spin-off or a regime change, and say so in the report."),
                },
                "fiscal_year_end_month": {
                    "type": "integer",
                    "default": 12,
                    "description": (
                        "Month the fiscal year ends, 1-12. Leave at 12 for "
                        "calendar-year filers. Set it to match the filer "
                        "before pairing these averages with EDGAR annuals - "
                        "INTU closes in July, and a calendar average against a "
                        "July-ending EPS is a real error."),
                },
                "refresh": {
                    "type": "boolean",
                    "default": False,
                    "description": "Bypass the 24h cache.",
                },
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "price_dividends",
        "description": (
            "Cash dividends per fiscal year from the same Tiingo daily rows "
            "as price_annual_averages (their `divCash` field), summed by "
            "ex-date and split-adjusted to today's share basis. A second "
            "dividend source next to EDGAR's dividend_per_share_declared: "
            "use it to corroborate a growth streak or DGR, for an IFRS filer "
            "where EDGAR has no dividend at all, for Visa-style filers whose "
            "EDGAR figure is one payment (per_payment_rate), and for the "
            "newest fiscal year before its 10-K reaches EDGAR. Independent "
            "of EDGAR, NOT of the price source. READ `quality` FIRST when "
            "present: `outsized_payments` are possible specials (Tiingo does "
            "not mark them), `irregular_payment_count` years are not "
            "comparable as they stand, `zero_years` break any growth ratio. "
            "Exclude `incomplete_years` from every streak, DGR and yield."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "e.g. KO. US listings, ADRs included.",
                },
                "years": {
                    "type": "integer",
                    "default": 15,
                    "description": "Window length, as for price_annual_averages.",
                },
                "fiscal_year_end_month": {
                    "type": "integer",
                    "default": 12,
                    "description": (
                        "Month the fiscal year ends, 1-12. Match the filer "
                        "(AAPL and V: 9) before comparing with EDGAR annuals."),
                },
                "refresh": {
                    "type": "boolean",
                    "default": False,
                    "description": "Bypass the 24h cache.",
                },
            },
            "required": ["ticker"],
        },
    },
]


def run_tool(name, arguments):
    args = dict(arguments or {})
    use_cache = not bool(args.get("refresh"))

    if name == "price_annual_averages":
        return price_core.annual_price_series(
            args["ticker"],
            years=int(args.get("years", price_core.DEFAULT_YEARS)),
            fye_month=int(args.get("fiscal_year_end_month", 12)),
            use_cache=use_cache)

    if name == "price_dividends":
        return price_core.dividend_series(
            args["ticker"],
            years=int(args.get("years", price_core.DEFAULT_YEARS)),
            fye_month=int(args.get("fiscal_year_end_month", 12)),
            use_cache=use_cache)

    raise RuntimeError("Unknown tool: %s" % name)


# --------------------------------------------------------------------------- #
# MCP stdio plumbing - identical in shape to the other three servers


def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def result_for(request):
    method = request.get("method")
    params = request.get("params") or {}

    if method == "initialize":
        return {
            "protocolVersion": params.get("protocolVersion",
                                          PROTOCOL_VERSION_FALLBACK),
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        try:
            outcome = run_tool(params.get("name"), params.get("arguments"))
            text = json.dumps(outcome, ensure_ascii=False,
                              separators=(",", ":"))
            is_error = not (isinstance(outcome, dict) and outcome.get("ok"))
        except KeyError as err:
            text = "ERROR: missing required argument %s" % err
            is_error = True
        except (RuntimeError, price_core.PriceError) as err:
            text = "ERROR: %s" % err
            is_error = True
        return {"content": [{"type": "text", "text": text}],
                "isError": is_error}
    raise LookupError(method)


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "id" not in request:
            continue
        try:
            send({"jsonrpc": "2.0", "id": request["id"],
                  "result": result_for(request)})
        except LookupError:
            send({"jsonrpc": "2.0", "id": request["id"],
                  "error": {"code": -32601,
                            "message": "Method not found: %s"
                                       % request.get("method")}})
        except Exception as err:  # noqa: BLE001 - the loop must not die
            send({"jsonrpc": "2.0", "id": request["id"],
                  "error": {"code": -32603, "message": str(err)}})


if __name__ == "__main__":
    main()
