"""Assertions about the SHIPPED `config/portfolio.json`, not a fixture.

Every other test in this suite builds its config in memory. That is why the
real file could drift out of step with the real sheet while 90 tests stayed
green - which is exactly what happened in BACKLOG item 10: item 5 turned
`Dividends received!F` from an ARRAYFORMULA spill into a manual column on the
live sheet, the config was never told, and from then on every audit reported a
CRITICAL that was not real.

**A test cannot see the Google Sheet.** What it CAN do is enforce the config's
own internal consistency, and pin the handful of facts that have already been
verified against the sheet by hand. Both classes are here, and the generic
invariants matter more than the pinned values: they catch the NEXT drift, not
only the one that has already been paid for.
"""

import json
import os
import unittest

CONFIG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "portfolio.json")

with open(CONFIG) as fh:
    CFG = json.load(fh)

SHEETS = CFG["sheets"]
DIVIDENDS = SHEETS["Dividends received"]


class GenericInvariants(unittest.TestCase):
    """Rules every sheet must satisfy, whatever the sheet is.

    These are the ones worth having. The pinned values below only prove that
    today's known drift is fixed; these catch tomorrow's.
    """

    def test_no_column_is_both_manual_and_a_spill_anchor(self):
        # The direct contradiction. Item 10 was exactly this: F sat in
        # spill_anchors while the sheet treated it as manual.
        for name, sheet in SHEETS.items():
            manual = set(sheet.get("manual_columns") or [])
            spilled = set(sheet.get("spill_anchors") or {})
            self.assertEqual(manual & spilled, set(),
                             "%s: column(s) declared both manual and spilled" % name)

    def test_every_spill_anchor_column_is_typed_as_a_spill(self):
        for name, sheet in SHEETS.items():
            for col in (sheet.get("spill_anchors") or {}):
                spec = (sheet.get("columns") or {}).get(col)
                self.assertIsNotNone(spec, "%s!%s has an anchor but no column" % (name, col))
                self.assertEqual(spec.get("type"), "arrayformula_spill",
                                 "%s!%s is an anchor but typed %r" % (name, col, spec.get("type")))

    def test_no_column_typed_as_a_spill_is_missing_its_anchor(self):
        # The mirror. A spill-typed column with no anchor cannot be checked at
        # all, so the check would go quiet rather than loud.
        for name, sheet in SHEETS.items():
            anchors = sheet.get("spill_anchors") or {}
            for col, spec in (sheet.get("columns") or {}).items():
                if spec.get("type") == "arrayformula_spill":
                    self.assertIn(col, anchors,
                                  "%s!%s is typed as a spill with no anchor" % (name, col))
                    self.assertEqual(spec.get("spill_anchor"), anchors[col])

    def test_a_manual_column_carries_no_spill_anchor_key(self):
        for name, sheet in SHEETS.items():
            for col in (sheet.get("manual_columns") or []):
                spec = (sheet.get("columns") or {}).get(col) or {}
                self.assertNotIn("spill_anchor", spec,
                                 "%s!%s is manual but keeps a spill_anchor" % (name, col))


class DividendsReceivedAfterItem5(unittest.TestCase):
    """Pinned facts, each verified against the live sheet by hand.

    `Dividends received!F2` is a deliberate literal since the gross convention
    changed to cash actually received (item 5). Re-read live 2026-09-05: F2
    holds no formula, G2 and H2 still hold ARRAYFORMULAs.
    """

    def test_F_is_not_a_spill_anchor_but_G_and_H_still_are(self):
        self.assertEqual(set(DIVIDENDS["spill_anchors"]), {"G", "H"})

    def test_F_is_manual(self):
        self.assertIn("F", DIVIDENDS["manual_columns"])

    def test_F_is_typed_as_a_plain_number(self):
        self.assertEqual(DIVIDENDS["columns"]["F"]["type"], "number")

    def test_the_append_rule_includes_F(self):
        # The dangerous half of item 10. This string is prose an agent reads
        # before appending a payment row, and it used to say the opposite of
        # the truth: omitting F now leaves a hole nothing fills.
        rule = DIVIDENDS["_append_rule"]
        self.assertIn("A:F and I", rule)
        self.assertNotIn("A:E and I ONLY", rule)

    def test_the_append_rule_still_protects_G_and_H(self):
        # Making the rule looser must not make it wrong in the other
        # direction: G and H are still spills and still must not be written.
        self.assertIn("G and H", DIVIDENDS["_append_rule"])


class MySharesLayout(unittest.TestCase):
    """The DGI flag moved to AA when a column was inserted after K on
    2026-07-31. The bridge cannot insert columns, so a future insert shifts
    everything again and this is the first thing that will be wrong."""

    def test_the_dgi_flag_is_in_AA(self):
        cols = SHEETS["MyShares"]["columns"]
        flagged = [c for c, spec in cols.items()
                   if spec.get("meaning") in ("dgi_flag", "is_dgi")]
        self.assertEqual(flagged, ["AA"], "DGI flag column moved: %r" % flagged)


if __name__ == "__main__":
    unittest.main(verbosity=2)
