#!/usr/bin/env python3
"""dgi-alphavantage - annual statements from Alpha Vantage as an MCP tool.

The fifth local server, for the reason the others exist: each statement
response is 120-190KB, so the fetch happens here and only the requested annual
series go back.

Reads an API key from `~/.dgi/alphavantage.json`:

    {"api_key": "..."}

Alpha Vantage takes the key as a query parameter, so it travels in a URL. It
never leaves this machine otherwise and is redacted from every error message.
Read-only: HTTP GETs plus a cache under `~/.dgi/av-cache/`.

What it is for, and what it is not: it is the share-count source for Visa,
which EDGAR cannot give (BACKLOG item 17), and a check on the EDGAR READER. It
is built from the same SEC filings, so it never corroborates a filing.
"""

import json
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import av_core  # noqa: E402

PROTOCOL_VERSION_FALLBACK = "2024-11-05"
SERVER_INFO = {"name": "dgi-alphavantage", "version": "0.2.0"}

TOOLS = [
    {
        "name": "av_financials",
        "description": (
            "Annual statement series from Alpha Vantage, reduced on this "
            "machine: only the concepts asked for, as {fiscal year: value} "
            "plus the fiscalDateEnding behind each year. Two uses: (1) the "
            "share count for filers EDGAR cannot give one for - Visa reports "
            "per share class only, here `shares_outstanding` and "
            "`eps_from_net_income` exist; (2) a check on edgar_financials - "
            "same alias names, so the series line up. It is built from the "
            "SAME SEC filings: agreement proves our EDGAR reader picked the "
            "right tag and date, never that the filing is right. READ each "
            "concept's `note`: `eps_reported` is STREET EPS, not GAAP (V "
            "FY2025 11.47 vs GAAP 10.20); `shares_outstanding` is already on "
            "today's split basis, so apply NO split factor; `short_term_debt` "
            "includes commercial paper and must not be mixed with EDGAR's in "
            "one ratio. Exclude `incomplete_years` (EARNINGS lists the year in "
            "progress as annual). `shares_outstanding` and "
            "`eps_from_net_income` carry `quality.count_basis_suspect`: years "
            "where net income / count is far from the reported EPS - a count "
            "on another basis (V FY2011-2012) or a large one-off; check before "
            "using them, and start the window after them if they come first. "
            "Asking for either adds the EARNINGS request. Free key: 25 requests a day, 5 a minute, one "
            "request per statement; a week of cache. OVERVIEW is premium and "
            "not offered."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string", "description": "e.g. V"},
                "concepts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Aliases: revenue, operating_income, net_income, "
                        "interest_expense, operating_cash_flow, capex, "
                        "dividends_paid, stockholders_equity, long_term_debt, "
                        "short_term_debt, total_assets, cash, "
                        "shares_outstanding, eps_reported, "
                        "eps_from_net_income. A raw field also works as "
                        "'FUNCTION:field', e.g. 'BALANCE_SHEET:inventory'. "
                        "Ask for every concept in one call: concepts from the "
                        "same statement share one request."),
                },
                "since_year": {
                    "type": "integer",
                    "description": "Drop years before this.",
                },
                "refresh": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "Bypass the week-long cache. Costs one request per "
                        "statement from the 25-a-day quota."),
                },
            },
            "required": ["ticker", "concepts"],
        },
    },
]


def run_tool(name, arguments):
    args = dict(arguments or {})
    if name == "av_financials":
        since = args.get("since_year")
        return av_core.financials(
            args["ticker"], list(args["concepts"]),
            since_year=int(since) if since is not None else None,
            use_cache=not bool(args.get("refresh")))
    raise RuntimeError("Unknown tool: %s" % name)


# --------------------------------------------------------------------------- #
# MCP stdio plumbing - identical in shape to the other servers


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
        except (RuntimeError, av_core.AvError) as err:
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
        except Exception as err:
            send({"jsonrpc": "2.0", "id": request["id"],
                  "error": {"code": -32603, "message": str(err)}})


if __name__ == "__main__":
    main()
