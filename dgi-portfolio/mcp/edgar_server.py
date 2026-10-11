#!/usr/bin/env python3
"""dgi-edgar - SEC EDGAR XBRL financial statements as MCP tools.

Runs on the user's machine, like the other two servers in this plugin, for two
reasons:

1. The agent sandbox has no route to arbitrary hosts.
2. **Response size.** EDGAR payloads are tens to hundreds of KB. Fetching them
   into the conversation is the single most expensive mistake available in this
   project, so the fetch happens here and only the annual values asked for go
   back - typically a few dozen numbers.

Unlike `dgi-sheet-bridge` and `dgi-ibkr-flex` this server holds no credential.
EDGAR needs no API key; it needs a descriptive User-Agent with a contact
address, which the SEC requires of all programmatic users. Put it in
`~/.dgi/edgar.json`:

    {"user_agent": "Your Name your@email.com"}

Read-only by construction: it issues HTTP GETs to sec.gov and writes nothing
except a local cache under `~/.dgi/edgar-cache/`.
"""

import json
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import edgar_core  # noqa: E402

PROTOCOL_VERSION_FALLBACK = "2024-11-05"
SERVER_INFO = {"name": "dgi-edgar", "version": "0.4.9"}

TOOLS = [
    {
        "name": "edgar_financials",
        "description": (
            "Annual financial statement values for a US filer, straight from "
            "its SEC XBRL filings. Free, no API key, no per-symbol gating, and "
            "the full filed history rather than a five-year window - use this "
            "instead of FMP for anything statement-derived. Returns ONLY the "
            "annual series for the concepts requested, so it is safe to call "
            "in a conversation; the raw EDGAR payload never leaves this "
            "machine. Concept names are aliases resolved through a chain of "
            "us-gaap tags: every (tag, unit) pair with data is RANKED - USD "
            "over non-USD, fresh over dead, then longer history - and the tag "
            "AND unit actually used are reported back. "
            "Two keys appear only when there is something to report, so a "
            "clean series stays quiet. `quality`: defects that survive the "
            "choice - `non_usd_unit` (the numerator is not USD, so any "
            "multiple against a USD price is wrong), `stale` (the filer "
            "stopped reporting this tag), `interior_gaps` (missing years "
            "mid-series, which silently break a consecutive-years count), "
            "`zero_values` and `negative_values` (years where a growth RATIO "
            "is undefined rather than imprecise - a DGR over a series starting "
            "at zero divides by zero. These are normally real: pre-dividend "
            "years and genuine loss years, not data errors. Start the window "
            "after them or say the metric cannot be computed), "
            "`per_payment_rate` (dividend per share only: in the listed years "
            "the 'annual' figure is ONE payment's rate - multiply by "
            "payments_per_year before any yield or payout), "
            "`count_jumps` (share counts only: years where the count moves "
            "1.9x or more against the year before - a split, not issuance. "
            "Counts are as filed, so DIVIDE each year by the split factor "
            "from price_annual_averages, keyed on its `filed` date, before "
            "reading a trend or building a per-share figure). "
            "Balance-sheet values are read at the filer's own fiscal year end. "
            "`alternatives`: the candidates that lost. READ `quality` BEFORE "
            "using the numbers - a growth streak or DGR computed over a "
            "gapped or stale series is wrong, not approximate. "
            "Also returns `filed`: the SEC filing date behind each year's "
            "value. **This is what you key a split adjustment on, never the "
            "year.** EDGAR restates the last few years in every 10-K, so the "
            "fact that wins for a year is usually filed about three years "
            "later and may already sit on a post-split share basis. Pass this "
            "date to `split_factor_by_filing_date` from price_annual_averages "
            "before dividing a price by an as-filed per-share figure."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string",
                           "description": "e.g. ZTS. US SEC filers only."},
                "concepts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Aliases: revenue, operating_income, net_income, "
                        "eps_diluted, eps_basic, operating_cash_flow, capex, "
                        "dividends_paid, dividend_per_share_declared, "
                        "stockholders_equity, long_term_debt, "
                        "short_term_debt, interest_expense, shares_diluted, "
                        "shares_basic, total_assets, cash. A raw us-gaap tag "
                        "also works. Ask only for what you need. "
                        "dividend_per_share_declared is the primary-source "
                        "answer to the growth streak and DGR.")},
                "since_year": {
                    "type": "integer",
                    "description": (
                        "Drop years before this. The scoring model wants 10 "
                        "years, so a sensible default is the current year "
                        "minus 10.")},
            },
            "required": ["ticker", "concepts"],
        },
    },
    {
        "name": "edgar_tags",
        "description": (
            "List the tags a filer actually reports, across EVERY namespace "
            "(us-gaap, ifrs-full, dei, ...), optionally filtered by substring. "
            "Names only, never values. Tags come back namespace-qualified, and "
            "the response also carries a `namespaces` count. Use this when "
            "edgar_financials returns an empty series. **Only a `us-gaap:` tag "
            "can be passed back to edgar_financials as a raw concept** - a "
            "filer whose tags are all `ifrs-full` cannot be read by this plugin "
            "at all, and `matched: 0` here means the filer reports nothing "
            "under any namespace, not merely nothing familiar. Read the empty "
            "series' own `note` first: it distinguishes an IFRS filer, a filer "
            "whose figures are reported only per share class (which companyfacts "
            "omits and no tag can recover), and an ordinary missing tag - only "
            "the third is worth searching for."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "contains": {"type": "string",
                             "description": "e.g. 'Dividend', 'Debt', 'Revenue'"},
                "limit": {"type": "integer", "default": 60},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "edgar_lookup",
        "description": (
            "Resolve a ticker to its SEC CIK and registered company name. Also "
            "the cheapest way to check whether a symbol files with the SEC at "
            "all - foreign issuers and most ETFs do not."),
        "inputSchema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
]


def run_tool(name, arguments):
    args = dict(arguments or {})

    if name == "edgar_lookup":
        cik, company = edgar_core.cik_for_ticker(args["ticker"])
        return {"ok": True, "ticker": args["ticker"].upper(),
                "cik": cik, "company": company}

    if name == "edgar_financials":
        cik, company, facts, from_cache = edgar_core.company_facts(args["ticker"])
        since = args.get("since_year")
        series = {c: edgar_core.series_for_concept(facts, c, since)
                  for c in args["concepts"]}
        return {"ok": True, "ticker": args["ticker"].upper(), "cik": cik,
                "company": company, "cached": from_cache, "concepts": series}

    if name == "edgar_tags":
        _, _, facts, _ = edgar_core.company_facts(args["ticker"])
        result = edgar_core.available_tags(facts, args.get("contains"),
                                           int(args.get("limit", 60)))
        result["ok"] = True
        return result

    raise RuntimeError("Unknown tool: %s" % name)


# --------------------------------------------------------------------------- #
# MCP stdio plumbing - identical in shape to the other two servers


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
        except (RuntimeError, edgar_core.EdgarError) as err:
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
