"""Tests for edgar_core's reduction of XBRL facts to annual series.

Every test runs offline against fixtures. The fixture shapes are copied from a
real ZTS `companyconcept` response fetched 2026-08-01, including the parts that
make naive parsing wrong: quarterly facts sitting beside annual ones, the same
fiscal year repeated across several filings, and year-to-date cumulative
figures that span more than one quarter but less than a year.
"""

import os
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp"))

import edgar_core  # noqa: E402


def duration(start, end, val, **kw):
    fact = {"start": start, "end": end, "val": val, "form": "10-K",
            "fp": "FY", "filed": kw.pop("filed", "2026-02-12")}
    fact.update(kw)
    return fact


def instant(end, val, **kw):
    fact = {"end": end, "val": val, "form": "10-K", "fp": "FY",
            "filed": kw.pop("filed", "2026-02-12")}
    fact.update(kw)
    return fact


def facts_with(tag, entries, unit="USD"):
    return {"facts": {"us-gaap": {tag: {"units": {unit: entries}}}}}


class AnnualSelection(unittest.TestCase):
    def test_quarters_are_excluded_annuals_kept(self):
        entries = [
            duration("2024-01-01", "2024-03-31", 1.31, frame="CY2024Q1", fp="Q1"),
            duration("2024-04-01", "2024-06-30", 1.37, frame="CY2024Q2", fp="Q2"),
            duration("2024-01-01", "2024-12-31", 5.47, frame="CY2024"),
            duration("2025-01-01", "2025-12-31", 6.02, frame="CY2025"),
        ]
        got = edgar_core._annual_from_unit(entries)
        self.assertEqual(got, {2024: 5.47, 2025: 6.02})

    def test_year_to_date_cumulative_is_not_annual(self):
        # 9-month cumulative figures span 273 days and would pass a naive
        # "longer than a quarter" test.
        entries = [
            duration("2025-01-01", "2025-09-30", 4.65, frame="CY2025Q3", fp="Q3"),
            duration("2025-01-01", "2025-12-31", 6.02, frame="CY2025"),
        ]
        self.assertEqual(edgar_core._annual_from_unit(entries), {2025: 6.02})

    def test_unframed_annual_is_recovered_by_day_span(self):
        # SEC does not frame every fact. A 10-K FY fact spanning ~a year still
        # counts, otherwise the most recent year is routinely missing.
        entries = [duration("2025-01-01", "2025-12-31", 6.02)]
        self.assertEqual(edgar_core._annual_from_unit(entries), {2025: 6.02})

    def test_unframed_quarter_is_not_recovered(self):
        entries = [duration("2025-01-01", "2025-03-31", 1.41, fp="Q1")]
        self.assertEqual(edgar_core._annual_from_unit(entries), {})

    def test_restatement_latest_filing_wins(self):
        entries = [
            duration("2025-01-01", "2025-12-31", 6.02, frame="CY2025",
                     filed="2026-02-12"),
            duration("2025-01-01", "2025-12-31", 5.90, frame="CY2025",
                     filed="2025-11-04"),
        ]
        self.assertEqual(edgar_core._annual_from_unit(entries), {2025: 6.02})

    def test_instant_facts_use_the_q4_frame(self):
        entries = [
            instant("2025-06-30", 900, frame="CY2025Q2I"),
            instant("2025-12-31", 1000, frame="CY2025Q4I"),
            instant("2024-12-31", 800, frame="CY2024Q4I"),
        ]
        self.assertEqual(edgar_core._annual_from_unit(entries),
                         {2024: 800, 2025: 1000})

    def test_duration_facts_win_over_instants_when_both_present(self):
        entries = [
            duration("2025-01-01", "2025-12-31", 6.02, frame="CY2025"),
            instant("2025-12-31", 1000, frame="CY2025Q4I"),
        ]
        self.assertEqual(edgar_core._annual_from_unit(entries), {2025: 6.02})

    def test_missing_values_are_skipped_not_zeroed(self):
        entries = [duration("2025-01-01", "2025-12-31", None, frame="CY2025")]
        self.assertEqual(edgar_core._annual_from_unit(entries), {})


class RealZoetisRows(unittest.TestCase):
    """Verbatim rows from the live ZTS EarningsPerShareDiluted response.

    Copied 2026-08-01, not invented. They carry the three shapes that break
    naive parsers: an annual fact filed BEFORE SEC framed it, the same year
    re-reported years later with a frame, a negative quarter, and a quarterly
    figure that was later restated.
    """

    ENTRIES = [
        {"start": "2013-01-01", "end": "2013-12-31", "val": 1.01,
         "fy": 2013, "fp": "FY", "form": "10-K", "filed": "2014-03-26"},
        {"start": "2013-01-01", "end": "2013-12-31", "val": 1.01,
         "fy": 2015, "fp": "FY", "form": "10-K", "filed": "2016-02-24",
         "frame": "CY2013"},
        {"start": "2015-03-30", "end": "2015-06-28", "val": -0.07,
         "fy": 2016, "fp": "FY", "form": "10-K", "filed": "2017-02-16",
         "frame": "CY2015Q2"},
        {"start": "2015-01-01", "end": "2015-12-31", "val": 0.68,
         "fy": 2017, "fp": "FY", "form": "10-K", "filed": "2018-02-15",
         "frame": "CY2015"},
        {"start": "2025-01-01", "end": "2025-03-31", "val": 1.41,
         "fy": 2025, "fp": "Q1", "form": "10-Q", "filed": "2025-05-06"},
        {"start": "2025-01-01", "end": "2025-03-31", "val": 1.34,
         "fy": 2026, "fp": "Q1", "form": "10-Q", "filed": "2026-05-07",
         "frame": "CY2025Q1"},
        {"start": "2025-01-01", "end": "2025-12-31", "val": 6.02,
         "fy": 2025, "fp": "FY", "form": "10-K", "filed": "2026-02-12",
         "frame": "CY2025"},
        {"start": "2026-01-01", "end": "2026-03-31", "val": 1.42,
         "fy": 2026, "fp": "Q1", "form": "10-Q", "filed": "2026-05-07",
         "frame": "CY2026Q1"},
    ]

    def test_only_full_years_survive(self):
        got = edgar_core._annual_from_unit(self.ENTRIES)
        self.assertEqual(got, {2013: 1.01, 2015: 0.68, 2025: 6.02})

    def test_negative_quarter_does_not_become_a_year(self):
        # -0.07 is a real ZTS quarter. If it leaked through as an annual value
        # criterion 4 would read a loss year that never happened.
        self.assertNotIn(-0.07,
                         edgar_core._annual_from_unit(self.ENTRIES).values())

    def test_partial_2026_is_not_reported_as_a_year(self):
        self.assertNotIn(2026, edgar_core._annual_from_unit(self.ENTRIES))


class ConceptResolution(unittest.TestCase):
    def test_fallback_chain_picks_the_tag_the_filer_uses(self):
        # Revenues is first-choice for some filers and absent for others; the
        # chain must fall through rather than report nothing.
        facts = facts_with("RevenueFromContractWithCustomerExcludingAssessedTax",
                           [duration("2025-01-01", "2025-12-31", 9.3e9,
                                     frame="CY2025")])
        got = edgar_core.series_for_concept(facts, "revenue")
        self.assertEqual(got["tag"],
                         "RevenueFromContractWithCustomerExcludingAssessedTax")
        self.assertEqual(got["annual"], {2025: 9.3e9})

    def test_chain_order_is_respected(self):
        facts = {"facts": {"us-gaap": {
            "Revenues": {"units": {"USD": [
                duration("2025-01-01", "2025-12-31", 1, frame="CY2025")]}},
            "RevenueFromContractWithCustomerExcludingAssessedTax": {
                "units": {"USD": [
                    duration("2025-01-01", "2025-12-31", 2, frame="CY2025")]}},
        }}}
        # The contract-revenue tag is listed first in CONCEPTS, so it wins even
        # though Revenues also exists.
        self.assertEqual(edgar_core.series_for_concept(facts, "revenue")["tag"],
                         "RevenueFromContractWithCustomerExcludingAssessedTax")

    def test_a_raw_tag_can_be_requested_directly(self):
        facts = facts_with("GoodwillImpairmentLoss",
                           [duration("2025-01-01", "2025-12-31", 5,
                                     frame="CY2025")])
        got = edgar_core.series_for_concept(facts, "GoodwillImpairmentLoss")
        self.assertEqual(got["annual"], {2025: 5})

    def test_zoetis_dividend_tag_is_in_the_chain(self):
        # Regression: the first live call returned an empty series for
        # dividends_paid because ZTS reports PaymentsOfOrdinaryDividends, which
        # was not in the chain. Found through edgar_tags, added, tested.
        facts = facts_with("PaymentsOfOrdinaryDividends",
                           [duration("2025-01-01", "2025-12-31", 9.6e8,
                                     frame="CY2025")])
        got = edgar_core.series_for_concept(facts, "dividends_paid")
        self.assertEqual(got["tag"], "PaymentsOfOrdinaryDividends")
        self.assertEqual(got["annual"], {2025: 9.6e8})

    def test_declared_dividend_per_share_resolves(self):
        facts = facts_with("CommonStockDividendsPerShareDeclared",
                           [duration("2025-01-01", "2025-12-31", 2.00,
                                     frame="CY2025")], unit="USD/shares")
        got = edgar_core.series_for_concept(facts,
                                            "dividend_per_share_declared")
        self.assertEqual(got["tag"], "CommonStockDividendsPerShareDeclared")
        self.assertEqual(got["unit"], "USD/shares")

    def test_unreported_concept_returns_empty_with_guidance_not_a_guess(self):
        got = edgar_core.series_for_concept(facts_with("Assets", []), "capex")
        self.assertEqual(got["annual"], {})
        self.assertIsNone(got["tag"])
        self.assertIn("edgar_tags", got["note"])

    def test_since_year_filters(self):
        facts = facts_with("EarningsPerShareDiluted", [
            duration("2013-01-01", "2013-12-31", 1.01, frame="CY2013"),
            duration("2025-01-01", "2025-12-31", 6.02, frame="CY2025"),
        ], unit="USD/shares")
        got = edgar_core.series_for_concept(facts, "eps_diluted", years=2016)
        self.assertEqual(got["annual"], {2025: 6.02})
        self.assertEqual(got["unit"], "USD/shares")


class TagDiscovery(unittest.TestCase):
    """`edgar_tags` is the documented escape hatch when a concept will not
    resolve. Until 2026-08-29 it read `us-gaap` alone, so it answered
    `matched: 0` for BCS - a filer with 476 `ifrs-full` tags - which reads as
    "this company reports nothing". See BACKLOG item 17.

    Note for whoever changes this next: the old version of this class asserted
    only on `matched` and `len(tags)`, never on the tag strings, so it passed
    unchanged through a response-shape change it should have caught. Assert on
    the values.
    """

    US = {"facts": {"us-gaap": {
        "PaymentsOfDividendsCommonStock": {}, "Assets": {},
        "DividendsCommonStockCash": {}, "Revenues": {}}}}
    IFRS = {"facts": {"ifrs-full": {"WeightedAverageShares": {},
                                    "ProfitLoss": {}},
                      "dei": {"EntityCommonStockSharesOutstanding": {}}}}

    def test_tags_come_back_namespace_qualified(self):
        got = edgar_core.available_tags(self.US, contains="dividend")
        self.assertEqual(got["matched"], 2)
        self.assertEqual(sorted(got["tags"]),
                         ["us-gaap:DividendsCommonStockCash",
                          "us-gaap:PaymentsOfDividendsCommonStock"])

    def test_an_ifrs_only_filer_is_not_reported_as_empty(self):
        # The BCS regression. Reading us-gaap alone returned matched: 0 here.
        got = edgar_core.available_tags(self.IFRS)
        self.assertEqual(got["matched"], 3)
        self.assertIn("ifrs-full:WeightedAverageShares", got["tags"])
        self.assertEqual(got["namespaces"], {"dei": 1, "ifrs-full": 2})

    def test_the_filter_matches_the_tag_not_the_namespace(self):
        # "gaap" appears in every us-gaap prefix; it must not match them all,
        # or the filter silently stops filtering.
        self.assertEqual(edgar_core.available_tags(self.US, contains="gaap")
                         ["matched"], 0)

    def test_the_note_says_which_tags_are_actually_usable(self):
        # A caller can pass a us-gaap tag straight back to edgar_financials
        # and cannot do that with an ifrs-full one. Saying so is the point.
        self.assertIn("us-gaap:", edgar_core.available_tags(self.IFRS)["note"])

    def test_truncation(self):
        got = edgar_core.available_tags(self.US, limit=2)
        self.assertTrue(got["truncated"])
        self.assertEqual(len(got["tags"]), 2)


class AbsenceDiagnosis(unittest.TestCase):
    """An empty series has three causes that used to share one message.

    The old note - "None of X is reported by this filer, use edgar_tags" - was
    correct for one of them and actively misleading for the other two, because
    in both of those no tag exists to be found. See BACKLOG items 11 and 17.
    """

    MARKER = edgar_core.EPS_COMPUTED_MARKER

    def note(self, facts, concept="eps_diluted"):
        return edgar_core.series_for_concept(facts, concept)["note"]

    def test_an_ifrs_filer_is_told_no_concept_will_ever_resolve(self):
        facts = {"facts": {"ifrs-full": {"ProfitLoss": {}}, "dei": {"X": {}}}}
        note = self.note(facts)
        self.assertIn("foreign private issuer", note)
        self.assertIn("ifrs-full", note)
        # The point of the whole message: do not read an absent source as a
        # bad company. A BCS run otherwise scores something like 12/21.
        self.assertIn("absent, not the performance", note)

    def test_dimensioned_eps_is_named_as_unrecoverable(self):
        # Visa: 626 us-gaap tags, no EPS tag, but the antidilutive-securities
        # tag is there - which cannot exist unless EPS is computed.
        facts = {"facts": {"us-gaap": {self.MARKER: {}, "Assets": {}}}}
        note = self.note(facts)
        self.assertIn("per share class", note)
        self.assertIn("No tag chain can recover these", note)
        # It must NOT send the reader to edgar_tags here: that hunt cannot
        # succeed, and sending them is the bug being fixed.
        self.assertNotIn("Use edgar_tags", note)

    def test_the_marker_alone_does_not_hijack_unrelated_concepts(self):
        facts = {"facts": {"us-gaap": {self.MARKER: {}, "Assets": {}}}}
        note = self.note(facts, "capex")
        self.assertNotIn("per share class", note)
        self.assertIn("edgar_tags", note)

    def test_an_ordinary_absence_still_points_at_the_escape_hatch(self):
        facts = {"facts": {"us-gaap": {"Assets": {}}}}
        note = self.note(facts, "capex")
        self.assertIn("edgar_tags", note)
        self.assertIn("us-gaap", note)

    def test_the_three_diagnoses_are_actually_different(self):
        # Guard against a future edit collapsing them back into one message.
        ifrs = self.note({"facts": {"ifrs-full": {"ProfitLoss": {}}}})
        dim = self.note({"facts": {"us-gaap": {self.MARKER: {}}}})
        plain = self.note({"facts": {"us-gaap": {"Assets": {}}}}, "capex")
        self.assertEqual(len({ifrs, dim, plain}), 3)


class UserAgent(unittest.TestCase):
    def test_missing_user_agent_is_a_clear_error_not_a_fake_default(self):
        # Inventing a UA is how an IP gets blocked by the SEC, and a block
        # looks like a code bug. Fail loudly instead.
        saved_env = os.environ.pop("DGI_EDGAR_USER_AGENT", None)
        saved_path = edgar_core.CONFIG_PATH
        edgar_core.CONFIG_PATH = "/nonexistent/edgar.json"
        try:
            with self.assertRaises(edgar_core.EdgarError) as ctx:
                edgar_core.load_user_agent()
            self.assertIn("contact address", str(ctx.exception))
        finally:
            edgar_core.CONFIG_PATH = saved_path
            if saved_env is not None:
                os.environ["DGI_EDGAR_USER_AGENT"] = saved_env

    def test_environment_variable_is_accepted(self):
        saved_path = edgar_core.CONFIG_PATH
        edgar_core.CONFIG_PATH = "/nonexistent/edgar.json"
        os.environ["DGI_EDGAR_USER_AGENT"] = "Tester test@example.com"
        try:
            self.assertEqual(edgar_core.load_user_agent(),
                             "Tester test@example.com")
        finally:
            edgar_core.CONFIG_PATH = saved_path
            os.environ.pop("DGI_EDGAR_USER_AGENT", None)


def quarter_report(end, val, frame, filed):
    """A 10-Q balance - fp Q1, the shape that carries a Dec 31 for V."""
    return instant(end, val, form="10-Q", fp="Q1", frame=frame, filed=filed)


class FiscalYearEndBalances(unittest.TestCase):
    """BACKLOG item 26. Shapes copied from Visa's stockholders' equity, 2026-10-04."""

    def test_a_september_filer_reads_september_not_december(self):
        entries = [
            instant("2025-09-30", 37909, frame="CY2025Q3I", filed="2025-11-06"),
            instant("2024-09-30", 39137, filed="2025-11-06"),
            quarter_report("2025-12-31", 38777, "CY2025Q4I", "2026-01-30"),
            quarter_report("2024-12-31", 38296, "CY2024Q4I", "2025-01-31"),
        ]
        self.assertEqual(edgar_core._annual_from_unit(entries),
                         {2024: 39137, 2025: 37909})

    def test_a_10q_comparative_fills_a_year_on_the_year_end(self):
        # Zoetis cash from 2018: the Dec 31 balance exists only as a 10-Q's
        # prior-year column. For a December filer that IS the year end.
        entries = [
            instant("2017-12-31", 1564, frame="CY2017Q4I"),
            quarter_report("2018-12-31", 1602, "CY2018Q4I", "2019-05-02"),
        ]
        self.assertEqual(edgar_core._annual_from_unit(entries),
                         {2017: 1564, 2018: 1602})

    def test_a_10q_comparative_off_the_year_end_does_not_fill(self):
        entries = [
            instant("2024-09-30", 16630, filed="2024-11-13"),
            quarter_report("2025-12-31", 19588, "CY2025Q4I", "2026-01-30"),
        ]
        self.assertEqual(edgar_core._annual_from_unit(entries), {2024: 16630})

    def test_a_52_week_year_end_drifting_by_days_still_counts(self):
        entries = [
            instant("2025-09-27", 500, filed="2025-11-01"),
            instant("2024-09-28", 450, filed="2024-11-01"),
            instant("2023-09-30", 400, filed="2023-11-01"),
        ]
        self.assertEqual(edgar_core._annual_from_unit(entries),
                         {2023: 400, 2024: 450, 2025: 500})

    def test_a_year_ending_jan_2_matches_a_dec_31_year_end(self):
        entries = [
            instant("2019-12-31", 100, filed="2020-02-20"),
            instant("2020-12-31", 110, filed="2021-02-20"),
            instant("2022-01-02", 120, filed="2022-02-20"),
        ]
        self.assertEqual(edgar_core._annual_from_unit(entries),
                         {2019: 100, 2020: 110, 2022: 120})

    def test_facts_without_form_or_fp_fall_back_to_the_frame(self):
        entries = [
            {"end": "2025-12-31", "val": 1000, "frame": "CY2025Q4I",
             "filed": "2026-02-12"},
            {"end": "2025-06-30", "val": 900, "frame": "CY2025Q2I",
             "filed": "2025-08-01"},
        ]
        self.assertEqual(edgar_core._annual_from_unit(entries), {2025: 1000})


def dps(start, end, val, accn, **kw):
    fact = duration(start, end, val, accn=accn, **kw)
    return fact


def quarters(fy_end_year, rate, accn):
    """Four quarters of an Oct-Sept year, all at one rate, in one filing."""
    y = fy_end_year
    bounds = [("%d-10-01" % (y - 1), "%d-12-31" % (y - 1)),
              ("%d-01-01" % y, "%d-03-31" % y),
              ("%d-04-01" % y, "%d-06-30" % y),
              ("%d-07-01" % y, "%d-09-30" % y)]
    return [dps(s, e, rate, accn, fp="FY") for s, e in bounds]


def annual(fy_end_year, val, accn, filed=None):
    return dps("%d-10-01" % (fy_end_year - 1), "%d-09-30" % fy_end_year, val,
               accn, frame="CY%d" % fy_end_year,
               filed=filed or "%d-11-15" % fy_end_year)


DPS_TAG = "CommonStockDividendsPerShareCashPaid"


def dps_quality(entries, tag=DPS_TAG, extra=None):
    us_gaap = {tag: {"units": {"USD/shares": entries}}}
    us_gaap.update(extra or {})
    result = edgar_core.series_for_concept(
        {"facts": {"us-gaap": us_gaap}}, "dividend_per_share_declared")
    return result, (result.get("quality") or {}).get("per_payment_rate")


class PerPaymentRate(unittest.TestCase):
    """BACKLOG item 25. Visa tags one quarter's dividend as the annual figure."""

    def test_a_rate_proven_by_its_own_filings_quarters_is_flagged(self):
        entries = [annual(2020, 0.30, "A20")] + quarters(2020, 0.30, "A20")
        result, flag = dps_quality(entries)
        self.assertEqual(result["annual"], {2020: 0.30})  # never rewritten
        self.assertEqual(flag["confirmed_years"], [2020])
        self.assertEqual(flag["payments_per_year"], 4)

    def test_a_true_annual_total_is_not_flagged(self):
        entries = [annual(2020, 1.20, "A20")] + quarters(2020, 0.30, "A20")
        self.assertIsNone(dps_quality(entries)[1])

    def test_quarters_from_another_filing_prove_nothing(self):
        # NextEra 2018: 1.11 is a split-restated annual, and the 4.44 of
        # quarters it "matches" came from a pre-split filing.
        entries = [annual(2018, 1.11, "LATER")] + quarters(2018, 1.11, "EARLIER")
        self.assertIsNone(dps_quality(entries)[1])

    def test_the_flag_walks_to_neighbours_on_the_same_basis(self):
        entries = ([annual(2020, 0.30, "A20")] + quarters(2020, 0.30, "A20")
                   + [annual(2021, 0.32, "A21"), annual(2022, 0.375, "A22"),
                      annual(2019, 0.25, "A19")])
        flag = dps_quality(entries)[1]
        self.assertEqual(flag["years"], [2019, 2020, 2021, 2022])
        self.assertEqual(flag["confirmed_years"], [2020])

    def test_the_walk_stops_at_a_four_fold_jump(self):
        # A year that really is an annual total sits ~4x above the rate.
        entries = ([annual(2020, 0.30, "A20")] + quarters(2020, 0.30, "A20")
                   + [annual(2021, 1.28, "A21")])
        self.assertEqual(dps_quality(entries)[1]["years"], [2020])

    def test_the_walk_crosses_a_gap_measured_per_year(self):
        # Visa has no 2018: 0.165 -> 0.25 over two years is +23% a year.
        entries = ([annual(2019, 0.25, "A19")] + quarters(2019, 0.25, "A19")
                   + [annual(2017, 0.165, "A17")])
        self.assertEqual(dps_quality(entries)[1]["years"], [2017, 2019])

    def test_a_sibling_tags_proof_counts_when_the_value_matches(self):
        sibling = {"CommonStockDividendsPerShareCashPaid": {"units": {
            "USD/shares": [annual(2020, 0.30, "A20")] + quarters(2020, 0.30, "A20")}}}
        longer = [annual(y, v, "D%d" % y) for y, v in
                  ((2016, 0.14), (2017, 0.165), (2019, 0.25), (2020, 0.30))]
        result, flag = dps_quality(longer, tag="CommonStockDividendsPerShareDeclared",
                                   extra=sibling)
        self.assertEqual(result["tag"], "CommonStockDividendsPerShareDeclared")
        self.assertEqual(flag["confirmed_years"], [2020])

    def test_a_sibling_on_another_basis_is_not_applied(self):
        sibling = {"CommonStockDividendsPerShareCashPaid": {"units": {
            "USD/shares": [annual(2020, 1.20, "A20")] + quarters(2020, 1.20, "A20")}}}
        longer = [annual(y, v, "D%d" % y) for y, v in
                  ((2018, 0.21), (2019, 0.25), (2020, 0.30))]
        flag = dps_quality(longer, tag="CommonStockDividendsPerShareDeclared",
                           extra=sibling)[1]
        self.assertIsNone(flag)

    def test_the_instruction_explains_what_to_multiply(self):
        entries = [annual(2020, 0.30, "A20")] + quarters(2020, 0.30, "A20")
        result, _ = dps_quality(entries)
        self.assertTrue("payments_per_year" in result["quality"]["_read_this"])

    def test_eps_is_never_checked(self):
        # Quarterly EPS also sits inside annual EPS; only dividend tags qualify.
        us_gaap = {"EarningsPerShareDiluted": {"units": {"USD/shares":
                   [annual(2020, 0.30, "A20")] + quarters(2020, 0.30, "A20")}}}
        result = edgar_core.series_for_concept({"facts": {"us-gaap": us_gaap}},
                                               "eps_diluted")
        self.assertFalse("per_payment_rate" in (result.get("quality") or {}))


if __name__ == "__main__":
    unittest.main()
