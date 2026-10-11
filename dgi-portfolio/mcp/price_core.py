"""Annual average share prices from Tiingo, reduced on the host.

WHY THIS EXISTS
---------------
Five of the six valuation methods in `company-analysis` need the SAME missing
input: an average share price per year over 10-15 years. Every denominator is
already solved by `dgi-edgar`; only this numerator was missing, so the skill
produced a score and no price - half its purpose.

A 15-year daily series is ~3,800 rows per ticker. Putting that in a
conversation is the most expensive mistake available in this project, which is
why `dgi-edgar` exists at all. Same answer here: fetch on the host, return ~15
numbers.

WHY A PAID API AND NOT A FREE ONE
---------------------------------
Because the free ones do not work. Measured 2026-08-03 from a normal
residential connection, no VPN: Yahoo's chart API answered HTTP 429 on the
crumb endpoint even after the session cookie landed, and Stooq answered a
"this site requires JavaScript to verify your browser" interstitial.
`edgar_lookup` succeeded from the same machine in the same minute, so it was
the anti-bot layer, not connectivity.

The lesson, kept because it reverses an earlier decision here: **a keyless
source is keyless because it is scraped, and being scraped is exactly why it
carries a browser challenge.** Tiingo was first rejected for "needs a key, no
gain over two keyless sources". That was backwards - "no key needed" was the
warning sign. Both walled sources were carried as dead code for one session and
then removed; do not reintroduce them as untried options.

THE TWO TRAPS THIS MODULE IS SHAPED AROUND
------------------------------------------
Both are silent. Neither raises, and both produce numbers that look plausible.

**1. Dividend-adjusted prices destroy the Weiss yield model.** An "adjusted
close" retro-subtracts dividends, so historical prices come back too low, the
per-year yield comes back too high, `historical yield` is inflated, and the
estimate lands too cheap. We use the raw as-traded `close` and apply only the
splits. `adjClose` is carried for verification and never averaged.

**2. Split adjustment must match on both sides of the fraction.** Historical
P/E is `average annual price / EPS`. Our prices are split-adjusted;
`eps_diluted` from EDGAR is AS FILED, on the share count of that year. For any
company with a split inside the window the ratio is wrong by exactly the split
factor - MA (10:1, 2014), V (4:1, 2015) and KO (2:1, 2012), for example.
`split_factor_table` returns the multiplier that fixes it. Using it is the
caller's job; not returning it would make the error invisible.

**The multiplier is keyed on the EDGAR fact's `filed` date, not its year.**
EDGAR restates the last few years in every 10-K, so a year just before a split
usually carries an ALREADY post-split figure. Keying on the year rescales it
twice and inflates the multiple by the whole split ratio. This was live and
silent until 2026-08-29; see BACKLOG item 16.

WHAT VERIFIES THIS, NOW THAT THERE IS ONE SOURCE
------------------------------------------------
`verify_split_arithmetic`. Our split-only series and Tiingo's own `adjClose`
are both split-adjusted, so splits CANCEL in the ratio between them and only
the dividend adjustment is left - a ratio that must be 1.0 at the newest bar
and non-increasing forward in time. It checks the one thing computed here
rather than supplied.

**It cannot catch an error Tiingo itself made.** There is no second provider.
When a valuation depends on this series, say which source it came from and that
it is unconfirmed elsewhere.
"""

import datetime
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

CACHE_DIR = os.path.expanduser("~/.dgi/price-cache")
CONFIG_PATH = os.path.expanduser("~/.dgi/prices.json")

# Historical daily bars change only when a split is applied retroactively.
# A day is generous, and it makes re-analysing the same ticker free.
CACHE_TTL_SECONDS = 24 * 3600
HTTP_TIMEOUT_SECONDS = 45

TIINGO_BASE = "https://api.tiingo.com/tiingo/daily"

USER_AGENT = "dgi-portfolio/0.5 (personal dividend portfolio analysis)"

DEFAULT_YEARS = 15

# Daily bars, so a full year has ~252. Below this a year is partial: still
# returned, because a partial current year is useful for the current multiple,
# but flagged, because it is misleading inside a 15-year mean.
MIN_DAILY_BARS_FOR_COMPLETE_YEAR = 120

ADJUSTMENT = "split_only"


class PriceError(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# HTTP seam.
#
# Kept deliberately thin and separate from every parse function below, so the
# whole module is testable offline against fixtures. The parsers take parsed
# JSON and never touch the network - the same split that keeps
# parse_dripinvesting.py testable.


def http_get(url, accept="*/*", extra_headers=None):
    """Plain GET. Raises PriceError, never HTTPError."""
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    headers.update(extra_headers or {})
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as err:
        if err.code == 404:
            raise PriceError(
                "404 - Tiingo does not know this symbol. US listings only; "
                "foreign issuers and most ETFs are not covered.")
        if err.code in (401, 403):
            raise PriceError(
                "HTTP %d - the token was rejected. Check `tiingo_token` in %s."
                % (err.code, CONFIG_PATH))
        if err.code == 429:
            raise PriceError(
                "HTTP 429 - Tiingo rate limit. Here this IS rate limiting, "
                "unlike the scraped sources this replaced. 17 tickers cached "
                "for a day sits far inside the free tier, so hitting it means "
                "something is looping or the cache is being bypassed.")
        raise PriceError("HTTP %d for %s" % (err.code, url))
    except urllib.error.URLError as err:
        raise PriceError("Cannot reach Tiingo: %s" % err.reason)


def _safe_name(*parts):
    raw = "_".join(str(p) for p in parts)
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in raw)


# --------------------------------------------------------------------------- #
# Tiingo


def tiingo_token():
    """Read the token. Never returned in an error, never put in a URL.

    It travels in an Authorization header, not a query string, so it cannot
    land in a cache filename, a log line, or an exception message that reaches
    the conversation. Same rule the sheet bridge token lives under.
    """
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as fh:
                value = (json.load(fh) or {}).get("tiingo_token", "").strip()
            if value:
                return value
        except (OSError, ValueError):
            pass
    env = os.environ.get("DGI_TIINGO_TOKEN", "").strip()
    if env:
        return env
    raise PriceError(
        "No Tiingo token. Create %s containing "
        "{\"tiingo_token\": \"...\"} - a free account at tiingo.com is enough "
        "for 17 tickers cached for a day." % CONFIG_PATH)


def tiingo_prices_url(ticker, years=DEFAULT_YEARS, now=None):
    """Daily rows. Reducing them here is what this whole server is for.

    Deliberately NOT `resampleFreq=monthly`: resampling would collapse the
    per-row `splitFactor`, and that field is the entire reason this source was
    chosen. ~3,800 rows per ticker stays on this machine and never enters a
    conversation.
    """
    now = now or datetime.datetime.now(datetime.timezone.utc)
    start = (now - datetime.timedelta(days=int(years * 366))).date().isoformat()
    query = urllib.parse.urlencode({"startDate": start, "format": "json"})
    return "%s/%s/prices?%s" % (
        TIINGO_BASE, urllib.parse.quote(ticker.strip().upper()), query)


def _split_label(ratio):
    if abs(ratio - round(ratio)) < 1e-6:
        return "%d:1" % round(ratio)
    if ratio and abs(1.0 / ratio - round(1.0 / ratio)) < 1e-6:
        return "1:%d" % round(1.0 / ratio)
    return "%.4f" % ratio


def parse_tiingo_prices(payload):
    """Tiingo daily rows -> split-only bars + split events. Pure, no network.

    Tiingo hands over `close` as actually traded, unadjusted, plus a
    `splitFactor` per row. So the split-adjusted series is computed here:

        split_adjusted(i) = close(i) / product(splitFactor(j) for j after i)

    That is the opposite of trusting a vendor's word for which adjustments are
    baked in. `adjClose` is captured for `verify_split_arithmetic` and never
    used as a price: it is split AND dividend adjusted, and averaging it would
    silently break the Weiss model.
    """
    if isinstance(payload, dict):
        raise PriceError(
            "Tiingo returned an object, not a row list: %s"
            % (payload.get("detail") or payload.get("error") or "unknown"))
    if not payload:
        raise PriceError(
            "Tiingo returned zero rows. Usually a ticker the free tier does "
            "not cover, or a start date before the listing.")

    rows = []
    for row in payload:
        date = (row.get("date") or "")[:10]
        close = row.get("close")
        if not date or close is None:
            continue
        try:
            factor = float(row.get("splitFactor") or 1.0)
        except (TypeError, ValueError):
            factor = 1.0
        try:
            div_cash = float(row.get("divCash") or 0.0)
        except (TypeError, ValueError):
            div_cash = 0.0
        rows.append({"date": date, "raw_close": float(close),
                     "adjclose": row.get("adjClose"),
                     "split_factor": factor, "div_cash": div_cash})
    rows.sort(key=lambda r: r["date"])
    if not rows:
        raise PriceError("Tiingo rows carried no usable close price.")

    # Walk backwards accumulating every split that happens AFTER each row.
    # A dividend on a row is on that row's share basis, exactly like its
    # close, so it is divided by the same cumulative factor.
    bars = []
    dividends = []
    cumulative = 1.0
    for row in reversed(rows):
        bars.append({
            "date": row["date"],
            "close": round(row["raw_close"] / cumulative, 6),
            "adjclose": (float(row["adjclose"])
                         if row["adjclose"] is not None else None),
        })
        if row["div_cash"] > 0:
            dividends.append({
                "ex_date": row["date"],
                "amount": round(row["div_cash"] / cumulative, 6),
                "as_paid": row["div_cash"],
            })
        cumulative *= row["split_factor"]
    bars.reverse()
    dividends.reverse()

    splits = [{"date": r["date"], "ratio": r["split_factor"],
               "label": _split_label(r["split_factor"])}
              for r in rows if abs(r["split_factor"] - 1.0) > 1e-9]

    return {"symbol": None, "currency": "USD", "bars": bars, "splits": splits,
            "dividends": dividends}


def fetch_tiingo(ticker, years=DEFAULT_YEARS, use_cache=True):
    url = tiingo_prices_url(ticker, years=years)
    name = _safe_name("tiingo", ticker.upper(), years) + ".json"
    path = os.path.join(CACHE_DIR, name)
    cached = False

    if use_cache and os.path.exists(path) and \
            time.time() - os.path.getmtime(path) < CACHE_TTL_SECONDS:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        cached = True
    else:
        text = http_get(url, accept="application/json", extra_headers={
            "Authorization": "Token %s" % tiingo_token()})
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    try:
        payload = json.loads(text)
    except ValueError:
        raise PriceError(
            "Tiingo returned something that is not JSON (%d bytes)." % len(text))
    parsed = parse_tiingo_prices(payload)
    parsed["cached"] = cached
    parsed["source"] = "tiingo"
    parsed["symbol"] = ticker.strip().upper()
    return parsed


# --------------------------------------------------------------------------- #
# Reduction to annual values - the part that keeps responses small


def fiscal_year_of(date_iso, fye_month=12):
    """Which fiscal year a date belongs to, given the month the year ends in.

    Calendar years are the `fye_month=12` case. INTU closes in July, so August
    2023 through July 2024 is FY2024 - and pairing a calendar-year average
    price with a July-ending EPS is a real error, not a rounding difference.
    """
    year = int(date_iso[:4])
    month = int(date_iso[5:7])
    if fye_month == 12:
        return year
    return year if month <= fye_month else year + 1


def fiscal_year_end_date(year, fye_month=12):
    """Last calendar day of the fiscal year labelled `year`."""
    month, next_year = fye_month + 1, year
    if month > 12:
        month, next_year = 1, year + 1
    return datetime.date(next_year, month, 1) - datetime.timedelta(days=1)


# A year's last bar may fall short of the fiscal year end by a holiday weekend
# without the year being partial.
YEAR_END_TOLERANCE_DAYS = 10


def annual_averages(bars, fye_month=12,
                    min_bars=MIN_DAILY_BARS_FOR_COMPLETE_YEAR):
    """Mean close per year, plus enough context to judge whether to trust it.

    `complete` needs BOTH tests, and the second was missing until a live run on
    2026-08-03 exposed it. Bar count alone called a seven-month 2026 complete,
    because 145 bars clears a 120 threshold set for stub years. **A year still
    in progress is partial no matter how many bars it has**, and averaging one
    into a 15-year mean drags the mean toward today's price - badly, for a name
    that has been rising steeply.

    So: enough bars AND the series actually reaches the fiscal year end.
    """
    buckets = {}
    for bar in bars:
        buckets.setdefault(fiscal_year_of(bar["date"], fye_month), []).append(bar)

    out = {}
    for year, items in sorted(buckets.items()):
        items.sort(key=lambda b: b["date"])
        closes = [b["close"] for b in items]
        last = datetime.date.fromisoformat(items[-1]["date"])
        reaches_year_end = (
            (fiscal_year_end_date(year, fye_month) - last).days
            <= YEAR_END_TOLERANCE_DAYS)
        out[year] = {
            "average": round(sum(closes) / len(closes), 4),
            "bars": len(closes),
            "first": items[0]["date"],
            "last": items[-1]["date"],
            "low": round(min(closes), 4),
            "high": round(max(closes), 4),
            "complete": len(closes) >= min_bars and reaches_year_end,
            "reaches_year_end": reaches_year_end,
        }
    return out


def split_factor_table(splits):
    """Step table putting an AS-FILED per-share figure on today's share basis.

    **Keyed by the EDGAR fact's `filed` date, never by its fiscal year.** That
    distinction is the entire point of this function, and getting it wrong was
    a live, silent bug - see BACKLOG item 16.

    Why the year is the wrong key: EDGAR restates the last few years in every
    10-K, and `edgar_financials` takes the latest filing for each year, so the
    annual fact that wins for year Y is usually the one filed about three years
    after Y. Measured on MA: the fact for 2010 was filed 2013-02-14 and carries
    0.60, pre-split; the fact for 2011 was filed 2014-02-14, three weeks after
    the 10:1 split, and already carries 0.06. A year-keyed factor rescaled that
    second figure a second time and turned a P/E of 24 into 240.

    The seam cannot be found by looking at the numbers. KO proves it: its
    dividend series steps by a clean 2x at the seam, but its EPS series steps
    by only 0.86 because underlying EPS grew that year and hid it. The filing
    date has no such blind spot - it is a fact about the document, not the
    value.

    How to read the table: take the EDGAR fact's `filed` date, find the FIRST
    row whose `filed_before` is later than it, use that row's `factor`. If no
    row matches, the figure is already on today's basis and the factor is 1.0.
    An empty table means the filer has never split inside the window.
    """
    rows, cumulative = [], 1.0
    for split in sorted(splits, key=lambda s: s["date"], reverse=True):
        cumulative *= split["ratio"]
        rows.append({"filed_before": split["date"],
                     "factor": round(1.0 / cumulative, 6) if cumulative else 1.0})
    rows.reverse()
    return rows


def split_factor_for(table, filed):
    """Apply split_factor_table. `filed` is an ISO date string from edgar."""
    for row in table:
        if filed < row["filed_before"]:
            return row["factor"]
    return 1.0


# --------------------------------------------------------------------------- #
# Self-verification against Tiingo's own adjClose.
#
# This is what a single-source design has instead of a second opinion, and it
# is narrower on purpose. We compute the split-only series ourselves from raw
# `close` and `splitFactor`. Tiingo independently publishes `adjClose`, adjusted
# for splits AND dividends. Both are split-adjusted, so splits CANCEL:
#
#     ratio(t) = our_split_only(t) / adjClose(t)   ->   dividend adjustment only
#
# That ratio has a shape it cannot escape if our arithmetic is right: exactly
# 1.0 at the newest bar, and non-increasing forward in time as dividends are
# added back. A residual step at a split date means WE mis-applied that split -
# the one computation nobody else is checking for us.


def verify_split_arithmetic(bars, splits, tolerance_pct=1.0):
    """Check our split-only series against the vendor's independent adjClose."""
    usable = [b for b in bars
              if b.get("adjclose") and b["adjclose"] > 0 and b["close"] > 0]
    if len(usable) < 30:
        return {"ok": None, "verdict": "unavailable",
                "note": "Too few rows carry adjClose to verify anything. The "
                        "split arithmetic is unchecked - say so."}

    usable.sort(key=lambda b: b["date"])
    ratios = [(b["date"], b["close"] / b["adjclose"]) for b in usable]

    newest_date, newest = ratios[-1]
    oldest_date, oldest = ratios[0]
    problems = []

    if abs(newest - 1.0) * 100.0 > tolerance_pct:
        problems.append(
            "The newest bar should have our price equal to adjClose - no "
            "dividends can have been added back yet - but the ratio is %.4f "
            "at %s." % (newest, newest_date))

    # Forward in time the ratio may only fall. A rise means an adjustment was
    # applied in the wrong direction or to the wrong side of a split.
    rises = []
    for (date_a, a), (date_b, b) in zip(ratios, ratios[1:]):
        if a > 0 and (b - a) / a * 100.0 > tolerance_pct:
            rises.append({"from": date_a, "to": date_b,
                          "ratio_before": round(a, 6),
                          "ratio_after": round(b, 6)})
    if rises:
        problems.append(
            "The dividend adjustment increases going forward at %d point(s), "
            "which it cannot do." % len(rises))

    # A split we mis-applied shows up as a step by roughly the split ratio.
    split_steps = []
    for split in splits:
        before = [r for d, r in ratios if d < split["date"]]
        after = [r for d, r in ratios if d >= split["date"]]
        if not before or not after:
            continue
        step = after[0] / before[-1] if before[-1] else 0.0
        if abs(step - 1.0) * 100.0 > tolerance_pct * 5:
            split_steps.append({"date": split["date"], "label": split["label"],
                                "step": round(step, 6)})
    if split_steps:
        problems.append(
            "A step remains at %d split date(s) after both series are "
            "split-adjusted. That is our arithmetic, not the vendor's."
            % len(split_steps))

    report = {
        "ok": not problems,
        "rows_checked": len(ratios),
        "window": [oldest_date, newest_date],
        "dividend_factor": round(oldest, 6),
        "dividend_factor_note": (
            "Cumulative dividend adjustment across the window. A dividend "
            "payer should sit above 1.0 and a non-payer at exactly 1.0; a "
            "number far from what the yield implies is worth a second look."),
    }
    if problems:
        report["verdict"] = "split_arithmetic_suspect"
        report["problems"] = problems
        report["rises"] = rises[:5]
        report["split_steps"] = split_steps
        report["note"] = (
            "Do NOT report a valuation from this series. The split handling is "
            "the one part computed here rather than supplied, and this is the "
            "check that it is right.")
    else:
        report["verdict"] = "consistent"
        report["note"] = (
            "Our split-only series and the vendor's adjClose differ by a clean "
            "dividend adjustment and nothing else - so the splits are applied "
            "correctly. This is NOT a second source: it cannot catch an error "
            "Tiingo itself made, and there is no other provider behind it.")
    return report


# --------------------------------------------------------------------------- #
# Orchestration


def annual_price_series(ticker, years=DEFAULT_YEARS, fye_month=12,
                        use_cache=True):
    """The one call a caller normally wants. Returns ~15 numbers, not 3,800."""
    primary = fetch_tiingo(ticker, years=years, use_cache=use_cache)
    if not primary["bars"]:
        raise PriceError(
            "Tiingo returned zero usable bars for %s." % ticker.upper())

    annual = annual_averages(primary["bars"], fye_month=fye_month)
    result = {
        "ok": True,
        "ticker": ticker.strip().upper(),
        "source": "tiingo",
        "source_note": (
            "Single source. No independent provider confirms these prices - "
            "state that when a valuation depends on them."),
        "adjustment": ADJUSTMENT,
        "adjustment_note": (
            "Split-adjusted close, NOT dividend-adjusted, and computed here "
            "from raw close plus splitFactor rather than taken on trust. "
            "Required by the Weiss yield model: a dividend-adjusted series "
            "inflates every historical yield and biases the estimate low."),
        "interval": "1d",
        "averaging": "mean of daily closes",
        "currency": primary.get("currency"),
        "fiscal_year_end_month": fye_month,
        "cached": primary.get("cached"),
        "annual": annual,
        "splits": primary["splits"],
        "split_factor_by_filing_date": {
            "table": split_factor_table(primary["splits"]),
            "rule": (
                "Puts an AS-FILED per-share figure from edgar_financials on "
                "today's share basis. KEY IT ON THAT FIGURE'S `filed` DATE, "
                "which edgar_financials returns per year - NOT on its fiscal "
                "year. Find the first row whose `filed_before` is later than "
                "the `filed` date and multiply by that row's `factor`; if no "
                "row matches, the factor is 1.0. An empty table means no "
                "split in the window. A SHARE COUNT is the inverse: divide "
                "it by the same factor. For EBIT, OpCF or FCF per share, "
                "divide the total by the as-filed count, then multiply."),
            "why": (
                "EDGAR restates the last few years in every 10-K, so the fact "
                "that wins for a year is usually filed about three years "
                "later and may ALREADY be post-split. Keying on the year "
                "rescales those figures twice and inflates the multiple by "
                "the full split ratio - MA 2013 came out at a P/E of 240 "
                "instead of 24. This replaces `as_filed_eps_factor`, which "
                "was year-keyed and wrong for the 2-3 years before every "
                "split."),
        },
        "verification": verify_split_arithmetic(primary["bars"],
                                                primary["splits"]),
    }

    incomplete = sorted(y for y, v in annual.items() if not v["complete"])
    if incomplete:
        partial = [y for y in incomplete if not annual[y]["reaches_year_end"]]
        stub = [y for y in incomplete if annual[y]["reaches_year_end"]]
        result["incomplete_years"] = incomplete
        result["incomplete_note"] = (
            "EXCLUDE these from any historical mean; they are fine for the "
            "current multiple. Still in progress (does not reach the fiscal "
            "year end): %s. Truncated by the start of the window (fewer than "
            "%d trading days): %s."
            % (partial or "none", MIN_DAILY_BARS_FOR_COMPLETE_YEAR,
               stub or "none"))
    return result


# --------------------------------------------------------------------------- #
# Dividends from the same daily rows - a second source next to EDGAR
#
# Every Tiingo daily row carries `divCash`: the cash dividend that went ex on
# that date, as paid, on that day's share basis. It arrives with the price
# fetch at no extra cost and was ignored until 2026-10-11. It is the only
# dividend history available for an IFRS filer (BCS), it gives Visa real
# annual totals where EDGAR tags one payment as the year (item 25), and it has
# the newest fiscal year weeks before its 10-K reaches EDGAR (AAPL FY2026).
#
# It is independent of EDGAR, NOT of the price source: same vendor, same fetch.

# A payment this many times the median of its neighbours is reported as a
# possible special. 2.5 rather than 2: semi-annual payers such as BCS pay a
# final dividend about twice the interim, and that is not a special.
OUTSIZED_PAYMENT_RATIO = 2.5
NEIGHBOUR_PAYMENTS = 4


# A large payment that comes back about a year later at a similar size is a
# pattern, not a special: UK issuers (BCS 2012-2016) paid three small
# quarterly dividends and one final about 3x their size, every year.
RECURRENCE_DAYS = (300, 430)
RECURRENCE_SIZE_RATIO = 1.5


def _recurs_a_year_apart(dividends, i):
    event = dividends[i]
    day = datetime.date.fromisoformat(event["ex_date"])
    low, high = RECURRENCE_DAYS
    for j, other in enumerate(dividends):
        if j == i or other["amount"] <= 0:
            continue
        gap = abs((datetime.date.fromisoformat(other["ex_date"]) - day).days)
        size = event["amount"] / other["amount"]
        if low <= gap <= high and \
                1 / RECURRENCE_SIZE_RATIO <= size <= RECURRENCE_SIZE_RATIO:
            return True
    return False


def outsized_payments(dividends, ratio=OUTSIZED_PAYMENT_RATIO,
                      neighbours=NEIGHBOUR_PAYMENTS):
    """Payments far above the ones around them. Flagged, never removed.

    Tiingo does not mark specials. A special left in an annual total inflates
    that year and every growth ratio that touches it, then shows up as a cut
    the year after. Which payments are specials is a fact about the issuer,
    so this only names candidates for the caller to confirm. A payment that
    recurs at a similar size about a year away is not flagged.
    """
    out = []
    amounts = [d["amount"] for d in dividends]
    for i, event in enumerate(dividends):
        around = (amounts[max(0, i - neighbours):i]
                  + amounts[i + 1:i + 1 + neighbours])
        if len(around) < 2:
            continue
        around.sort()
        mid = len(around) // 2
        median = (around[mid] if len(around) % 2
                  else (around[mid - 1] + around[mid]) / 2.0)
        if median > 0 and event["amount"] > ratio * median \
                and not _recurs_a_year_apart(dividends, i):
            out.append({"ex_date": event["ex_date"],
                        "amount": event["amount"],
                        "median_of_neighbours": round(median, 6)})
    return out


def annual_dividends(dividends, bars, fye_month=12):
    """Split-adjusted dividend total per fiscal year, by ex-date.

    A year is `complete` when the price series covers it end to end - the same
    test `annual_averages` applies - because a year the window only partly
    covers has a partial total that reads as a cut.
    """
    coverage = annual_averages(bars, fye_month=fye_month)
    out = {}
    for year, info in coverage.items():
        out[year] = {"total": 0.0, "payments": 0, "first_ex": None,
                     "last_ex": None, "complete": info["complete"]}
    for event in dividends:
        year = fiscal_year_of(event["ex_date"], fye_month)
        slot = out.setdefault(year, {"total": 0.0, "payments": 0,
                                     "first_ex": None, "last_ex": None,
                                     "complete": False})
        slot["total"] += event["amount"]
        slot["payments"] += 1
        slot["first_ex"] = slot["first_ex"] or event["ex_date"]
        slot["last_ex"] = event["ex_date"]
    for slot in out.values():
        slot["total"] = round(slot["total"], 6)
    return dict(sorted(out.items()))


def modal_payment_count(annual):
    """Most common payment count across complete years that paid anything."""
    counts = [v["payments"] for v in annual.values()
              if v["complete"] and v["payments"]]
    if not counts:
        return None
    return max(sorted(set(counts)), key=counts.count)


def dividend_series(ticker, years=DEFAULT_YEARS, fye_month=12, use_cache=True):
    """Annual dividends per fiscal year from the daily rows. ~15 numbers."""
    primary = fetch_tiingo(ticker, years=years, use_cache=use_cache)
    dividends = primary.get("dividends") or []
    annual = annual_dividends(dividends, primary["bars"], fye_month=fye_month)
    modal = modal_payment_count(annual)

    result = {
        "ok": True,
        "ticker": ticker.strip().upper(),
        "source": "tiingo",
        "source_note": (
            "Independent of EDGAR, not of the price source: same vendor and "
            "the same daily fetch as price_annual_averages. Use it to "
            "corroborate dividend_per_share_declared, and as the only "
            "dividend history where EDGAR has none (IFRS filers) or has not "
            "caught up (a fiscal year whose 10-K is not filed yet)."),
        "basis": "ex_date",
        "basis_note": (
            "Totals are summed by ex-dividend date. EDGAR's "
            "dividend_per_share_declared is by declaration, so a payment "
            "declared in one fiscal year and going ex in the next can move "
            "one payment across the boundary. Compare growth over several "
            "years, not one boundary year."),
        "adjustment": ADJUSTMENT,
        "adjustment_note": (
            "Amounts are split-adjusted to today's share basis, the same "
            "basis as price_annual_averages, so a yield is a plain division "
            "and no split factor applies. `as_paid` on each listed payment "
            "is the raw figure."),
        "currency": primary.get("currency"),
        "currency_note": (
            "USD as paid on the US listing. For an ADR the issuer declares "
            "in its home currency, so USD growth includes the exchange rate."),
        "fiscal_year_end_month": fye_month,
        "cached": primary.get("cached"),
        "pays_dividends": bool(dividends),
        "annual": annual,
        "modal_payments_per_year": modal,
        "last_payments": dividends[-4:],
        "splits": primary["splits"],
    }

    quality = {}
    if modal is not None:
        irregular = [y for y, v in annual.items()
                     if v["complete"] and v["payments"] != modal]
        if irregular:
            quality["irregular_payment_count"] = irregular
    flagged = outsized_payments(dividends)
    if flagged:
        quality["outsized_payments"] = flagged
    zero = [y for y, v in annual.items() if v["complete"] and not v["total"]]
    if dividends and zero:
        quality["zero_years"] = zero
    if quality:
        quality["_read_this"] = (
            "irregular_payment_count: complete years whose payment count "
            "differs from the usual one - a fifth payment pulled across the "
            "year boundary, an extra special, or a skipped payment; the total "
            "for that year is not comparable as it stands. outsized_payments: "
            "possible specials, more than %.1fx the median of the payments "
            "around them; confirm and exclude before any DGR or streak. "
            "zero_years: complete years with no payment - a suspension, or a "
            "year before the first dividend. A growth ratio through one is "
            "undefined." % OUTSIZED_PAYMENT_RATIO)
        result["quality"] = quality

    incomplete = sorted(y for y, v in annual.items() if not v["complete"])
    if incomplete:
        result["incomplete_years"] = incomplete
        result["incomplete_note"] = (
            "EXCLUDE these from any growth streak, DGR or historical yield: "
            "the price window does not cover the whole fiscal year, so the "
            "total is partial and reads as a cut. A year still in progress "
            "is included for the current rate only - use last_payments.")
    return result
