"""Does the shipped prose still describe what the shipped code returns?

This project's most repeated failure is not a bug: it is a fix that ships while
the prose describing it does not. Item 8 shipped a config fix behind a stale
warning. Item 16's whole danger lived in a tool note. Item 11's fix was written
into `edgar_core` in v0.7.0 and the skill did not mention `quality` at all until
2026-09-05 - three versions later.

A test cannot check that prose is *good*. It can check that every response key
the code can emit is named somewhere a reader will find it, which is the drift
that actually happens. **The key list is derived from the source, not typed
here**, so adding a new `quality` key without documenting it fails this suite.
"""

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


EDGAR_CORE = read("mcp", "edgar_core.py")
EDGAR_SERVER = read("mcp", "edgar_server.py")
SKILL = read("skills", "company-analysis", "SKILL.md")
DATA_SOURCES = read("skills", "company-analysis", "references", "data-sources.md")

# Every key the code assigns into the `quality` dict. Derived, not listed.
QUALITY_KEYS = set(re.findall(r'quality\["([a-z_]+)"\]', EDGAR_CORE)) - {"_read_this"}


class QualityKeysAreDocumented(unittest.TestCase):
    def test_the_derivation_found_something(self):
        # Guard against the regex silently matching nothing, which would make
        # every test below pass vacuously - the exact failure mode that let
        # TagDiscovery survive a response-shape change (item 19).
        self.assertGreaterEqual(len(QUALITY_KEYS), 4, sorted(QUALITY_KEYS))

    # assertTrue, not assertIn, throughout this file. assertIn prints the whole
    # container on failure, and these containers are 20KB documents - a test
    # whose failure output has to be scrolled past is a test that gets ignored.

    def test_every_quality_key_is_named_in_the_skill(self):
        for key in sorted(QUALITY_KEYS):
            self.assertTrue(key in SKILL,
                            "%s is emitted by edgar_core, absent from SKILL.md" % key)

    def test_every_quality_key_is_named_in_data_sources(self):
        for key in sorted(QUALITY_KEYS):
            self.assertTrue(key in DATA_SOURCES,
                            "%s is emitted, absent from data-sources.md" % key)

    def test_every_quality_key_is_named_in_the_tool_description(self):
        # The tool description is what a model reads at the moment it calls.
        for key in sorted(QUALITY_KEYS):
            self.assertTrue(key in EDGAR_SERVER,
                            "%s is emitted, absent from the tool description" % key)


class ResponseFieldsAreDocumented(unittest.TestCase):
    """The other keys `series_for_concept` can add to a response."""

    FIELDS = ["alternatives", "filed"]

    def test_named_in_the_skill_or_its_references(self):
        for field in self.FIELDS:
            self.assertTrue(field in SKILL or field in DATA_SOURCES,
                            "%s is returned but documented nowhere" % field)


class StaleInstructionsThatWereWrongOnce(unittest.TestCase):
    """Regression guards for prose that was actively misleading, not just thin.

    Each string below shipped and produced a real wrong outcome. They are
    cheaper to assert against than to rediscover.
    """

    def test_an_empty_series_is_not_described_as_one_cause(self):
        # Item 17: "an empty series means this filer uses a tag outside the
        # chain" sent readers hunting for a tag that cannot exist, for BCS and
        # for V.
        self.assertNotIn("it means this filer uses a tag outside the chain", SKILL)

    def test_the_split_factor_is_not_described_as_year_keyed(self):
        # Item 16: keying on the year instead of the filing date turned MA's
        # 2013 P/E from 24 into 240.
        for doc, name in ((SKILL, "SKILL.md"), (DATA_SOURCES, "data-sources.md")):
            self.assertFalse("as_filed_eps_factor" in doc,
                             "%s still names the year-keyed factor" % name)


class ShareCountsAreTheInverse(unittest.TestCase):
    """BACKLOG item 29: the split factor multiplies a per-share figure and
    divides a share count. Every document described only the first half,
    and AAPL's criterion 9 read backwards for it. Keep the second half said
    wherever the factor is described."""

    PRICE_CORE = read("mcp", "price_core.py")

    def test_the_skill_says_a_count_is_divided(self):
        self.assertIn("DIVIDED by it", SKILL)

    def test_data_sources_says_criterion_9_divides(self):
        self.assertIn("**divide** each year by the split factor", DATA_SOURCES)

    def test_the_price_tool_rule_says_a_count_is_the_inverse(self):
        self.assertIn("A SHARE COUNT is the inverse", self.PRICE_CORE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
