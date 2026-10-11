"""Tests for price_core's reduction of a daily series to annual averages.

Every test runs offline against fixtures. The shapes follow a real Tiingo
`/tiingo/daily/<t>/prices` response, including the parts that make naive
parsing wrong: `close` is the raw as-traded price rather than an adjusted one,
`splitFactor` sits on the row where the split takes effect, and `adjClose`
carries BOTH split and dividend adjustments so it must never become a price.

Two classes are worth reading before changing anything here. `TiingoSplitOnly`
encodes the MA/V/KO trap - split-adjusted prices against as-filed EDGAR EPS.
`SplitArithmeticVerification` encodes what a single-source design has instead
of a second opinion, after Yahoo and Stooq were removed for being walled.
"""

import datetime
import os
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp"))

import price_core  # noqa: E402


def row(date, close, adj_close, split_factor=1.0):
    return {"date": "%sT00:00:00.000Z" % date, "close": close,
            "adjClose": adj_close, "splitFactor": split_factor,
            "high": close, "low": close, "open": close, "volume": 1000}


class TiingoSplitOnly(unittest.TestCase):
    """We compute the split adjustment instead of trusting a vendor's word.

    The fixture is the MA shape: a 10:1 split partway through, raw closes on
    each side of it, and an `adjClose` that is split AND dividend adjusted.
    """

    ROWS = [
        row("2013-12-31", 800.0, 70.0),
        row("2014-01-21", 840.0, 73.5),
        row("2014-01-22", 84.0, 73.5, split_factor=10.0),
        row("2014-12-31", 86.0, 75.0),
    ]

    def test_pre_split_closes_are_divided_by_the_later_split(self):
        parsed = price_core.parse_tiingo_prices(self.ROWS)
        closes = {b["date"]: b["close"] for b in parsed["bars"]}
        self.assertEqual(closes["2013-12-31"], 80.0)
        self.assertEqual(closes["2014-01-21"], 84.0)
        self.assertEqual(closes["2014-01-22"], 84.0)
        self.assertEqual(closes["2014-12-31"], 86.0)

    def test_split_event_is_derived_from_the_factor_column(self):
        parsed = price_core.parse_tiingo_prices(self.ROWS)
        self.assertEqual(parsed["splits"],
                         [{"date": "2014-01-22", "ratio": 10.0, "label": "10:1"}])

    def test_adjclose_is_carried_but_never_becomes_the_close(self):
        parsed = price_core.parse_tiingo_prices(self.ROWS)
        for bar in parsed["bars"]:
            self.assertNotEqual(bar["close"], bar["adjclose"])

    def test_rows_arriving_out_of_order_are_sorted_before_adjusting(self):
        shuffled = [self.ROWS[2], self.ROWS[0], self.ROWS[3], self.ROWS[1]]
        parsed = price_core.parse_tiingo_prices(shuffled)
        closes = {b["date"]: b["close"] for b in parsed["bars"]}
        self.assertEqual(closes["2013-12-31"], 80.0)

    def test_reverse_split_gets_a_one_to_n_label(self):
        rows = [row("2020-01-01", 10.0, 10.0),
                row("2020-06-01", 80.0, 80.0, split_factor=0.125)]
        parsed = price_core.parse_tiingo_prices(rows)
        self.assertEqual(parsed["splits"][0]["label"], "1:8")

    def test_missing_split_factor_defaults_to_one(self):
        parsed = price_core.parse_tiingo_prices(
            [{"date": "2024-01-01T00:00:00.000Z", "close": 10.0,
              "adjClose": 9.0}])
        self.assertEqual(parsed["splits"], [])
        self.assertEqual(parsed["bars"][0]["close"], 10.0)

    def test_error_object_is_reported_not_parsed_as_rows(self):
        with self.assertRaises(price_core.PriceError):
            price_core.parse_tiingo_prices({"detail": "Not found"})

    def test_empty_response_raises(self):
        with self.assertRaises(price_core.PriceError):
            price_core.parse_tiingo_prices([])

    def test_adjustment_constant_is_split_only(self):
        self.assertEqual(price_core.ADJUSTMENT, "split_only")


class TokenHandling(unittest.TestCase):
    def test_token_never_appears_in_the_url(self):
        url = price_core.tiingo_prices_url("MA", years=15)
        self.assertIn("/tiingo/daily/MA/prices", url)
        self.assertNotIn("token", url.lower())

    def test_daily_not_resampled_so_split_factors_survive(self):
        self.assertNotIn("resampleFreq", price_core.tiingo_prices_url("MA"))

    def test_window_spans_the_requested_years(self):
        now = datetime.datetime(2026, 8, 3, tzinfo=datetime.timezone.utc)
        url = price_core.tiingo_prices_url("MA", years=15, now=now)
        self.assertIn("startDate=2011-", url)

    def test_missing_token_names_the_file_to_create(self):
        saved_config = price_core.CONFIG_PATH
        saved_env = os.environ.pop("DGI_TIINGO_TOKEN", None)
        price_core.CONFIG_PATH = "/nonexistent/prices.json"
        try:
            with self.assertRaises(price_core.PriceError) as caught:
                price_core.tiingo_token()
            self.assertIn("prices.json", str(caught.exception))
        finally:
            price_core.CONFIG_PATH = saved_config
            if saved_env is not None:
                os.environ["DGI_TIINGO_TOKEN"] = saved_env


class FiscalYears(unittest.TestCase):
    def test_calendar_year_is_the_default(self):
        self.assertEqual(price_core.fiscal_year_of("2024-08-15"), 2024)

    def test_july_filer_rolls_august_into_the_next_fiscal_year(self):
        # INTU closes in July: Aug 2023 - Jul 2024 is FY2024.
        self.assertEqual(price_core.fiscal_year_of("2023-08-01", 7), 2024)
        self.assertEqual(price_core.fiscal_year_of("2024-07-31", 7), 2024)
        self.assertEqual(price_core.fiscal_year_of("2024-08-01", 7), 2025)


class AnnualAveraging(unittest.TestCase):
    @staticmethod
    def bars(dates_and_closes):
        return [{"date": d, "close": c, "adjclose": None}
                for d, c in dates_and_closes]

    def test_average_is_the_mean_of_daily_closes(self):
        bars = self.bars([("2024-%02d-01" % m, float(m)) for m in range(1, 13)])
        annual = price_core.annual_averages(bars, min_bars=1)
        self.assertEqual(annual[2024]["average"], 6.5)
        self.assertEqual(annual[2024]["bars"], 12)
        self.assertEqual(annual[2024]["low"], 1.0)
        self.assertEqual(annual[2024]["high"], 12.0)

    def test_a_year_short_of_a_full_calendar_is_flagged_incomplete(self):
        bars = self.bars([("2026-%02d-01" % m, 10.0) for m in range(1, 4)])
        annual = price_core.annual_averages(bars)
        self.assertFalse(annual[2026]["complete"])

    def test_a_full_trading_year_is_complete(self):
        bars = self.bars([("2024-%02d-%02d" % (m, d), 10.0)
                          for m in range(1, 13) for d in range(1, 22)])
        annual = price_core.annual_averages(bars)
        self.assertTrue(annual[2024]["complete"])

    def test_a_year_still_in_progress_is_incomplete_however_many_bars(self):
        """Found live 2026-08-03: 145 bars cleared the 120 threshold and a
        seven-month year was reported complete. Bar count alone cannot see it.
        """
        bars = self.bars([("2026-%02d-%02d" % (m, d), 10.0)
                          for m in range(1, 8) for d in range(1, 22)])
        annual = price_core.annual_averages(bars)
        self.assertGreater(annual[2026]["bars"],
                           price_core.MIN_DAILY_BARS_FOR_COMPLETE_YEAR)
        self.assertFalse(annual[2026]["reaches_year_end"])
        self.assertFalse(annual[2026]["complete"])

    def test_a_holiday_weekend_at_year_end_does_not_make_a_year_partial(self):
        bars = self.bars([("2024-%02d-%02d" % (m, d), 10.0)
                          for m in range(1, 13) for d in range(1, 22)]
                         + [("2024-12-27", 10.0)])
        annual = price_core.annual_averages(bars)
        self.assertTrue(annual[2024]["reaches_year_end"])
        self.assertTrue(annual[2024]["complete"])

    def test_fiscal_year_end_date_follows_the_filer(self):
        self.assertEqual(price_core.fiscal_year_end_date(2024, 12),
                         datetime.date(2024, 12, 31))
        self.assertEqual(price_core.fiscal_year_end_date(2024, 7),
                         datetime.date(2024, 7, 31))
        self.assertEqual(price_core.fiscal_year_end_date(2024, 2),
                         datetime.date(2024, 2, 29))

    def test_a_july_filer_year_running_to_july_is_complete(self):
        bars = self.bars([("2023-%02d-%02d" % (m, d), 10.0)
                          for m in range(8, 13) for d in range(1, 22)]
                         + [("2024-%02d-%02d" % (m, d), 10.0)
                            for m in range(1, 8) for d in range(1, 22)])
        annual = price_core.annual_averages(bars, fye_month=7)
        self.assertTrue(annual[2024]["complete"])

    def test_fiscal_year_bucketing_moves_bars_between_years(self):
        bars = self.bars([("2023-09-01", 100.0), ("2024-06-01", 200.0)])
        calendar = price_core.annual_averages(bars, fye_month=12, min_bars=1)
        fiscal = price_core.annual_averages(bars, fye_month=7, min_bars=1)
        self.assertEqual(sorted(calendar), [2023, 2024])
        self.assertEqual(sorted(fiscal), [2024])
        self.assertEqual(fiscal[2024]["average"], 150.0)


class AsFiledEpsAlignment(unittest.TestCase):
    """The MA/V/KO trap, and the second trap hiding inside it.

    Trap one: split-adjusted prices divided by as-filed EDGAR EPS are wrong by
    the split factor. Known since item 1.

    Trap two, live and silent until 2026-08-29: the fix was keyed on the fiscal
    YEAR. EDGAR restates the last few years in every 10-K and `edgar_financials`
    keeps the latest filing, so the fact that wins for a year is usually filed
    about three years later - and for the 2-3 years before a split it is ALREADY
    post-split. Rescaling it again inflated the multiple by the whole split
    ratio. See BACKLOG item 16.

    Every filing date below is real, read out of the local EDGAR cache on
    2026-08-29 by `changesets/2026-08-29-item16-probe.py`.
    """

    MA = [{"date": "2014-01-22", "ratio": 10.0, "label": "10:1"}]
    KO = [{"date": "2012-08-13", "ratio": 2.0, "label": "2:1"}]
    NEE = [{"date": "2020-10-27", "ratio": 4.0, "label": "4:1"}]
    V = [{"date": "2015-03-19", "ratio": 4.0, "label": "4:1"}]

    def factor(self, splits, filed):
        return price_core.split_factor_for(
            price_core.split_factor_table(splits), filed)

    def test_mastercard_the_case_that_produced_a_pe_of_240(self):
        # FY2010 value 0.60 was filed 2013-02-14, before the split: rescale.
        self.assertEqual(self.factor(self.MA, "2013-02-14"), 0.1)
        # FY2011 value 0.06 was filed 2014-02-14, three weeks AFTER the split.
        # It is already on today's basis. A year key said 0.1 here and turned
        # a P/E of 24 into 240.
        self.assertEqual(self.factor(self.MA, "2014-02-14"), 1.0)

    def test_coca_cola_where_the_eps_step_was_invisible(self):
        # KO is why the seam cannot be found by looking at the numbers: its
        # dividend series steps by a clean 2x here and its EPS series by only
        # 0.86, because underlying EPS grew that year. The filing date does not
        # care.
        self.assertEqual(self.factor(self.KO, "2012-02-23"), 0.5)   # FY2009
        self.assertEqual(self.factor(self.KO, "2013-10-24"), 1.0)   # FY2010

    def test_nextera(self):
        self.assertEqual(self.factor(self.NEE, "2020-02-14"), 0.25)  # FY2017
        self.assertEqual(self.factor(self.NEE, "2021-02-12"), 1.0)   # FY2018

    def test_visa(self):
        self.assertEqual(self.factor(self.V, "2014-11-21"), 0.25)    # FY2012
        self.assertEqual(self.factor(self.V, "2015-11-20"), 1.0)     # FY2013

    def test_the_year_key_and_the_filing_key_disagree_and_that_is_the_bug(self):
        # Regression guard. Both of these are fiscal year 2011 for MA. A
        # year-keyed factor cannot tell them apart; that is precisely why it
        # was wrong. If someone reintroduces a year key, this fails.
        filed_before_split = self.factor(self.MA, "2013-02-14")
        filed_after_split = self.factor(self.MA, "2014-02-14")
        self.assertNotEqual(filed_before_split, filed_after_split)

    def test_two_splits_compound(self):
        splits = self.MA + self.V
        self.assertEqual(self.factor(splits, "2013-02-14"), 0.025)
        self.assertEqual(self.factor(splits, "2014-06-01"), 0.25)
        self.assertEqual(self.factor(splits, "2016-02-01"), 1.0)

    def test_table_is_ordered_oldest_cutoff_first(self):
        # The lookup takes the FIRST matching row, so order is load-bearing.
        table = price_core.split_factor_table(self.MA + self.V)
        self.assertEqual([r["filed_before"] for r in table],
                         ["2014-01-22", "2015-03-19"])

    def test_no_splits_gives_an_empty_table_and_a_no_op_factor(self):
        self.assertEqual(price_core.split_factor_table([]), [])
        self.assertEqual(self.factor([], "2020-01-01"), 1.0)

    def test_filed_exactly_on_the_split_date_is_treated_as_already_adjusted(self):
        # A documented choice, not an accident: the comparison is strict, so a
        # filing dated the same day as the split gets factor 1.0. No real case
        # has hit this - splits take effect after the close and 10-Ks are not
        # filed on split days - but the boundary must be somewhere and a future
        # reader should find it decided rather than emergent.
        self.assertEqual(self.factor(self.MA, "2014-01-22"), 1.0)
        self.assertEqual(self.factor(self.MA, "2014-01-21"), 0.1)


class SplitArithmeticVerification(unittest.TestCase):
    """What a single-source design has instead of a second provider.

    Our split-only series and the vendor's adjClose are both split-adjusted, so
    splits cancel in the ratio and only the dividend adjustment is left. That
    ratio must be 1.0 at the newest bar and non-increasing forward in time. A
    residual step at a split date is our error, and nothing else finds it.
    """

    @staticmethod
    def series(triples):
        return [{"date": d, "close": c, "adjclose": a} for d, c, a in triples]

    def clean(self):
        # Dividend adjustment shrinking smoothly to 1.0 at the right edge.
        bars = []
        for i in range(60):
            factor = 1.30 - 0.005 * i
            bars.append(("2020-%02d-%02d" % (i // 28 + 1, i % 28 + 1),
                         100.0, 100.0 / factor))
        return self.series(bars)

    def test_a_clean_series_verifies(self):
        report = price_core.verify_split_arithmetic(self.clean(), [])
        self.assertTrue(report["ok"])
        self.assertEqual(report["verdict"], "consistent")
        self.assertGreater(report["dividend_factor"], 1.0)

    def test_the_consistent_note_admits_it_is_not_a_second_source(self):
        report = price_core.verify_split_arithmetic(self.clean(), [])
        self.assertIn("not a second source", report["note"].lower())

    def test_ratio_rising_forward_in_time_is_caught(self):
        bars = self.clean()
        bars[40]["adjclose"] = bars[40]["adjclose"] / 1.5
        report = price_core.verify_split_arithmetic(bars, [])
        self.assertFalse(report["ok"])
        self.assertEqual(report["verdict"], "split_arithmetic_suspect")

    def test_newest_bar_must_have_our_price_equal_to_adjclose(self):
        bars = self.clean()
        bars[-1]["adjclose"] = bars[-1]["close"] / 1.25
        report = price_core.verify_split_arithmetic(bars, [])
        self.assertFalse(report["ok"])

    def test_a_step_left_at_a_split_date_is_named_as_our_error(self):
        bars = self.clean()
        split_date = bars[30]["date"]
        for bar in bars[:30]:
            bar["close"] = bar["close"] * 2.0   # split never applied on our side
        report = price_core.verify_split_arithmetic(
            bars, [{"date": split_date, "ratio": 2.0, "label": "2:1"}])
        self.assertFalse(report["ok"])
        self.assertTrue(report["split_steps"])

    def test_too_few_rows_is_reported_as_unverified_not_as_pass(self):
        report = price_core.verify_split_arithmetic(
            self.series([("2024-01-01", 10.0, 9.0)]), [])
        self.assertIsNone(report["ok"])
        self.assertEqual(report["verdict"], "unavailable")


class RemovedSources(unittest.TestCase):
    """Yahoo and Stooq were removed 2026-08-03 - both behind anti-bot walls.

    Kept as a test so a future session sees the removal was deliberate rather
    than reintroducing them as untried options. See BACKLOG item 1.
    """

    def test_no_yahoo_or_stooq_entry_points_survive(self):
        for name in ("fetch_yahoo", "fetch_stooq", "parse_yahoo_chart",
                     "parse_stooq_csv", "compare_annual", "yahoo_url",
                     "stooq_url", "ensure_yahoo_session"):
            self.assertFalse(hasattr(price_core, name),
                             "%s should have been removed" % name)


class DividendsFromDivCash(unittest.TestCase):
    """`divCash` on the same daily rows: a dividend source next to EDGAR.

    The split shape is AAPL's: a 4:1 split, with dividends on both sides, and
    a fiscal year ending in September. The special and the UK final are the
    two cases the `outsized_payments` flag must tell apart.
    """

    @staticmethod
    def drow(date, close, div=0.0, split_factor=1.0):
        r = row(date, close, close, split_factor)
        r["divCash"] = div
        return r

    def test_pre_split_dividend_is_divided_by_the_later_split(self):
        parsed = price_core.parse_tiingo_prices([
            self.drow("2020-08-07", 444.0, div=0.82),
            self.drow("2020-08-31", 129.0, split_factor=4.0),
            self.drow("2020-11-06", 118.0, div=0.205),
        ])
        self.assertEqual([d["amount"] for d in parsed["dividends"]],
                         [0.205, 0.205])
        self.assertEqual(parsed["dividends"][0]["as_paid"], 0.82)

    def test_dividend_on_the_split_row_is_already_post_split(self):
        parsed = price_core.parse_tiingo_prices([
            self.drow("2020-08-28", 500.0),
            self.drow("2020-08-31", 125.0, div=0.2, split_factor=4.0),
        ])
        self.assertEqual(parsed["dividends"][0]["amount"], 0.2)

    def test_missing_or_unreadable_divcash_is_no_dividend(self):
        rows = [row("2024-01-02", 10.0, 10.0), self.drow("2024-01-03", 10.0)]
        rows[1]["divCash"] = "n/a"
        self.assertEqual(price_core.parse_tiingo_prices(rows)["dividends"], [])

    def test_totals_follow_the_fiscal_year_of_the_ex_date(self):
        bars = [{"date": "2025-%02d-01" % m, "close": 1.0, "adjclose": None}
                for m in range(1, 13)]
        divs = [{"ex_date": "2025-08-11", "amount": 0.26, "as_paid": 0.26},
                {"ex_date": "2025-11-10", "amount": 0.26, "as_paid": 0.26}]
        annual = price_core.annual_dividends(divs, bars, fye_month=9)
        self.assertEqual(annual[2025]["total"], 0.26)
        self.assertEqual(annual[2026]["total"], 0.26)
        self.assertEqual(annual[2026]["first_ex"], "2025-11-10")

    def test_a_year_the_window_only_partly_covers_is_incomplete(self):
        bars = [{"date": "2026-%02d-01" % m, "close": 1.0, "adjclose": None}
                for m in range(1, 4)]
        divs = [{"ex_date": "2026-02-09", "amount": 0.5, "as_paid": 0.5}]
        annual = price_core.annual_dividends(divs, bars)
        self.assertFalse(annual[2026]["complete"])

    @staticmethod
    def events(pairs):
        return [{"ex_date": d, "amount": a, "as_paid": a} for d, a in pairs]

    def test_a_one_off_special_is_flagged(self):
        divs = self.events([("2024-02-01", 0.5), ("2024-05-01", 0.5),
                            ("2024-08-01", 3.0), ("2024-11-01", 0.5),
                            ("2025-02-01", 0.5)])
        flagged = price_core.outsized_payments(divs)
        self.assertEqual([f["ex_date"] for f in flagged], ["2024-08-01"])

    def test_a_large_final_that_recurs_every_year_is_not_a_special(self):
        # BCS 2012-2016: three small quarterlies and a final ~3x their size.
        divs = self.events([("2013-02-20", 0.21), ("2013-05-01", 0.065),
                            ("2013-08-01", 0.065), ("2013-11-01", 0.065),
                            ("2014-02-19", 0.23), ("2014-05-01", 0.065),
                            ("2014-08-01", 0.065)])
        self.assertEqual(price_core.outsized_payments(divs), [])

    def _series(self, rows, fye_month=12):
        parsed = price_core.parse_tiingo_prices(rows)
        parsed.update(cached=True, source="tiingo")
        original = price_core.fetch_tiingo
        price_core.fetch_tiingo = lambda *a, **k: parsed
        try:
            return price_core.dividend_series("TEST", fye_month=fye_month)
        finally:
            price_core.fetch_tiingo = original

    @staticmethod
    def year_of_rows(year, dividend_days=(), amount=0.25):
        out = []
        for m in range(1, 13):
            for d in range(1, 22):
                date = "%d-%02d-%02d" % (year, m, d)
                div = amount if (m, d) in dividend_days else 0.0
                r = row(date, 10.0, 10.0)
                r["divCash"] = div
                out.append(r)
        return out

    def test_a_fifth_payment_marks_the_year_irregular_and_stays_in_the_total(self):
        quarterly = ((2, 1), (5, 1), (8, 1), (11, 1))
        rows = (self.year_of_rows(2022, quarterly)
                + self.year_of_rows(2023, quarterly + ((12, 20),))
                + self.year_of_rows(2024, quarterly))
        result = self._series(rows)
        self.assertEqual(result["modal_payments_per_year"], 4)
        self.assertEqual(result["quality"]["irregular_payment_count"], [2023])
        self.assertEqual(result["annual"][2023]["total"], 1.25)

    def test_a_non_payer_reports_no_dividends_and_no_zero_years(self):
        result = self._series(self.year_of_rows(2024))
        self.assertFalse(result["pays_dividends"])
        self.assertNotIn("quality", result)

    def test_a_suspension_year_is_reported(self):
        quarterly = ((2, 1), (5, 1), (8, 1), (11, 1))
        rows = (self.year_of_rows(2019, quarterly) + self.year_of_rows(2020)
                + self.year_of_rows(2021, quarterly))
        result = self._series(rows)
        self.assertEqual(result["quality"]["zero_years"], [2020])

    def test_the_server_exposes_the_tool(self):
        import price_server
        self.assertIn("price_dividends",
                      [t["name"] for t in price_server.TOOLS])


if __name__ == "__main__":
    unittest.main(verbosity=2)
