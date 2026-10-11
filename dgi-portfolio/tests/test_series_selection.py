"""Tests for how edgar_core chooses BETWEEN candidate (tag, unit) pairs.

`test_edgar_core.py` covers reducing one tag's facts to annual values. This
file covers the layer above it: which tag, and which unit, should answer the
concept at all. That layer did not exist until BACKLOG item 12 - the chain
returned the first tag with any data, uncompared - and it produced two silent
failures on real holdings:

- **JNJ**: `CommonStockDividendsPerShareDeclared` has ONE year (2021 = 1.01, a
  quarterly rate). `CommonStockDividendsPerShareCashPaid` has sixteen
  (2007-2025, annual). First-match returned the stub and never looked at the
  other, so a cornerstone holding's growth streak and DGR were unanswerable.
- **CB**: the same tag exists in CHF and in USD. First-match returned whichever
  unit the dict yielded first, so a CHF numerator could be divided by a USD
  price with nothing raised anywhere.

The JNJ numbers below are real, read from the live `edgar_financials` tool on
2026-08-29 - including the interior gaps at 2009, 2015 and 2020, which are
genuine absences in the filer's data and which no ranking can repair. The CB
fixture is representative of the multi-unit shape, not a transcript: the live
tool reports only the unit it chose, so the full unit list was never observable
from outside. That is itself part of what `alternatives` now fixes.
"""

import os
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp"))

import edgar_core  # noqa: E402


# --------------------------------------------------------------------------- #
# Fixture helpers


def year_fact(year, val):
    """One annual duration fact, framed the way SEC frames a full year."""
    return {"start": "%d-01-01" % year, "end": "%d-12-31" % year, "val": val,
            "form": "10-K", "fp": "FY", "filed": "%d-02-20" % (year + 1),
            "frame": "CY%d" % year}


def series(values_by_year):
    return [year_fact(y, v) for y, v in sorted(values_by_year.items())]


def facts(*tag_specs):
    """facts(("Tag", "USD", {2025: 1.0}), ...) -> a companyfacts-shaped dict."""
    us_gaap = {}
    for tag, unit, values in tag_specs:
        us_gaap.setdefault(tag, {"units": {}})["units"][unit] = series(values)
    return {"facts": {"us-gaap": us_gaap}}


DECLARED = "CommonStockDividendsPerShareDeclared"
CASHPAID = "CommonStockDividendsPerShareCashPaid"

# Real, from the live tool on 2026-08-29. Note the missing 2009, 2015, 2020.
JNJ_CASHPAID = {2007: 1.62, 2008: 1.795, 2010: 1.93, 2011: 2.11, 2012: 2.4,
                2013: 2.59, 2014: 2.76, 2016: 2.95, 2017: 3.32, 2018: 3.54,
                2019: 3.75, 2021: 3.98, 2022: 4.19, 2023: 4.7, 2024: 4.91,
                2025: 5.14}
JNJ_DECLARED = {2021: 1.01}


class FrozenYear(unittest.TestCase):
    """Staleness is measured against today, so today has to be pinned."""

    YEAR = 2026

    def setUp(self):
        self._real = edgar_core._current_year
        edgar_core._current_year = lambda: self.YEAR

    def tearDown(self):
        edgar_core._current_year = self._real


# --------------------------------------------------------------------------- #


class JohnsonAndJohnson(FrozenYear):
    """The case that made this item dangerous rather than merely untidy."""

    def setUp(self):
        FrozenYear.setUp(self)
        self.facts = facts((DECLARED, "USD/shares", JNJ_DECLARED),
                           (CASHPAID, "USD/shares", JNJ_CASHPAID))
        self.got = edgar_core.series_for_concept(
            self.facts, "dividend_per_share_declared")

    def test_sixteen_years_beats_the_one_year_stub(self):
        self.assertEqual(self.got["tag"], CASHPAID)
        self.assertEqual(len(self.got["annual"]), 16)
        self.assertEqual(min(self.got["annual"]), 2007)
        self.assertEqual(max(self.got["annual"]), 2025)

    def test_the_first_tag_in_the_chain_does_not_win_on_position_alone(self):
        # This is the regression guard. DECLARED is listed first in CONCEPTS;
        # reverting to first-match makes it win again and fails here.
        self.assertNotEqual(self.got["tag"], DECLARED)

    def test_the_loser_is_reported_not_discarded(self):
        alts = self.got["alternatives"]
        self.assertEqual(len(alts), 1)
        self.assertEqual(alts[0]["tag"], DECLARED)
        self.assertEqual(alts[0]["years"], 1)
        self.assertEqual(alts[0]["last_year"], 2021)

    def test_real_interior_gaps_are_reported_not_hidden(self):
        # 2009, 2015 and 2020 are genuinely absent from JNJ's own filings.
        # Ranking cannot invent them; `quality` has to say so.
        self.assertEqual(self.got["quality"]["interior_gaps"],
                         [2009, 2015, 2020])

    def test_a_fresh_series_is_not_also_flagged_stale(self):
        self.assertNotIn("stale", self.got["quality"])

    def test_the_two_tags_are_different_bases_not_just_different_lengths(self):
        # Declared 2021 = 1.01 is a quarterly rate; CashPaid 2021 = 3.98 is
        # annual. So first-match did not merely lose history - it could
        # silently change what the number MEANS. Worth a test of its own.
        self.assertEqual(JNJ_DECLARED[2021], 1.01)
        self.assertEqual(JNJ_CASHPAID[2021], 3.98)
        self.assertGreater(JNJ_CASHPAID[2021], JNJ_DECLARED[2021] * 3)


class Currency(FrozenYear):
    def test_usd_beats_non_usd_for_the_same_tag(self):
        got = edgar_core.series_for_concept(
            facts((DECLARED, "CHF", {2009: 1.26, 2015: 2.56}),
                  (DECLARED, "USD/shares", {2024: 3.64, 2025: 3.88})),
            "dividend_per_share_declared")
        self.assertEqual(got["unit"], "USD/shares")
        self.assertNotIn("non_usd_unit", got.get("quality", {}))

    def test_usd_wins_even_when_the_non_usd_series_is_longer(self):
        # Length must not rescue a wrong unit: the multiple is wrong either way.
        got = edgar_core.series_for_concept(
            facts((DECLARED, "CHF", dict((y, 1.0) for y in range(2010, 2026))),
                  (DECLARED, "USD/shares", {2025: 3.88})),
            "dividend_per_share_declared")
        self.assertEqual(got["unit"], "USD/shares")

    def test_a_share_count_is_not_flagged_for_its_unit(self):
        # BACKLOG item 20, found by running company-analysis on MA. `shares` is
        # the correct unit for a share count and says nothing about currency;
        # flagging it was noise, and noise is how a quality field gets ignored.
        got = edgar_core.series_for_concept(
            facts(("WeightedAverageNumberOfDilutedSharesOutstanding", "shares",
                   {2024: 927000000, 2025: 906000000})), "shares_diluted")
        self.assertEqual(got["unit"], "shares")
        self.assertNotIn("quality", got)

    def test_the_exemption_is_for_counts_only_not_for_any_non_usd_unit(self):
        # The narrow scope is the point. CHF must still be flagged, and so must
        # a unit nobody has measured yet - silence there would be worse than a
        # false positive, because a wrong multiple is a wrong number.
        for unit in ("CHF", "CHF/shares", "pure"):
            got = edgar_core.series_for_concept(
                facts((DECLARED, unit, {2024: 1.0, 2025: 1.1})),
                "dividend_per_share_declared")
            self.assertEqual(got["quality"]["non_usd_unit"], unit, unit)

    def test_a_share_count_still_reports_its_other_defects(self):
        # Exempting the unit must not exempt the series. Gaps and zeros in a
        # share count break the same arithmetic they always did.
        got = edgar_core.series_for_concept(
            facts(("WeightedAverageNumberOfDilutedSharesOutstanding", "shares",
                   {2022: 971000000, 2024: 927000000, 2025: 0})),
            "shares_diluted")
        self.assertEqual(got["quality"]["interior_gaps"], [2023])
        self.assertEqual(got["quality"]["zero_values"], [2025])
        self.assertNotIn("non_usd_unit", got["quality"])

    def test_a_non_usd_winner_is_flagged_when_nothing_else_exists(self):
        got = edgar_core.series_for_concept(
            facts((DECLARED, "CHF", {2014: 2.47, 2015: 2.56})),
            "dividend_per_share_declared")
        self.assertEqual(got["unit"], "CHF")
        self.assertEqual(got["quality"]["non_usd_unit"], "CHF")

    def test_usd_shares_counts_as_usd(self):
        got = edgar_core.series_for_concept(
            facts((DECLARED, "USD/shares", {2025: 2.0})),
            "dividend_per_share_declared")
        self.assertEqual(got.get("quality", {}).get("non_usd_unit"), None)


class FreshnessIsAGateNotASort(FrozenYear):
    """The trap that makes a naive last_year sort worse than first-match."""

    def test_a_current_year_stub_does_not_beat_eighteen_years(self):
        stub = {2026: 9.99}
        long_run = dict((y, 1.0) for y in range(2008, 2026))   # 18y, ends 2025
        got = edgar_core.series_for_concept(
            facts(("Revenues", "USD", stub),
                  ("SalesRevenueNet", "USD", long_run)), "revenue")
        self.assertEqual(got["tag"], "SalesRevenueNet")
        self.assertEqual(len(got["annual"]), 18)

    def test_a_short_current_series_beats_a_long_dead_one(self):
        # The mirror image. Here the gap is wide enough that the dead series
        # fails the gate, and length must not rescue it.
        recent = {2024: 1.0, 2025: 1.1, 2026: 1.2}
        dead = dict((y, 1.0) for y in range(2000, 2016))       # 16y, ends 2015
        got = edgar_core.series_for_concept(
            facts(("Revenues", "USD", dead),
                  ("SalesRevenueNet", "USD", recent)), "revenue")
        self.assertEqual(got["tag"], "SalesRevenueNet")

    def test_one_year_behind_the_freshest_still_passes_the_gate(self):
        # Fiscal years land differently; a series ending last year is not dead.
        ends_2025 = dict((y, 1.0) for y in range(2015, 2026))  # 11y
        ends_2026 = {2026: 5.0}
        got = edgar_core.series_for_concept(
            facts(("Revenues", "USD", ends_2026),
                  ("SalesRevenueNet", "USD", ends_2025)), "revenue")
        self.assertEqual(got["tag"], "SalesRevenueNet")

    def test_the_gate_is_relative_to_the_freshest_candidate(self):
        # Every candidate dead: the least dead one still wins rather than the
        # function refusing to choose.
        got = edgar_core.series_for_concept(
            facts(("Revenues", "USD", {2001: 1.0}),
                  ("SalesRevenueNet", "USD", {2014: 1.0, 2015: 1.1})),
            "revenue")
        self.assertEqual(got["tag"], "SalesRevenueNet")
        self.assertEqual(got["quality"]["stale"]["last_year"], 2015)


class QualityReporting(FrozenYear):
    def test_a_clean_series_gets_no_quality_and_no_alternatives(self):
        # The KO control. The fix must not add noise where there is none.
        got = edgar_core.series_for_concept(
            facts((DECLARED, "USD/shares",
                   dict((y, 1.0) for y in range(2016, 2026)))),
            "dividend_per_share_declared")
        self.assertNotIn("quality", got)
        self.assertNotIn("alternatives", got)

    def test_stale_reports_how_far_behind(self):
        got = edgar_core.series_for_concept(
            facts((DECLARED, "USD/shares", {2014: 2.4, 2015: 2.56})),
            "dividend_per_share_declared")
        self.assertEqual(got["quality"]["stale"],
                         {"last_year": 2015, "years_behind": 11})

    def test_last_year_is_not_stale(self):
        got = edgar_core.series_for_concept(
            facts((DECLARED, "USD/shares", {2024: 1.0, 2025: 1.1})),
            "dividend_per_share_declared")
        self.assertNotIn("quality", got)

    def test_a_single_value_series_reports_no_gaps(self):
        got = edgar_core.series_for_concept(
            facts((DECLARED, "USD/shares", {2019: 1.0})),
            "dividend_per_share_declared")
        self.assertNotIn("interior_gaps", got["quality"])

    def test_quality_carries_an_instruction_not_just_flags(self):
        got = edgar_core.series_for_concept(
            facts((DECLARED, "CHF", {2015: 2.56})),
            "dividend_per_share_declared")
        self.assertIn("growth streak", got["quality"]["_read_this"])


class ShareCountJumps(FrozenYear):
    """BACKLOG item 29, found by running company-analysis on AAPL.

    A share count is as filed, so the years filed before a split carry the old
    share basis. AAPL reads 5.25bn for FY2017 and 20.0bn for FY2018 - the 4:1
    split of 2020, not issuance. Read as a trend, criterion 9 scores backwards.
    """

    DILUTED = "WeightedAverageNumberOfDilutedSharesOutstanding"

    def series(self, values, unit="shares", concept="shares_diluted",
               tag=None):
        return edgar_core.series_for_concept(
            facts((tag or self.DILUTED, unit, values)), concept)

    def test_the_aapl_split_is_flagged_with_its_ratio(self):
        got = self.series({2016: 5500281000, 2017: 5251692000,
                           2018: 20000435000, 2019: 18595651000})
        self.assertEqual(got["quality"]["count_jumps"],
                         [{"year": 2018, "ratio": 3.808}])
        self.assertIn("DIVIDE", got["quality"]["_read_this"])

    def test_a_reverse_split_is_flagged_too(self):
        got = self.series({2024: 800000000, 2025: 100000000})
        self.assertEqual(got["quality"]["count_jumps"][0]["year"], 2025)

    def test_ordinary_buybacks_and_issuance_stay_quiet(self):
        # 2-5% a year either way is the normal life of a share count.
        got = self.series({2022: 1000000000, 2023: 960000000,
                           2024: 1010000000, 2025: 980000000})
        self.assertNotIn("quality", got)

    def test_a_gap_year_is_not_compared_across(self):
        # Two years apart is not one year's move; interior_gaps reports it.
        got = self.series({2022: 1000000000, 2024: 4000000000,
                           2025: 3950000000})
        self.assertNotIn("count_jumps", got["quality"])
        self.assertEqual(got["quality"]["interior_gaps"], [2023])

    def test_a_per_share_figure_is_never_checked_for_jumps(self):
        # EPS doubling is earnings, not a split - only counts are in scope.
        got = self.series({2024: 3.0, 2025: 7.0}, unit="USD/shares",
                          concept="eps_diluted", tag="EarningsPerShareDiluted")
        self.assertNotIn("quality", got)


class ZeroAndNegativeValues(FrozenYear):
    """BACKLOG item 15. A zero or a negative does not make the series wrong -
    it makes a growth RATIO undefined, and nothing said so.

    Both are common and both are real. INTU reports 0 for 2010-2011 and ZTS for
    2011-2012, genuine pre-dividend years. QCOM, MO, MA, GPC and ARE all carry
    real loss years in eps_diluted. The failure was silence, not the values.
    """

    def test_zero_years_are_listed(self):
        got = edgar_core.series_for_concept(
            facts((DECLARED, "USD/shares",
                   {2011: 0, 2012: 0, 2013: 0.267, 2014: 0.299})),
            "dividend_per_share_declared")
        self.assertEqual(got["quality"]["zero_values"], [2011, 2012])

    def test_negative_years_are_listed(self):
        got = edgar_core.series_for_concept(
            facts(("EarningsPerShareDiluted", "USD/shares",
                   {2023: 1.5, 2024: -3.39, 2025: 2.1})), "eps_diluted")
        self.assertEqual(got["quality"]["negative_values"], [2024])

    def test_both_at_once(self):
        got = edgar_core.series_for_concept(
            facts(("EarningsPerShareDiluted", "USD/shares",
                   {2022: 0, 2023: -1.0, 2024: 2.0, 2025: 3.0})), "eps_diluted")
        q = got["quality"]
        self.assertEqual(q["zero_values"], [2022])
        self.assertEqual(q["negative_values"], [2023])

    def test_a_clean_series_reports_neither(self):
        got = edgar_core.series_for_concept(
            facts((DECLARED, "USD/shares",
                   dict((y, 1.0) for y in range(2016, 2026)))),
            "dividend_per_share_declared")
        self.assertNotIn("quality", got)

    def test_a_float_zero_counts(self):
        got = edgar_core.series_for_concept(
            facts((DECLARED, "USD/shares", {2024: 0.0, 2025: 1.0})),
            "dividend_per_share_declared")
        self.assertEqual(got["quality"]["zero_values"], [2024])

    def test_a_missing_year_is_a_gap_not_a_zero(self):
        # The two must never be conflated: a gap means the filer reported
        # nothing, a zero means it reported no dividend. Different facts.
        got = edgar_core.series_for_concept(
            facts((DECLARED, "USD/shares", {2022: 1.0, 2024: 1.2, 2025: 1.3})),
            "dividend_per_share_declared")
        q = got["quality"]
        self.assertEqual(q["interior_gaps"], [2023])
        self.assertNotIn("zero_values", q)

    def test_the_note_explains_why_a_ratio_breaks(self):
        got = edgar_core.series_for_concept(
            facts((DECLARED, "USD/shares", {2024: 0, 2025: 1.0})),
            "dividend_per_share_declared")
        note = got["quality"]["_read_this"]
        self.assertIn("UNDEFINED", note)
        self.assertIn("do not treat them as data errors", note)

    def test_the_extra_note_appears_only_when_relevant(self):
        # A gapped but non-zero series must not carry the divide-by-zero
        # explanation - noise in a quality field is how a quality field starts
        # getting ignored.
        got = edgar_core.series_for_concept(
            facts((DECLARED, "USD/shares", {2022: 1.0, 2024: 1.2, 2025: 1.3})),
            "dividend_per_share_declared")
        self.assertNotIn("UNDEFINED", got["quality"]["_read_this"])


class ChainOrderAndFiltering(FrozenYear):
    def test_chain_position_breaks_a_genuine_tie(self):
        # Same unit, same length, same last year: the documented order decides,
        # so the result is deterministic rather than dict-ordering luck.
        got = edgar_core.series_for_concept(
            facts(("Revenues", "USD", {2025: 1.0}),
                  ("RevenueFromContractWithCustomerExcludingAssessedTax",
                   "USD", {2025: 2.0})), "revenue")
        self.assertEqual(
            got["tag"], "RevenueFromContractWithCustomerExcludingAssessedTax")

    def test_since_year_is_applied_before_ranking(self):
        # A candidate that empties out under the filter is not a candidate, and
        # must not appear in alternatives either.
        got = edgar_core.series_for_concept(
            facts((DECLARED, "USD/shares", {2010: 1.0}),
                  (CASHPAID, "USD/shares", {2024: 2.0, 2025: 2.1})),
            "dividend_per_share_declared", years=2020)
        self.assertEqual(got["tag"], CASHPAID)
        self.assertNotIn("alternatives", got)

    def test_nothing_reported_still_returns_guidance_not_a_guess(self):
        got = edgar_core.series_for_concept(
            facts(("Assets", "USD", {2025: 1.0})), "capex")
        self.assertEqual(got["annual"], {})
        self.assertIsNone(got["tag"])
        self.assertIn("edgar_tags", got["note"])

    def test_a_raw_tag_outside_any_chain_still_resolves(self):
        got = edgar_core.series_for_concept(
            facts(("GoodwillImpairmentLoss", "USD", {2025: 5.0})),
            "GoodwillImpairmentLoss")
        self.assertEqual(got["annual"], {2025: 5.0})


class FilingDates(FrozenYear):
    """`filed` per year - the key a split adjustment must use.

    Added for BACKLOG item 16. `_annual_from_unit` always read the filing date
    (it is how a restatement supersedes an original) and then discarded it,
    which is why nothing downstream could tell an already-post-split figure
    from a pre-split one.
    """

    def test_filed_is_returned_for_every_year(self):
        got = edgar_core.series_for_concept(
            facts((DECLARED, "USD/shares", {2024: 1.0, 2025: 1.1})),
            "dividend_per_share_declared")
        self.assertEqual(sorted(got["filed"]), sorted(got["annual"]))

    def test_filed_is_the_winning_filing_not_the_first(self):
        # A restatement supersedes the original, so the date reported must be
        # the restatement's - that is the whole point for item 16.
        entries = [
            {"start": "2019-01-01", "end": "2019-12-31", "val": 1.00,
             "frame": "CY2019", "form": "10-K", "fp": "FY",
             "filed": "2020-02-14"},
            {"start": "2019-01-01", "end": "2019-12-31", "val": 0.25,
             "frame": "CY2019", "form": "10-K", "fp": "FY",
             "filed": "2022-02-11"},
        ]
        f = {"facts": {"us-gaap": {DECLARED: {"units": {"USD/shares": entries}}}}}
        got = edgar_core.series_for_concept(f, "dividend_per_share_declared")
        self.assertEqual(got["annual"][2019], 0.25)
        self.assertEqual(got["filed"][2019], "2022-02-11")

    def test_the_plain_annual_view_is_unchanged(self):
        # _annual_from_unit is used by tests and callers that do not need the
        # date; splitting it must not have changed its shape.
        entries = [{"start": "2025-01-01", "end": "2025-12-31", "val": 3.0,
                    "frame": "CY2025", "form": "10-K", "fp": "FY",
                    "filed": "2026-02-11"}]
        self.assertEqual(edgar_core._annual_from_unit(entries), {2025: 3.0})
        self.assertEqual(edgar_core._annual_with_filed(entries),
                         {2025: ("2026-02-11", 3.0)})


if __name__ == "__main__":
    unittest.main(verbosity=2)
