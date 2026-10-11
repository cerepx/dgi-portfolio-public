# dgi-portfolio

Integrity audit for a dividend-growth portfolio, and DGI company analysis using
the Dividende.blog methodology.

## Skills

**`portfolio-audit`** checks sheet integrity and reconciles it against the
market. It is a deterministic Python validator with 15 checks, not LLM
interpretation, so findings are reproducible and each carries a cell, evidence
and a fix. Read-only by default. `/audit-live` drives it on the live sheet.

**`company-analysis`** gives a 10-criteria score (max 30, floor 10) plus six
price valuation methods. One ticker at a time.

## Install

1. Install the archive with `bash ~/Desktop/claude-dgi/install-plugin.sh
   <archive>`. It does what the app's upload does and byte-compares the
   installed and registry copies against the archive. Then open a **new
   session**: a running one keeps its old copy.
2. Configure `config/portfolio.json`, which maps the structure of your sheet.
3. **SEC EDGAR** (`dgi-edgar`): create `~/.dgi/edgar.json` with
   `{"user_agent": "Your Name your@email.com"}`. No key and no quota, but the
   SEC returns 403 without a contact address.
4. **Tiingo** (`dgi-prices`): put a token in `~/.dgi/prices.json`. Without it,
   valuation methods 1-5 and `price_dividends` do not run.
5. **IBKR Flex** (`dgi-ibkr-flex`): a Flex token and query ids in
   `~/.dgi/ibkr-flex.json`. See *IBKR Flex* below.
6. **Alpha Vantage** (`dgi-alphavantage`), optional: a free key in
   `~/.dgi/alphavantage.json` as `{"api_key": "..."}`. It is the share-count
   source for Visa and a check on the EDGAR reader.
7. **FMP connector**, optional: profile and current price only. **Never use it
   for statements**: it gates fundamentals per symbol and covered 4 of 17
   tickers tested (measured 2026-08-01).
8. **Sheet access**: follow `setup/apps-script/SETUP.md`.

Every credential lives in a `chmod 600` file under `~/.dgi/`. None goes in the
repo or the conversation.

### The five MCP servers

`.mcp.json` declares five local stdio servers: `dgi-sheet-bridge`,
`dgi-ibkr-flex`, `dgi-edgar`, `dgi-prices` and `dgi-alphavantage`. They run on the host because the
agent sandbox has no route to `script.google.com` and similar hosts. They also
reduce large payloads (EDGAR facts, ~3,800 daily price rows) to a few dozen
numbers before anything reaches the conversation.

**`dgi-sheet-bridge`** exposes the Apps Script bridge: `bridge_ping`,
`bridge_structure`, `bridge_read`, `bridge_write`, `bridge_backup`,
`bridge_log`, `bridge_snapshot` and `bridge_prune`.
- `bridge_read` returns display values by default. `formulas`, `raw`,
  `formats` and `all` are opt-ins via `fields`.
- `bridge_snapshot` dumps every visible sheet at formula level to a local JSON
  file and returns only a summary. `/audit-live` is built on it.
- Formatting and structure, which the bridge cannot write, go through the
  Google Sheets connector, under the rule in the repository's `CLAUDE.md`.

**Bridge setup.** Put the web app URL and token in a file the server reads:

```bash
mkdir -p ~/.dgi && printf '{"webapp_url":"%s","token":"%s"}\n' \
  "$WEBAPP_URL" "$DGI_SHEET_TOKEN" > ~/.dgi/sheet-bridge.json \
  && chmod 600 ~/.dgi/sheet-bridge.json
```

**How the token is kept out of sight.** It goes only in POST bodies, and Apps
Script refuses GET. The server redacts it from every error message.

**Why a file and not an environment variable:** macOS GUI apps never read
`~/.zshrc`. An earlier FMP `.mcp.json` built on `${FMP_API_KEY}` failed for
exactly that reason.

FMP itself comes through the app's connector. Its tool names carry a
per-installation uuid, so the skills discover them with `ToolSearch`.

## Usage

Trigger phrases are bilingual:

```
auditeaza portofoliul          audit my portfolio
verifica formulele din excel   check my formulas
analizeaza KO                  analyze KO
ce scor DGI are Realty Income  DGI score for Realty Income
```

## Language convention

Conversation with the user is in Romanian. Everything written to disk is in
English: code, comments, config keys, docs, file names. Four kinds of Romanian
string are deliberate and must not be translated:

| Category | Example | Why |
|---|---|---|
| Skill trigger phrases | `"verifica excelul"` | the skill will not fire on Romanian input without them |
| Spreadsheet identifiers | `Valoare achizitie`, `Ani creștere`, `Jurnal` | literal strings in the sheet; translating breaks the column mapping |
| Proper nouns | `Declarația Unică` | the Romanian tax return has no English name |
| Source attribution | `Dividende.blog`, `Cum analizez o companie` | publication titles |

## DGI vs non-DGI positions

- **DGI positions** feed every dividend aggregate: income, weight, yield, yield
  on cost, growth years, DGR, charts.
- **Non-DGI positions** are tracking only: `PLTR`, `META`, `SXR8`, `BVBETF`.
  Their dividend cells are deliberately `N/A`.

The rules that follow:
- Empty dividend cells on non-DGI rows are never reported as missing.
- A dividend aggregate that reaches into the non-DGI block is `CRITICAL`.
- Non-DGI positions still count in value, cost and profit.
- `company-analysis` does not score them, rather than producing a meaningless
  10/30.

The boundary is data, not a row number: the `DGI` TRUE/FALSE column, in
**`AA`** since a column insert on 2026-07-31, drives `SUMIFS`. The row blocks in
the config are a cross-check only.

## Dividend tax

| Year of receipt | Rate | Net factor |
|---|---|---|
| 2021 - 2022 | 5% | 0.95 |
| 2023 | 8% | 0.92 |
| 2024 - 2025 | 10% | 0.90 |
| 2026 onwards | **16%** | **0.84** |

For a Romanian resident holding US stock, the US withholds 10% and Romania
taxes the gross with a credit, so the total equals the Romanian rate. The
factor applies **per payment, by year of receipt**. Applying 0.84 to a
cumulative column re-taxes 2024-2025. Detail is in
`skills/portfolio-audit/references/tax-treatment.md`. The open questions
belong to the user's advisor.

## Safety

The sheet is a critical report. No change is applied without explicit consent
for that specific batch, given after the diff is shown.

1. The skill asks for consent per risk group and confirms a backup exists.
2. Apps Script defaults to `ALLOW_WRITES = false`. It has a sheet and range
   whitelist, a 60-cell cap and all-or-nothing validation.
3. Every write takes a backup, requires a reason, is logged with the old
   values, and is verified by reading back.

**`ClaudePortofoliu` is the master.** It was promoted on 2026-07-31, and the
backups and the write log are its only safety net.

**The local `.xlsx` is never modified.** It is a dead export: Google functions
have become `__xludf.DUMMYFUNCTION`, and the custom price functions exist only
in Apps Script. `Portofoliu.xlsx` is the pre-migration archive, MD5
`8f671ede51e038f3d8973f9a7456053e`; check against it whenever there is doubt.
Experiments go to copies, recorded in `changesets/`.

## Traps

Permanent properties of this system, each of which has already cost real time.
A fixed trap keeps its entry, because the same shape recurs.

### Writing to the sheet

- **A `bridge_write` can time out with the write already applied.** Never retry
  blind: `bridge_read` the target cells, then retry only what is unchanged.
- **`Dividends received` F/G/H are ARRAYFORMULA spills anchored in F2/G2/H2.**
  Gross = D×E, tax factor = VLOOKUP year on K:L, Net = F×G. A literal written
  into a spill blocks it and silently empties every prior row. New rows get
  **A:E and I only**. A spilled cell looks exactly like a literal unless you
  read the anchor row.
- **The bridge writes cells only.** It cannot insert or delete rows, columns,
  sheets or its own `_bk_*` backups. A manual insert shifts every column
  reference, so **re-read the layout before composing a batch**.
- **Every write adds a backup.** `bridge_prune` (keep 5) previews by default.
  The manual functions in `Code.gs` have deliberately different names,
  because Apps Script shares one global scope and lets a duplicate name
  silently shadow another:
  - `pruneBackups(days)` prunes by age.
  - `pruneKeepLatest()` keeps the newest backup per sheet.
- **Apps Script: pencil-edit the existing deployment → New version.** A new
  deployment mints a new URL, and the bridge returns 404. `node --check` on a
  `.js` copy is the only syntax gate on `Code.gs`. Editor runs execute the
  *saved* code; web actions run the *deployed* version.

### A running session keeps the plugin copy it started with

An install does not reach the session that requested it. Skill and command
text, the config and any **new** tool load at session start. v0.12.0's
`price_dividends` appeared only in the next session. In the old Cowork setup
the stale copy could survive app restarts as well
([anthropics/claude-code#82732](https://github.com/anthropics/claude-code/issues/82732),
[#56678](https://github.com/anthropics/claude-code/issues/56678)).

Check the copy before trusting it:
1. Note the "Base directory" the `Skill` tool announces. The install lives at
   `~/.claude/plugins/marketplaces/local-desktop-app-uploads/dgi-portfolio/`.
2. Read `.claude-plugin/plugin.json` beside it.
3. If the version does not match, start a new session, or use the MCP tools
   directly with `skills/*/references/*.md` from the source tree.

**A green `/audit-live` does not confirm an install.** It runs the script and
the config from the working folder, so it exercises source. Only a probe of
the running copy confirms an install.

### Auditing

- **`audit_formulas.py` reads formulas only** (`data_only=False`), so it is
  blind to a cached `#REF!`. `scan_error_values.py` reads `displayValues` from
  the snapshot. That step is not optional.
- **Never audit the local `.xlsx`.** It has the pre-insert 26-column layout,
  so every check from `L` onward is off by one, and it predates
  `Dividends received`. Do not "fix" the config to match it.
- The 199 dead Google formulas were an export artefact. Live, the count is
  zero, so any dead formula reported now is real.

### Data

- **Every hand-typed value checked so far was wrong or stale:** `N2:N13` (11
  of 12), `R5`, `N16`/`N17` (an annual figure in a per-payment column, 4x
  income), `R2:R18` (a uniform -2 drift). An unchecked manual column does not
  deserve a neutral prior.
- **dripinvesting's `DGR` can be plain wrong.** ZTS showed 1Y -19.3% against
  +13.0% in the filings. A negative DGR from it must be corroborated before it
  disqualifies anything.
- **A feed that returns a well-formed document with zero matches looks like a
  network failure and like an empty period.** BNR moved its XML namespace from
  `http://` to `https://` and the parser silently found nothing.
  `bnr_coverage` tells the three cases apart.
- **The sheet's Gross is shares × rate; IBKR pays cash rounded to the cent.**
  The ±half-cent differences are expected, and the cash received is what the
  tax return needs.

## Data sources

Full detail and measured limits:
`skills/company-analysis/references/data-sources.md`.

| Source | For | Reality |
|---|---|---|
| `dgi-edgar` | statements, EPS, share count, dividends declared and paid | free, no key, full filed history, US filers (`us-gaap` only) |
| `dgi-prices` → `price_annual_averages` | annual average prices, valuation methods 1-5 | Tiingo, split-only, a single uncorroborated source |
| `dgi-prices` → `price_dividends` | dividends per fiscal year, by ex-date, split-adjusted | the same Tiingo rows (`divCash`); independent of EDGAR, not of the prices; specials unmarked, flagged as `outsized_payments` |
| `dgi-alphavantage` → `av_financials` | Visa's share count and GAAP EPS; a check on the EDGAR reader | free key, 25 requests/day; the same SEC filings, so it never corroborates a filing. `eps_reported` is street EPS |
| FMP connector | sector, industry, current price, last dividend | `company` / `profile-symbol` only; `quote` denied since 2026-08-22, `statements` denied for every symbol |
| dripinvesting screener CSV | Chowder, frequency, DGR cross-check | manual download; **its prices and DGR can be wrong** |
| dripinvesting calendar | ex-date and pay date | fetchable |
| `WebSearch` | credit rating and outlook, S&P 500 yield | - |
| `dgi-ibkr-flex` | the user's own payments, withholding, FX; BNR rates | see below |

### EDGAR - what makes it hard

- **Tag mapping is per company.** Each alias in `edgar_core.py` is a ranked
  chain of `(tag, unit)` pairs, and the tag actually used is returned. An
  empty series carries a `note` that says why: an IFRS filer, figures
  reported only per share class, or an ordinary missing tag. Only the last one
  is worth hunting with `edgar_tags`.
- **Picking the annual figure is the whole difficulty.**
  - Quarterly facts sit beside annual ones. SEC's `frame` marks the annual
    ones; a 350-380 day span with `fp=FY` is the fallback.
  - Year-to-date figures span 273 days and pass any naive "longer than a
    quarter" test.
  - The latest `filed` date wins.
  - Balance-sheet values are read at the filer's own fiscal year end.
  - The rule lives in `_annual_series`; read its docstring before changing it.
- **`filed` is the split key, never the fiscal year.** EDGAR restates recent
  years on a post-split basis.
- **Never fetch EDGAR into a conversation.** One `companyconcept` call returned
  ~40KB inline. Facts are cached under `~/.dgi/edgar-cache/` for 24h.

FMP sector names are not GICS (MA is `Financial Services`, not `Financials`).
Translate them through `fmp_sector_to_gics` in the config.

### dripinvesting

```bash
# Screener CSV: manual download from https://www.dripinvesting.org/stocks/
# (the button builds the file client-side, so there is no URL to request)
python3 -B skills/company-analysis/scripts/parse_dripinvesting.py \
    screener stocks-2026-07-31.csv --tickers KO,MO,JNJ
python3 -B skills/company-analysis/scripts/parse_dripinvesting.py \
    screener stocks-2026-07-31.csv --unresolved
python3 -B skills/company-analysis/scripts/parse_dripinvesting.py \
    history ko-history.txt --ticker KO
```

- **`Stock Type` is a bucket.** A Contender (10-24 years) straddles
  criterion 1's 15-year line, so the script reports it as `UNRESOLVED` rather
  than guessing.
- **Its prices are wrong**, not stale: QCOM showed $229.49 against $150.91. The
  script withholds price columns unless `--unsafe-prices` is passed.
- **Its DGR includes specials.** AFG showed 1Y -23.7% while the regular
  dividend rose.

### IBKR Flex Web Service - the account side

Flex is the only IBKR surface that is unattended and **cannot place an order**,
which IBKR itself enforces. TWS needs a logged-in app with daily 2FA, and the
Client Portal API needs a gateway. The IBKR MCP connector has no transaction
history, and its tools include order endpoints.

Setup, once, in Client Portal:
- Enable the Flex Web Service and generate a token.
- Build an Activity Flex Query with Cash Transactions → Dividends and
  Withholding Tax.

The parser depends on these query settings:

| Setting | Value | Why |
|---|---|---|
| Format | **XML** | the parser does not read CSV |
| Date Format | **yyyyMMdd** | year and month are sliced out of `settleDate` |
| Time Format | **HHmmss**, separator `;` | IBKR's own `20230829;101454` shape |
| Period | **Last 365 Calendar Days** | `transactionID` makes overlap free; a short window leaves permanent holes |
| Cash Transactions fields | Symbol, ISIN, Date/Time, SettleDate, Amount, Type, Currency, **FXRateToBase**, Description, TransactionID | `FXRateToBase` is a field in this list, not the "Include Currency Rates?" toggle |

- **The two calls go to two hosts.** SendRequest goes to the configured
  `send_request_url` (ndcdyn), and GetStatement goes to the URL IBKR returns
  (`gdcdyn.interactivebrokers.com`). That second host has failed DNS and hung
  while the first answered. Since v0.11.7 such a failure retries once on the
  configured host, only within `interactivebrokers.com`.
- **`fxRateToBase` converts to the base currency (USD), not to RON.** That is
  why `bnr_rate` exists and `flex_dividends` accepts `convert_to_ron`.
- **BNR rates merge three feeds:** the yearly archive, the 10-day feed and the
  daily feed. On weekends and holidays the lookup falls back to the previous
  publication and says which date it used. Per-100-unit quotes (HUF, JPY) are
  divided out.
- **The rate date** (settlement by default, in one marked place in
  `ibkr_flex_server.py`) is a question for the tax advisor, not a setting.
- **Per-share rates are parsed out of IBKR's prose description.** Rows without
  the pattern (specials, typically) go to `per_share_unparsed`. Only "not ready
  yet" codes are retried; an expired token fails at once.
- **Tools:** `flex_queries`, `flex_fetch`, `flex_dividends`, `flex_trades`,
  `bnr_rate`, `bnr_coverage`. All read-only, and none writes to the sheet.
  Reports refresh once a day.

## Known limitations

- Average-cost verification needs `Jurnal` parsed; its format is irregular.
- Non-US instruments (`SXR8.DE`, `BVBETF` on BVB) do not reconcile
  automatically.
- IFRS filers (20-F) cannot be scored from EDGAR: the reader takes `us-gaap`
  only. Prices and `price_dividends` still work.
- `expected_sectors` must be kept in sync when positions are added.
- Companion plugins (`earnings-reviewer:audit-xls`,
  `equity-research:initiating-coverage`, `equity-research:thesis-tracker`,
  `equity-research:earnings-preview`) are workflows that supply no data.

## Layout

```
claude-dgi/
├── CLAUDE.md                         session bootstrap, non-negotiable rules
├── BACKLOG.md                        work state: open, untested, decided
├── install-plugin.sh                 one-command install, byte-verified
├── Portofoliu.xlsx                   pre-migration archive, never written
├── stocks-2026-07-31.csv             dripinvesting screener download
├── analyses/                         company analyses, one per ticker
├── changesets/                       record of every applied change
├── dgi-portfolio-X.Y.Z.plugin        delivered builds (git-ignored)
├── sheet-snapshot.json               written by /audit-live (git-ignored)
└── dgi-portfolio/
    ├── .claude-plugin/plugin.json
    ├── README.md
    ├── dgi-portfolio.plugin          canonical built archive (tracked)
    ├── config/portfolio.json         column map, row blocks, tax, sectors, limits
    ├── commands/audit-live.md        /audit-live, the 6-step pipeline
    ├── skills/
    │   ├── portfolio-audit/
    │   │   ├── SKILL.md
    │   │   ├── references/
    │   │   │   ├── validation-rules.md
    │   │   │   └── tax-treatment.md
    │   │   └── scripts/
    │   │       ├── audit_formulas.py           15 checks, formulas only
    │   │       ├── scan_error_values.py        cached #REF! scan
    │   │       ├── check_missing_dividends.py  Flex payments absent from the sheet
    │   │       ├── snapshot_fetch.py           CLI twin of bridge_snapshot
    │   │       ├── snapshot_to_xlsx.py         snapshot -> formula-level workbook
    │   │       └── patch_xlsx.py               non-destructive cell patcher
    │   └── company-analysis/
    │       ├── SKILL.md
    │       ├── references/
    │       │   ├── scoring-model.md
    │       │   ├── valuation-methods.md
    │       │   └── data-sources.md
    │       └── scripts/parse_dripinvesting.py
    ├── mcp/
    │   ├── sheet_bridge_server.py    dgi-sheet-bridge
    │   ├── snapshot_core.py
    │   ├── edgar_server.py           dgi-edgar
    │   ├── edgar_core.py
    │   ├── price_server.py           dgi-prices
    │   ├── price_core.py
    │   ├── price_probe.py            layer-by-layer price diagnostic
    │   ├── av_server.py              dgi-alphavantage
    │   ├── av_core.py
    │   ├── ibkr_flex_server.py       dgi-ibkr-flex
    │   └── dot-mcp.json.template     source of .mcp.json
    ├── setup/apps-script/
    │   ├── Code.gs
    │   └── SETUP.md
    └── tests/                        12 unittest files + 3 print-and-assert smoke scripts
```

`.mcp.json` cannot live in the source tree: the Claude app blocks that filename
in a connected folder. The build generates it from the template.

`patch_xlsx.py` edits cells inside the xlsx zip directly. openpyxl, by
contrast, destroys 10 internal parts and every cached value on a Google export.

## Development

### Code layout convention

Extract a `*_core.py` when the logic has, or predictably will have, a second
caller; otherwise keep one file. The server file owns the MCP surface (the
`TOOLS` schemas, `run_tool`, the stdio loop); the core owns the domain logic
and imports nothing MCP-related.

| Server | Shape | Second caller |
|---|---|---|
| `dgi-sheet-bridge` | server + `snapshot_core.py` | `snapshot_fetch.py` |
| `dgi-edgar` | server + `edgar_core.py` | a batch script over all positions |
| `dgi-prices` | server + `price_core.py` | `price_probe.py` |
| `dgi-alphavantage` | server + `av_core.py` | none yet; split so the reduction is testable offline |
| `dgi-ibkr-flex` | one file | none yet. Frozen by user decision (BACKLOG item 7), because it is the only component proven against a real account |

The MCP loop always sits behind `if __name__ == "__main__"`, and
`sys.dont_write_bytecode = True` precedes any sibling import.

### Build

The recipe stages the tree, injects `.mcp.json` from the template, and zips. An
older recipe zipped the source directly, and the archive shipped without
`.mcp.json`, so no server registered.

```bash
cd ~/Desktop/claude-dgi/dgi-portfolio
rm -rf /tmp/dgi-stage && mkdir -p /tmp/dgi-stage
rsync -a --exclude '.DS_Store' --exclude '__pycache__' --exclude '*.pyc' \
         --exclude '*.plugin' ./ /tmp/dgi-stage/
# Strip the template's _comment key: the plugin validator has rejected an
# unknown top-level field once already.
python3 -c "import json; d=json.load(open('mcp/dot-mcp.json.template')); \
json.dump({'mcpServers': d['mcpServers']}, open('/tmp/dgi-stage/.mcp.json','w'), indent=2)"
rm -f /tmp/dgi-portfolio.plugin
(cd /tmp/dgi-stage && zip -rq /tmp/dgi-portfolio.plugin .)
cp /tmp/dgi-portfolio.plugin ./dgi-portfolio.plugin
```

### Five verifications, every build

```bash
unzip -p dgi-portfolio.plugin .claude-plugin/plugin.json | python3 -c "
import json,sys
d=json.load(sys.stdin); n=len(d['description'])
assert n<=500, f'description {n} > 500'
print(f'description {n}/500, v{d[\"version\"]}')"
unzip -p dgi-portfolio.plugin .mcp.json | python3 -c "
import json,sys; print('servers:', list(json.load(sys.stdin)['mcpServers']))"
unzip -l dgi-portfolio.plugin | grep -E 'commands/|mcp/|__pycache__'
rm -rf /tmp/pb && mkdir -p /tmp/pb && unzip -q -d /tmp/pb ./dgi-portfolio.plugin
for f in $(cd /tmp/pb && find . -type f | sed 's|^\./||'); do
  [ "$f" = ".mcp.json" ] && continue          # bundle-only by design
  cmp -s "/tmp/pb/$f" "./$f" || echo "STALE IN BUNDLE: $f"
done
```

What each check catches:
1. **`description` ≤ 500 characters.** The validator rejects anything longer
   at install time.
2. **`.mcp.json` lists all five servers.** A missing one fails silently: the
   plugin installs and the tools are simply absent.
3. **`commands/` is present and `__pycache__` is absent.**
4. **Staleness: every bundled file matches source.** **An empty output is the
   pass condition.** A shipped skill was once 85 minutes behind its source and
   gave wrong instructions for two days without failing loudly.

`tests/test_packaged_plugin.py` asserts all of this on the tracked archive. A
missing archive counts as a failure, not a skip. It cannot prove the
*install*: that is a probe of the running copy, from a new session.

**Every rebuild that changes shipped content gets a version bump**, docs
included. Put the archive at
`~/Desktop/claude-dgi/dgi-portfolio-X.Y.Z.plugin` and deliver it into the
conversation when a file tool exists (`SendUserFile` in Cowork). Then give the
`install-plugin.sh` command as one `bash` block. Editing a test makes the tree
one file ahead of the archive, and the test says so: rebuild.

### Bytecode

- Use `python3 -B` for every invocation.
- Run tests from a scratch copy, never inside the source tree.
- **`python3 -m py_compile` writes bytecode even under `-B`**, so never use it
  as a syntax check. Use
  `python3 -B -c "import ast; ast.parse(open(f).read())"`.
- In a mounted (Cowork) folder, removing `__pycache__` needs the folder's
  delete permission.

## Methodology

Based on *"Cum analizez o companie"* - Dividende.blog, 10 January 2021:
<https://www.dividende.blog/stiri/cum-analizez-o-companie>. Scoring thresholds
are transcribed verbatim, including the DGR matrix keyed to yield bucket and
the REIT payout columns.

Not financial advice.
