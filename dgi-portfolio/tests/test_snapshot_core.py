"""Tests for snapshot_core, the read loop behind bridge_snapshot.

`call_bridge` is injected, so every one of these runs offline. That is the
point: the real transport needs the host's network and token, and a test that
needs those is a test that never runs.
"""

import os
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "mcp"))

import snapshot_core  # noqa: E402



# The real `structure` action returns ONLY the sheet list -- no name, no id.
# Those come from `ping`. A fake that mixed them up is exactly how the first
# version of this shipped snapshots with spreadsheet: null.
PING = {"ok": True, "spreadsheet": "ClaudePortofoliu", "id": "sheet-id",
        "writesAllowed": False}

STRUCTURE = {
    "ok": True,
    "sheets": [
        {"name": "MyShares", "rows": 62, "columns": 27, "hidden": False},
        {"name": "Jurnal", "rows": 37, "columns": 4, "hidden": False},
        {"name": "_DGI_Log", "rows": 1306, "columns": 8, "hidden": True},
        {"name": "_bk_MyShares_20260801-142057", "rows": 62, "columns": 27,
         "hidden": True},
        {"name": "Huge", "rows": 5000, "columns": 2, "hidden": False},
    ],
}


def fake_bridge(calls):
    """Record every call and answer with a minimal well-formed payload."""
    def call(action, payload=None):
        calls.append((action, dict(payload or {})))
        if action == "ping":
            return PING
        if action == "structure":
            return STRUCTURE
        if action == "read":
            return {"ok": True,
                    "formulas": [["=A1"]],
                    "rawValues": [[1]],
                    "displayValues": [["1"]]}
        raise AssertionError("unexpected action %r" % action)
    return call


class ColumnLetter(unittest.TestCase):
    def test_boundaries(self):
        for index, expected in ((1, "A"), (26, "Z"), (27, "AA"), (28, "AB"),
                                (52, "AZ"), (53, "BA"), (702, "ZZ"),
                                (703, "AAA")):
            self.assertEqual(snapshot_core.column_letter(index), expected)


class Wanted(unittest.TestCase):
    def test_skips_log_and_backups(self):
        self.assertFalse(snapshot_core.wanted("_DGI_Log", None))
        self.assertFalse(snapshot_core.wanted("_bk_MyShares_20260801", None))
        self.assertTrue(snapshot_core.wanted("MyShares", None))

    def test_explicit_list_narrows(self):
        self.assertTrue(snapshot_core.wanted("MyShares", ["MyShares"]))
        self.assertFalse(snapshot_core.wanted("Jurnal", ["MyShares"]))

    def test_explicit_list_cannot_resurrect_a_skipped_sheet(self):
        # Asking for the write log by name must still not fetch 1300 rows.
        self.assertFalse(snapshot_core.wanted("_DGI_Log", ["_DGI_Log"]))


class BuildSnapshot(unittest.TestCase):
    def test_skips_and_ranges(self):
        calls = []
        snap = snapshot_core.build_snapshot(fake_bridge(calls))

        self.assertEqual(sorted(snap["sheets"]), ["Huge", "Jurnal", "MyShares"])
        self.assertEqual(sorted(snap["skipped"]),
                         ["_DGI_Log", "_bk_MyShares_20260801-142057"])
        self.assertEqual(snap["sheets"]["MyShares"]["range"], "A1:AA62")
        self.assertEqual(snap["sheets"]["Jurnal"]["range"], "A1:D37")
        self.assertEqual(snap["spreadsheet"], "ClaudePortofoliu")

    def test_max_rows_caps_a_runaway_sheet(self):
        calls = []
        snap = snapshot_core.build_snapshot(fake_bridge(calls), max_rows=400)
        self.assertEqual(snap["sheets"]["Huge"]["range"], "A1:B400")

    def test_fields_sent_as_csv_not_array(self):
        # The Apps Script side parses a CSV string; an array silently reads as
        # the default value-only payload and the audit would see no formulas.
        calls = []
        snapshot_core.build_snapshot(fake_bridge(calls))
        reads = [payload for action, payload in calls if action == "read"]
        self.assertTrue(reads)
        for payload in reads:
            self.assertEqual(payload["fields"], "formulas,raw,values")

    def test_never_calls_a_mutating_action(self):
        # A snapshot must be safe to take at any time, including with
        # ALLOW_WRITES off. Assert the exact action set, so adding a write or
        # backup call here fails loudly rather than quietly taking effect.
        calls = []
        snapshot_core.build_snapshot(fake_bridge(calls))
        self.assertEqual({action for action, _ in calls},
                         {"ping", "structure", "read"})

    def test_identity_comes_from_ping_not_structure(self):
        snap = snapshot_core.build_snapshot(fake_bridge([]))
        self.assertEqual(snap["spreadsheet"], "ClaudePortofoliu")
        self.assertEqual(snap["spreadsheet_id"], "sheet-id")

    def test_sheets_filter_limits_the_reads(self):
        calls = []
        snap = snapshot_core.build_snapshot(fake_bridge(calls),
                                            sheets=["MyShares"])
        self.assertEqual(list(snap["sheets"]), ["MyShares"])
        self.assertEqual(len([a for a, _ in calls if a == "read"]), 1)

    def test_structure_failure_raises(self):
        def call(action, payload=None):
            return {"ok": False, "error": "nope"}
        with self.assertRaises(RuntimeError):
            snapshot_core.build_snapshot(call)

    def test_read_failure_raises_and_names_the_sheet(self):
        def call(action, payload=None):
            if action == "structure":
                return STRUCTURE
            return {"ok": False, "error": "boom"}
        with self.assertRaises(RuntimeError) as ctx:
            snapshot_core.build_snapshot(call)
        self.assertIn("MyShares", str(ctx.exception))


class Summarise(unittest.TestCase):
    def test_summary_carries_no_cell_data(self):
        # The whole reason bridge_snapshot writes to disk is that the cells
        # must never reach the conversation. Guard the payload keys directly;
        # do not grep the blob for "formulas", which also matches the
        # audit_formulas.py mentioned in next_step.
        snap = snapshot_core.build_snapshot(fake_bridge([]))
        summary = snapshot_core.summarise(snap, "/tmp/x.json")

        for name, entry in summary["sheets"].items():
            self.assertEqual(set(entry), {"range", "rows", "columns"},
                             "%s leaked a cell payload into the summary" % name)
        self.assertNotIn("=A1", repr(summary))
        self.assertEqual(summary["written_to"], "/tmp/x.json")
        self.assertIn("MyShares", summary["sheets"])


if __name__ == "__main__":
    unittest.main()
