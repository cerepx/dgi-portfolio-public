# Google Sheets bridge setup

About 15 minutes, once.

## Why Apps Script and not a connector

The Google Drive MCP exposes `create_file`, `read_file_content` and `search_files`.
It can read and create files, but it **cannot write a cell**. There is no
cell-level write through it.

Apps Script runs *inside* the sheet. It sees formulas as they are, not as exported.
It does not route OAuth credentials through a third-party server. It can be revoked
instantly by deleting the deployment. And it writes cell by cell with automatic
backups.

## Steps

### 1. Open the script editor

In the portfolio sheet: `Extensions > Apps Script`.

### 2. Paste the code

Delete the contents of `Code.gs` and paste the full contents of `Code.gs` from this
folder. Save with `Ctrl+S`.

### 3. Generate the token

In the editor, pick `generateToken` from the function dropdown next to Run, then
press **Run**.

The first run asks for permissions: `Review permissions` > choose the account >
`Advanced` > `Go to <project name> (unsafe)` > `Allow`.

The "unsafe" warning appears for any script not published to the Marketplace. This
is your own script in your own sheet.

Open `Execution log` (`Ctrl+Enter`) and copy the token. It is 48 characters.

### 4. Deploy as a web app

`Deploy > New deployment` > gear icon > `Web app`:

| Field | Value |
|---|---|
| Description | `DGI bridge v1` |
| Execute as | **Me** |
| Who has access | **Anyone** |

Copy the **Web app URL** (ends in `/exec`).

> "Anyone" looks alarming, but without a valid token every request is rejected. The
> token is the only gate. Never put it in config, in chat, or in git. If it leaks,
> run `generateToken` again - the old one is invalidated immediately.

### 5. Wire it into the plugin

Fill in `config/portfolio.json`:

```json
"google_sheet": {
  "spreadsheet_id": "1AbC...",
  "url": "https://docs.google.com/spreadsheets/d/1AbC.../edit",
  "apps_script_webapp_url": "https://script.google.com/macros/s/AKfy.../exec"
}
```

The token goes in an environment variable, **not** in config:

```bash
export DGI_SHEET_TOKEN="your_48_character_token"
```

For persistence, add that line to `~/.zshrc`.

### 6. Verify

```bash
curl -s -X POST "$WEBAPP_URL" -H 'Content-Type: application/json' \
  -d '{"token":"'"$DGI_SHEET_TOKEN"'","action":"ping"}'
```

Expected:

```json
{"ok":true,"spreadsheet":"Portofoliu","writesAllowed":false,...}
```

`writesAllowed: false` is correct and intentional.

---

## Available actions

Everything is **POST with a JSON body**. GET is refused by design: a GET can
only carry the token in the URL, and URLs end up in logs. (Until 2026-07-31
the bridge accepted GET with `token=` in the query string; that surface was
removed.)

| Action | Purpose |
|---|---|
| `ping` | Check the connection and write state |
| `structure` | List sheets, sizes, which are writable |
| `read` | Values (and optionally formulas/formats) for a range |
| `write` | Apply changes, with automatic backup |
| `backup` | Hidden copy of a sheet |
| `log` | Write history |

### Reading

```bash
curl -s -X POST "$WEBAPP_URL" -H 'Content-Type: application/json' -d '{
  "token": "'"$DGI_SHEET_TOKEN"'",
  "action": "read", "sheet": "MyShares", "range": "A1:Y30",
  "fields": "values,formulas"
}'
```

Returns **display values only by default**. `fields` selects representations:
`values`, `formulas`, `raw` (unformatted values), `formats` (number formats),
`all` — as a comma-separated string or array. The old behaviour of always
returning all four was the single largest context cost in practice; ask for
`all` only when the audit genuinely needs every representation. Unknown field
names are an error, not a silent default.

### Writing

Disabled by default. To enable:

1. In `Code.gs`, change `const ALLOW_WRITES = false;` to `true`.
2. `Deploy > Manage deployments` > pencil > `Version: New version` > `Deploy`.
3. Apply the changes.
4. **Set it back to `false` and redeploy.**

```bash
curl -s -X POST "$WEBAPP_URL" -H 'Content-Type: application/json' -d '{
  "token": "'"$DGI_SHEET_TOKEN"'",
  "action": "write",
  "reason": "Fix sector labels: MA and V moved to Financials in the 2023 GICS reclassification",
  "changes": [
    {"sheet":"MyShares","cell":"U16","value":"Financials"},
    {"sheet":"MyShares","cell":"U17","value":"Financials"},
    {"sheet":"MyShares","cell":"U23","value":"Communication Services"}
  ]
}'
```

## Built-in protections

| Protection | Effect |
|---|---|
| Token required | Every action rejected without it |
| `ALLOW_WRITES = false` | Writes refused by default |
| `WRITE_WHITELIST` | Only listed sheets, only within the declared range |
| `MAX_CELLS_PER_REQUEST = 60` | One request cannot rewrite the sheet |
| All-or-nothing validation | One invalid cell aborts the entire batch before any write |
| Automatic backup | Hidden copy of each touched sheet before any change |
| `reason` required | No write without a logged justification |
| Read-back verification | Every cell re-read and the result returned |
| `_DGI_Log` sheet | Timestamp, reason, cell, old and new value |

Backup sheets are named `_bk_<sheet>_<date-time>` and hidden. Run `pruneBackups(30)`
from the editor occasionally, or they accumulate.

## Recovering from a mistake

1. `File > Version history > See version history` - Google keeps granular versions.
   Fastest route.
2. The `_bk_...` sheet created immediately before the write.
3. The `_DGI_Log` sheet holds the exact old values, cell by cell.

## Shutting it down

`Deploy > Manage deployments` > `Archive`. The URL goes dead immediately. For
maximum certainty, also delete `DGI_TOKEN` from
`Project Settings > Script Properties`.

## Part B - the custom price functions

`Code.gs` also contains two custom spreadsheet functions covering instruments
`GOOGLEFINANCE` does not:

| Cell | Function | Instrument |
|---|---|---|
| `E24` | `getYahooPrice("SXR8.DE")` | iShares Core S&P 500 UCITS, Xetra, EUR |
| `E25` | `getBVBPrice("BVBETF")` | Bucharest Stock Exchange, RON |

They are in the same file as the web app only because Apps Script shares one global
namespace across every file in a project - splitting them bought nothing but an extra
thing to paste. They are otherwise unrelated: the web app is token-gated and never
called from a cell; these are called from cells and have no auth and no side effects.

### What was fixed

| Defect | Before | Now |
|---|---|---|
| Thousands separator | `parseFloat("1.234,56".replace(',','.'))` returned `1.234` - a silent division by a thousand | `parseRomanianNumber()` decides the decimal separator by whichever appears last, strips thousands groups. 9 cases tested |
| BVB label regex | matched `Ultimul pret` literally; broke on a diacritic, extra whitespace or uppercase | `/Ultimul\s*pre[tţț]\s*<\/td>\s*<td[^>]*>\s*([\d.,]+)/i` - verified against 6 markup variants |
| Failure returns | returned the strings `"N/A"` / `"Not found"`, which turn `F=D*E` into `#VALUE!` | `throw new Error(...)` - the cell shows `#ERROR!` with a specific message on hover |
| Repeated fetches | every recalculation hit the source | `CacheService`, 15 minutes, per ticker |

Neither function ever falls back to a stale price. A plausible wrong number is the
failure mode worth avoiding most - an error you can see beats a price you cannot
trust.

### Freshness

Custom functions **cannot write to the sheet**, so they cannot stamp their own
timestamp. Google caches their results per argument set, and with constant arguments
a value persists through a session; it does refresh when the spreadsheet is reopened.

If you want a guaranteed periodic refresh and a visible marker, run once from the
editor:

```
installPriceRefreshTrigger()
```

That installs a daily trigger for `refreshPrices()`, which clears the price cache,
rewrites the two formulas in place to force recalculation - **the cells stay
formulas, nothing is replaced by a literal** - and writes the current time to
`MyShares!AC1`. Change `PRICE_TIMESTAMP_CELL` at the top of `Code.gs` to move it.
(It was `AA1` until 2026-07-31, when a column insert put the DGI header there.)

The trigger fires at 20:00 in the script's time zone, after both Xetra and BVB have
closed.

### Protecting totals from a scraping failure

`E24` and `E25` are rows 24 and 25. The row 27 totals are `SUM(x2:x19)`, so they do
**not** currently include those rows and an `#ERROR!` there cannot reach them.

That changes the moment total portfolio value is extended to cover the non-DGI block.
If that happens, wrap the aggregates so one broken position cannot take the whole
total with it:

```
=SUMIF(F2:F26, "<>#ERROR!")
```

or keep the price in a helper column and let the total read only numeric values.

### Dependency risk

`query1.finance.yahoo.com/v8/finance/chart/` is undocumented and unversioned, and has
required cookies plus a crumb parameter at times. The BVB function scrapes HTML.
Neither is a stable contract. Both now fail loudly rather than silently, which is the
most that can be done from inside the sheet.
