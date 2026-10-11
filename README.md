# dgi-portfolio

A Claude plugin for running a dividend-growth (DGI) portfolio: an integrity
audit of the portfolio spreadsheet, and company analysis with a 10-criteria
score and six valuation methods, following the *Dividende.blog* methodology.

Statements and dividends come straight from SEC EDGAR filings, prices from
Tiingo. Every data source is a local MCP server that reduces large payloads on
your machine, so only a few dozen numbers reach the conversation.

## Read this first: a reference project, not a product

This was built for one specific Google Sheet and one investor's workflow, and
it is published as a working reference rather than a ready-to-install tool.
What that means in practice:

| Part | Reusable as is? |
|---|---|
| `company-analysis` skill with `dgi-edgar`, `dgi-prices`, `dgi-alphavantage` | **Yes**, for any US-listed ticker. Needs a SEC contact User-Agent and a Tiingo token |
| `edgar_core.py`, `price_core.py`, `av_core.py` | Yes, as libraries: plain Python, no MCP dependency, unit-tested offline |
| `portfolio-audit`, `/audit-live`, `dgi-sheet-bridge` | **Only after adapting** `config/portfolio.json` to your own sheet. It maps sheet names, columns and row blocks of the original sheet; no template sheet is shipped |
| `dgi-ibkr-flex` and the dividend tax rules | Specific to an Interactive Brokers account and a Romanian tax resident (BNR exchange rates, Romanian dividend tax). Useful as an example of the pattern |

Two more things to change before use:

- Both skills tell Claude to **converse in Romanian** (`Conversation with the
  user is in Romanian` near the top of each `SKILL.md`). Edit that line to your
  language.
- The tickers in `config/portfolio.json` are **examples**. The tickers named
  in the documentation (KO, MA, V, ZTS and others) are there because each one
  illustrates a data behaviour: a split, a missing XBRL tag, a per-share-class
  filer.

## What is in this repository

| Path | What it is |
|---|---|
| `dgi-portfolio/` | The plugin: skills, the `/audit-live` command, five MCP servers, tests |
| `dgi-portfolio/README.md` | Full documentation: install, configuration, data-source limits, known traps, build recipe |
| `dgi-portfolio/setup/apps-script/` | The Google Apps Script bridge that gives the plugin access to your sheet |
| `analyses/` | Worked company analyses produced with the `company-analysis` skill |
| `install-plugin.sh` | Installs a built archive into the Claude desktop app's local plugin store |

## Skills

- **`portfolio-audit`** checks the sheet's integrity and reconciles it against
  the market. A deterministic Python validator, so findings are reproducible,
  and read-only by default.
- **`company-analysis`** scores one company on 10 criteria (maximum 30, floor
  10) and estimates a price range with six methods: dividend yield (Weiss),
  historical P/E, P/EBIT, P/OpCF, P/FCF and Gordon Growth.

## MCP servers

| Server | Source | Credential |
|---|---|---|
| `dgi-edgar` | SEC EDGAR XBRL | a contact User-Agent, no key |
| `dgi-prices` | Tiingo | API token |
| `dgi-alphavantage` | Alpha Vantage (optional) | free API key |
| `dgi-ibkr-flex` | Interactive Brokers Flex Web Service, BNR exchange rates | Flex token and query ids |
| `dgi-sheet-bridge` | Your Google Sheet, through an Apps Script web app | bridge URL and token |

Every credential lives in a `chmod 600` file under `~/.dgi/`, never in the
repository. `dgi-portfolio/config/portfolio.json` ships with placeholders
(`YOUR_SPREADSHEET_ID`, `YOUR_DEPLOYMENT_ID`) and a sheet layout you will need
to adapt to your own.

## Quick start

1. Configure the credentials and `config/portfolio.json` as described in
   `dgi-portfolio/README.md` → *Install*.
2. Build the archive with the recipe in `dgi-portfolio/README.md` →
   *Development*, or use the `dgi-portfolio.plugin` shipped here.
3. `bash install-plugin.sh dgi-portfolio/dgi-portfolio.plugin`, then open a new
   Claude session.

Tests: `cd dgi-portfolio && python3 -B -m unittest discover -s tests -p 'test_*.py'`.

## Not included

- **No portfolio data.** The spreadsheet, the change log and the personal
  position figures stay private.
- **No third-party datasets.** The dripinvesting.org screener CSV the skills
  can read is a manual download; get it from the site under its own terms.

Some references to `BACKLOG.md`, `CLAUDE.md` and `changesets/` remain in the
documentation. Those files belong to the private working copy and are not
published.

## Disclaimer

This is a research tool, not financial advice. Scores and valuations depend on
third-party data that can be wrong, and every price-derived figure rests on a
single price source. Decisions are yours.

## License

MIT, see `LICENSE`.
