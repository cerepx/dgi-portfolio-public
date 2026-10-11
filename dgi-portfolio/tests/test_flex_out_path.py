"""Tests for `flex_dividends` / `flex_trades` writing to disk instead of chat.

BACKLOG item 19. `bridge_snapshot` has always taken an `out_path`; these two
did not, so `/audit-live` step 5 told the agent to save the tool's JSON result
to a file - which in practice meant retyping 62 rows of amounts, pay dates and
transaction ids by hand. That is the exact thing `CLAUDE.md` forbids, and a
transcription slip there invents a missing payment or hides a real one.

`write_payload` is pure and does not touch the network, so it is testable on
its own. The MCP loop sits behind `if __name__ == "__main__"`, which is why
this 31KB single file can be imported at all - see README -> Development.
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

import ibkr_flex_server as flex  # noqa: E402


PAYLOAD = {
    "ok": True,
    "count": 3,
    "per_share_unparsed": [],
    "note": None,
    "cols": ["pay_date", "symbol", "amount"],
    "rows": [["20260901", "V", 1.20],
             ["20260901", "ZTS", 2.4],
             ["20260814", "O", 1.50]],
}


class WritePayload(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "flex-dividends.json")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, path=None):
        return flex.write_payload(dict(PAYLOAD), path or self.path, "next step")

    def test_the_file_holds_the_whole_payload_rows_included(self):
        self.write()
        with open(self.path) as fh:
            written = json.load(fh)
        self.assertEqual(written, PAYLOAD)

    def test_rows_are_dropped_from_the_response_not_truncated(self):
        # A half-list read as a whole one is worse than no list, so there must
        # be no preview, no first-N, nothing row-shaped in the summary.
        summary = self.write()
        self.assertNotIn("rows", summary)
        self.assertNotIn("V", json.dumps(summary))
        self.assertNotIn("ZTS", json.dumps(summary))

    def test_the_summary_keeps_everything_that_is_not_rows(self):
        summary = self.write()
        for key in ("ok", "count", "per_share_unparsed", "note", "cols"):
            self.assertEqual(summary[key], PAYLOAD[key], key)

    def test_the_summary_says_where_the_rows_went_and_how_many(self):
        summary = self.write()
        self.assertEqual(summary["written_to"], self.path)
        self.assertEqual(summary["bytes"], os.path.getsize(self.path))
        self.assertIn("3 row(s)", summary["rows_omitted"])
        self.assertEqual(summary["next_step"], "next step")

    def test_a_tilde_path_is_accepted_and_expanded(self):
        target = os.path.join(os.path.expanduser("~"), "_flex_out_path_probe.json")
        try:
            summary = self.write("~/_flex_out_path_probe.json")
            self.assertEqual(summary["written_to"], target)
            self.assertTrue(os.path.exists(target))
        finally:
            if os.path.exists(target):
                os.remove(target)

    def test_a_relative_path_is_refused_with_a_reason(self):
        # The dangerous one. A relative path lands in whatever directory the
        # server process happens to be in - not the user's folder - so the file
        # would be written "successfully" somewhere nobody looks.
        with self.assertRaises(flex.FlexError) as caught:
            self.write("flex-dividends.json")
        self.assertIn("absolute", str(caught.exception))
        self.assertIn("flex-dividends.json", str(caught.exception))

    def test_a_missing_directory_is_refused_rather_than_created(self):
        with self.assertRaises(flex.FlexError) as caught:
            self.write(os.path.join(self.dir, "nope", "x.json"))
        self.assertIn("does not exist", str(caught.exception))

    def test_the_original_payload_is_not_mutated(self):
        payload = dict(PAYLOAD)
        flex.write_payload(payload, self.path, "next step")
        self.assertIn("rows", payload)


class ToolSchemas(unittest.TestCase):
    """The parameter has to be declared, not merely handled."""

    def schema(self, name):
        return [t for t in flex.TOOLS if t["name"] == name][0]

    def test_both_row_returning_tools_offer_out_path(self):
        for name in ("flex_dividends", "flex_trades"):
            props = self.schema(name)["inputSchema"]["properties"]
            self.assertIn("out_path", props, name)
            self.assertIn("ABSOLUTE", props["out_path"]["description"], name)

    def test_out_path_is_optional(self):
        for name in ("flex_dividends", "flex_trades"):
            self.assertEqual(self.schema(name)["inputSchema"]["required"],
                             ["query"], name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
