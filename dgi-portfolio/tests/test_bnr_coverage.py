"""
Smoke tests for the BNR feed diagnostics added in v0.4.2.

Run: python3 tests/test_bnr_coverage.py (from dgi-portfolio/)

Context, measured 2026-07-31: BNR served the python-urllib User-Agent a
well-formed XML document with zero Cube elements for every mutable feed, while
the immutable 2025 year archive (long-lived in the CDN cache) came through
intact. The old bnr_coverage could only say "all returned nothing"; the new one
reports bytes, cube counts and the head of any cube-less document per feed.
"""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "..", "mcp", "ibkr_flex_server.py")

spec = importlib.util.spec_from_file_location("srv", SERVER)
srv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)

GOOD = """<?xml version="1.0"?><DataSet xmlns="http://www.bnr.ro/xsd"><Body>
<Cube date="2026-01-05"><Rate currency="USD">4.60</Rate></Cube>
<Cube date="2026-03-26"><Rate currency="USD">4.62</Rate></Cube></Body></DataSet>"""

# Well-formed XML with no Cube elements - the shape an anti-bot interstitial
# takes when it happens to be valid XHTML. Parses cleanly, yields nothing.
CHALLENGE = ('<html><head><script src="x"></script></head>'
             '<body><iframe src="y"></iframe></body></html>')

feeds = {}


def fake_get(url, label):
    response = feeds[label]
    if isinstance(response, Exception):
        raise response
    return response


srv._bnr_get = fake_get

# One good feed, one cube-less feed, one network failure: merged coverage comes
# from the good feed alone and each feed reports its own outcome.
feeds = {"year 2026": GOOD, "recent days": CHALLENGE,
         "today": srv.FlexError("Cannot reach BNR (today): boom")}
out = srv.bnr_coverage(2026)
assert out["days"] == 2 and out["first"] == "2026-01-05" \
    and out["last"] == "2026-03-26", out
by_feed = {e["feed"]: e for e in out["feeds"]}
assert by_feed["year 2026"]["cubes_in_year"] == 2
assert by_feed["recent days"]["cubes"] == 0
assert by_feed["recent days"]["root_tag"] == "html"
assert "iframe" in by_feed["recent days"]["head"]
assert "boom" in by_feed["today"]["error"]

# All feeds cube-less: no raise, days 0, no first/last, diagnostics present.
feeds = {"year 2026": CHALLENGE, "recent days": CHALLENGE, "today": CHALLENGE}
out = srv.bnr_coverage(2026)
assert out["days"] == 0 and "first" not in out, out
assert all(e["cubes"] == 0 for e in out["feeds"])

# bnr_rate on total emptiness fails with a pointer to bnr_coverage, not a
# KeyError and not the old blind "all returned nothing".
srv._bnr_cache.clear()
try:
    srv.bnr_rate("20260401", "USD")
    raise SystemExit("expected FlexError")
except srv.FlexError as err:
    assert "bnr_coverage" in str(err), str(err)

# Weekend fallback still works through the rewritten path.
srv._bnr_cache.clear()
feeds = {"year 2026": GOOD, "recent days": CHALLENGE, "today": CHALLENGE}
rate, used, back = srv.bnr_rate("20260107", "USD")
assert (rate, used, back) == (4.60, "2026-01-05", 2), (rate, used, back)

# The fix itself: headers must be browser-like.
assert srv.BNR_HEADERS["User-Agent"].startswith("Mozilla/5.0")

# The REAL 2026-07-31 defect: BNR migrated the feed namespace from
# http://www.bnr.ro/xsd to https://www.bnr.ro/xsd. The parser must accept
# both - and, being namespace-agnostic, any future migration too.
GOOD_HTTPS_NS = GOOD.replace('xmlns="http://www.bnr.ro/xsd"',
                             'xmlns="https://www.bnr.ro/xsd"')
assert GOOD_HTTPS_NS != GOOD
srv._bnr_cache.clear()
feeds = {"year 2026": GOOD_HTTPS_NS, "recent days": CHALLENGE,
         "today": CHALLENGE}
out = srv.bnr_coverage(2026)
assert out["days"] == 2 and out["first"] == "2026-01-05", out
rate, used, back = srv.bnr_rate("20260105", "USD")
assert (rate, used, back) == (4.60, "2026-01-05", 0), (rate, used, back)

print("ALL SMOKE TESTS PASS")
