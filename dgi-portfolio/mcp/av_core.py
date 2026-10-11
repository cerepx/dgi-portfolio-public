"""Annual statement series from Alpha Vantage, reduced on the host.

WHY THIS EXISTS
---------------
Two gaps `dgi-edgar` cannot close on its own, measured 2026-10-11:

1. **Visa's share count.** Visa tags EPS and share counts only per share
   class, and SEC `companyfacts` omits dimensioned facts (BACKLOG item 17).
   Alpha Vantage's balance sheet carries `commonStockSharesOutstanding` for V,
   1.966bn for FY2025. Net income divided by it gives $10.20, Visa's GAAP
   diluted EPS. With it, valuation methods 2-5 can run on V.
2. **A check on the EDGAR reader.** On AAPL every figure compared - revenue,
   operating income, net income, OCF, capex, dividends, equity - matched EDGAR
   to the dollar. That is the point and the limit: Alpha Vantage is built from
   the same SEC filings. It corroborates OUR tag and date selection (the
   failure mode of items 25 and 26), never the filing itself.

WHAT THE FREE KEY GIVES, MEASURED
---------------------------------
- `INCOME_STATEMENT`, `BALANCE_SHEET`, `CASH_FLOW`: 20 annual years for AAPL and
  V (FY2006-2025), 17 for ZTS.
- `EARNINGS`: annual EPS back to 1996 for AAPL.
- `OVERVIEW`: premium, refused.
- 25 requests a day, 5 a minute. Each response is 120-190KB, which is why this
  runs here and returns a few dozen numbers.

THREE TRAPS, ALL MEASURED, ALL REPORTED IN THE RESPONSE
-------------------------------------------------------
- **`EARNINGS.reportedEPS` is the street figure, not GAAP.** V FY2025 reads 11.47
  against a GAAP 10.20. `eps_from_net_income` (net income / shares) is the
  GAAP-consistent one.
- **`EARNINGS` lists the year in progress as annual.** AAPL "2026" was three
  quarters. Years with fewer than four quarters are flagged.
- **`shortTermDebt` includes commercial paper.** AAPL FY2025 reads 22.4bn here
  against 12.35bn for EDGAR's `LongTermDebtCurrent`. Do not mix the two
  sources inside one debt-to-capital ratio.

Share counts here are already on today's split basis (AAPL FY2017 21.007bn, the
figure item 29 derived by hand). They take no split factor.
"""

import datetime
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

CONFIG_PATH = os.path.expanduser("~/.dgi/alphavantage.json")
CACHE_DIR = os.path.expanduser("~/.dgi/av-cache")
BASE_URL = "https://www.alphavantage.co/query"
HTTP_TIMEOUT_SECONDS = 40
# Statements change once a quarter and the key allows 25 requests a day, so a
# week of cache costs nothing real and saves most of the quota.
CACHE_TTL_SECONDS = 7 * 24 * 3600
# 5 requests a minute on the free key. Only spent between NETWORK calls.
SECONDS_BETWEEN_CALLS = 13
USER_AGENT = "dgi-portfolio (personal dividend portfolio analysis)"

FUNCTIONS = ("INCOME_STATEMENT", "BALANCE_SHEET", "CASH_FLOW", "EARNINGS")

# alias -> (function, field). The same alias names as edgar_financials where
# the concept matches, so the two series line up side by side.
CONCEPTS = {
    "revenue": ("INCOME_STATEMENT", "totalRevenue"),
    "operating_income": ("INCOME_STATEMENT", "operatingIncome"),
    "net_income": ("INCOME_STATEMENT", "netIncome"),
    "interest_expense": ("INCOME_STATEMENT", "interestExpense"),
    "operating_cash_flow": ("CASH_FLOW", "operatingCashflow"),
    "capex": ("CASH_FLOW", "capitalExpenditures"),
    "dividends_paid": ("CASH_FLOW", "dividendPayout"),
    "stockholders_equity": ("BALANCE_SHEET", "totalShareholderEquity"),
    "long_term_debt": ("BALANCE_SHEET", "longTermDebt"),
    "short_term_debt": ("BALANCE_SHEET", "shortTermDebt"),
    "total_assets": ("BALANCE_SHEET", "totalAssets"),
    "cash": ("BALANCE_SHEET", "cashAndCashEquivalentsAtCarryingValue"),
    "shares_outstanding": ("BALANCE_SHEET", "commonStockSharesOutstanding"),
    "eps_reported": ("EARNINGS", "reportedEPS"),
}
DERIVED = {"eps_from_net_income": (("INCOME_STATEMENT", "netIncome"),
                                   ("BALANCE_SHEET",
                                    "commonStockSharesOutstanding"))}

NOTES = {
    "eps_reported": (
        "STREET EPS, not GAAP: the figure compared with analyst estimates. "
        "V FY2025 reads 11.47 against a GAAP 10.20. Never score criterion 4 or "
        "compute a historical P/E on it - use eps_from_net_income."),
    "eps_from_net_income": (
        "Net income / commonStockSharesOutstanding, both from these "
        "statements - GAAP-consistent and on today's split basis. Close to "
        "diluted EPS, not identical to it: the count is the balance-sheet "
        "figure, not the weighted diluted average."),
    "short_term_debt": (
        "Includes commercial paper: AAPL FY2025 reads 22.4bn here, 12.35bn as "
        "EDGAR's LongTermDebtCurrent. Never mix the two sources in one "
        "debt-to-capital ratio."),
    "shares_outstanding": (
        "Already on today's split basis - do NOT apply split_factor_by_"
        "filing_date (AAPL FY2017 reads 21.007bn, not the as-filed 5.25bn)."),
}

# The concepts whose numbers depend on the share count, and so carry the
# basis check below.
COUNT_CONCEPTS = ("shares_outstanding", "eps_from_net_income")

# Net income / count against the company's own reported EPS. Street EPS runs
# above GAAP by a few percent for most filers and by 12% for V FY2025, so a
# year outside this band is not noise. Measured on V FY2011-2012: the count
# read 4.09bn and 3.86bn, a different class basis, and the ratio fell to 0.71
# and below while FY2013 onward sat near 0.9.
COUNT_BASIS_BAND = (0.75, 1.25)


def count_basis_check(income, balance, earnings, band=COUNT_BASIS_BAND):
    """Years where net income / share count is far from the reported EPS.

    Two causes produce it, and the data cannot tell them apart: a share count
    on a different basis (V FY2011-2012, the case that motivated this) or a
    year whose GAAP result carries a large one-off that the street figure
    excludes (V FY2012's litigation provision is both). Either way, a
    per-share figure built on that year needs checking before use.
    """
    net, _ = annual_field(income, "INCOME_STATEMENT", "netIncome")
    count, _ = annual_field(balance, "BALANCE_SHEET",
                            "commonStockSharesOutstanding")
    street, _ = annual_field(earnings, "EARNINGS", "reportedEPS")
    partial = set(incomplete_earnings_years(earnings))
    low, high = band
    out = []
    for year in sorted(set(net) & set(count) & set(street)):
        if year in partial or not count[year] or not street[year] \
                or street[year] <= 0:
            continue
        ratio = (net[year] / count[year]) / street[year]
        if not low <= ratio <= high:
            out.append({"year": year,
                        "eps_from_net_income": round(net[year] / count[year], 4),
                        "eps_reported": street[year],
                        "ratio": round(ratio, 3)})
    return out


COUNT_BASIS_NOTE = (
    "count_basis_suspect: years where net income / share count is outside "
    "%.2f-%.2fx of the company's reported EPS. Either the count is on another "
    "basis (V FY2011-2012 read 4.09bn and 3.86bn: $0.89 and $0.56 against "
    "GAAP EPS of about $1.29 and $0.79) or the year carries a large one-off. "
    "Do not build a per-share figure or a share-count trend on a listed year "
    "without checking it; start the window after them if they are the "
    "earliest years." % COUNT_BASIS_BAND)


SOURCE_NOTE = (
    "Built from the same SEC filings as dgi-edgar: it corroborates the EDGAR "
    "READER (tag and date selection), never the filing itself. Where the two "
    "agree, the reader is right; where they disagree, check which definition "
    "each one uses before preferring either.")


class AvError(RuntimeError):
    pass


def api_key():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            key = (json.load(fh).get("api_key") or "").strip()
    except FileNotFoundError:
        raise AvError(
            "No Alpha Vantage key. Create %s containing "
            '{"api_key": "..."} with chmod 600. Never paste the key into the '
            "conversation." % CONFIG_PATH)
    except ValueError:
        raise AvError("%s is not valid JSON." % CONFIG_PATH)
    if not key:
        raise AvError("%s has an empty api_key." % CONFIG_PATH)
    return key


def _redact(text, key):
    return text.replace(key, "<redacted>") if key else text


def query_url(function, ticker, key):
    return BASE_URL + "?" + urllib.parse.urlencode(
        {"function": function, "symbol": ticker.strip().upper(),
         "apikey": key})


def parse_payload(text, function):
    """JSON -> dict, or AvError carrying Alpha Vantage's own message.

    The service answers HTTP 200 with a one-key object for a premium endpoint,
    an exhausted quota or an unknown symbol, so the status code says nothing.
    """
    try:
        data = json.loads(text)
    except ValueError:
        raise AvError("%s did not return JSON (%d bytes)." % (function, len(text)))
    if not isinstance(data, dict):
        raise AvError("%s returned %s, not an object." % (function,
                                                          type(data).__name__))
    for key in ("Error Message", "Note", "Information"):
        if key in data:
            raise AvError("%s refused: %s" % (function, str(data[key])[:240]))
    if not data:
        raise AvError("%s returned an empty object - usually an unknown "
                      "symbol." % function)
    return data


_last_network_call = [0.0]


def fetch(function, ticker, use_cache=True, key=None):
    """One function for one ticker, from the cache or the network."""
    name = "%s_%s.json" % (ticker.strip().upper(), function)
    path = os.path.join(CACHE_DIR, name)
    if use_cache and os.path.exists(path) and \
            time.time() - os.path.getmtime(path) < CACHE_TTL_SECONDS:
        with open(path, encoding="utf-8") as fh:
            return parse_payload(fh.read(), function), True

    key = key or api_key()
    wait = SECONDS_BETWEEN_CALLS - (time.time() - _last_network_call[0])
    if wait > 0:
        time.sleep(wait)
    request = urllib.request.Request(query_url(function, ticker, key),
                                     headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request,
                                    timeout=HTTP_TIMEOUT_SECONDS) as response:
            text = response.read().decode("utf-8")
    except (urllib.error.URLError, OSError) as err:
        raise AvError(_redact("%s: %s" % (function, err), key))
    finally:
        _last_network_call[0] = time.time()

    data = parse_payload(text, function)  # never cache a refusal
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return data, False


def _number(text):
    if text in (None, "", "None", "-"):
        return None
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return int(value) if value.is_integer() and (abs(value) >= 1000 or value == 0) else value


def _year(date_text):
    return int(str(date_text)[:4])


def annual_field(data, function, field):
    """{fiscal year: value} and {fiscal year: fiscalDateEnding}.

    "None" in the payload is a missing value, never a zero.
    """
    rows = data.get("annualEarnings" if function == "EARNINGS"
                    else "annualReports") or []
    values, dates = {}, {}
    for row in rows:
        date = row.get("fiscalDateEnding")
        value = _number(row.get(field))
        if not date or value is None:
            continue
        year = _year(date)
        values[year] = value
        dates[year] = date
    return dict(sorted(values.items())), dict(sorted(dates.items()))


def incomplete_earnings_years(data):
    """Annual EARNINGS years that are not a finished fiscal year.

    Alpha Vantage lists the year in progress as annual, labelled two ways, both
    seen live on 2026-10-11:
    - with the fiscal year end and fewer than four quarters inside it: AAPL
      "2026-09-30" at 6.87 with three quarters reported;
    - with the latest quarter's date, which is not the filer's fiscal year
      end: ZTS (December year end) "2026-09-30".
    Either one flags the year.
    """
    annual = [row.get("fiscalDateEnding") for row in
              (data.get("annualEarnings") or []) if row.get("fiscalDateEnding")]
    months = [int(d[5:7]) for d in annual]
    usual_month = max(sorted(set(months)), key=months.count) if months else None

    quarters = [q.get("fiscalDateEnding") for q in
                (data.get("quarterlyEarnings") or [])
                if _number(q.get("reportedEPS")) is not None]
    quarter_dates = [datetime.date.fromisoformat(q) for q in quarters if q]
    # Annual EPS reaches back further than the quarters (AAPL: 1996 against
    # 2006). A year before quarterly coverage cannot be counted, so only the
    # month test applies to it.
    covered_from = min(quarter_dates) if quarter_dates else None

    out = []
    for end_text in annual:
        end = datetime.date.fromisoformat(end_text)
        if usual_month is not None and end.month != usual_month:
            out.append(end.year)
            continue
        start = end - datetime.timedelta(days=365)
        if covered_from is None or start < covered_from - datetime.timedelta(days=100):
            continue
        inside = [d for d in quarter_dates if start < d <= end]
        if len(inside) < 4:
            out.append(end.year)
    return sorted(set(out))


def financials(ticker, concepts, since_year=None, use_cache=True):
    """The tool's work: only the requested series, a few dozen numbers."""
    unknown = [c for c in concepts if c not in CONCEPTS and c not in DERIVED
               and ":" not in c]
    if unknown:
        raise AvError("Unknown concept(s): %s. Known: %s, plus "
                      "'FUNCTION:field' for a raw field."
                      % (", ".join(unknown),
                         ", ".join(sorted(list(CONCEPTS) + list(DERIVED)))))

    def source_of(concept):
        if concept in CONCEPTS:
            return [CONCEPTS[concept]]
        if concept in DERIVED:
            return list(DERIVED[concept])
        function, field = concept.split(":", 1)
        if function not in FUNCTIONS:
            raise AvError("Unknown function %r in %r. Use one of %s."
                          % (function, concept, ", ".join(FUNCTIONS)))
        return [(function, field)]

    needed = []
    for concept in concepts:
        for function, _ in source_of(concept):
            if function not in needed:
                needed.append(function)
    # The basis check needs all three statements it compares; EARNINGS is one
    # extra request the first time, then a week of cache.
    checking_counts = any(c in COUNT_CONCEPTS for c in concepts)
    if checking_counts:
        for function in ("INCOME_STATEMENT", "BALANCE_SHEET", "EARNINGS"):
            if function not in needed:
                needed.append(function)

    payloads, cached, network = {}, {}, 0
    for function in needed:
        payloads[function], cached[function] = fetch(function, ticker,
                                                     use_cache=use_cache)
        network += 0 if cached[function] else 1

    def keep(series):
        return {y: v for y, v in series.items()
                if since_year is None or y >= since_year}

    out = {}
    for concept in concepts:
        if concept in DERIVED:
            (f1, n_field), (f2, d_field) = DERIVED[concept]
            num, dates = annual_field(payloads[f1], f1, n_field)
            den, _ = annual_field(payloads[f2], f2, d_field)
            series = {y: round(num[y] / den[y], 4) for y in num
                      if den.get(y)}
            entry = {"derived_from": ["%s.%s" % (f1, n_field),
                                      "%s.%s" % (f2, d_field)],
                     "annual": keep(series),
                     "fiscal_date": keep({y: dates[y] for y in series})}
        else:
            function, field = source_of(concept)[0]
            series, dates = annual_field(payloads[function], function, field)
            entry = {"function": function, "field": field,
                     "annual": keep(series), "fiscal_date": keep(dates)}
            if function == "EARNINGS":
                partial = [y for y in incomplete_earnings_years(
                    payloads[function]) if y in entry["annual"]]
                if partial:
                    entry["incomplete_years"] = partial
                    entry["incomplete_note"] = (
                        "Fewer than four reported quarters: the year in "
                        "progress (or a stub), listed as annual. Exclude it.")
        if concept in NOTES:
            entry["note"] = NOTES[concept]
        if concept in COUNT_CONCEPTS:
            suspect = [row for row in count_basis_check(
                payloads["INCOME_STATEMENT"], payloads["BALANCE_SHEET"],
                payloads["EARNINGS"]) if row["year"] in entry["annual"]]
            if suspect:
                entry["quality"] = {"count_basis_suspect": suspect,
                                    "_read_this": COUNT_BASIS_NOTE}
        if not entry["annual"]:
            entry["empty_note"] = (
                "No values for this field. Alpha Vantage writes 'None' where "
                "a filer does not report it; that is absence, not zero.")
        out[concept] = entry

    return {"ok": True, "ticker": ticker.strip().upper(),
            "source": "alphavantage", "source_note": SOURCE_NOTE,
            "cached": all(cached.values()), "network_requests": network,
            "quota_note": ("Free key: 25 requests a day, 5 a minute. Each "
                           "statement is one request; the cache holds a week."),
            "concepts": out}
