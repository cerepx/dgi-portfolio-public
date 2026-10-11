"""Tests for av_core's reduction of Alpha Vantage statements to annual series.

Offline, against fixtures shaped like the live responses measured on
2026-10-11 (AAPL, V, ZTS). The three traps the module reports are each pinned
here: street EPS against GAAP, the year in progress listed as annual, and a
refusal that arrives as HTTP 200.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp"))

import av_core  # noqa: E402


def report(date, **fields):
    row = {"fiscalDateEnding": date, "reportedCurrency": "USD"}
    row.update({k: str(v) for k, v in fields.items()})
    return row


# Visa FY2024-2025 as Alpha Vantage returns it, values from the live probe.
V_INCOME = {"symbol": "V", "annualReports": [
    report("2025-09-30", totalRevenue=40000000000, netIncome=20058000000),
    report("2024-09-30", totalRevenue=35926000000, netIncome=19743000000)]}
V_BALANCE = {"symbol": "V", "annualReports": [
    report("2025-09-30", commonStockSharesOutstanding=1966000000,
           shortTermDebt=5569000000, longTermDebtNoncurrent="None"),
    report("2024-09-30", commonStockSharesOutstanding=2029000000,
           shortTermDebt=0, longTermDebtNoncurrent="None")]}
V_EARNINGS = {"symbol": "V",
              "annualEarnings": [
                  {"fiscalDateEnding": "2026-09-30", "reportedEPS": "9.8"},
                  {"fiscalDateEnding": "2025-09-30", "reportedEPS": "11.47"},
                  {"fiscalDateEnding": "2024-09-30", "reportedEPS": "10.05"}],
              "quarterlyEarnings": [
                  {"fiscalDateEnding": d, "reportedEPS": "3.0"} for d in (
                      "2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30",
                      "2025-06-30", "2025-03-31", "2024-12-31", "2024-09-30",
                      "2024-06-30", "2024-03-31", "2023-12-31")]}


class Payloads(unittest.TestCase):
    def test_a_premium_refusal_at_http_200_raises_with_its_text(self):
        # OVERVIEW on the free key, verbatim shape.
        text = json.dumps({"Information": "Thank you for using Alpha Vantage! "
                           "This is a premium endpoint."})
        with self.assertRaises(av_core.AvError) as caught:
            av_core.parse_payload(text, "OVERVIEW")
        self.assertIn("premium endpoint", str(caught.exception))

    def test_a_rate_limit_note_raises(self):
        with self.assertRaises(av_core.AvError):
            av_core.parse_payload(json.dumps({"Note": "5 calls per minute"}),
                                  "INCOME_STATEMENT")

    def test_an_empty_object_is_an_unknown_symbol(self):
        with self.assertRaises(av_core.AvError):
            av_core.parse_payload("{}", "INCOME_STATEMENT")

    def test_the_key_is_redacted_from_errors(self):
        self.assertEqual(av_core._redact("bad url ?apikey=SECRET1", "SECRET1"),
                         "bad url ?apikey=<redacted>")


class AnnualSeries(unittest.TestCase):
    def test_none_is_missing_not_zero_and_zero_stays_zero(self):
        values, _ = av_core.annual_field(V_BALANCE, "BALANCE_SHEET",
                                         "longTermDebtNoncurrent")
        self.assertEqual(values, {})
        values, _ = av_core.annual_field(V_BALANCE, "BALANCE_SHEET",
                                         "shortTermDebt")
        self.assertEqual(values, {2024: 0, 2025: 5569000000})

    def test_years_come_from_fiscal_date_ending_with_the_date_kept(self):
        values, dates = av_core.annual_field(V_INCOME, "INCOME_STATEMENT",
                                             "totalRevenue")
        self.assertEqual(values[2025], 40000000000)
        self.assertEqual(dates[2025], "2025-09-30")

    def test_the_year_in_progress_is_flagged(self):
        # V "2026" carries the fiscal year end, 2026-09-30, but only three
        # quarters of fiscal 2026 are reported.
        self.assertEqual(av_core.incomplete_earnings_years(V_EARNINGS), [2026])

    def test_a_year_labelled_with_a_quarter_date_is_flagged(self):
        # ZTS closes in December; "2026-09-30" is the latest quarter, not a
        # fiscal year end.
        data = {"annualEarnings": [
                    {"fiscalDateEnding": "2026-09-30", "reportedEPS": "3.4"},
                    {"fiscalDateEnding": "2025-12-31", "reportedEPS": "6.42"},
                    {"fiscalDateEnding": "2024-12-31", "reportedEPS": "5.92"}],
                "quarterlyEarnings": [
                    {"fiscalDateEnding": d, "reportedEPS": "1.6"} for d in (
                        "2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30",
                        "2025-06-30", "2025-03-31", "2024-12-31", "2024-09-30",
                        "2024-06-30", "2024-03-31")]}
        self.assertEqual(av_core.incomplete_earnings_years(data), [2026])

    def test_years_before_quarterly_coverage_are_not_flagged(self):
        # AAPL's annual EPS reaches 1996; its quarters start in 2006.
        data = {"annualEarnings": [
                    {"fiscalDateEnding": "1996-09-30", "reportedEPS": "-0.1"},
                    {"fiscalDateEnding": "2007-09-30", "reportedEPS": "0.2"}],
                "quarterlyEarnings": [
                    {"fiscalDateEnding": d, "reportedEPS": "0.05"} for d in
                    ("2007-09-30", "2007-06-30", "2007-03-31", "2006-12-31")]}
        self.assertEqual(av_core.incomplete_earnings_years(data), [])


class Financials(unittest.TestCase):
    FIXTURES = {"INCOME_STATEMENT": V_INCOME, "BALANCE_SHEET": V_BALANCE,
                "EARNINGS": V_EARNINGS}

    def setUp(self):
        self.calls = []
        self.original = av_core.fetch

        def fake_fetch(function, ticker, use_cache=True, key=None):
            self.calls.append(function)
            return self.FIXTURES[function], True
        av_core.fetch = fake_fetch

    def tearDown(self):
        av_core.fetch = self.original

    def test_visa_gets_a_gaap_eps_from_net_income_over_shares(self):
        got = av_core.financials("V", ["eps_from_net_income"])
        self.assertEqual(got["concepts"]["eps_from_net_income"]["annual"][2025],
                         10.2024)
        self.assertIn("GAAP", got["concepts"]["eps_from_net_income"]["note"])

    def test_street_eps_is_labelled_and_its_partial_year_flagged(self):
        got = av_core.financials("V", ["eps_reported"])["concepts"]["eps_reported"]
        self.assertEqual(got["annual"][2025], 11.47)
        self.assertIn("STREET EPS, not GAAP", got["note"])
        self.assertEqual(got["incomplete_years"], [2026])

    def test_shares_say_no_split_factor_applies(self):
        got = av_core.financials("V", ["shares_outstanding"])
        self.assertIn("do NOT apply", got["concepts"]["shares_outstanding"]["note"])

    def test_one_request_per_statement_however_many_concepts(self):
        av_core.financials("V", ["revenue", "net_income", "short_term_debt"])
        self.assertEqual(sorted(self.calls), ["BALANCE_SHEET", "INCOME_STATEMENT"])

    def test_a_count_concept_adds_earnings_for_the_basis_check(self):
        av_core.financials("V", ["revenue", "shares_outstanding",
                                 "eps_from_net_income"])
        self.assertEqual(sorted(self.calls),
                         ["BALANCE_SHEET", "EARNINGS", "INCOME_STATEMENT"])

    def test_since_year_drops_older_years(self):
        got = av_core.financials("V", ["revenue"], since_year=2025)
        self.assertEqual(list(got["concepts"]["revenue"]["annual"]), [2025])

    def test_a_raw_field_works(self):
        got = av_core.financials("V", ["INCOME_STATEMENT:netIncome"])
        self.assertEqual(got["concepts"]["INCOME_STATEMENT:netIncome"]["annual"][2024],
                         19743000000)

    def test_an_unknown_concept_is_refused_before_any_request(self):
        with self.assertRaises(av_core.AvError):
            av_core.financials("V", ["free_cash_flow"])
        self.assertEqual(self.calls, [])

    def test_an_empty_series_says_absence_not_zero(self):
        got = av_core.financials("V", ["BALANCE_SHEET:longTermDebtNoncurrent"])
        self.assertIn("absence, not zero",
                      got["concepts"]["BALANCE_SHEET:longTermDebtNoncurrent"]["empty_note"])


class CountBasisCheck(unittest.TestCase):
    """The basis check on the share count, from V's FY2011-2012.

    Alpha Vantage's count read 4.09bn and 3.86bn there, on another class
    basis, and nothing said so. Net income over it gave $0.89 against a
    reported $1.26; from FY2013 the two agree.
    """

    INCOME = {"annualReports": [
        report("2013-09-30", netIncome=4980000000),
        report("2011-09-30", netIncome=3650000000)]}
    BALANCE = {"annualReports": [
        report("2013-09-30", commonStockSharesOutstanding=2624000000),
        report("2011-09-30", commonStockSharesOutstanding=4088000000)]}
    EARNINGS = {"annualEarnings": [
        {"fiscalDateEnding": "2013-09-30", "reportedEPS": "1.98"},
        {"fiscalDateEnding": "2011-09-30", "reportedEPS": "1.26"}],
        "quarterlyEarnings": []}

    def test_the_off_basis_year_is_flagged_and_the_good_one_is_not(self):
        got = av_core.count_basis_check(self.INCOME, self.BALANCE, self.EARNINGS)
        self.assertEqual([row["year"] for row in got], [2011])
        self.assertEqual(got[0]["ratio"], 0.709)

    def test_a_year_in_progress_is_not_judged(self):
        # Three quarters of fiscal 2013 reported, so "2013" is still in progress.
        earnings = {"annualEarnings": [
                        {"fiscalDateEnding": "2013-09-30", "reportedEPS": "0.5"}],
                    "quarterlyEarnings": [
                        {"fiscalDateEnding": d, "reportedEPS": "0.4"} for d in (
                            "2013-06-30", "2013-03-31", "2012-12-31",
                            "2012-06-30", "2012-03-31")]}
        self.assertEqual(av_core.count_basis_check(
            self.INCOME, self.BALANCE, earnings), [])

    def test_a_loss_or_zero_street_eps_is_skipped_not_divided(self):
        earnings = {"annualEarnings": [
            {"fiscalDateEnding": "2011-09-30", "reportedEPS": "0"}],
            "quarterlyEarnings": []}
        self.assertEqual(av_core.count_basis_check(
            self.INCOME, self.BALANCE, earnings), [])

    def test_the_flag_rides_on_count_concepts_only_and_fetches_earnings(self):
        fixtures = {"INCOME_STATEMENT": self.INCOME,
                    "BALANCE_SHEET": self.BALANCE, "EARNINGS": self.EARNINGS}
        calls = []
        original = av_core.fetch

        def fake_fetch(function, ticker, use_cache=True, key=None):
            calls.append(function)
            return fixtures[function], True
        av_core.fetch = fake_fetch
        try:
            got = av_core.financials("V", ["shares_outstanding", "revenue",
                                           "net_income"])
        finally:
            av_core.fetch = original
        self.assertIn("EARNINGS", calls)
        flagged = got["concepts"]["shares_outstanding"]["quality"]
        self.assertEqual(flagged["count_basis_suspect"][0]["year"], 2011)
        self.assertIn("another basis", flagged["_read_this"])
        self.assertNotIn("quality", got["concepts"]["net_income"])


class CacheAndKey(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = (av_core.CACHE_DIR, av_core.CONFIG_PATH)
        av_core.CACHE_DIR = self.tmp
        av_core.CONFIG_PATH = os.path.join(self.tmp, "missing.json")

    def tearDown(self):
        av_core.CACHE_DIR, av_core.CONFIG_PATH = self.saved
        shutil.rmtree(self.tmp)

    def test_a_fresh_cache_file_needs_neither_key_nor_network(self):
        with open(os.path.join(self.tmp, "V_INCOME_STATEMENT.json"), "w") as fh:
            json.dump(V_INCOME, fh)
        data, cached = av_core.fetch("INCOME_STATEMENT", "v")
        self.assertTrue(cached)
        self.assertEqual(data["symbol"], "V")

    def test_a_missing_key_names_the_file_and_warns_off_the_conversation(self):
        with self.assertRaises(av_core.AvError) as caught:
            av_core.api_key()
        self.assertIn(av_core.CONFIG_PATH, str(caught.exception))
        self.assertIn("Never paste the key", str(caught.exception))


class Server(unittest.TestCase):
    def test_the_server_exposes_the_tool(self):
        import av_server
        self.assertEqual([t["name"] for t in av_server.TOOLS], ["av_financials"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
