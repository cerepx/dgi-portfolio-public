#!/usr/bin/env python3
"""
MCP stdio server wrapping the Interactive Brokers Flex Web Service.

Why this exists, and why it is a local server rather than a direct call: the
agent sandbox has no network route to arbitrary hosts, the same constraint that
forced dgi-sheet-bridge to run on the user's machine. Same shape, same rules -
credentials live in ~/.dgi/, never travel through the conversation, and are
redacted from every error message.

Why Flex rather than TWS API or the Client Portal Web API: Flex is the only IBKR
surface that is genuinely unattended. It is read-only by construction, needs no
desktop application running, no daily 2FA, and no session keepalive. A Flex token
CANNOT place an order - that is enforced by IBKR, not by convention here.

What it is for: pulling real dividend payments into the 'Dividends received'
sheet - actual pay dates, withholding tax, currency and the FX rate to base, which
is what Declaratia Unica needs and what no screener can supply. Also, since
0.5.4, pulling per-execution trade commissions to check the hand-entered
column T (Comision) in MyShares - the one column in the sheet that had never
been verified against anything.

What it is NOT for: dividend growth streaks, DGR, Chowder, credit ratings. Those
are facts about the issuer, not about the account, and IBKR does not publish them.
See skills/company-analysis/references/data-sources.md.

Setup, once, by hand in Client Portal:

  1. Settings -> Account Report -> Flex Web Service. Enable it, Generate New
     Token, pick a lifespan (6 hours to 1 year), optionally whitelist an IP.
  2. Performance & Reports -> Flex Queries. Build an Activity Flex Query with the
     Cash Transactions section enabled, ticking Dividends and Withholding Tax,
     and the fields Symbol, ISIN, Date/Time, SettleDate, Amount, Type, Currency,
     FXRateToBase, Description, TransactionID. Take its Query ID from the Info icon.
     For flex_trades, add the Trades section to the same query (or build a
     second one) with Symbol, ISIN, TradeDate, Buy/Sell, Quantity, TradePrice,
     Currency, IBCommission, IBCommissionCurrency, Proceeds, NetCash,
     AssetCategory, TransactionID.
  3. Write ~/.dgi/ibkr-flex.json and chmod 600 it:

     {
       "token": "...numeric token...",
       "queries": {"dividends": "123456", "trades": "123457"}
     }

Flex Query configuration is per Client Portal username - a query built by one
username is invisible to another.
"""

import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

CONFIG_PATH = os.path.expanduser("~/.dgi/ibkr-flex.json")
# Per blocking socket operation, not per request. A healthy Flex answer took
# 0.4-0.8s when measured; at 60 a host that hangs instead of refusing held each
# call for a full minute (BACKLOG item 27).
HTTP_TIMEOUT_SECONDS = 20

# The GetStatement URL comes from IBKR's own response, and its host
# (gdcdyn.interactivebrokers.com) has been seen with no DNS record while the
# configured SendRequest host answered. On that failure, the same path is tried
# once on the configured host - never on a host outside this domain, since the
# request carries the token. BACKLOG item 27.
FALLBACK_DOMAIN = ".interactivebrokers.com"
PROTOCOL_VERSION_FALLBACK = "2024-11-05"
# Kept in step with .claude-plugin/plugin.json so a log line identifies the build.
SERVER_INFO = {"name": "dgi-ibkr-flex", "version": "0.5.4"}

# The one constant that could NOT be verified from IBKR's own documentation page:
# the rendered docs strip the base URL out of the code samples. This is the
# long-standing value. It is overridable in the config precisely because it is
# the weakest link here - if requests fail with a DNS or 404 error rather than a
# Flex ErrorCode, check this first.
DEFAULT_SEND_REQUEST_URL = (
    "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest")

# Documented limits: 1 request per second, 10 per minute, per token.
MIN_SECONDS_BETWEEN_CALLS = 1.2

# Error codes that mean "the report is not ready, come back" rather than
# "your setup is wrong". Retrying anything else just burns the rate limit.
RETRYABLE_CODES = {"1001", "1004", "1005", "1006", "1007", "1008",
                   "1009", "1019", "1021"}
FATAL_HINTS = {
    "1010": "Legacy Flex Query. Rebuild it as an Activity Flex Query.",
    "1011": "The Flex Web Service is disabled. Re-enable it in Client Portal.",
    "1012": "Token has expired. Generate a new one in Client Portal.",
    "1013": "IP restriction. This machine's IP is not the whitelisted one.",
    "1014": "Query ID is invalid, or belongs to a different Client Portal user.",
    "1015": "Token is invalid.",
    "1018": "Rate limited: 1 request per second, 10 per minute per token.",
}

_last_call_at = [0.0]


class ConfigError(Exception):
    pass


class FlexError(RuntimeError):
    pass


class FlexUnreachable(FlexError):
    """The host could not be reached at all. `kind` is dns, timeout or other."""

    def __init__(self, message, kind):
        super().__init__(message)
        self.kind = kind


# --------------------------------------------------------------------------- #
# Credentials


def load_config():
    if not os.path.exists(CONFIG_PATH):
        raise ConfigError(
            "Credentials file not found: %s. Create it with "
            '{"token": "...", "queries": {"dividends": "123456"}} '
            "and chmod 600 it." % CONFIG_PATH)
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        try:
            cfg = json.load(fh)
        except json.JSONDecodeError as err:
            raise ConfigError("Credentials file is not valid JSON: %s" % err)
    if not cfg.get("token"):
        raise ConfigError("Credentials file is missing 'token'.")
    if not isinstance(cfg.get("queries"), dict) or not cfg["queries"]:
        raise ConfigError(
            "Credentials file needs a non-empty 'queries' map, e.g. "
            '{"dividends": "123456"}.')
    cfg.setdefault("send_request_url", DEFAULT_SEND_REQUEST_URL)
    if not str(cfg["send_request_url"]).startswith("https://"):
        # The token travels as a query parameter on this URL (IBKR's design,
        # not ours) - never let it ride on plaintext http.
        raise ConfigError("send_request_url must be https://, got: %s"
                          % cfg["send_request_url"])
    return cfg


def redact(text, token):
    """Never let the token leak through an error message, echo or URL."""
    if token:
        text = text.replace(token, "***TOKEN***")
    return text


# --------------------------------------------------------------------------- #
# Flex HTTP client


def _throttle():
    gap = time.time() - _last_call_at[0]
    if gap < MIN_SECONDS_BETWEEN_CALLS:
        time.sleep(MIN_SECONDS_BETWEEN_CALLS - gap)
    _last_call_at[0] = time.time()


def _get(url, params, token):
    """GET with the mandatory User-Agent header. Returns the raw body."""
    _throttle()
    full = url + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        full, headers={"User-Agent": "dgi-portfolio/0.1 (python-urllib)"})
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as err:
        body = err.read(400).decode("utf-8", errors="replace")
        raise FlexError(redact("Flex HTTP %d: %s" % (err.code, body), token))
    except urllib.error.URLError as err:
        raise _unreachable(err.reason, url, token)
    except (TimeoutError, OSError) as err:
        # A timeout while READING the body is not wrapped in URLError, and
        # used to escape as a bare traceback.
        raise _unreachable(err, url, token)


def _unreachable(reason, url, token):
    if isinstance(reason, socket.gaierror):
        kind = "dns"
    elif isinstance(reason, (TimeoutError, socket.timeout)):
        kind = "timeout"
    else:
        kind = "other"
    host = urllib.parse.urlsplit(url).netloc
    return FlexUnreachable(redact(
        "Cannot reach the Flex Web Service at %s (%s): %s. If this is DNS or a "
        "404 rather than a Flex error code, check 'send_request_url' in %s."
        % (host, kind, reason, CONFIG_PATH), token), kind)


def _fallback_url(get_url, send_request_url):
    """GetStatement's path on the configured host, or None when not applicable.

    None when the hosts are the same (nothing new to try) or either host sits
    outside FALLBACK_DOMAIN (the request carries the token).
    """
    got = urllib.parse.urlsplit(get_url)
    configured = urllib.parse.urlsplit(send_request_url)
    if got.netloc == configured.netloc:
        return None
    for host in (got.hostname or "", configured.hostname or ""):
        if not host.endswith(FALLBACK_DOMAIN):
            return None
    return got._replace(scheme=configured.scheme,
                        netloc=configured.netloc).geturl()


def _parse_status(raw, token):
    """
    Both endpoints answer with XML. A failure is a 200 with Status=Fail, so the
    HTTP status code alone tells you nothing.
    """
    try:
        root = ET.fromstring(raw.strip())
    except ET.ParseError:
        raise FlexError(redact("Flex returned non-XML: %s" % raw[:300], token))
    status = (root.findtext("Status") or "").strip()
    if status == "Fail":
        code = (root.findtext("ErrorCode") or "").strip()
        message = (root.findtext("ErrorMessage") or "unknown error").strip()
        hint = FATAL_HINTS.get(code)
        raise FlexError("Flex error %s: %s%s" % (
            code, message, ("  -> " + hint) if hint else ""), )
    return root


def fetch_statement(query_id, attempts=6, wait_seconds=5):
    """
    Two-step Flex workflow. Returns the report XML as a string.

    Step one asks IBKR to generate the report and yields a reference code plus
    the URL to collect it from - that URL is taken from the response rather than
    constructed, because IBKR returns it explicitly. If its host cannot be
    resolved or hangs, the same path is tried once on the configured host and
    used from then on (BACKLOG item 27; see `_fallback_url` for the limits).

    Step two may legitimately fail several times while generation completes.
    Only the documented "not ready yet" codes are retried; a bad token or a bad
    query ID fails immediately rather than burning the rate limit.
    """
    cfg = load_config()
    token = cfg["token"]

    root = _parse_status(
        _get(cfg["send_request_url"],
             {"t": token, "q": query_id, "v": "3"}, token), token)
    reference = (root.findtext("ReferenceCode") or "").strip()
    get_url = (root.findtext("Url") or "").strip()
    if not reference or not get_url:
        raise FlexError("SendRequest succeeded but returned no reference code "
                        "or URL. Report shape changed unexpectedly.")

    last = None
    fallback = _fallback_url(get_url, cfg["send_request_url"])
    for attempt in range(attempts):
        params = {"t": token, "q": reference, "v": "3"}
        try:
            raw = _get(get_url, params, token)
        except FlexUnreachable as err:
            if fallback is None or err.kind not in ("dns", "timeout"):
                raise
            get_url, fallback = fallback, None   # switch once, for good
            raw = _get(get_url, params, token)
        if "<FlexQueryResponse" in raw:
            return raw
        try:
            _parse_status(raw, token)
        except FlexError as err:
            last = err
            code = re.search(r"Flex error (\d+)", str(err))
            if not code or code.group(1) not in RETRYABLE_CODES:
                raise
            time.sleep(wait_seconds)
            continue
        last = FlexError("GetStatement returned neither a report nor an error.")
    raise last


# --------------------------------------------------------------------------- #
# Report shaping

# IBKR writes the per-share rate into the description, e.g.
# "KO(US1912161007) CASH DIVIDEND USD 0.53 PER SHARE (Ordinary Dividend)".
# That is the only place the per-share figure appears in a cash transaction, and
# it is what the sheet's 'Gross per share' column needs.
PER_SHARE_RE = re.compile(
    r"\b([A-Z]{3})\s+([\d.]+)\s+PER\s+SHARE\b", re.IGNORECASE)


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_cash_transactions(xml_text, types=None):
    """Pull CashTransaction rows out of an Activity Flex report."""
    root = ET.fromstring(xml_text)
    rows = []
    for node in root.iter("CashTransaction"):
        a = node.attrib
        kind = a.get("type", "")
        if types and not any(t.lower() in kind.lower() for t in types):
            continue
        description = a.get("description", "")
        per_share = None
        match = PER_SHARE_RE.search(description)
        if match:
            per_share = _num(match.group(2))
        # settleDate is the actual pay date; dateTime is the ex/report moment.
        pay_date = a.get("settleDate") or a.get("dateTime", "")[:8]
        rows.append({
            "pay_date": pay_date,
            "year": int(pay_date[:4]) if pay_date[:4].isdigit() else None,
            "month": int(pay_date[4:6]) if pay_date[4:6].isdigit() else None,
            "symbol": a.get("symbol"),
            "isin": a.get("isin"),
            "type": kind,
            "amount": _num(a.get("amount")),
            "currency": a.get("currency"),
            "fx_rate_to_base": _num(a.get("fxRateToBase")),
            "gross_per_share": per_share,
            "description": description,
            "transaction_id": a.get("transactionID"),
        })
    rows.sort(key=lambda r: (r["pay_date"] or "", r["symbol"] or ""))
    return rows


def extract_trades(xml_text, asset_category="STK", side=None):
    """
    Pull Trade rows (one per execution) out of an Activity Flex report.

    IBKR reports per execution, not per position - a position built over
    several buys sums several trade rows. This function returns the raw rows;
    aggregation per symbol happens in run_tool, since the caller may want the
    raw rows too (to see which execution belongs to which buy).

    `ibCommission` is IBKR's own sign convention - typically negative on a buy
    (a cost). It is passed through as-is, not normalised, so a caller comparing
    against the sheet's positive-valued column T must take the sign into
    account explicitly rather than assume one.
    """
    root = ET.fromstring(xml_text)
    rows = []
    for node in root.iter("Trade"):
        a = node.attrib
        cat = a.get("assetCategory", "")
        if asset_category and cat != asset_category:
            continue
        bs = (a.get("buySell") or "").upper()
        if side and bs != side.upper():
            continue
        trade_date = a.get("tradeDate", "")
        rows.append({
            "trade_date": trade_date,
            "year": int(trade_date[:4]) if trade_date[:4].isdigit() else None,
            "symbol": a.get("symbol"),
            "isin": a.get("isin"),
            "buy_sell": bs,
            "quantity": _num(a.get("quantity")),
            "trade_price": _num(a.get("tradePrice")),
            "currency": a.get("currency"),
            "commission": _num(a.get("ibCommission")),
            "commission_currency": a.get("ibCommissionCurrency"),
            "proceeds": _num(a.get("proceeds")),
            "net_cash": _num(a.get("netCash")),
            "asset_category": cat,
            "transaction_id": a.get("transactionID") or a.get("tradeID"),
        })
    rows.sort(key=lambda r: (r["trade_date"] or "", r["symbol"] or ""))
    return rows


def summarise(xml_text):
    root = ET.fromstring(xml_text)
    statements = []
    for st in root.iter("FlexStatement"):
        counts = {}
        for child in st:
            for entry in child:
                counts[entry.tag] = counts.get(entry.tag, 0) + 1
        statements.append({
            "account_id": st.get("accountId"),
            "from_date": st.get("fromDate"),
            "to_date": st.get("toDate"),
            "period": st.get("period"),
            "when_generated": st.get("whenGenerated"),
            "row_counts": counts,
        })
    return {"query_name": root.get("queryName"), "statements": statements}


# --------------------------------------------------------------------------- #
# BNR reference rates
#
# Why this lives here rather than in its own component: with a USD-base IBKR
# account, `fxRateToBase` is 1.0 on every USD dividend and is fiscally useless.
# Declaratia Unica needs the RON rate published by the National Bank of Romania.
# Flex supplies the exact pay date, BNR supplies the rate for that date, and the
# join is one operation - splitting it across two components would mean every
# future analysis has to remember to do the second half.
#
# WHICH date's rate is a tax question, not a technical one. This code implements
# "the rate published for the day the payment settled, falling back to the most
# recent publication before it". BNR does not publish on weekends or holidays,
# and dividends do settle on those days. Confirm the rule with an advisor before
# filing anything - it is already an open item in BACKLOG.md.

BNR_YEAR_URL = "https://www.bnr.ro/files/xml/years/nbrfxrates%d.xml"
# Rolling window of the most recent publications. Measured 2026-07-31: the
# current-year archive lagged by four months while this file was current, so the
# year file alone is not enough for recent payments.
BNR_RECENT_URL = "https://www.bnr.ro/nbrfxrates10days.xml"
BNR_DAILY_URL = "https://www.bnr.ro/nbrfxrates.xml"
_bnr_cache = {}


def _bnr_parse(raw):
    """
    {'YYYY-MM-DD': {'USD': 4.5732, ...}} from any of BNR's three feeds.

    Namespace-agnostic on purpose. BNR migrated the feeds from
    xmlns="http://www.bnr.ro/xsd" to "https://www.bnr.ro/xsd" (observed live
    2026-07-31 via bnr_coverage diagnostics: full documents, zero matching
    Cubes), while older year files and stale CDN copies still carry the old
    one. Matching a hardcoded namespace made every parse of a migrated file
    silently return nothing.
    """
    root = ET.fromstring(raw)
    days = {}
    for cube in root.iter():
        if cube.tag.rsplit("}", 1)[-1] != "Cube":
            continue
        rates = {}
        for rate in cube:
            currency = rate.get("currency")
            value = _num(rate.text)
            if value is None:
                continue
            # HUF, JPY and friends are quoted per 100 units.
            multiplier = _num(rate.get("multiplier")) or 1.0
            rates[currency] = value / multiplier
        days[cube.get("date")] = rates
    return days


# Browser-like headers. Kept as a hedge, not as the fix: the 2026-07-31 "all
# feeds returned nothing" defect turned out to be the namespace migration
# handled in _bnr_parse, not an anti-bot layer. These headers are harmless and
# may still influence which CDN copy is served - stale pre-migration copies of
# the current-year archive (months behind, old namespace) were observed in the
# wild the same day.
BNR_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "application/xml,text/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "identity",
}


def _bnr_get(url, label):
    _throttle()
    request = urllib.request.Request(url, headers=BNR_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (urllib.error.HTTPError, urllib.error.URLError) as err:
        raise FlexError("Cannot reach BNR (%s): %s" % (label, err))


def bnr_year_rates(year):
    """
    Rates for a calendar year, cached.

    The year archive is authoritative for completed years, but on 2026-07-31 the
    current-year file stopped at 26 March while its own PublishingDate header
    claimed 28 July - a four-month lag that silently broke every recent lookup.
    So the rolling recent-days feed is merged in on top of it. Feeds that fail
    are skipped rather than fatal, because one of them covering the date is
    enough; only a genuinely absent date raises.
    """
    if year in _bnr_cache:
        return _bnr_cache[year]

    days = {}
    errors = []
    for url, label in ((BNR_YEAR_URL % year, "year %d" % year),
                       (BNR_RECENT_URL, "recent days"),
                       (BNR_DAILY_URL, "today")):
        try:
            for date, rates in _bnr_parse(_bnr_get(url, label)).items():
                if date.startswith(str(year)):
                    days.setdefault(date, rates)
        except (FlexError, ET.ParseError) as err:
            errors.append("%s: %s" % (label, err))

    if not days:
        raise FlexError(
            "No BNR data for %d. Feeds tried - %s. "
            "Run bnr_coverage(%d) for per-feed detail: it reports bytes, cube "
            "counts and the head of any document that parsed without cubes."
            % (year,
               "; ".join(errors)
               or "all fetched and parsed but contained no rates for %d" % year,
               year))
    _bnr_cache[year] = days
    return days


def bnr_coverage(year):
    """
    Per-feed diagnostics plus merged coverage. Bypasses the cache on purpose:
    this is the tool run when something is wrong, and a cached answer would
    hide exactly the failure being diagnosed. Never raises on empty feeds -
    an empty result WITH the per-feed detail is the diagnosis.
    """
    feeds = []
    days = {}
    for url, label in ((BNR_YEAR_URL % year, "year %d" % year),
                       (BNR_RECENT_URL, "recent days"),
                       (BNR_DAILY_URL, "today")):
        entry = {"feed": label, "url": url}
        try:
            raw = _bnr_get(url, label)
            entry["bytes"] = len(raw)
            parsed = _bnr_parse(raw)
            entry["cubes"] = len(parsed)
            in_year = sorted(d for d in parsed
                             if d and d.startswith(str(year)))
            entry["cubes_in_year"] = len(in_year)
            if in_year:
                entry["first"] = in_year[0]
                entry["last"] = in_year[-1]
            if not parsed:
                # Parsed as XML but no Cube elements: show what arrived, so a
                # substituted document (anti-bot page, error page) is visible
                # instead of inferred.
                entry["root_tag"] = ET.fromstring(raw).tag
                entry["head"] = raw[:300]
            for date in in_year:
                days.setdefault(date, parsed[date])
        except (FlexError, ET.ParseError) as err:
            entry["error"] = str(err)
        feeds.append(entry)
    dates = sorted(days)
    result = {"year": year, "days": len(dates), "feeds": feeds}
    if dates:
        result["first"] = dates[0]
        result["last"] = dates[-1]
    return result


def bnr_rate(date_yyyymmdd, currency="USD", max_lookback_days=10):
    """
    Rate for a date, falling back to the most recent earlier publication.
    Returns (rate, date_actually_used, days_back).
    """
    if currency == "RON":
        return 1.0, date_yyyymmdd, 0
    import datetime
    try:
        day = datetime.date(int(date_yyyymmdd[:4]), int(date_yyyymmdd[4:6]),
                            int(date_yyyymmdd[6:8]))
    except (ValueError, IndexError):
        raise FlexError("Not a yyyyMMdd date: %r" % date_yyyymmdd)
    for back in range(max_lookback_days + 1):
        probe = day - datetime.timedelta(days=back)
        rates = bnr_year_rates(probe.year)
        found = rates.get(probe.isoformat(), {}).get(currency)
        if found is not None:
            return found, probe.isoformat(), back
    # Say what the feeds actually cover. Without this the failure looks like a
    # missing rate when it is really a gap in BNR's own publication.
    spans = []
    for probe_year in {day.year, (day - datetime.timedelta(
            days=max_lookback_days)).year}:
        try:
            span = bnr_coverage(probe_year)
            if span["days"]:
                spans.append("%d covers %s..%s (%d days)" % (
                    span["year"], span["first"], span["last"], span["days"]))
            else:
                spans.append("%d empty - run bnr_coverage(%d) for per-feed "
                             "detail" % (probe_year, probe_year))
        except FlexError as err:
            spans.append("%d unavailable: %s" % (probe_year, err))
    raise FlexError(
        "No BNR %s rate within %d days before %s. Feed coverage: %s."
        % (currency, max_lookback_days, date_yyyymmdd, "; ".join(spans)))


# --------------------------------------------------------------------------- #
# Tools

TOOLS = [
    {
        "name": "bnr_rate",
        "description": (
            "BNR reference rate for a currency on a date, for converting "
            "foreign dividend income to RON. BNR does not publish on weekends "
            "or holidays, so the most recent earlier publication is used and "
            "the response says which date it actually came from and how many "
            "days back. WHICH date's rate the tax return wants is a question "
            "for a tax advisor, not a setting - this returns the settlement "
            "date's rate by default."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "yyyyMMdd"},
                "currency": {"type": "string", "default": "USD"},
            },
            "required": ["date"],
        },
    },
    {
        "name": "bnr_coverage",
        "description": (
            "Diagnostic: which dates the merged BNR feeds actually cover for a "
            "year. Use when a rate lookup fails, to tell a missing publication "
            "apart from a bug. The current-year archive has been observed "
            "lagging by months while claiming to be current."),
        "inputSchema": {
            "type": "object",
            "properties": {"year": {"type": "integer"}},
            "required": ["year"],
        },
    },
    {
        "name": "flex_queries",
        "description": (
            "List the Flex Query names and IDs configured locally. Makes no "
            "network call and never returns the token. Use it to see what can "
            "be fetched before spending a request against the rate limit."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "flex_fetch",
        "description": (
            "Run a configured Flex Query and return a summary of the report: "
            "account, date range, and how many rows of each kind it contains. "
            "Read-only - a Flex token cannot place orders. Activity reports "
            "refresh once daily after close, so fetching repeatedly on the "
            "same day returns identical data and only burns the rate limit "
            "(1 request per second, 10 per minute)."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "Name from the local config, e.g. dividends"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "flex_dividends",
        "description": (
            "Fetch a Flex Query and return dividend and withholding-tax cash "
            "transactions, shaped for the 'Dividends received' sheet: pay date, "
            "symbol, gross amount, currency, FX rate to base, and the "
            "per-share rate parsed out of IBKR's description text. Output is "
            "columnar: a `cols` name array plus positional `rows`. This is the "
            "only source in the whole plugin for real pay dates and per-payment "
            "FX, which Declaratia Unica needs. Read-only. Does NOT write to the "
            "sheet - review the rows, then write them through the sheet bridge "
            "with the usual explicit approval."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "Name from the local config, e.g. dividends"},
                "symbol": {"type": "string",
                           "description": "Optional ticker filter"},
                "include_withholding": {
                    "type": "boolean", "default": True,
                    "description": "Include Withholding Tax rows alongside Dividends"},
                "include_descriptions": {
                    "type": "boolean", "default": False,
                    "description": (
                        "Add IBKR's prose description to every row. Off by "
                        "default: the per-share rate is already parsed out of "
                        "it, and 150+ rows of prose are pure token cost.")},
                "convert_to_ron": {
                    "type": "boolean", "default": False,
                    "description": (
                        "Add the BNR rate and the RON amount to every row. "
                        "Needed when the IBKR account base currency is not RON, "
                        "because fxRateToBase is then 1.0 and fiscally useless.")},
                "out_path": {
                    "type": "string",
                    "description": (
                        "ABSOLUTE path (or ~/...). Write the full result there "
                        "as JSON and return only a summary. USE THIS whenever "
                        "the rows are headed for a script rather than for "
                        "reading - /audit-live step 5 above all. Without it "
                        "the only way to get a file is to retype every row by "
                        "hand, which is both slow and a chance to invent or "
                        "hide a payment.")},
            },
            "required": ["query"],
        },
    },
    {
        "name": "flex_trades",
        "description": (
            "Fetch a Flex Query and return individual trade executions: date, "
            "symbol, side, quantity, price, currency, and IBKR's own "
            "per-execution commission. Output is columnar like flex_dividends, "
            "and it takes the same `out_path`. "
            "This is the only source in the plugin for checking column T "
            "(Comision) in MyShares, which is hand-entered as a PER-POSITION "
            "total while IBKR reports PER EXECUTION - a position built over "
            "several buys sums several commissions, so the response also "
            "returns commission totals summed per symbol, ready to compare "
            "against T. IBKR's `ibCommission` sign convention is passed "
            "through as-is (typically negative on a buy) rather than "
            "normalised - read the note in the response before comparing. "
            "Two coverage gaps to expect, not bugs: Flex covers a rolling "
            "window only, so older purchases have no IBKR source, and "
            "positions transferred in from another broker have no IBKR "
            "execution ever - a partial reconciliation is the expected "
            "outcome, not a sign of a broken query. Read-only. Does NOT "
            "write to the sheet."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "Name from the local config, e.g. trades"},
                "symbol": {"type": "string",
                           "description": "Optional ticker filter"},
                "side": {"type": "string", "enum": ["BUY", "SELL"],
                         "description": "Optional filter to one side of the trade"},
                "asset_category": {
                    "type": "string", "default": "STK",
                    "description": (
                        "Filter to this IBKR asset category. Set to an empty "
                        "string to disable the filter and include everything "
                        "(options, FX, etc.) - the DGI portfolio is stocks, "
                        "so STK is the sensible default.")},
                "out_path": {
                    "type": "string",
                    "description": (
                        "ABSOLUTE path (or ~/...). Write the full result there "
                        "as JSON and return only a summary. Use it whenever "
                        "the rows are headed for a script rather than for "
                        "reading.")},
            },
            "required": ["query"],
        },
    },
]


def resolve_query(cfg, name):
    queries = cfg["queries"]
    if name in queries:
        return str(queries[name])
    raise KeyError("No Flex Query named %r in %s. Configured: %s"
                   % (name, CONFIG_PATH, ", ".join(sorted(queries))))


def write_payload(payload, out_path, what):
    """Write the full columnar payload to disk; return a summary to the caller.

    Same contract as `bridge_snapshot`'s `out_path`, and for the same reason.
    `CLAUDE.md`: "Never pull a large file, sheet range, CSV, xlsx or web page
    into the conversation to look at part of it."

    Without this, `/audit-live` step 5 told the agent to save this tool's JSON
    result to `flex-dividends.json` - which in practice means RETYPING 62 rows
    of amounts, pay dates and transaction ids by hand. That is the rule's exact
    violation, and every retyped figure is a chance to invent a missing payment
    or hide a real one. See BACKLOG item 19.

    `rows` is dropped from the response, never truncated: a half-list read as a
    whole one is worse than no list.
    """
    if not (out_path.startswith("~") or os.path.isabs(out_path)):
        raise FlexError(
            "out_path must be absolute, or start with ~. A relative path lands "
            "in this server's working directory, which is NOT the user's "
            "folder and is not predictable. Got: %r" % out_path)
    path = os.path.abspath(os.path.expanduser(out_path))
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        raise FlexError("Directory does not exist: %s" % parent)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1)

    summary = dict((k, v) for k, v in payload.items() if k != "rows")
    summary["written_to"] = path
    summary["bytes"] = os.path.getsize(path)
    summary["rows_omitted"] = (
        "The %d row(s) are in the file, not in this response. Read them with a "
        "script that prints only what you need - never load the file into the "
        "conversation." % payload.get("count", 0))
    summary["next_step"] = what
    return summary


def run_tool(name, arguments):
    args = arguments or {}

    if name == "bnr_coverage":
        return {"ok": True, **bnr_coverage(int(args["year"]))}

    if name == "bnr_rate":
        rate, used, back = bnr_rate(args["date"], args.get("currency", "USD"))
        return {"ok": True, "requested_date": args["date"],
                "currency": args.get("currency", "USD"),
                "rate_ron": rate, "rate_published_for": used,
                "days_back": back,
                "note": ("BNR did not publish on the requested date - used the "
                         "most recent earlier publication." if back else None)}

    if name == "flex_queries":
        cfg = load_config()
        return {"ok": True, "config_path": CONFIG_PATH,
                "queries": {k: str(v) for k, v in cfg["queries"].items()},
                "send_request_url": cfg["send_request_url"]}

    if name == "flex_fetch":
        cfg = load_config()
        xml_text = fetch_statement(resolve_query(cfg, args["query"]))
        return {"ok": True, **summarise(xml_text)}

    if name == "flex_dividends":
        cfg = load_config()
        xml_text = fetch_statement(resolve_query(cfg, args["query"]))
        types = ["Dividend"]
        if args.get("include_withholding", True):
            types.append("Withholding")
        rows = extract_cash_transactions(xml_text, types=types)
        symbol = (args.get("symbol") or "").strip().upper()
        if symbol:
            rows = [r for r in rows if (r["symbol"] or "").upper() == symbol]
        if args.get("convert_to_ron"):
            for row in rows:
                try:
                    rate, used, back = bnr_rate(
                        row["pay_date"], row["currency"] or "USD")
                except FlexError as err:
                    row["bnr_error"] = str(err)
                    continue
                row["bnr_rate_ron"] = rate
                row["bnr_rate_published_for"] = used
                row["bnr_days_back"] = back
                if row["amount"] is not None:
                    row["amount_ron"] = round(row["amount"] * rate, 4)

        missing = [r["transaction_id"] for r in rows
                   if r["gross_per_share"] is None and "Dividend" in (r["type"] or "")]

        # Columnar output: one cols header, positional rows. With 150+ rows the
        # per-row key names were most of the payload. Cells hold null where a
        # value is absent - position carries the meaning, so nulls must stay.
        columns = ["pay_date", "symbol", "type", "amount", "currency",
                   "fx_rate_to_base", "gross_per_share", "isin",
                   "transaction_id"]
        if args.get("include_descriptions"):
            columns.append("description")
        if args.get("convert_to_ron"):
            columns += ["bnr_rate_ron", "bnr_rate_published_for",
                        "bnr_days_back", "amount_ron", "bnr_error"]
        payload = {
            "ok": True,
            "count": len(rows),
            "per_share_unparsed": missing,
            "note": ("Rows listed in per_share_unparsed had no 'CCY n.nn PER SHARE' "
                     "text in the IBKR description - fill those by hand rather "
                     "than deriving them." if missing else None),
            "cols": columns,
            "rows": [[r.get(c) for c in columns] for r in rows],
        }
        if args.get("out_path"):
            return write_payload(
                payload, args["out_path"],
                "Run check_missing_dividends.py against this file and the "
                "sheet snapshot. See /audit-live step 5.")
        return payload

    if name == "flex_trades":
        cfg = load_config()
        xml_text = fetch_statement(resolve_query(cfg, args["query"]))
        asset_category = args.get("asset_category", "STK")
        rows = extract_trades(xml_text, asset_category=asset_category or None,
                              side=args.get("side"))
        symbol = (args.get("symbol") or "").strip().upper()
        if symbol:
            rows = [r for r in rows if (r["symbol"] or "").upper() == symbol]

        totals = {}
        for r in rows:
            if r["buy_sell"] == "BUY" and r["commission"] is not None:
                sym = r["symbol"] or "?"
                totals[sym] = totals.get(sym, 0.0) + r["commission"]

        columns = ["trade_date", "symbol", "buy_sell", "quantity",
                   "trade_price", "currency", "commission",
                   "commission_currency", "proceeds", "net_cash",
                   "asset_category", "transaction_id"]
        payload = {
            "ok": True,
            "count": len(rows),
            "cols": columns,
            "rows": [[r.get(c) for c in columns] for r in rows],
            "buy_commission_totals_by_symbol": {
                k: round(v, 4) for k, v in sorted(totals.items())},
            "note": (
                "buy_commission_totals_by_symbol sums raw ibCommission across "
                "every BUY execution for that symbol, sign as IBKR reports it "
                "- typically negative. Compare abs(total) against the sheet's "
                "column T, and expect only a partial match - Flex covers a "
                "rolling window, and shares transferred in from another "
                "broker were never an IBKR execution."),
        }
        if args.get("out_path"):
            return write_payload(
                payload, args["out_path"],
                "Read the file with a script that prints only the columns and "
                "rows you need - never load it into the conversation.")
        return payload

    raise LookupError(name)


# --------------------------------------------------------------------------- #
# MCP stdio plumbing: newline-delimited JSON-RPC 2.0


def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def result_for(request):
    method = request.get("method")
    params = request.get("params") or {}

    if method == "initialize":
        return {
            "protocolVersion": params.get(
                "protocolVersion", PROTOCOL_VERSION_FALLBACK),
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
            text = json.dumps(_compact(outcome), ensure_ascii=False,
                              separators=(",", ":"))
            is_error = not (isinstance(outcome, dict) and outcome.get("ok"))
        except KeyError as err:
            text = "ERROR: %s" % err
            is_error = True
        except (FlexError, ConfigError) as err:
            text = "ERROR: %s" % err
            is_error = True
        return {"content": [{"type": "text", "text": text}],
                "isError": is_error}
    raise LookupError(method)


def _compact(obj):
    """
    Strip None-valued dict keys recursively before serialising: absence and
    null read the same to the caller, absence is cheaper. List elements are
    preserved untouched - in columnar rows the position IS the meaning, so a
    null cell must stay a null cell.
    """
    if isinstance(obj, dict):
        return {k: _compact(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_compact(v) for v in obj]
    return obj


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue  # not ours to answer
        if "id" not in request:
            continue  # notification, no response allowed
        try:
            send({"jsonrpc": "2.0", "id": request["id"],
                  "result": result_for(request)})
        except LookupError:
            send({"jsonrpc": "2.0", "id": request["id"],
                  "error": {"code": -32601,
                            "message": "Method not found: %s"
                                       % request.get("method")}})
        except Exception as err:  # last-resort guard: never crash the loop
            send({"jsonrpc": "2.0", "id": request["id"],
                  "error": {"code": -32603, "message": str(err)}})


if __name__ == "__main__":
    main()
