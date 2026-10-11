"""SEC EDGAR XBRL: fetch, cache, and reduce company facts to annual series.

WHY THIS EXISTS
---------------
FMP gates financial statements **per symbol**. Measured 2026-08-01, the user's
key covered 4 of 17 tickers tested; the other 13 return HTTP 402. That makes it
unusable as the source for criteria 4-9, which need statements for every
holding, not a quarter of them.

EDGAR has no such limit: free, no API key, every US filer, and the full filed
history rather than a five-year window. For ZTS - a symbol FMP refuses - it
returns diluted EPS from 2013 to 2025.

THE RULE THAT SHAPES THIS MODULE
--------------------------------
**EDGAR responses must never reach the conversation.** A single
`companyconcept` call for one ZTS tag returned ~40KB inline and cost a large
slice of a session's context; `companyfacts` for a whole company is far bigger.
So the network call happens here, on the user's machine, and the caller gets
back only the annual values it asked for - a few dozen numbers.

That is the same reason `dgi-sheet-bridge` and `dgi-ibkr-flex` exist, minus the
credentials: EDGAR needs no key, only a descriptive User-Agent, which the SEC
requires of all programmatic users.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request

CONFIG_PATH = os.path.expanduser("~/.dgi/edgar.json")
CACHE_DIR = os.path.expanduser("~/.dgi/edgar-cache")

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK%s.json"

# SEC asks for no more than 10 requests/second. One call per ticker per day is
# nowhere near that, but the courtesy pause costs nothing and keeps a future
# batch loop honest.
REQUEST_PAUSE_SECONDS = 0.15
HTTP_TIMEOUT_SECONDS = 60

# Company facts change only when something is filed. A day is generous for an
# annual analysis and turns repeat runs into zero network calls.
CACHE_TTL_SECONDS = 24 * 3600
TICKER_CACHE_TTL_SECONDS = 30 * 24 * 3600

FRAME_ANNUAL = re.compile(r"^CY\d{4}$")
FRAME_INSTANT = re.compile(r"^CY\d{4}Q4I$")


class EdgarError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# Concept aliases.
#
# Companies tag the same idea differently, and some invent their own extensions.
# Each alias is a CANDIDATE CHAIN. Every (tag, unit) pair in it that yields
# data is evaluated and ranked - see series_for_concept. Chain order still
# matters, but only as the tie-break between candidates that are otherwise
# equally good. The tag AND unit actually used are reported back, so a caller
# never has to guess which definition produced a number.
#
# It used to be first-match: the first tag with any data won, uncompared. That
# returned a one-year JNJ dividend series and a CHF Chubb series, both labelled
# OK. See BACKLOG item 12.

CONCEPTS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax",
                "RevenueFromContractWithCustomerIncludingAssessedTax",
                "Revenues", "SalesRevenueNet", "SalesRevenueGoodsNet"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss",
                   "ProfitLoss"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "eps_basic": ["EarningsPerShareBasic"],
    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment",
              "PaymentsToAcquireProductiveAssets"],
    # PaymentsOfOrdinaryDividends added 2026-08-01: it is what ZTS reports, and
    # the first three missed it entirely. Found via edgar_tags, which is the
    # designed escape hatch for exactly this.
    "dividends_paid": ["PaymentsOfDividendsCommonStock",
                       "PaymentsOfOrdinaryDividends",
                       "PaymentsOfDividends",
                       "PaymentsOfDividendsMinorityInterest"],
    # Declared dividend per share, straight from the filings. This is the
    # primary-source answer to the growth streak and DGR, which until now came
    # only from dripinvesting - whose DGR 1Y for ZTS is demonstrably wrong
    # (see references/data-sources.md).
    "dividend_per_share_declared": ["CommonStockDividendsPerShareDeclared",
                                    "CommonStockDividendsPerShareCashPaid"],
    "stockholders_equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "long_term_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "short_term_debt": ["LongTermDebtCurrent",
                        "ShortTermBorrowings",
                        "OtherShortTermBorrowings"],
    "interest_expense": ["InterestExpense",
                         "InterestExpenseDebt",
                         "InterestIncomeExpenseNet"],
    "shares_diluted": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    "shares_basic": ["WeightedAverageNumberOfSharesOutstandingBasic",
                     "WeightedAverageNumberOfSharesOutstanding"],
    "total_assets": ["Assets"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
}


# --------------------------------------------------------------------------- #
# HTTP with the SEC's required identification


def load_user_agent():
    """The SEC requires a descriptive User-Agent with a contact address.

    Deliberately not defaulted to something invented: an anonymous or fake UA
    is how an IP gets blocked, and a block would look like a code bug.
    """
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            value = (json.load(fh) or {}).get("user_agent", "").strip()
        if value:
            return value
    env = os.environ.get("DGI_EDGAR_USER_AGENT", "").strip()
    if env:
        return env
    raise EdgarError(
        "SEC requires a descriptive User-Agent with a contact address. Create "
        "%s containing {\"user_agent\": \"Your Name your@email\"}, or set "
        "DGI_EDGAR_USER_AGENT." % CONFIG_PATH)


def fetch_json(url):
    request = urllib.request.Request(url, headers={
        "User-Agent": load_user_agent(),
        "Accept-Encoding": "gzip, deflate",
        "Accept": "application/json",
    })
    time.sleep(REQUEST_PAUSE_SECONDS)
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                import gzip
                raw = gzip.decompress(raw)
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as err:
        if err.code == 403:
            raise EdgarError(
                "SEC returned 403. That is almost always the User-Agent: it "
                "must identify you and include a contact address.")
        if err.code == 404:
            raise EdgarError("Not found at %s - check the CIK." % url)
        if err.code == 429:
            raise EdgarError(
                "SEC rate limit hit (10 requests/second). Wait and retry; do "
                "not loop faster.")
        raise EdgarError("SEC HTTP %d for %s" % (err.code, url))
    except urllib.error.URLError as err:
        raise EdgarError("Cannot reach SEC: %s" % err.reason)


def cached_json(url, cache_name, ttl):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, cache_name)
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < ttl:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), True
    payload = fetch_json(url)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return payload, False


# --------------------------------------------------------------------------- #
# Ticker -> CIK


def cik_for_ticker(ticker):
    mapping, _ = cached_json(TICKER_MAP_URL, "company_tickers.json",
                             TICKER_CACHE_TTL_SECONDS)
    wanted = ticker.strip().upper()
    for row in mapping.values():
        if str(row.get("ticker", "")).upper() == wanted:
            return "%010d" % int(row["cik_str"]), row.get("title")
    raise EdgarError(
        "No SEC filer with ticker %s. Foreign issuers and most ETFs do not "
        "file with the SEC and will never be found here." % ticker)


def company_facts(ticker):
    cik, name = cik_for_ticker(ticker)
    facts, from_cache = cached_json(FACTS_URL % cik, "CIK%s.json" % cik,
                                    CACHE_TTL_SECONDS)
    return cik, name, facts, from_cache


# --------------------------------------------------------------------------- #
# Reduction to annual values - the part that keeps responses small


def _annual_with_filed(entries):
    """Pick one value per fiscal year, keeping the filing date that produced it from a tag's fact list.

    Two shapes exist and need different rules:

    - DURATION facts (income, cash flow) carry `start` and `end`. The annual one
      spans roughly a year. SEC's own `frame` of the form CY2024 marks exactly
      those, so it is preferred; the day-span test is the fallback for facts SEC
      has not framed.
    - INSTANT facts (balance sheet) carry only `end`. The year-end one is the
      balance an annual report states at its own fiscal year end - see
      `_fiscal_year_end_instants`. SEC's CY2024Q4I frame is only the fallback,
      because it marks the instant nearest Dec 31: for a September filer that
      is a 10-Q balance one quarter into the NEXT fiscal year (item 26).

    Restatements mean the same year appears several times across filings. The
    latest `filed` date wins, so a corrected figure supersedes the original.
    """
    annual, framed = {}, {}

    for fact in entries:
        value, end = fact.get("val"), fact.get("end")
        if value is None or not end:
            continue
        year = int(end[:4])
        frame = fact.get("frame", "")
        filed = fact.get("filed", "")

        if fact.get("start"):
            is_annual = bool(FRAME_ANNUAL.match(frame))
            if not is_annual and not frame:
                days = _day_span(fact["start"], end)
                is_annual = days is not None and 350 <= days <= 380 \
                    and str(fact.get("fp", "")).upper() == "FY"
            if is_annual and filed >= annual.get(year, ("",))[0]:
                annual[year] = (filed, value)
        else:
            if FRAME_INSTANT.match(frame) and filed >= framed.get(year, ("",))[0]:
                framed[year] = (filed, value, end)

    if annual:
        return dict(sorted(annual.items()))

    year_end = _fiscal_year_end_instants(entries)
    if year_end:
        return dict(sorted(year_end.items()))
    return dict(sorted((y, (f, v)) for y, (f, v, _) in framed.items()))


ANNUAL_FORMS = ("10-K", "20-F", "40-F")

# 52/53-week filers end on a weekday, not a date: "last Saturday of September"
# drifts across a week. A balance within this many days of the usual year end
# is still the year-end balance.
YEAR_END_TOLERANCE_DAYS = 7


def _fiscal_year_end_instants(entries):
    """Year-end balances as an annual report states them. {year: (filed, value)}.

    The year end itself comes from annual reports (fp FY on a 10-K, 20-F or
    40-F): the most common month-day among their balances, which also ignores
    the odd quarter-end instant an annual report sometimes carries. The VALUE
    then comes from any filing stating a balance on that date, latest filed
    winning as everywhere else - a 10-Q's prior-year-end comparative counts,
    and for some years it is the only one (V's debt 2016-2018, STERIS's cash).

    Keyed by the year of `end`, the same key the duration facts use, so V's
    Sept 30 2025 balance pairs with the year ending Sept 30 2025 rather than
    with a Dec 31 balance from the next fiscal year's first 10-Q. BACKLOG
    item 26.

    Empty when the facts carry no form or fp, so the frame fallback still
    applies to data shaped that way.
    """
    import collections

    balances = [f for f in entries
                if not f.get("start") and f.get("val") is not None
                and _as_date(f.get("end")) is not None]
    year_end_dates = [
        f["end"][5:10] for f in balances
        if str(f.get("fp", "")).upper() == "FY"
        and str(f.get("form", "")).upper().startswith(ANNUAL_FORMS)]
    if not year_end_dates:
        return {}

    usual = collections.Counter(year_end_dates).most_common(1)[0][0]
    usual = tuple(int(p) for p in usual.split("-"))

    picked = {}
    for fact in balances:
        if not _near_year_end(fact["end"], usual):
            continue
        year, filed = int(fact["end"][:4]), fact.get("filed", "")
        if filed >= picked.get(year, ("",))[0]:
            picked[year] = (filed, fact["val"])
    return picked


def _as_date(text):
    import datetime
    try:
        return datetime.date.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def _near_year_end(end, usual):
    """True when `end` falls within YEAR_END_TOLERANCE_DAYS of the usual year end.

    Measured across the year boundary too, so a 52-week year ending Jan 2 still
    matches a Dec 31 year end.
    """
    when = _as_date(end)
    if when is None:
        return False
    month, day = usual
    day = min(day, 28) if month == 2 else day
    import datetime
    return min(abs((when - datetime.date(y, month, day)).days)
               for y in (when.year - 1, when.year, when.year + 1)) \
        <= YEAR_END_TOLERANCE_DAYS


def _annual_from_unit(entries):
    """{year: value}. The plain view, for callers that do not need `filed`."""
    return {y: v for y, (_, v) in _annual_with_filed(entries).items()}


def _day_span(start, end):
    import datetime
    try:
        a = datetime.date.fromisoformat(start)
        b = datetime.date.fromisoformat(end)
    except ValueError:
        return None
    return (b - a).days


# --------------------------------------------------------------------------- #
# Candidate selection - which (tag, unit) actually answers the concept


# A candidate is "fresh" if it ends within this many years of the freshest
# candidate available. See _rank_key for why this is a gate and not a sort key.
FRESHNESS_SLACK_YEARS = 1

# Reported as stale in `quality` when the chosen series ends this far behind the
# current calendar year. Measured against today, NOT against the other
# candidates: a concept where every candidate died in 2015 is stale even though
# one of them is the freshest on offer.
STALE_AFTER_YEARS = 2


def _current_year():
    import datetime
    return datetime.date.today().year


def _is_usd(unit):
    """USD and USD/shares both count.

    Every price this pairs with is USD, so a non-USD numerator is a wrong
    multiple rather than a different opinion.
    """
    return str(unit).upper().startswith("USD")


# Units that count things instead of measuring money. "not USD" says nothing
# useful about a share count - it is never the numerator of a price multiple.
#
# v0.11.0 flagged MA's `shares_diluted` with `non_usd_unit: "shares"`, which is
# true and pure noise, and noise in a quality field is how a quality field
# starts being ignored. Found by running company-analysis end to end on MA -
# no unit test would have, because every fixture used USD. BACKLOG item 20.
#
# Deliberately narrow: only share units, which is what was measured. Other
# non-currency units exist in EDGAR (`pure` for ratios, `Year`) and would
# still be flagged. Widen this when one of them actually bites, not before.
COUNT_UNITS = frozenset({"shares", "share"})


def _is_count_unit(unit):
    return str(unit).strip().lower() in COUNT_UNITS


# A share count that moves this far in one year is a split, not issuance or
# buybacks: AAPL's diluted count reads 5.25bn for FY2017 (filed before the 4:1
# split) and 20.0bn for FY2018 (filed after it). The count is as filed, so a
# trend read off it scores criterion 9 backwards. BACKLOG item 29.
COUNT_JUMP_RATIO = 1.9


def _count_jumps(annual):
    """Consecutive years where a share count changes by COUNT_JUMP_RATIO or more."""
    jumps = []
    years = sorted(annual)
    for prev, year in zip(years, years[1:]):
        a, b = annual[prev], annual[year]
        if year != prev + 1 or not a or not b or a <= 0 or b <= 0:
            continue
        ratio = b / a
        if ratio >= COUNT_JUMP_RATIO or ratio <= 1 / COUNT_JUMP_RATIO:
            jumps.append({"year": year, "ratio": round(ratio, 3)})
    return jumps


def _interior_gaps(years_present):
    """Years missing between the first and last reported year.

    Not the same as a short series: an interior gap silently breaks any
    consecutive-years count, which is what a growth streak is.
    """
    if len(years_present) < 2:
        return []
    return [y for y in range(min(years_present), max(years_present) + 1)
            if y not in years_present]


def _per_payment_years(entries):
    """Years whose 'annual' dividend per share is provably one payment's rate.

    Visa files an annual-duration fact (frame CY2025, Oct 2024 - Sept 2025)
    whose value, 0.59, is the quarterly dividend; the year paid 2.36. Nothing
    in the fact says so. It is only provable where the SAME filing (`accn`)
    also carries the quarters inside that year: they then add up to several
    times the 'annual' figure, and one of them equals it. BACKLOG item 25.

    Same filing, never across filings: a filing states every figure on one
    share basis, while comparing across filings mixes bases around a split.
    Across filings NextEra 2018 looks identical to this defect - 1.11 annual
    against 4.44 of quarters - and is in fact a correct split-restated annual.

    Returns {year: (payments counted in that year, the per-payment value)}.
    """
    quarters = {}
    for fact in entries:
        days = _day_span(fact.get("start") or "", fact.get("end") or "")
        if days is not None and 80 <= days <= 100 and fact.get("val") is not None:
            quarters.setdefault(fact.get("accn"), {})[
                (fact["start"], fact["end"])] = fact["val"]

    found = {}
    for fact in entries:
        value, start, end = fact.get("val"), fact.get("start"), fact.get("end")
        days = _day_span(start or "", end or "")
        if not value or value <= 0 or days is None or not 350 <= days <= 380:
            continue
        inside = [v for (s, e), v in quarters.get(fact.get("accn"), {}).items()
                  if s >= start and e <= end]
        if len(inside) < 3 or sum(inside) < PER_PAYMENT_MIN_RATIO * value:
            continue
        if any(_same_amount(v, value) for v in inside):
            found[int(end[:4])] = (len(inside), value)
    return found


def _same_amount(a, b):
    return abs(a - b) <= 1e-9 + 0.005 * abs(b)


# A real annual total is about equal to the sum of its quarters. A per-payment
# rate is a quarter of it, so the sum sits near 4x. 2.5 separates the two with
# room for a mid-year raise and for a semi-annual payer's 2x staying unflagged.
PER_PAYMENT_MIN_RATIO = 2.5

# Two neighbouring years share a basis while the series moves less than this
# factor per year. A per-payment year next to a true annual one jumps about 4x;
# no real dividend doubles or halves in a year often enough to matter here.
SAME_BASIS_MAX_STEP = 2.0


def _candidates(facts, tags, since_year=None):
    """Every (tag, unit) pair in the chain that yields at least one value."""
    us_gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    found = []
    for position, tag in enumerate(tags):
        entry = us_gaap.get(tag)
        if not entry:
            continue
        for unit, entries in (entry.get("units") or {}).items():
            detailed = _annual_with_filed(entries)
            if since_year:
                detailed = {y: fv for y, fv in detailed.items()
                            if y >= since_year}
            if not detailed:
                continue
            candidate = {"tag": tag, "unit": unit,
                         "annual": {y: v for y, (_, v) in detailed.items()},
                         "filed": {y: f for y, (f, _) in detailed.items()},
                         "position": position}
            if "DividendsPerShare" in tag:
                candidate["per_payment"] = _per_payment_years(entries)
            found.append(candidate)
    return found


def _per_payment_span(annual, confirmed):
    """Extend proven per-payment years to neighbours on the same basis.

    Visa's quarters sit in its filings only for 2019-2020, yet 2021-2025 are the
    same per-payment rate: the series steps 0.30, 0.32, 0.375... with no 4x
    jump that a switch to true annual totals would show. Growth is measured per
    year across an interior gap, so a missing year does not stop the walk; a
    split does, which is correct - across it the basis changed. A lower bound,
    not a full list: unflagged years are unproven, not proven annual.
    """
    years = sorted(annual)
    flagged = {y for y in confirmed if y in annual}
    for direction in (1, -1):
        ordered = years if direction == 1 else years[::-1]
        for prev, cur in zip(ordered, ordered[1:]):
            if prev not in flagged or cur in flagged:
                continue
            a, b = annual[prev], annual[cur]
            if not a or not b or a <= 0 or b <= 0:
                continue
            step = (b / a) ** (1.0 / abs(cur - prev))
            if 1 / SAME_BASIS_MAX_STEP <= step <= SAME_BASIS_MAX_STEP:
                flagged.add(cur)
    return sorted(flagged)


def _rank_key(candidate, freshest_year):
    """Sort key for one candidate. Highest wins. The order is deliberate.

    1. **USD outranks everything.** Nothing downstream checks the unit, and
       every price this pairs with is USD, so a CHF numerator is simply wrong.
    2. **Freshness is a boolean gate, not a raw sort.** Sorting on last_year
       directly would let a one-value stub for the current year beat eighteen
       years ending last year. Both that trap and its mirror - a short current
       series correctly beating a long dead one - are covered by tests.
    3. **More history** among candidates that pass the gate.
    4. **Chain position**, so the result is deterministic and the documented
       fallback order still decides genuine ties.
    """
    last_year = max(candidate["annual"])
    is_fresh = last_year >= freshest_year - FRESHNESS_SLACK_YEARS
    return (_is_usd(candidate["unit"]), is_fresh, len(candidate["annual"]),
            -candidate["position"])


def _quality_of(chosen, candidate_count):
    """Defects that survive the choice. Empty dict when there is nothing to say.

    The point is that picking the best candidate does not make it good. MA, V
    and DPZ have real holes in the filer's own data; no ranking can invent the
    missing years. Saying so out loud is the difference between a wrong number
    and a known-incomplete one.
    """
    quality = {}
    if not _is_usd(chosen["unit"]) and not _is_count_unit(chosen["unit"]):
        quality["non_usd_unit"] = chosen["unit"]

    last_year = max(chosen["annual"])
    behind = _current_year() - last_year
    if behind >= STALE_AFTER_YEARS:
        quality["stale"] = {"last_year": last_year, "years_behind": behind}

    gaps = _interior_gaps(set(chosen["annual"]))
    if gaps:
        quality["interior_gaps"] = gaps

    # A zero or a negative does not make the series wrong - it makes a growth
    # RATIO undefined. Both are common and both are real: INTU (2010-2011) and
    # ZTS (2011-2012) have genuine pre-dividend years, and QCOM, MO, MA, GPC and
    # ARE all have real loss years in eps_diluted. See BACKLOG item 15.
    zeros = sorted(y for y, v in chosen["annual"].items() if v == 0)
    if zeros:
        quality["zero_values"] = zeros
    negatives = sorted(y for y, v in chosen["annual"].items()
                       if v is not None and v < 0)
    if negatives:
        quality["negative_values"] = negatives

    # Only a confirmation whose value is the one the series actually returned
    # counts - another filing's fact for the same year may be the true total.
    proven = {}
    for year, proofs in chosen.get("per_payment", {}).items():
        if not isinstance(proofs, list):
            proofs = [proofs]
        for payments, value in proofs:
            if year in chosen["annual"] and _same_amount(chosen["annual"][year], value):
                proven[year] = payments
    jumps = (_count_jumps(chosen["annual"])
             if _is_count_unit(chosen["unit"]) else [])
    if jumps:
        quality["count_jumps"] = jumps

    if proven:
        quality["per_payment_rate"] = {
            "years": _per_payment_span(chosen["annual"], proven),
            "confirmed_years": sorted(proven),
            "payments_per_year": max(proven.values()),
        }

    if quality:
        quality["_read_this"] = (
            "Best of %d candidate (tag, unit) pairs, but these defects survive "
            "the choice. Do not compute a growth streak, a DGR or a multiple "
            "without accounting for them." % candidate_count)
    if zeros or negatives:
        quality["_read_this"] += (
            " A zero or negative value makes a growth ratio UNDEFINED rather "
            "than imprecise: a DGR over a series starting at zero divides by "
            "zero, and a streak counted through one is meaningless. These are "
            "normally real - pre-dividend years and genuine loss years - so do "
            "not treat them as data errors. Start the window after them, or "
            "report that the metric cannot be computed.")
    if jumps:
        quality["_read_this"] += (
            " count_jumps: the share count changes %.1fx or more between two "
            "consecutive years - almost always a split, because each year is "
            "as filed and a filing before the split carries the old share "
            "basis. Do NOT read it as issuance or a buyback. Put the series "
            "on today's basis first: DIVIDE each year by the factor from "
            "price_annual_averages' split_factor_by_filing_date, keyed on that "
            "year's `filed` date (per-share figures are MULTIPLIED by it; a "
            "count is the inverse)." % COUNT_JUMP_RATIO)
    if proven:
        quality["_read_this"] += (
            " per_payment_rate: in the listed years the 'annual' figure is ONE "
            "payment's rate, as the filer tagged it - proven where the same "
            "filing's quarters add up to several times it. A yield or a payout "
            "on it is wrong by the payment count; multiply by "
            "payments_per_year first. Growth ratios inside the listed years "
            "are fine, but never across into an unlisted year: unlisted means "
            "unproven, not annual.")
    return quality


def series_for_concept(facts, concept, years=None):
    """Resolve one alias through its candidate chain and return annual values.

    Every (tag, unit) pair the chain offers is evaluated and ranked; the winner
    is returned. Two keys appear ONLY when there is something to report, so a
    clean series stays clean and quiet:

    - `quality`  - defects that survive the choice (non-USD unit, stale series,
                   interior gaps).
    - `alternatives` - the candidates that lost, so a caller can see that a
                   choice was made rather than trusting a bare series.
    """
    tags = CONCEPTS.get(concept, [concept])
    candidates = _candidates(facts, tags, years)

    if not candidates:
        return {"tag": None, "unit": None, "annual": {},
                "note": _absence_note(facts, tags)}

    freshest = max(max(c["annual"]) for c in candidates)
    candidates.sort(key=lambda c: _rank_key(c, freshest), reverse=True)
    chosen, rejected = candidates[0], candidates[1:]

    # A sibling dividend tag's proof counts too: Visa's quarters sit under
    # ...CashPaid while the longer ...Declared wins the ranking. _quality_of
    # only accepts a proof whose value equals the returned one, which is what
    # keeps a sibling on another share basis from being applied.
    if "per_payment" in chosen:
        merged = {}
        for c in candidates:
            for year, proof in c.get("per_payment", {}).items():
                merged.setdefault(year, []).append(proof)
        chosen = dict(chosen, per_payment=merged)

    result = {"tag": chosen["tag"], "unit": chosen["unit"],
              "annual": chosen["annual"], "filed": chosen["filed"]}

    quality = _quality_of(chosen, len(candidates))
    if quality:
        result["quality"] = quality

    if rejected:
        result["alternatives"] = [
            {"tag": c["tag"], "unit": c["unit"], "years": len(c["annual"]),
             "first_year": min(c["annual"]), "last_year": max(c["annual"])}
            for c in rejected]

    return result


# Present when a filer computes EPS but reports it only per share class. The
# tag itself is a count of excluded securities, never EPS - but it cannot exist
# unless an EPS computation does. Visa carries 96 rows of it and no EPS tag at
# all. See BACKLOG item 17.
EPS_COMPUTED_MARKER = (
    "AntidilutiveSecuritiesExcludedFromComputationOfEarningsPerShareAmount")


def _absence_note(facts, tags):
    """Why a concept came back empty. Three causes that look identical.

    The old note said "None of X is reported by this filer, use edgar_tags" for
    all three. That sent the reader on a hunt that cannot succeed in two of
    them, and `edgar_tags` itself only searched us-gaap, so it answered
    `matched: 0` for a filer with 476 IFRS tags. See BACKLOG items 11 and 17.
    """
    present = sorted((facts.get("facts") or {}))
    chain = ", ".join(tags)
    where = "Namespaces this filer reports: %s." % (", ".join(present) or "none")

    us_gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    if not us_gaap:
        return ("No us-gaap facts at all. %s This is a foreign private issuer "
                "filing under IFRS; every concept chain here is us-gaap only, "
                "so NO concept will resolve and there is no alternate tag to "
                "find. Do not score this as a weak company - the source is "
                "absent, not the performance. See BACKLOG item 11." % where)

    if EPS_COMPUTED_MARKER in us_gaap and any(
            "EarningsPerShare" in t or "SharesOutstanding" in t for t in tags):
        return ("None of %s is in us-gaap for this filer, but %s IS - which "
                "cannot exist unless the filer computes EPS. The likely cause "
                "is that it reports per-share figures only per share class, "
                "and SEC companyfacts omits dimensioned facts entirely. **No "
                "tag chain can recover these**; edgar_tags will not help. Use "
                "a non-EDGAR source or report the figure as unavailable. See "
                "BACKLOG item 17." % (chain, EPS_COMPUTED_MARKER))

    return ("None of %s is reported by this filer. %s Use edgar_tags, which "
            "searches every namespace, to see what it does report. If nothing "
            "plausible turns up, the filer may report this only with "
            "dimensions such as a share class - SEC companyfacts omits those, "
            "and no tag chain can recover them." % (chain, where))


def available_tags(facts, contains=None, limit=60):
    """Every tag the filer reports, across EVERY namespace.

    Widened 2026-08-29. It used to read `facts["us-gaap"]` alone, so it
    answered `matched: 0` for BCS - a filer with 476 `ifrs-full` tags - which
    reads as "reports nothing" and is the opposite of the truth. This is the
    documented escape hatch for a concept that will not resolve; an escape
    hatch that cannot see the data is worse than none.

    Tags come back namespace-qualified (`ifrs-full:WeightedAverageShares`) so
    the caller can tell a us-gaap tag it can pass straight back to
    `edgar_financials` from one it cannot.
    """
    by_ns = (facts.get("facts") or {})
    names = ["%s:%s" % (ns, tag) for ns in sorted(by_ns)
             for tag in sorted(by_ns[ns])]
    if contains:
        needle = contains.lower()
        names = [n for n in names if needle in n.split(":", 1)[1].lower()]
    return {"matched": len(names), "tags": names[:limit],
            "truncated": len(names) > limit,
            "namespaces": {ns: len(by_ns[ns]) for ns in sorted(by_ns)},
            "note": ("Only `us-gaap:` tags can be passed back to "
                     "edgar_financials as a raw concept. A filer whose tags "
                     "are all in another namespace cannot be read by this "
                     "plugin at all.")}