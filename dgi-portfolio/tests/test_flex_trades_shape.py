"""
Smoke tests for flex_trades (v0.5.4): columnar trade-execution output,
asset_category / side / symbol filters, and per-symbol commission totals.

Run: PYTHONDONTWRITEBYTECODE=1 python3 tests/test_flex_trades_shape.py
"""
import importlib.util
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "..", "mcp", "ibkr_flex_server.py")

spec = importlib.util.spec_from_file_location("srv", SERVER)
srv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)

# Two buys of the same symbol (position built over several executions - the
# exact case column T's per-position total has to be reconciled against),
# one sell, and one non-STK row that the default asset_category filter must
# drop.
REPORT = """<FlexQueryResponse queryName="FlexTrades" type="AF">
<FlexStatements count="1">
<FlexStatement accountId="U1234567" fromDate="20250731" toDate="20260730">
<Trades>
<Trade symbol="KO" isin="US1912161007" assetCategory="STK" buySell="BUY"
  tradeDate="20250805" quantity="10" tradePrice="63.50" currency="USD"
  ibCommission="-1.00" ibCommissionCurrency="USD" proceeds="-635.00"
  netCash="-636.00" transactionID="201"/>
<Trade symbol="KO" isin="US1912161007" assetCategory="STK" buySell="BUY"
  tradeDate="20251203" quantity="10" tradePrice="65.20" currency="USD"
  ibCommission="-1.00" ibCommissionCurrency="USD" proceeds="-652.00"
  netCash="-653.00" transactionID="202"/>
<Trade symbol="KO" isin="US1912161007" assetCategory="STK" buySell="SELL"
  tradeDate="20260110" quantity="-5" tradePrice="68.00" currency="USD"
  ibCommission="-1.00" ibCommissionCurrency="USD" proceeds="340.00"
  netCash="339.00" transactionID="203"/>
<Trade symbol="EUR.USD" isin="" assetCategory="CASH" buySell="BUY"
  tradeDate="20250901" quantity="1000" tradePrice="1.08" currency="USD"
  ibCommission="-2.00" ibCommissionCurrency="USD" proceeds="-1080.00"
  netCash="-1082.00" transactionID="204"/>
</Trades>
</FlexStatement>
</FlexStatements>
</FlexQueryResponse>"""

srv.fetch_statement = lambda query_id, **kw: REPORT
srv.load_config = lambda: {"queries": {"trades": "1608998"},
                           "send_request_url": "https://example.invalid",
                           "token": "t"}

out = srv.run_tool("flex_trades", {"query": "trades"})

# Columnar shape, same convention as flex_dividends.
assert out["cols"][:3] == ["trade_date", "symbol", "buy_sell"], out["cols"]

# Default asset_category="STK" drops the CASH/FX row.
assert out["count"] == 3, out["count"]
symbols = {r[out["cols"].index("symbol")] for r in out["rows"]}
assert symbols == {"KO"}, symbols

# Two buys summed into one per-symbol total; the sell is excluded from it.
assert out["buy_commission_totals_by_symbol"] == {"KO": -2.0}, \
    out["buy_commission_totals_by_symbol"]

# asset_category="" (empty string) disables the filter.
out_all = srv.run_tool("flex_trades", {"query": "trades", "asset_category": ""})
assert out_all["count"] == 4, out_all["count"]

# symbol filter.
out_ko = srv.run_tool("flex_trades", {"query": "trades", "symbol": "ko"})
assert out_ko["count"] == 3, out_ko["count"]

# side filter.
out_sell = srv.run_tool("flex_trades", {"query": "trades", "side": "SELL"})
assert out_sell["count"] == 1, out_sell["count"]
assert out_sell["buy_commission_totals_by_symbol"] == {}, \
    "a SELL-only result must not populate buy totals"

# Serialisation is compact, same convention as the rest of the server.
text = json.dumps(srv._compact(out), ensure_ascii=False,
                  separators=(",", ":"))
assert "\n" not in text and ": " not in text

print("ALL FLEX_TRADES SHAPE TESTS PASS")
