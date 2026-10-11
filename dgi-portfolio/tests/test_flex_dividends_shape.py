"""
Smoke tests for the v0.4.3 token-efficiency changes to the flex server:
columnar flex_dividends output, opt-in descriptions, compact serialisation
and None-pruning.

Run: PYTHONDONTWRITEBYTECODE=1 python3 tests/test_flex_dividends_shape.py
"""
import importlib.util
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "..", "mcp", "ibkr_flex_server.py")

spec = importlib.util.spec_from_file_location("srv", SERVER)
srv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)

REPORT = """<FlexQueryResponse queryName="FlexDividends" type="AF">
<FlexStatements count="1">
<FlexStatement accountId="U1234567" fromDate="20250731" toDate="20260730">
<CashTransactions>
<CashTransaction type="Dividends" symbol="KO" isin="US1912161007"
  description="KO(US1912161007) CASH DIVIDEND USD 0.51 PER SHARE (Ordinary Dividend)"
  amount="2.04" currency="USD" fxRateToBase="1" settleDate="20251001"
  dateTime="20251001;101454" transactionID="111"/>
<CashTransaction type="Withholding Tax" symbol="KO" isin="US1912161007"
  description="KO(US1912161007) CASH DIVIDEND USD 0.51 PER SHARE - US TAX"
  amount="-0.20" currency="USD" fxRateToBase="1" settleDate="20251001"
  dateTime="20251001;101454" transactionID="112"/>
<CashTransaction type="Dividends" symbol="XYZ" isin=""
  description="XYZ SPECIAL CASH DISTRIBUTION" amount="3.00" currency="USD"
  fxRateToBase="1" settleDate="20251105" dateTime="20251105;101454"
  transactionID="113"/>
<CashTransaction type="Broker Interest Received" symbol="" isin=""
  description="USD CREDIT INT" amount="0.12" currency="USD" fxRateToBase="1"
  settleDate="20251103" dateTime="20251103;101454" transactionID="114"/>
</CashTransactions>
</FlexStatement>
</FlexStatements>
</FlexQueryResponse>"""

srv.fetch_statement = lambda query_id, **kw: REPORT
srv.load_config = lambda: {"queries": {"dividends": "1589258"},
                           "send_request_url": "https://example.invalid",
                           "token": "t"}

out = srv.run_tool("flex_dividends", {"query": "dividends"})

# Columnar shape: cols header + positional rows, no per-row dicts.
assert out["cols"][:3] == ["pay_date", "symbol", "type"], out["cols"]
assert "description" not in out["cols"], "descriptions must be opt-in"
assert out["count"] == 3, out["count"]  # broker interest excluded
rows = {r[out["cols"].index("transaction_id")]: r for r in out["rows"]}
ps = out["cols"].index("gross_per_share")
assert rows["111"][ps] == 0.51
assert rows["113"][ps] is None            # special: no PER SHARE text
assert out["per_share_unparsed"] == ["113"]

# Opt-in descriptions appear as a trailing column.
out2 = srv.run_tool("flex_dividends",
                    {"query": "dividends", "include_descriptions": True})
d = out2["cols"].index("description")
assert "PER SHARE" in {r[out2["cols"].index("transaction_id")]: r
                       for r in out2["rows"]}["111"][d]

# _compact drops None dict keys but preserves None list cells (positional).
compacted = srv._compact({"a": None, "b": 1, "rows": [[None, 2], {"x": None}]})
assert compacted == {"b": 1, "rows": [[None, 2], {}]}, compacted

# Serialisation is compact: no indentation newlines inside the payload.
text = json.dumps(srv._compact(out), ensure_ascii=False,
                  separators=(",", ":"))
assert "\n" not in text and ": " not in text

print("ALL SHAPE TESTS PASS")
