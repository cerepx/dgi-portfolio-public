"""`fetch_statement` when the GetStatement host IBKR hands back is unreachable.

BACKLOG item 27. SendRequest goes to the configured host (ndcdyn) and works;
IBKR's response then names a GetStatement URL on gdcdyn, which has been seen
with no DNS record and, separately, hanging instead of refusing. The first made
step 5 of /audit-live fail outright, the second held each call for a minute.

Offline: `urlopen` is replaced, so no request leaves the machine and no real
token is involved.
"""

import os
import socket
import sys
import unittest
import urllib.error
import urllib.parse

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp"))

import ibkr_flex_server as flex  # noqa: E402

TOKEN = "SECRET-TOKEN-123"
SEND = "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest"
GET_RETURNED = "https://gdcdyn.interactivebrokers.com/AccountManagement/FlexWebService/GetStatement"

SEND_OK = ("<FlexStatementResponse><Status>Success</Status>"
           "<ReferenceCode>REF1</ReferenceCode><Url>%s</Url>"
           "</FlexStatementResponse>" % GET_RETURNED)
REPORT = "<FlexQueryResponse><FlexStatements count='0'/></FlexQueryResponse>"


class _Body:
    def __init__(self, text):
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.text.encode("utf-8")


class FakeNetwork:
    """Answers per host. A value is a body string or an exception to raise."""

    def __init__(self, by_host):
        self.by_host = by_host
        self.calls = []

    def urlopen(self, request, timeout=None):
        host = urllib.parse.urlsplit(request.full_url).netloc
        self.calls.append((host, timeout))
        outcome = self.by_host[host]
        if isinstance(outcome, list):
            outcome = outcome.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return _Body(outcome)


class Resilience(unittest.TestCase):
    def setUp(self):
        self.saved = (flex.urllib.request.urlopen, flex.load_config,
                      flex._throttle, flex.time.sleep)
        flex.load_config = lambda: {"token": TOKEN, "send_request_url": SEND}
        flex._throttle = lambda: None
        flex.time.sleep = lambda s: None

    def tearDown(self):
        (flex.urllib.request.urlopen, flex.load_config,
         flex._throttle, flex.time.sleep) = self.saved

    def run_with(self, by_host):
        net = FakeNetwork(by_host)
        flex.urllib.request.urlopen = net.urlopen
        return net

    def test_a_dns_failure_on_the_returned_host_falls_back_once(self):
        net = self.run_with({
            "ndcdyn.interactivebrokers.com": [SEND_OK, REPORT],
            "gdcdyn.interactivebrokers.com": urllib.error.URLError(
                socket.gaierror(8, "nodename nor servname provided")),
        })
        self.assertEqual(flex.fetch_statement("Q1"), REPORT)
        self.assertEqual([h for h, _ in net.calls], [
            "ndcdyn.interactivebrokers.com", "gdcdyn.interactivebrokers.com",
            "ndcdyn.interactivebrokers.com"])

    def test_a_hanging_host_falls_back_too(self):
        self.run_with({
            "ndcdyn.interactivebrokers.com": [SEND_OK, REPORT],
            "gdcdyn.interactivebrokers.com": urllib.error.URLError(
                socket.timeout("timed out")),
        })
        self.assertEqual(flex.fetch_statement("Q1"), REPORT)

    def test_a_timeout_while_reading_is_caught_not_a_bare_traceback(self):
        # Raised by read(), outside URLError - this escaped before item 27.
        self.run_with({
            "ndcdyn.interactivebrokers.com": [SEND_OK, REPORT],
            "gdcdyn.interactivebrokers.com": TimeoutError("read timed out"),
        })
        self.assertEqual(flex.fetch_statement("Q1"), REPORT)

    def test_a_refused_connection_is_not_a_reason_to_switch_host(self):
        self.run_with({
            "ndcdyn.interactivebrokers.com": [SEND_OK, REPORT],
            "gdcdyn.interactivebrokers.com": urllib.error.URLError(
                ConnectionRefusedError(61, "refused")),
        })
        with self.assertRaises(flex.FlexUnreachable) as caught:
            flex.fetch_statement("Q1")
        self.assertEqual(caught.exception.kind, "other")

    def test_when_both_hosts_fail_the_error_names_the_host_and_hides_the_token(self):
        dns = urllib.error.URLError(socket.gaierror(8, "nodename %s" % TOKEN))
        self.run_with({
            "ndcdyn.interactivebrokers.com": [SEND_OK, dns],
            "gdcdyn.interactivebrokers.com": dns,
        })
        with self.assertRaises(flex.FlexUnreachable) as caught:
            flex.fetch_statement("Q1")
        message = str(caught.exception)
        self.assertTrue("ndcdyn.interactivebrokers.com" in message, message)
        self.assertFalse(TOKEN in message, message)

    def test_every_request_carries_the_shorter_timeout(self):
        net = self.run_with({
            "ndcdyn.interactivebrokers.com": [SEND_OK],
            "gdcdyn.interactivebrokers.com": REPORT,
        })
        flex.fetch_statement("Q1")
        self.assertTrue(all(t == flex.HTTP_TIMEOUT_SECONDS for _, t in net.calls))
        self.assertLessEqual(flex.HTTP_TIMEOUT_SECONDS, 30)


class FallbackUrl(unittest.TestCase):
    def test_same_path_on_the_configured_host(self):
        self.assertEqual(
            flex._fallback_url(GET_RETURNED, SEND),
            "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService/GetStatement")

    def test_nothing_to_try_when_the_hosts_already_match(self):
        same = SEND.replace("SendRequest", "GetStatement")
        self.assertIsNone(flex._fallback_url(same, SEND))

    def test_never_toward_a_host_outside_the_domain(self):
        self.assertIsNone(flex._fallback_url(
            "https://evil.example.com/AccountManagement/FlexWebService/GetStatement", SEND))
        self.assertIsNone(flex._fallback_url(
            GET_RETURNED, "https://proxy.example.com/FlexWebService/SendRequest"))

    def test_a_lookalike_domain_does_not_pass(self):
        self.assertIsNone(flex._fallback_url(
            "https://gdcdyn.notinteractivebrokers.com/GetStatement", SEND))


if __name__ == "__main__":
    unittest.main()
