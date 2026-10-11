"""Tests for check_missing_dividends.py.

Covers the case the script exists for: payments in a flex_dividends
pull with no row on the Dividends received sheet. The fixtures are
synthetic, plus the count-based matching edge case
a plain key-presence check would miss.
"""

import importlib.util
import os
import sys
import unittest

sys.dont_write_bytecode = True

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "skills", "portfolio-audit", "scripts",
                       "check_missing_dividends.py")

spec = importlib.util.spec_from_file_location("cmd", SCRIPT)
cmd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cmd)


def snapshot(rows):
    """rows: list of (year, month, ticker) as they'd display on the sheet."""
    display = [["Year", "Month", "Ticker", "Shares", "Gross per share",
                "Gross", "Net factor", "Net", "Type"]]
    for year, month, ticker in rows:
        display.append([str(year), str(month), ticker, "1", "1", "1",
                         "0.84", "0.84", "regular"])
    return {"sheets": {"Dividends received": {"displayValues": display}}}


def flex(rows):
    """rows: list of (pay_date, symbol, amount)."""
    return {
        "cols": ["pay_date", "symbol", "type", "amount", "currency"],
        "rows": [[d, s, "Dividends", a, "USD"] for d, s, a in rows],
    }


class MissingDetection(unittest.TestCase):
    def test_payments_missing_from_the_sheet_are_reported(self):
        # Three August 2026 payments were never entered.
        sheet_rows = [(2026, 7, "O"), (2026, 7, "VICI"), (2026, 7, "AFG")]
        flex_rows = [
            ("20260715", "O", 1.50), ("20260709", "VICI", 2.25),
            ("20260724", "AFG", 3.00),
            ("20260807", "MA", 1.10), ("20260814", "ABBV", 4.80),
            ("20260814", "O", 1.50),
        ]
        sheet_keys = cmd.load_sheet_keys(snapshot(sheet_rows))
        flex_entries = cmd.load_flex_rows(flex(flex_rows))
        missing = cmd.find_missing(sheet_keys, flex_entries)
        self.assertEqual(
            sorted((m["symbol"], m["pay_date"]) for m in missing),
            [("ABBV", "20260814"), ("MA", "20260807"), ("O", "20260814")])

    def test_fully_covered_reports_nothing(self):
        sheet_rows = [(2026, 8, "MA"), (2026, 8, "ABBV"), (2026, 8, "O")]
        flex_rows = [("20260807", "MA", 1.10), ("20260814", "ABBV", 4.80),
                     ("20260814", "O", 1.50)]
        sheet_keys = cmd.load_sheet_keys(snapshot(sheet_rows))
        flex_entries = cmd.load_flex_rows(flex(flex_rows))
        self.assertEqual(cmd.find_missing(sheet_keys, flex_entries), [])

    def test_matching_is_by_count_not_just_key_presence(self):
        # Two O payments the same month in Flex (IBKR split the payment);
        # the sheet only has one row for that key. The second must still be
        # reported missing -- a plain "is this key present" check would miss
        # it because the key already exists once.
        sheet_rows = [(2026, 8, "O")]
        flex_rows = [("20260814", "O", 1.35), ("20260814", "O", 1.36)]
        sheet_keys = cmd.load_sheet_keys(snapshot(sheet_rows))
        flex_entries = cmd.load_flex_rows(flex(flex_rows))
        missing = cmd.find_missing(sheet_keys, flex_entries)
        self.assertEqual(len(missing), 1)

    def test_a_flex_row_with_a_malformed_pay_date_is_skipped_not_crashed(self):
        flex_entries = cmd.load_flex_rows(flex([("2026081", "O", 1.50)]))
        self.assertEqual(flex_entries, [])

    def test_ticker_case_and_whitespace_are_normalised(self):
        sheet_keys = cmd.load_sheet_keys(snapshot([(2026, 8, " abbv ")]))
        flex_entries = cmd.load_flex_rows(flex([("20260814", "ABBV", 4.80)]))
        self.assertEqual(cmd.find_missing(sheet_keys, flex_entries), [])

    def test_load_sheet_keys_requires_the_payment_sheet(self):
        with self.assertRaises(SystemExit):
            cmd.load_sheet_keys({"sheets": {}})

    def test_load_flex_rows_requires_the_needed_columns(self):
        with self.assertRaises(SystemExit):
            cmd.load_flex_rows({"cols": ["symbol"], "rows": [["O"]]})

    def test_withholding_tax_rows_do_not_shadow_their_own_dividend(self):
        # Regression: flex_dividends defaults to include_withholding=true, and a
        # Withholding Tax row shares the exact same (year, month, ticker) key
        # as its sibling Dividends row. Order-dependent count matching let the
        # withholding row consume the sheet's one matching credit first,
        # making the real, already-on-the-sheet dividend report as "missing".
        cols = ["pay_date", "symbol", "type", "amount", "currency"]
        flex_dump = {"cols": cols, "rows": [
            ["20250909", "JNJ", "Withholding Tax", -0.60, "USD"],
            ["20250909", "JNJ", "Dividends", 6.0, "USD"],
        ]}
        sheet_keys = cmd.load_sheet_keys(snapshot([(2025, 9, "JNJ")]))
        flex_entries = cmd.load_flex_rows(flex_dump)
        # The Withholding Tax row must not even reach find_missing.
        self.assertEqual(len(flex_entries), 1)
        self.assertEqual(flex_entries[0]["type"], "Dividends")
        self.assertEqual(cmd.find_missing(sheet_keys, flex_entries), [])


if __name__ == "__main__":
    unittest.main()
