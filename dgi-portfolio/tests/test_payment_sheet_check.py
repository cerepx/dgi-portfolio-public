"""Tests for the per-payment dividend sheet checks.

These exist because the sheet that feeds every dividend aggregate spent a week
with zero audit coverage, and the one thing that actually broke in that week --
an ARRAYFORMULA spill collapsed by literal writes -- was caught by a human
re-reading aggregates, not by a check.

Every test builds a workbook in memory. Nothing here touches the live sheet,
the bridge, or a file on disk.
"""

import os
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "skills", "portfolio-audit", "scripts"))

import openpyxl  # noqa: E402

import audit_formulas as af  # noqa: E402


SPILL = "=ARRAYFORMULA(IF(LEN($C$2:$C),$D$2:$D*$E$2:$E,))"

CONFIG = {
    "sheets": {
        "MyShares": {
            "role": "open_positions",
            "header_row": 1,
            "blocks": {"dgi": {"first_row": 2, "last_row": 3},
                       "non_dgi": {"first_row": 5, "last_row": 5}},
            "columns": {
                "B": {"name": "Ticker", "type": "text", "meaning": "ticker"},
                "D": {"name": "Nr actiuni", "type": "number",
                      "meaning": "quantity"},
                "N": {"name": "Div/actiune", "type": "number",
                      "meaning": "dividend_per_share"},
                "O": {"name": "Venit/An", "type": "formula",
                      "meaning": "annual_income"},
            },
        },
        "Dividends received": {
            "role": "dividend_payments",
            "header_row": 1,
            "first_data_row": 2,
            "spill_anchors": {"F": "F2", "G": "G2", "H": "H2"},
            "manual_columns": ["A", "B", "C", "D", "E", "I"],
            "columns": {
                "A": {"name": "Year", "type": "number",
                      "meaning": "payment_year"},
                "B": {"name": "Month", "type": "number",
                      "meaning": "payment_month"},
                "C": {"name": "Ticker", "type": "text", "meaning": "ticker"},
                "F": {"name": "Gross", "type": "arrayformula_spill",
                      "meaning": "gross_amount"},
                "G": {"name": "Net factor", "type": "arrayformula_spill",
                      "meaning": "net_factor"},
                "H": {"name": "Net", "type": "arrayformula_spill",
                      "meaning": "net_amount"},
                "I": {"name": "Type", "type": "text", "meaning": "payment_type",
                      "allowed": ["regular", "special"]},
            },
        },
    }
}


def build(payments, positions=(("KO", 4), ("O", 12)), spill=SPILL,
          spill_below=None):
    """A workbook with a positions sheet and a per-payment sheet.

    `payments` is a list of (year, month, ticker, type) tuples. Spilled columns
    get plain values, exactly as they arrive from a bridge snapshot: only the
    anchor carries a formula.
    """
    workbook = openpyxl.Workbook()
    shares = workbook.active
    shares.title = "MyShares"
    shares["B1"], shares["O1"] = "Ticker", "Venit/An"
    for index, (ticker, frequency) in enumerate(positions):
        row = 2 + index
        shares[f"B{row}"] = ticker
        shares[f"D{row}"] = 10
        shares[f"O{row}"] = f"=N{row}*{frequency}*D{row}"

    sheet = workbook.create_sheet("Dividends received")
    for col, title in zip("ABCDEFGHI",
                          ["Year", "Month", "Ticker", "Shares",
                           "Gross per share", "Gross", "Net factor", "Net",
                           "Type"]):
        sheet[f"{col}1"] = title

    for index, (year, month, ticker, kind) in enumerate(payments):
        row = 2 + index
        sheet[f"A{row}"], sheet[f"B{row}"] = year, month
        sheet[f"C{row}"], sheet[f"D{row}"] = ticker, 10
        sheet[f"E{row}"] = 0.5
        sheet[f"F{row}"] = 5.0          # spilled value, no formula
        sheet[f"G{row}"] = 0.84
        sheet[f"H{row}"] = 4.2
        sheet[f"I{row}"] = kind

    # All three spilled columns are anchored in row 2 on the real sheet.
    # Anchoring only F would make every healthy fixture report G and H broken.
    sheet["F2"] = spill
    sheet["G2"] = "=ARRAYFORMULA(IF(LEN($C$2:$C),VLOOKUP($A$2:$A,$K:$L,2),))"
    sheet["H2"] = "=ARRAYFORMULA(IF(LEN($C$2:$C),$F$2:$F*$G$2:$G,))"
    if spill_below:
        for cell, value in spill_below.items():
            sheet[cell] = value
    return workbook


def four_quarters(ticker, kind="regular"):
    return [(2025, 10, ticker, kind), (2026, 1, ticker, kind),
            (2026, 4, ticker, kind), (2026, 7, ticker, kind)]


def twelve_months(ticker):
    out = []
    for offset in range(12):
        stamp = (2025 * 12 + 7) + offset
        out.append((stamp // 12, stamp % 12 + 1, ticker, "regular"))
    return out


def run(workbook, check=None):
    report = af.Report()
    for fn in ([check] if check else af.CHECKS):
        fn(workbook, CONFIG, report)
    return report.sorted_findings()


def titles(findings, severity=None):
    return [f["title"] for f in findings
            if severity is None or f["severity"] == severity]


class SpillIntegrity(unittest.TestCase):
    def test_healthy_spill_is_silent(self):
        workbook = build(four_quarters("KO") + twelve_months("O"))
        self.assertEqual(titles(run(workbook, af.check_payment_sheet)), [])

    # BACKLOG item 18. A literal in the anchor and an empty anchor used to
    # produce the same sentence - "the spill is broken" - because the check
    # treats the config as ground truth. Only one of the two states actually
    # says that. The other is ambiguous, and item 10 was two weeks of it.

    def only(self, findings, severity=af.CRITICAL):
        found = [f for f in findings if f["severity"] == severity]
        self.assertEqual(len(found), 1, titles(findings))
        return found[0]

    def test_an_empty_anchor_is_an_unambiguous_break(self):
        # A column made manual on purpose carries a value in its first data
        # row, so nothing here is ambiguous.
        finding = self.only(run(build(four_quarters("KO"), spill=None),
                                af.check_payment_sheet))
        self.assertEqual(finding["title"],
                         "ARRAYFORMULA spill broken in column F")
        self.assertIn("real break", finding["evidence"])
        self.assertIn("clear every literal", finding["fix"])

    def test_a_literal_anchor_is_reported_as_ambiguous_not_as_a_break(self):
        # The 2026-07-31 incident and the item 10 false positive are the SAME
        # sheet state. The check cannot tell them apart and now says so.
        finding = self.only(run(build(four_quarters("KO"), spill=5.0),
                                af.check_payment_sheet))
        self.assertIn("one of the two is stale", finding["title"])
        self.assertIn("cannot tell you which", finding["evidence"])

    def test_the_ambiguous_case_never_tells_anyone_to_clear_the_column(self):
        # The payload of item 18. Following "clear every literal below" on a
        # deliberately manual column destroys every row of real data in it,
        # and nothing refills them. This assertion is the whole point.
        finding = self.only(run(build(four_quarters("KO"), spill=5.0),
                                af.check_payment_sheet))
        self.assertIn("DO NOT clear the column", finding["fix"])
        self.assertIn("config/portfolio.json", finding["fix"])

    def test_both_states_stay_critical(self):
        # Naming the ambiguity must not soften it. If the spill really did
        # break, the whole column is silently empty and that is still the most
        # expensive finding this audit can make.
        for spill in (None, 5.0):
            finding = self.only(run(build(four_quarters("KO"), spill=spill),
                                    af.check_payment_sheet))
            self.assertEqual(finding["severity"], af.CRITICAL, repr(spill))

    def test_the_two_states_do_not_share_a_title(self):
        empty = self.only(run(build(four_quarters("KO"), spill=None),
                              af.check_payment_sheet))
        literal = self.only(run(build(four_quarters("KO"), spill=5.0),
                                af.check_payment_sheet))
        self.assertNotEqual(empty["title"], literal["title"])

    def test_formula_inside_the_spill_range_is_serious(self):
        workbook = build(four_quarters("KO"),
                         spill_below={"F4": "=D4*E4"})
        self.assertIn("Formula written inside the spill range of column F",
                      titles(run(workbook, af.check_payment_sheet), af.SERIOUS))

    def test_empty_payment_sheet_is_reported(self):
        workbook = build([])
        self.assertIn("Per-payment sheet is empty",
                      titles(run(workbook, af.check_payment_sheet), af.SERIOUS))


class RowValidity(unittest.TestCase):
    def test_unknown_payment_type_is_serious(self):
        workbook = build(four_quarters("KO")[:3] +
                         [(2026, 7, "KO", "reglar")])
        self.assertIn("Unrecognised payment type in 1 row(s)",
                      titles(run(workbook, af.check_payment_sheet), af.SERIOUS))

    def test_impossible_month_is_serious(self):
        workbook = build([(2026, 13, "KO", "regular")])
        self.assertIn("Missing or impossible payment date in 1 row(s)",
                      titles(run(workbook, af.check_payment_sheet), af.SERIOUS))

    def test_ticker_absent_from_positions_is_a_warning(self):
        workbook = build(four_quarters("KO") + four_quarters("XYZ"))
        self.assertIn("1 ticker(s) not present in MyShares",
                      titles(run(workbook, af.check_payment_sheet), af.WARNING))

    def test_repeated_tickers_are_not_duplicate_positions(self):
        # Regression guard: adding the payment sheet to the config once turned
        # every ticker with a payment history into a CRITICAL "duplicate
        # position" - 12 of them in one run.
        workbook = build(twelve_months("O"))
        criticals = titles(run(workbook, af.check_tickers), af.CRITICAL)
        self.assertEqual(criticals, [])


class FrequencyVerification(unittest.TestCase):
    def test_matching_frequency_is_info_not_warning(self):
        workbook = build(four_quarters("KO") + twelve_months("O"))
        findings = run(workbook, af.check_hardcoded_frequency)
        self.assertEqual(titles(findings, af.WARNING), [])
        self.assertTrue(any("Payment frequency verified" in t
                            for t in titles(findings, af.INFO)))

    def test_mismatching_frequency_is_serious(self):
        # KO's formula says 4x but only two regular payments fall inside the
        # trailing year -- annual income is overstated twofold. The 2024 row
        # exists so KO counts as having a full year of history; without it the
        # ticker would be classed unverifiable instead, which is a different
        # verdict entirely.
        payments = [(2024, 1, "KO", "regular"),
                    (2025, 10, "KO", "regular"), (2026, 4, "KO", "regular")]
        workbook = build(payments + twelve_months("O"))
        findings = run(workbook, af.check_hardcoded_frequency)
        self.assertTrue(any("disagrees with payment history" in t
                            for t in titles(findings, af.SERIOUS)))

    def test_specials_do_not_inflate_the_count(self):
        # AFG's real pattern: four regular plus one annual special. Counting
        # the special would make it 5x and fake a mismatch.
        payments = four_quarters("KO") + [(2026, 2, "KO", "special")]
        workbook = build(payments + twelve_months("O"))
        findings = run(workbook, af.check_hardcoded_frequency)
        self.assertEqual(titles(findings, af.SERIOUS), [])

    def test_short_history_is_unverifiable_not_wrong(self):
        # A position bought two months ago must not be reported as a mismatch;
        # that failure mode is why a counted frequency was rejected.
        workbook = build(twelve_months("O") + [(2026, 7, "KO", "regular")])
        findings = run(workbook, af.check_hardcoded_frequency)
        self.assertEqual(titles(findings, af.SERIOUS), [])
        self.assertTrue(any("Not yet verifiable" in f["evidence"]
                            for f in findings))

    # BACKLOG item 21. The window used to be anchored on the newest payment
    # ANYWHERE in the sheet, so one ticker paying early in a month pushed the
    # window past another ticker's payment that was not due yet. Adding two
    # September-1 payments turned five correct rows into SERIOUS.

    def test_a_newer_payment_from_another_ticker_does_not_break_the_count(self):
        # The 2026-09-05 incident, reproduced. O pays monthly, twelve payments
        # ending 2026-07. A DIFFERENT ticker then pays on 2026-09 - V and ZTS
        # both pay on the 1st, earlier in the month than most.
        #
        # Under a sheet-wide window that pushed everyone to 2025-10..2026-09,
        # dropping O's 2025-08 and 2025-09 payments and leaving 10 against a
        # 12x multiplier: a SERIOUS on a position that is entirely correct.
        payments = (twelve_months("O") + four_quarters("KO")
                    + [(2026, 9, "ZTS", "regular")])
        findings = run(build(payments), af.check_hardcoded_frequency)
        self.assertEqual(titles(findings, af.SERIOUS), [],
                         "O pays 12x and its own twelve months hold 12")

    def test_each_ticker_is_counted_over_its_own_twelve_months(self):
        counts, _, windows = af.trailing_year_counts(
            [{"year": y, "month": m, "ticker": t, "type": "regular"}
             for y, m, t, _ in four_quarters("KO") + [(2026, 9, "ZTS", "regular")]])
        # KO's window ends at KO's newest payment, 2026-07, not at ZTS's 2026-09.
        self.assertEqual(counts["KO"], 4)
        self.assertEqual(windows["KO"], (2025 * 12 + 8, 2026 * 12 + 7))
        self.assertEqual(windows["ZTS"], (2025 * 12 + 10, 2026 * 12 + 9))

    def test_a_stale_sheet_still_does_not_shrink_the_count(self):
        # The original reason for anchoring on the data rather than on today.
        # Per-ticker anchoring must preserve it: a sheet last updated a year
        # ago still counts four quarters, not zero.
        counts, _, _ = af.trailing_year_counts(
            [{"year": y, "month": m, "ticker": "KO", "type": "regular"}
             for y, m in ((2020, 1), (2020, 4), (2020, 7), (2020, 10))])
        self.assertEqual(counts["KO"], 4)

    def test_a_real_mismatch_is_still_caught(self):
        # Naming the old false positive must not blunt the check. KO genuinely
        # paying twice against a 4x multiplier is still SERIOUS.
        payments = [(2024, 1, "KO", "regular"),
                    (2025, 10, "KO", "regular"), (2026, 4, "KO", "regular")]
        findings = run(build(payments + twelve_months("O")),
                       af.check_hardcoded_frequency)
        self.assertTrue(any("disagrees with payment history" in t
                            for t in titles(findings, af.SERIOUS)))

    def test_without_a_payment_sheet_it_falls_back_to_warning(self):
        config = {"sheets": {"MyShares": CONFIG["sheets"]["MyShares"]}}
        workbook = build(four_quarters("KO"))
        report = af.Report()
        af.check_hardcoded_frequency(workbook, config, report)
        self.assertIn("Payment frequency hardcoded for 2 position(s)",
                      titles(report.sorted_findings(), af.WARNING))


class HistoryShape(unittest.TestCase):
    def test_sumifs_column_is_not_parsed_as_inline_sums(self):
        # The false positive fixed on 2026-08-01: the digits of a cell
        # reference inside SUMIFS were counted as payment amounts.
        config = {"sheets": {
            "MyShares": dict(CONFIG["sheets"]["MyShares"],
                             columns=dict(CONFIG["sheets"]["MyShares"]["columns"],
                                          Q={"name": "Div platite",
                                             "type": "formula",
                                             "meaning": "dividends_received_net"})),
            "Dividends received": CONFIG["sheets"]["Dividends received"],
        }}
        workbook = build(four_quarters("KO"))
        workbook["MyShares"]["Q2"] = \
            "=SUMIFS('Dividends received'!$H:$H,'Dividends received'!$C:$C,B2)"

        report = af.Report()
        af.check_dividend_history_shape(workbook, config, report)
        found = titles(report.sorted_findings())
        self.assertIn("Dividend history is per-payment, not inline sums", found)
        self.assertFalse(any("inline sums" in t and "per-payment" not in t
                             for t in found))


if __name__ == "__main__":
    unittest.main()
