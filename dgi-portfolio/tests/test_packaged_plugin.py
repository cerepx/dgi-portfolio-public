"""Does the archive on disk contain what the source tree says it does?

The gap this closes, in the words BACKLOG.md used for three weeks: *no test
asserts on a packaged or installed file*. The 90-test suite stayed green
through three versions of source/bundle drift (item 14), and on 2026-08-01 the
bundled `company-analysis` skill was 85 minutes older than its source and told
the model to use FMP endpoints that had been documented as denied that same
afternoon. Nothing failed loudly. The skill simply gave wrong instructions for
two days.

Every check here is one of the five manual verifications from README ->
Development, which were only ever a recipe a session could skip. A recipe that
is skipped and a recipe that passes look identical afterwards; a red test does
not.

**Scope, stated so it is not overclaimed.** This file proves *packaged*. It
says nothing about *installed* - the running copy is unpacked per session under
`~/Library/Application Support/Claude/local-agent-mode-sessions/`, no test can
reach the copy a future session will load, and a session cannot verify its own
install. Source -> archive is the half that is mechanizable, so it is the half
mechanized here.

The target is `dgi-portfolio.plugin` at the plugin root. That is the canonical
artifact by .gitignore's own words: it is tracked, and the version-stamped
`dgi-portfolio-<version>.plugin` copies are ignored delivery copies.
"""

import json
import os
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVE = os.path.join(ROOT, "dgi-portfolio.plugin")
MANIFEST = ".claude-plugin/plugin.json"

# Exactly the rsync --exclude list from README -> Development. If the recipe
# gains an exclude, it has to gain one here too, or the completeness check
# below starts reporting a file the build deliberately dropped.
EXCLUDED_NAMES = (".DS_Store",)
EXCLUDED_DIRS = ("__pycache__",)
EXCLUDED_SUFFIXES = (".pyc", ".plugin")

# Regenerated artifacts, named in .gitignore. `/audit-live` writes these into
# the working folder after a build, so they can exist in the tree and legally
# be absent from an archive built before them. They are not source.
GENERATED = ("sheet-snapshot.json", "live-audit.xlsx", "flex-dividends.json")


def is_source(rel):
    """Would the build's rsync have carried this file into the stage?"""
    name = os.path.basename(rel)
    if name in EXCLUDED_NAMES or name in GENERATED:
        return False
    if any(d in rel.split(os.sep) for d in EXCLUDED_DIRS):
        return False
    return not rel.endswith(EXCLUDED_SUFFIXES)


def source_files():
    out = set()
    for base, _dirs, names in os.walk(ROOT):
        for name in names:
            rel = os.path.relpath(os.path.join(base, name), ROOT)
            if is_source(rel):
                out.add(rel)
    return out


def read_source(rel):
    with open(os.path.join(ROOT, rel), "rb") as fh:
        return fh.read()


SOURCE_MANIFEST = json.loads(read_source(MANIFEST).decode("utf-8"))
TEMPLATE = json.loads(read_source("mcp/dot-mcp.json.template").decode("utf-8"))


class PackagedPlugin(unittest.TestCase):
    """Every assertion runs against bytes read out of the zip, never the tree.

    A missing archive is a failure here, deliberately, not a skip. `skipUnless`
    would make this whole class vacuous in exactly the case it exists to catch:
    a version bumped with nothing rebuilt. The failure message names the other
    cause too, so a tree copied without the archive is one line to diagnose.
    """

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(ARCHIVE):
            raise AssertionError(
                "no archive at %s. Either the build was never run for source "
                "v%s, or this tree is a copy that dropped it - copy the "
                "archive in and re-run." % (ARCHIVE, SOURCE_MANIFEST["version"]))
        cls.zf = zipfile.ZipFile(ARCHIVE)
        cls.members = set(
            n for n in cls.zf.namelist() if not n.endswith("/")
        )
        cls.bundled_manifest = json.loads(
            cls.zf.read(MANIFEST).decode("utf-8")
        )

    @classmethod
    def tearDownClass(cls):
        cls.zf.close()

    # -- the archive exists at all -------------------------------------------
    # Without this the whole class can pass by comparing nothing, which is the
    # failure mode test_shipped_docs guards with its own derivation check.

    def test_the_archive_is_not_empty(self):
        self.assertGreater(len(self.members), 30, sorted(self.members)[:5])

    def test_the_comparison_has_something_to_compare(self):
        self.assertGreater(len(source_files()), 30)

    # -- version, the item 14 catch ------------------------------------------

    def test_the_bundled_version_equals_the_source_version(self):
        # Source at 0.11.5 with a 0.11.4 archive means the version was bumped
        # and nothing was rebuilt. That is item 14 exactly, and it survived a
        # green suite for three versions.
        self.assertEqual(
            self.bundled_manifest["version"], SOURCE_MANIFEST["version"],
            "archive is v%s, source is v%s - rebuild before claiming the "
            "version" % (self.bundled_manifest["version"],
                         SOURCE_MANIFEST["version"]))

    def test_the_bundled_name_is_the_kebab_case_identifier(self):
        # `name` is the identifier behind /dgi-portfolio:audit-live, the MCP
        # tool prefixes and the install directory. A space in it breaks command
        # parsing outright. See BACKLOG -> Decided.
        self.assertEqual(self.bundled_manifest["name"], "dgi-portfolio")

    def test_the_bundled_description_fits_the_validator_cap(self):
        # 500 is the plugin validator's cap. Over it, the install is rejected -
        # after the archive is built, which is the annoying moment to find out.
        self.assertLessEqual(len(self.bundled_manifest["description"]), 500)

    # -- .mcp.json, the silent failure ---------------------------------------
    # A missing .mcp.json installs cleanly and the tools are simply absent.

    def test_the_archive_carries_a_dot_mcp_json(self):
        self.assertTrue(".mcp.json" in self.members,
                        "archive has no .mcp.json - it would install cleanly "
                        "with every MCP tool absent")

    def test_the_source_tree_does_not(self):
        # The Claude app blocks writing a literal .mcp.json inside a connected
        # folder, so it is bundle-only by design and the template is its source
        # of truth. If one ever appears in the tree, the build would ship the
        # wrong one silently.
        self.assertFalse(os.path.exists(os.path.join(ROOT, ".mcp.json")))

    def test_the_bundled_servers_are_exactly_the_templates(self):
        # Derived from the template, not typed here, so adding a server to the
        # template without rebuilding fails this.
        bundled = json.loads(self.zf.read(".mcp.json").decode("utf-8"))
        self.assertEqual(bundled["mcpServers"], TEMPLATE["mcpServers"])

    def test_the_bundled_mcp_json_drops_the_template_comment(self):
        # An unknown top-level field has been rejected by the validator once.
        bundled = json.loads(self.zf.read(".mcp.json").decode("utf-8"))
        self.assertEqual(list(bundled), ["mcpServers"])

    def test_every_declared_server_script_is_in_the_archive(self):
        # A template entry pointing at a file the build never carried fails at
        # server start, in a place nobody is watching.
        bundled = json.loads(self.zf.read(".mcp.json").decode("utf-8"))
        for server, spec in sorted(bundled["mcpServers"].items()):
            for arg in spec["args"]:
                if "${CLAUDE_PLUGIN_ROOT}/" not in arg:
                    continue
                rel = arg.split("${CLAUDE_PLUGIN_ROOT}/", 1)[1]
                self.assertTrue(rel in self.members,
                                "%s declares %s, absent from the archive"
                                % (server, rel))

    # -- what must and must not be inside ------------------------------------

    def test_the_commands_directory_shipped(self):
        # commands/ carries /audit-live. It has been missed before.
        self.assertTrue("commands/audit-live.md" in self.members)

    def test_no_bytecode_or_os_junk_shipped(self):
        # The rsync --exclude list is the only thing keeping these out.
        for name in sorted(self.members):
            self.assertFalse(
                "__pycache__" in name or name.endswith((".pyc", ".pyo"))
                or os.path.basename(name) == ".DS_Store",
                "%s should not be in the archive" % name)

    def test_no_archive_shipped_inside_the_archive(self):
        for name in sorted(self.members):
            self.assertFalse(name.endswith(".plugin"), name)

    # -- fidelity, the 85-minute staleness catch -----------------------------

    def test_every_bundled_file_matches_its_source(self):
        stale = []
        for name in sorted(self.members):
            if name == ".mcp.json":
                continue          # bundle-only by design, checked above
            if not os.path.exists(os.path.join(ROOT, name)):
                continue          # reported by the completeness test instead
            if self.zf.read(name) != read_source(name):
                stale.append(name)
        # Names only. Printing a diff of a 20KB skill document is a failure
        # message nobody reads.
        self.assertEqual(stale, [], "stale in bundle: %s" % stale)

    def test_the_archive_holds_no_file_the_source_lost(self):
        orphans = sorted(
            n for n in self.members
            if n != ".mcp.json" and not os.path.exists(os.path.join(ROOT, n)))
        self.assertEqual(orphans, [], "in archive, not in source: %s" % orphans)

    def test_every_source_file_reached_the_archive(self):
        # The other direction. A file that never made it in fails exactly like
        # a file that was never written.
        missing = sorted(source_files() - self.members)
        self.assertEqual(missing, [], "in source, not in archive: %s" % missing)

    # -- the delivered copy --------------------------------------------------

    def test_the_delivered_copy_is_the_canonical_one(self):
        # The version-stamped copy handed to the user must be the same bytes as
        # the tracked archive, or git records a build nobody installed. Absent
        # when the suite runs from a /tmp copy, which is normal - the skip says
        # so rather than passing quietly.
        delivered = os.path.join(
            os.path.dirname(ROOT),
            "dgi-portfolio-%s.plugin" % SOURCE_MANIFEST["version"])
        if not os.path.exists(delivered):
            self.skipTest("not checked: no %s next to the plugin root"
                          % os.path.basename(delivered))
        with open(delivered, "rb") as fh:
            self.assertEqual(fh.read(), read_source("dgi-portfolio.plugin"),
                             "%s differs from the tracked archive"
                             % os.path.basename(delivered))


if __name__ == "__main__":
    unittest.main()
