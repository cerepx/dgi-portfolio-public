/**
 * DGI portfolio - single Apps Script file.
 *
 * Two independent things live here. They are in one file only because Apps Script
 * shares one global namespace across every file in a project anyway, so splitting
 * them bought nothing but an extra thing to copy.
 *
 *   PART A - read/write web app bridge (doGet / doPost)
 *            Token-gated. Writes disabled by default. Used by tooling, never by
 *            a spreadsheet cell.
 *
 *   PART B - custom price functions (getYahooPrice / getBVBPrice)
 *            Called directly from cells. No auth, no side effects, read-only.
 *            They cover instruments GOOGLEFINANCE does not:
 *              MyShares!E24 = getYahooPrice("SXR8.DE")    Xetra, EUR
 *              MyShares!E25 = getBVBPrice("BVBETF")     Bucharest, RON
 *
 * Setup: see SETUP.md
 */

// ============================ PART A CONFIGURATION ============================

/** Set ALLOW_WRITES to true only when you actually intend to apply changes.
 *  Recommended: leave it false, flip it to true for the change session, then
 *  set it back to false and redeploy. */
const ALLOW_WRITES = false;

/** Sheets that may be written to, and the maximum range per sheet.
 *  Nothing outside this list can be modified, even by accident.
 *  Widened 2026-07-31 to match the live deployment. 'Watchlist' dropped - the
 *  sheet does not exist in ClaudePortofoliu; re-add it if it is ever created. */
const WRITE_WHITELIST = {
  'MyShares':            'A1:AE100',
  'Dividends received':  'A1:L2000',
  'Cresteri Dividende':  'A1:X100',
  'Dividende lunare':    'A1:K100',
  'Evolutie':            'A1:Z1000',
  'Jurnal':              'A1:K100',
};

/** Maximum number of cells modified in a single request. */
const MAX_CELLS_PER_REQUEST = 60;

/** Name of the audit log sheet. Created automatically. */
const LOG_SHEET = '_DGI_Log';

// ============================ PART B CONFIGURATION ============================

/** How long a fetched price stays cached, in seconds. Caps how often the sources
 *  are hit during a single working session. Not a freshness guarantee. */
const PRICE_CACHE_SECONDS = 900;  // 15 minutes

/** Cell that records when prices were last refreshed by the scheduled trigger.
 *  Custom functions cannot write to the sheet, so only the trigger stamps this.
 *  AC1, not AA1: the 2026-07-31 column insert moved the DGI header into AA1,
 *  and the trigger stamping there would have silently destroyed it. */
const PRICE_TIMESTAMP_CELL = 'MyShares!AC1';

// ============================ ENTRY POINTS ============================

// POST only. GET is refused because a GET request can only carry the token in
// the URL, and URLs end up in logs; the README's "the token never travels in a
// URL" promise is enforced here, not just documented.
function doGet(e) {
  return respond({
    ok: false,
    error: 'GET is not supported: it would put the token in the URL. ' +
           'POST a JSON body with {token, action, ...}.'
  });
}
function doPost(e) { return handle(e, 'POST'); }

function handle(e, method) {
  try {
    const params = (e && e.parameter) ? e.parameter : {};
    let body = {};
    if (method === 'POST' && e.postData && e.postData.contents) {
      body = JSON.parse(e.postData.contents);
    }

    // Token from the POST body ONLY - never from the query string.
    const token = body.token;
    if (!verifyToken(token)) {
      return respond({ ok: false, error: 'Invalid or missing token.' });
    }

    const action = params.action || body.action;
    switch (action) {
      case 'ping':      return respond(ping());
      case 'structure': return respond(structure());
      case 'read':      return respond(read(
                                params.sheet || body.sheet,
                                params.range || body.range,
                                String(params.formulasOnly || body.formulasOnly) === 'true',
                                params.fields || body.fields));
      case 'write':     return respond(write(body));
      case 'backup':    return respond(backup(body.sheet || params.sheet));
      case 'log':       return respond(readLog(Number(params.limit || body.limit || 50)));
      case 'prune':     return respond(prune(body));
      default:
        return respond({
          ok: false,
          error: 'Unknown action: ' + action,
          actions: ['ping', 'structure', 'read', 'write', 'backup', 'log']
        });
    }
  } catch (err) {
    return respond({ ok: false, error: String(err), stack: err.stack });
  }
}

function verifyToken(token) {
  const expected = PropertiesService.getScriptProperties().getProperty('DGI_TOKEN');
  if (!expected || !token) return false;
  if (token.length !== expected.length) return false;
  // constant-time comparison
  let diff = 0;
  for (let i = 0; i < expected.length; i++) {
    diff |= token.charCodeAt(i) ^ expected.charCodeAt(i);
  }
  return diff === 0;
}

function respond(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

// ============================ READ ============================

function ping() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  return {
    ok: true,
    spreadsheet: ss.getName(),
    id: ss.getId(),
    writesAllowed: ALLOW_WRITES,
    timeZone: ss.getSpreadsheetTimeZone(),
    now: new Date().toISOString()
  };
}

function structure() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  return {
    ok: true,
    sheets: ss.getSheets().map(function (sh) {
      return {
        name: sh.getName(),
        rows: sh.getLastRow(),
        columns: sh.getLastColumn(),
        hidden: sh.isSheetHidden(),
        writable: !!WRITE_WHITELIST[sh.getName()]
      };
    })
  };
}

/** Reads a range. `fields` (array or comma-separated string) picks which
 *  representations to return: 'values' (display values), 'formulas', 'raw'
 *  (unformatted values), 'formats' (number formats), or 'all'. Default is
 *  values only - the old always-all-four payload was measured on 2026-07-31
 *  as the project's single largest context cost, so it is now behind an
 *  explicit opt-in. Legacy `formulasOnly` is still honoured. Unknown field
 *  names are an error, not a silent default: a caller that typos a field
 *  must find out, not quietly analyse the wrong representation. */
function read(sheetName, range, formulasOnly, fields) {
  const sh = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(sheetName);
  if (!sh) return { ok: false, error: 'No such sheet: ' + sheetName };

  let want;
  if (formulasOnly) {
    want = { formulas: true };
  } else if (fields && String(fields).length) {
    const list = Array.isArray(fields) ? fields : String(fields).split(',');
    want = {};
    const unknown = [];
    list.forEach(function (f) {
      f = String(f).trim().toLowerCase();
      if (f === 'all') {
        want.values = want.formulas = want.raw = want.formats = true;
      } else if (f === 'values') { want.values = true;
      } else if (f === 'formulas') { want.formulas = true;
      } else if (f === 'raw') { want.raw = true;
      } else if (f === 'formats') { want.formats = true;
      } else if (f !== '') { unknown.push(f); }
    });
    if (unknown.length) {
      return { ok: false,
               error: 'Unknown fields: ' + unknown.join(', ') +
                      '. Valid: values, formulas, raw, formats, all.' };
    }
  } else {
    want = { values: true };
  }

  const rng = range ? sh.getRange(range) : sh.getDataRange();
  const result = { ok: true, sheet: sheetName, range: rng.getA1Notation() };
  if (want.values)   result.displayValues = rng.getDisplayValues();
  if (want.formulas) result.formulas = rng.getFormulas();
  if (want.raw)      result.rawValues = rng.getValues();
  if (want.formats)  result.numberFormats = rng.getNumberFormats();
  return result;
}

// ============================ WRITE ============================

/**
 * Expected body:
 * {
 *   "token": "...",
 *   "action": "write",
 *   "reason": "Fix non-DGI weight denominators in column L",
 *   "changes": [
 *     { "sheet": "MyShares", "cell": "U16", "value": "Financials" },
 *     { "sheet": "MyShares", "cell": "L22", "value": "=F22/$F$28" }
 *   ]
 * }
 */
function write(body) {
  if (!ALLOW_WRITES) {
    return {
      ok: false,
      error: 'Writes are disabled. Set ALLOW_WRITES = true in Code.gs and redeploy ' +
             'to apply changes. Recommended: set it back to false afterwards.'
    };
  }

  const changes = body.changes;
  if (!Array.isArray(changes) || changes.length === 0) {
    return { ok: false, error: 'Missing "changes" array.' };
  }
  if (!body.reason) {
    return { ok: false, error: 'Missing "reason". Every change set must be justified in the log.' };
  }
  if (changes.length > MAX_CELLS_PER_REQUEST) {
    return {
      ok: false,
      error: 'Too many cells (' + changes.length + '). Maximum ' +
             MAX_CELLS_PER_REQUEST + ' per request. Split into smaller batches.'
    };
  }

  const ss = SpreadsheetApp.getActiveSpreadsheet();

  // Validate everything BEFORE writing anything - all or nothing.
  const touchedSheets = {};
  for (let i = 0; i < changes.length; i++) {
    const c = changes[i];
    if (!c.sheet || !c.cell) {
      return { ok: false, error: 'Change ' + i + ' is missing sheet or cell.' };
    }
    const allowed = WRITE_WHITELIST[c.sheet];
    if (!allowed) {
      return { ok: false, error: 'Sheet "' + c.sheet + '" is not in WRITE_WHITELIST.' };
    }
    const sh = ss.getSheetByName(c.sheet);
    if (!sh) return { ok: false, error: 'No such sheet: ' + c.sheet };

    try {
      sh.getRange(c.cell);
    } catch (err) {
      return { ok: false, error: 'Invalid cell reference: ' + c.cell };
    }
    if (!withinRange(sh, c.cell, allowed)) {
      return {
        ok: false,
        error: 'Cell ' + c.sheet + '!' + c.cell + ' is outside the allowed range ' + allowed
      };
    }
    touchedSheets[c.sheet] = true;
  }

  // Backup every sheet about to be touched.
  const backups = [];
  for (const name in touchedSheets) {
    const result = backup(name);
    if (!result.ok) return { ok: false, error: 'Backup failed for ' + name };
    backups.push(result.copy);
  }

  // Apply.
  const applied = [];
  for (let i = 0; i < changes.length; i++) {
    const c = changes[i];
    const rng = ss.getSheetByName(c.sheet).getRange(c.cell);
    const oldValue = rng.getFormula() || rng.getValue();

    if (c.value === '' || c.value === null) {
      rng.clearContent();
    } else if (typeof c.value === 'string' && c.value.charAt(0) === '=') {
      // setValue() with a formula string can silently reset the cell's
      // number format (observed 2026-08-21 on Evolutie!H2:J4 - explicit
      // currency formats were wiped after a formula write). setFormula()
      // writes the same formula without touching formatting.
      rng.setFormula(c.value);
    } else {
      rng.setValue(c.value);
    }

    applied.push({
      sheet: c.sheet,
      cell: c.cell,
      oldValue: String(oldValue),
      newValue: String(c.value)
    });
  }

  SpreadsheetApp.flush();

  // Read back to verify.
  for (let i = 0; i < applied.length; i++) {
    const a = applied[i];
    const rng = ss.getSheetByName(a.sheet).getRange(a.cell);
    a.resultingDisplay = String(rng.getDisplayValue());
    a.resultingFormula = rng.getFormula();
  }

  writeLog(body.reason, applied, backups);

  return {
    ok: true,
    reason: body.reason,
    backups: backups,
    changesApplied: applied.length,
    details: applied
  };
}

function withinRange(sheet, cell, allowedRange) {
  const c = sheet.getRange(cell);
  const a = sheet.getRange(allowedRange);
  return c.getRow() >= a.getRow() &&
         c.getLastRow() <= a.getLastRow() &&
         c.getColumn() >= a.getColumn() &&
         c.getLastColumn() <= a.getLastColumn();
}

function backup(sheetName) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sh = ss.getSheetByName(sheetName);
  if (!sh) return { ok: false, error: 'No such sheet: ' + sheetName };

  const stamp = Utilities.formatDate(new Date(), ss.getSpreadsheetTimeZone(), 'yyyyMMdd-HHmmss');
  const copyName = '_bk_' + sheetName + '_' + stamp;
  const copy = sh.copyTo(ss).setName(copyName);
  copy.hideSheet();
  return { ok: true, copy: copyName };
}

// ============================ LOG ============================

function writeLog(reason, applied, backups) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let log = ss.getSheetByName(LOG_SHEET);
  if (!log) {
    log = ss.insertSheet(LOG_SHEET);
    log.appendRow(['Timestamp', 'Reason', 'Sheet', 'Cell', 'Old value',
                   'New value', 'Resulting display', 'Backup']);
    log.setFrozenRows(1);
    log.hideSheet();
  }
  const now = new Date();
  const backupList = backups.join(', ');
  for (let i = 0; i < applied.length; i++) {
    const a = applied[i];
    log.appendRow([now, reason, a.sheet, a.cell, a.oldValue, a.newValue,
                   a.resultingDisplay, backupList]);
  }
}

function readLog(limit) {
  const log = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(LOG_SHEET);
  if (!log) return { ok: true, entries: [], note: 'No writes performed yet.' };
  const last = log.getLastRow();
  if (last < 2) return { ok: true, entries: [] };
  const start = Math.max(2, last - limit + 1);
  return { ok: true, entries: log.getRange(start, 1, last - start + 1, 8).getDisplayValues() };
}

// ================================================================
// PART B - CUSTOM PRICE FUNCTIONS
// ================================================================
//
// Called from spreadsheet cells. Constraints that shape the code below:
//   - Custom functions CANNOT write to the sheet, so they cannot stamp a
//     timestamp themselves. Only refreshPrices() can, and only via a trigger.
//   - Results are cached by Google per argument set. With constant arguments a
//     value can persist across a session; it does refresh when the spreadsheet
//     is reopened, which matches how this report is actually used.
//   - On failure they throw. The cell shows #ERROR! with the message on hover,
//     which is loud and specific. They never fall back to a stale price - a
//     plausible wrong number is the failure mode worth avoiding most.

/**
 * Last traded price from Yahoo Finance.
 * Use for instruments GOOGLEFINANCE does not cover, e.g. European listings.
 *
 * @param {string} ticker Yahoo symbol, e.g. "SXR8.DE"
 * @param {*} [refreshToken] Optional. Ignored. Point it at a cell that changes
 *        if you ever want to force recalculation on a schedule.
 * @return {number} Price in the listing currency.
 * @customfunction
 */
function getYahooPrice(ticker, refreshToken) {
  if (!ticker || typeof ticker !== 'string') {
    throw new Error('getYahooPrice: ticker must be a non-empty string');
  }
  ticker = ticker.trim();

  const cache = CacheService.getScriptCache();
  const key = 'yh_' + ticker;
  const cached = cache.get(key);
  if (cached !== null) return Number(cached);

  const url = 'https://query1.finance.yahoo.com/v8/finance/chart/' +
              encodeURIComponent(ticker);
  const options = {
    muteHttpExceptions: true,
    headers: {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
      'Accept': 'application/json'
    }
  };

  const response = UrlFetchApp.fetch(url, options);
  const status = response.getResponseCode();
  if (status !== 200) {
    throw new Error('Yahoo returned HTTP ' + status + ' for ' + ticker);
  }

  let data;
  try {
    data = JSON.parse(response.getContentText());
  } catch (e) {
    throw new Error('Yahoo returned unparseable JSON for ' + ticker);
  }

  const result = data && data.chart && data.chart.result && data.chart.result[0];
  if (!result || !result.meta) {
    throw new Error('No data for ticker ' + ticker + ' - check the symbol suffix');
  }

  const price = result.meta.regularMarketPrice;
  if (typeof price !== 'number' || !isFinite(price) || price <= 0) {
    throw new Error('Yahoo gave no usable price for ' + ticker +
                    ' (got ' + price + ')');
  }

  cache.put(key, String(price), PRICE_CACHE_SECONDS);
  return price;
}


/**
 * Last traded price from the Bucharest Stock Exchange.
 *
 * @param {string} ticker BVB symbol, e.g. "BVBETF"
 * @param {*} [refreshToken] Optional. Ignored. See getYahooPrice.
 * @return {number} Price in RON.
 * @customfunction
 */
function getBVBPrice(ticker, refreshToken) {
  if (!ticker || typeof ticker !== 'string') {
    throw new Error('getBVBPrice: ticker must be a non-empty string');
  }
  ticker = ticker.trim();

  const cache = CacheService.getScriptCache();
  const key = 'bvb_' + ticker;
  const cached = cache.get(key);
  if (cached !== null) return Number(cached);

  const url = 'https://www.bvb.ro/FinancialInstruments/Details/' +
              'FinancialInstrumentsDetails.aspx?s=' + encodeURIComponent(ticker);
  const options = {
    muteHttpExceptions: true,
    headers: {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
  };

  const response = UrlFetchApp.fetch(url, options);
  const status = response.getResponseCode();
  if (status !== 200) {
    throw new Error('BVB returned HTTP ' + status + ' for ' + ticker);
  }

  const html = response.getContentText();

  // Tolerate the diacritic BVB may or may not render, extra whitespace inside the
  // label cell, and any attributes on the value cell. The original regex matched
  // "Ultimul pret" literally and broke on all three.
  const match = html.match(
    /Ultimul\s*pre[tţț]\s*<\/td>\s*<td[^>]*>\s*([\d.,]+)/i);
  if (!match) {
    throw new Error('Could not find the price on the BVB page for ' + ticker +
                    ' - the page layout or label has probably changed');
  }

  const price = parseRomanianNumber(match[1]);
  if (!isFinite(price) || price <= 0) {
    throw new Error('BVB price for ' + ticker + ' did not parse: ' + match[1]);
  }

  cache.put(key, String(price), PRICE_CACHE_SECONDS);
  return price;
}


/**
 * Parse a number in Romanian format, where "." groups thousands and "," is the
 * decimal separator.
 *
 * The previous implementation used replace(',', '.') alone, which turned
 * "1.234,56" into 1.234 - a silent division by a thousand with no visible symptom.
 * String.replace with a string argument also only replaces the first occurrence,
 * so "1.234.567,89" kept its second dot.
 *
 * @param {string} text e.g. "1.234,56"
 * @return {number} e.g. 1234.56
 */
function parseRomanianNumber(text) {
  if (typeof text !== 'string') return NaN;
  const cleaned = text.trim().replace(/\s/g, '');
  const lastComma = cleaned.lastIndexOf(',');
  const lastDot = cleaned.lastIndexOf('.');

  // Whichever separator appears last is the decimal one. If only dots are
  // present and they look like thousands groups, treat them as such.
  if (lastComma > lastDot) {
    return parseFloat(cleaned.replace(/\./g, '').replace(',', '.'));
  }
  if (lastDot > lastComma) {
    if (/^\d{1,3}(\.\d{3})+$/.test(cleaned)) {
      return parseFloat(cleaned.replace(/\./g, ''));  // 1.234 means 1234
    }
    return parseFloat(cleaned.replace(/,/g, ''));     // already decimal-dot
  }
  return parseFloat(cleaned);
}


/**
 * Refresh the custom prices and stamp the time.
 *
 * Custom functions cannot write to the sheet, so this exists to give the report a
 * visible freshness marker. Attach it to a time-driven trigger with
 * installPriceRefreshTrigger(), or run it manually.
 *
 * It clears the price cache and rewrites each formula in place, which forces
 * recalculation. The formulas stay formulas - nothing is replaced by a literal.
 */
function refreshPrices() {
  CacheService.getScriptCache().removeAll(['yh_SXR8.DE', 'bvb_BVBETF']);

  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = spreadsheet.getSheetByName('MyShares');
  if (!sheet) {
    Logger.log('refreshPrices: sheet MyShares not found');
    return;
  }

  ['E24', 'E25'].forEach(function (a1) {
    const range = sheet.getRange(a1);
    const formula = range.getFormula();
    if (formula) {
      range.setFormula('');
      SpreadsheetApp.flush();
      range.setFormula(formula);
    }
  });
  SpreadsheetApp.flush();

  const stampCell = PRICE_TIMESTAMP_CELL.split('!');
  spreadsheet.getSheetByName(stampCell[0]).getRange(stampCell[1])
    .setValue(new Date());

  Logger.log('refreshPrices: E24=' + sheet.getRange('E24').getDisplayValue() +
             '  E25=' + sheet.getRange('E25').getDisplayValue());
}


/** Install a daily trigger for refreshPrices(). Run once from the editor. */
function installPriceRefreshTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (trigger) {
    if (trigger.getHandlerFunction() === 'refreshPrices') {
      ScriptApp.deleteTrigger(trigger);
    }
  });
  ScriptApp.newTrigger('refreshPrices')
    .timeBased()
    .everyDays(1)
    .atHour(20)          // after both Xetra and BVB have closed
    .create();
  Logger.log('Daily refreshPrices trigger installed for ~20:00 script time zone.');
}


// ============================ UTILITY ============================

/** Run once manually from the editor to generate and reveal the token. */
function generateToken() {
  const token = Utilities.getUuid().replace(/-/g, '') +
                Utilities.getUuid().replace(/-/g, '').slice(0, 16);
  PropertiesService.getScriptProperties().setProperty('DGI_TOKEN', token);
  Logger.log('DGI_TOKEN = ' + token);
  Logger.log('Copy it into the DGI_SHEET_TOKEN environment variable. Never put it in config.');
  return token;
}

/** Run manually to delete backup sheets older than the given number of days.
 *  Useless for clearing a burst of backups made in one session - they are all
 *  the same age. Use pruneKeepLatest() for that. */
function pruneBackups(olderThanDays) {
  const days = olderThanDays || 30;
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const cutoff = new Date().getTime() - days * 24 * 60 * 60 * 1000;
  let removed = 0;
  ss.getSheets().forEach(function (sh) {
    const name = sh.getName();
    const match = name.match(/^_bk_.*_(\d{8})-(\d{6})$/);
    if (!match) return;
    const d = match[1], t = match[2];
    const when = new Date(
      Number(d.slice(0, 4)), Number(d.slice(4, 6)) - 1, Number(d.slice(6, 8)),
      Number(t.slice(0, 2)), Number(t.slice(2, 4)), Number(t.slice(4, 6))
    ).getTime();
    if (when < cutoff) { ss.deleteSheet(sh); removed++; }
  });
  Logger.log('Removed ' + removed + ' backup sheet(s) older than ' + days + ' days.');
  return removed;
}

/* --------------------------- BACKUP PRUNING BY GENERATION -------------------
 * Keeps the most recent backup per source sheet and drops the rest, regardless
 * of age. This is the one to use after a working session, where every backup
 * was created within the same hour and the age-based prune above matches none.
 *
 * Backup names are '_bk_<sourceSheet>_<yyyyMMdd-HHmmss>'. Source names may
 * contain underscores and spaces ('Dividends received'), so the timestamp is
 * split off from the RIGHT, never by splitting on '_' left to right.
 * -------------------------------------------------------------------------- */

const BACKUP_STAMP_RE = /_(\d{8}-\d{6})$/;

/** DRY RUN. Logs what would be deleted and what would be kept. Changes nothing.
 *  Run this first, read the log, then run pruneKeepLatest(). */
function previewPruneKeepLatest() {
  const plan = planKeepLatest_();
  Logger.log('KEEP (' + plan.keep.length + '):');
  plan.keep.forEach(function (n) { Logger.log('  ' + n); });
  Logger.log('DELETE (' + plan.drop.length + '):');
  plan.drop.forEach(function (n) { Logger.log('  ' + n); });
  return plan;
}

/** Deletes every backup except the most recent one per source sheet.
 *  Irreversible. Run previewPruneKeepLatest() first. */
function pruneKeepLatest() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const plan = planKeepLatest_();

  if (plan.drop.length === 0) {
    Logger.log('Nothing to prune.');
    return 0;
  }

  plan.drop.forEach(function (name) {
    ss.deleteSheet(ss.getSheetByName(name));
  });

  Logger.log('Deleted ' + plan.drop.length + ', kept ' + plan.keep.length + '.');
  return plan.drop.length;
}

/** Deletes ALL backups, including the most recent per source sheet.
 *  Only sensible right after verifying the spreadsheet is in a good state. */
function pruneAllBackups() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const names = backupSheetNames_(ss);

  names.forEach(function (name) {
    ss.deleteSheet(ss.getSheetByName(name));
  });

  Logger.log('Deleted all ' + names.length + ' backup sheet(s).');
  return names.length;
}

function backupSheetNames_(ss) {
  return ss.getSheets()
    .map(function (s) { return s.getName(); })
    .filter(function (n) { return n.indexOf('_bk_') === 0; });
}

/** Web action: prune backup sheets, keeping the newest N per source sheet.
 *
 *  Deleting sheets is irreversible and backups are the only safety net now
 *  that ClaudePortofoliu is the master, so this is guarded twice:
 *
 *    - `apply` defaults to FALSE. Without it this is a dry run and returns
 *      the plan only, which is what the caller must show the user first.
 *    - Applying requires ALLOW_WRITES, exactly like a cell write. A read-only
 *      deployment can preview a prune but can never perform one.
 *
 *  `keep` defaults to 5 and is clamped to at least 1 downstream.
 */
function prune(body) {
  body = body || {};
  const keep = Number(body.keep === undefined ? 5 : body.keep);
  const apply = body.apply === true || body.apply === 'true';

  const plan = planKeepN_(keep);

  if (!apply) {
    return {
      ok: true,
      dryRun: true,
      keepPerSheet: plan.keepPerSheet,
      wouldKeep: plan.keep,
      wouldDelete: plan.drop,
      note: 'Nothing was deleted. Re-send with apply=true to perform it.'
    };
  }

  if (!ALLOW_WRITES) {
    return {
      ok: false,
      error: 'Writes are disabled, and pruning deletes sheets. Set ' +
             'ALLOW_WRITES = true in Code.gs and redeploy (pencil-edit the ' +
             'existing deployment, New version) before applying a prune.'
    };
  }

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  plan.drop.forEach(function (name) {
    ss.deleteSheet(ss.getSheetByName(name));
  });

  return {
    ok: true,
    dryRun: false,
    keepPerSheet: plan.keepPerSheet,
    kept: plan.keep,
    deleted: plan.drop
  };
}

/** Keeps the newest `keep` backups per source sheet, drops the rest.
 *  Irreversible. Call previewPruneKeepN(keep) first.
 *  This is what the `prune` web action calls; pruneKeepLatest() is now
 *  the keep = 1 case of it. */
function pruneKeepN(keep) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const plan = planKeepN_(keep);

  plan.drop.forEach(function (name) {
    ss.deleteSheet(ss.getSheetByName(name));
  });

  Logger.log('Deleted ' + plan.drop.length + ', kept ' + plan.keep.length + '.');
  return plan;
}

/** DRY RUN for pruneKeepN. Changes nothing. */
function previewPruneKeepN(keep) {
  const plan = planKeepN_(keep);
  Logger.log('KEEP (' + plan.keep.length + '):');
  plan.keep.forEach(function (n) { Logger.log('  ' + n); });
  Logger.log('DELETE (' + plan.drop.length + '):');
  plan.drop.forEach(function (n) { Logger.log('  ' + n); });
  return plan;
}

/** Groups backups by source sheet and marks the newest of each group as keep.
 *  Names without a parseable timestamp are kept, never guessed at. */
function planKeepLatest_() {
  return planKeepN_(1);
}

/** Generalised form: keep the newest `keep` per source sheet.
 *  `keep` is clamped to at least 1 - this function must never be a way to
 *  delete every backup by passing 0. pruneAllBackups() exists for that, and
 *  it is deliberately a separate, manually invoked function. */
function planKeepN_(keepCount) {
  // NOT named `keep`: the body already declares a `keep` array, and Apps
  // Script would have failed to load the whole file on the collision.
  const howMany = Math.max(1, Math.floor(Number(keepCount) || 1));
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const groups = {};
  const keep = [];
  const drop = [];

  backupSheetNames_(ss).forEach(function (name) {
    const m = name.match(BACKUP_STAMP_RE);
    if (!m) {
      keep.push(name);            // unrecognised shape - leave it alone
      return;
    }
    const source = name.slice('_bk_'.length, name.length - m[0].length);
    (groups[source] = groups[source] || []).push({ name: name, stamp: m[1] });
  });

  Object.keys(groups).forEach(function (source) {
    const rows = groups[source].sort(function (a, b) {
      return a.stamp < b.stamp ? 1 : a.stamp > b.stamp ? -1 : 0;
    });
    rows.slice(0, howMany).forEach(function (r) { keep.push(r.name); });
    rows.slice(howMany).forEach(function (r) { drop.push(r.name); });
  });

  return { keep: keep, drop: drop, keepPerSheet: howMany };
}
