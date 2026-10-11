# DGI scoring model - 10 criteria, maximum 30 points

Verbatim thresholds from *"Cum analizez o companie"* (Dividende.blog, 10 January
2021). Each criterion scores 1, 2 or 3 points.

## Two structural facts about this scale

**The floor is 10, not 0.** Every criterion awards a minimum of 1 point, so the
real range is 10-30. The author's guidance ("avoid companies scoring under 10,
10-20 is ok with question marks, over 20 is solid") therefore means: 10 is the
absolute floor, most companies land in the 10-20 band, and 20+ is the bar.
Do not present a score as "18/30" and imply the company used 60% of the range -
it used 40% of a 10-30 range. Report the band, not just the number.

**Criterion 3 has a hard reject.** The DGR table has a fourth row labelled `NO`,
below the 1-point row. That is not zero points - it is a disqualification. If DGR
falls in the `NO` band for its yield bucket, say so explicitly in the verdict and
do not average it away into a total.

## Data availability

If an indicator cannot be found, score 0 for that criterion and reduce the
maximum. Report `18/27 (3 criteria without data)`, never `18/30`. A confident
score built on two guessed inputs is more dangerous than an honest partial one.

---

## 1. Consecutive years of dividend growth

| Points | Threshold |
|---|---|
| 3 | 15+ years of growth |
| 2 | 10-15 years |
| 1 | < 10 years |

Preferred source: the dripinvesting per-stock history page, which gives the exact
streak. The screener CSV only gives a bucket, and `Contender` (10-24 years)
straddles the 15-year line between 3 and 2 points — never resolve a Contender from
the bucket. Do not trust the growth-years column
in the user's sheet - it is entered by hand and verifying it is one of the audit
findings.

Exceptions the author allows explicitly:

- Recently created companies that look promising, without a long history of their
  own (`ABBV`).
- Companies with a long history that **froze** the dividend at some point and then
  resumed growth (`INTC`). A freeze is not a cut. Investigate the context: were
  they in trouble? did they get past it? can further increases be relied on?

State any exception applied, in the report. An undeclared exception is a thumb on
the scale.

## 2. Dividend yield versus the S&P 500

Look up the current S&P 500 yield with `WebSearch`. Do not take it from memory.

| Points | Threshold |
|---|---|
| 3 | > 2.5x S&P 500 yield |
| 2 | 1x - 2.5x S&P 500 yield |
| 1 | < 1x S&P 500 yield |

Use current **Dividend Yield** (annual dividend / current price), not Yield on
Cost. If the user quotes a yield from the sheet, check which of the two they are
reading - column `K` is mislabeled.

Exception: the author buys only when yield is at least equal to the S&P 500, and
prefers at least 2x, but makes small exceptions when 3-year or 5-year DGR is very
high (above 15-20%).

## 3. Dividend growth rate (DGR)

**This is a matrix, not a single threshold.** The band depends on the current
yield bucket - a low-yield company must grow its dividend much faster to earn the
same score.

| Points | Low Yield (< 2%) | Medium Yield (2% - 4%) | High Yield (4%+) |
|---|---|---|---|
| 3 | > 13% | > 10% | > 7% |
| 2 | 9% - 13% | 5% - 10% | 2% - 7% |
| 1 | 5% - 9% | 2% - 5% | 1% - 2% |
| **NO** | **< 5%** | **< 2%** | **< 1%** |

Procedure: determine the yield bucket from criterion 2 first, then read the DGR
column for that bucket. Getting the bucket wrong changes the score by up to two
points.

The author calls dividend growth "probably the most important pillar of this
strategy". The non-negotiable floor: the dividend must grow at least with
inflation, otherwise the purchasing power of the income stream shrinks.

Required nuances:

- A mature company grows more slowly than a young one. Compare within the sector.
- **Decelerating DGR is the single most useful signal in the whole model.** If
  DGR 1y < DGR 3y < DGR 5y < DGR 10y, growth is systematically slowing, which
  usually precedes a freeze. Report it separately even when the score is still 2.
- Use DGR over 5 years for the score, but show 1, 3, 5 and 10 year figures so the
  trend is visible.
- DGR cannot be computed from the user's own data while the dividends-received
  column is a flat string. Use an external source and say so.

## 4. EPS and earnings payout ratio

Three dimensions. Score the **lowest** of the three - this criterion measures
whether earnings can support the dividend, and the weakest link governs.

> **Inference, not article text.** The article shows the three columns per
> criterion but never states how to combine them. "Score the lowest" was chosen
> because criteria 4 and 5 measure dividend safety, where the weakest link is
> what breaks. Applies to criterion 5 as well. If the user prefers averaging or
> another rule, change it here and in the skill - but flag the difference.

| Points | EPS trend | EPS consistency | Payout ratio |
|---|---|---|---|
| 3 | growing | no decline in last 10 years | < 40% (< 80% REITs) |
| 2 | small or zero growth | 1-2 declines in last 10 years | 40% - 60% (80% - 90% REITs) |
| 1 | declining | 3+ declines in last 10 years | > 60% (> 90% REITs) |

The author's stated ideal is a payout ratio up to 60%, leaving money for
additional investment.

**The REIT thresholds are part of the model, not an improvisation.** REITs are
legally required to distribute most of their taxable income, and property
depreciation destroys EPS without touching cash. For REITs
(for example `O`, `VICI`, `ARE`) apply the REIT column. Consider also computing payout on
**FFO** or **AFFO** and reporting both - a 180% payout on EPS can be a healthy
75% on AFFO.

## 5. Free cash flow and FCF payout ratio

`FCF = operating cash flow - capital expenditures`.
`FCF payout = total dividends paid / FCF`.

Same three dimensions, same rule: score the lowest.

| Points | FCF trend | FCF consistency | FCF payout ratio |
|---|---|---|---|
| 3 | growing | no decline in last 10 years | < 50% (< 80% REITs) |
| 2 | small or zero growth | 1-2 declines in last 10 years | 50% - 70% (80% - 90% REITs) |
| 1 | declining | 3+ declines in last 10 years | > 70% (> 90% REITs) |

The payout thresholds sit 10 percentage points above criterion 4, matching the
author's "small upward adjustment".

This is the hardest criterion to manipulate with accounting. The author's
reasoning: a good accountant can make the balance sheet look good, but when it
comes to the cash available for dividends the same tricks do not work - either
you have the money or you do not.

**Conflict rule:** when criterion 4 says healthy and criterion 5 says stressed,
**criterion 5 wins** and that goes in the opening verdict. EPS/FCF divergence is
the most common early warning of a dividend cut.

Also check whether the dividend is debt-funded: FCF payout under 100% while debt
accelerates means the dividend is being paid with borrowed money.

## 6. Debt to total capital

`total debt / (total debt + shareholders' equity)`

| Points | Ratio | Trend |
|---|---|---|
| 3 | 0% - 30% | low or declining |
| 2 | 30% - 60% | normal level |
| 1 | 60% - 80% | elevated or rising |

The author cites `AT&T` as the example of leverage that puts the dividend at risk,
and states the ratio should ideally stay under 60%.

Note the table scores both a **level** and a **direction**. Report the 10-year
trend, not just today's value. A company at 55% that came from 35% is riskier
than one steady at 60% for a decade.

Above 80% the table gives no score - treat it the way criterion 3 treats `NO` and
flag it in the verdict.

Supporting checks: interest coverage (`EBIT / interest expense`) and the debt
maturity schedule. Large fixed-rate long-dated debt is far less dangerous than
smaller debt refinancing next year. For utilities and REITs the sector median is
structurally higher - compare within the sector.

## 7. Return on equity

| Points | ROE | Trend |
|---|---|---|
| 3 | > 25% | high or rising |
| 2 | 10% - 25% | stable, small growth |
| 1 | 5% - 10% | low or declining |

The S&P 500 average is roughly 11-12%.

**Important trap:** ROE inflates artificially when equity shrinks - through
aggressive buybacks or heavy debt. A 60% ROE at a company with near-zero equity
(typical of `MO`, `ABBV`) does not signal exceptional profitability, it signals an
extreme capital structure. When ROE exceeds 40%, also compute **ROIC** and report
it alongside. ROIC is immune to the leverage trick.

## 8. Operating income margin

`operating income (EBIT) / total revenue`

| Points | Margin | Trend |
|---|---|---|
| 3 | > 18% | high or rising |
| 2 | 11% - 18% | stable, small growth |
| 1 | 5% - 11% | low or declining |

Thresholds are strongly sector-dependent - grocery retail is healthy at 3%,
software at 30%. **Always compare against the sector median and state what it
is.** Scoring a distributor 1 point against a threshold designed for software is a
methodological error, so name the tension when it arises.

The author cites studies correlating a good operating margin with superior stock
returns. The 10-year margin trend says more than the absolute level: steadily
compressing margins mean an eroding competitive advantage.

## 9. Share count

| Points | Pattern |
|---|---|
| 3 | consistent decline |
| 2 | erratic decline, or flat |
| 1 | increasing |

Ideal: share count declines gradually, so total dividend payments are divided
across fewer shares and dividend per share can grow without total cash outlay
rising.

Two warnings from the author:

- Buybacks done **for the wrong reasons** (management bonuses tied to EPS) or **at
  the wrong times** (at highs, or debt-funded) destroy value even while the share
  count falls. Check the average repurchase price against the price history.
- Issuing new shares to raise funds **dilutes** existing shareholders. This is
  normal and expected for REITs, which finance through equity - do not penalise
  them automatically.

## 10. Credit rating

| Points | Rating |
|---|---|
| 3 | AA, AAA |
| 2 | A, BBB+ |
| 1 | BBB, BBB- |

Anything below BBB- is not investment grade and the bankruptcy probability becomes
significant - the table below gives no score for it, so treat sub-BBB- the way
criterion 3 treats `NO`.

30-year bankruptcy probability by rating, as published in the article:

| Rating | Probability | Rating | Probability |
|---|---|---|---|
| AAA | 0.07% | BB+ | 14% |
| AA+ | 0.29% | BB | 17% |
| AA | 0.51% | BB- | 21% |
| AA- | 0.55% | B+ | 25% |
| A+ | 0.60% | B | 37% |
| A | 0.66% | B- | 45% |
| A- | 2.5% | CCC+ | 52% |
| BBB+ | 5% | CCC | 59% |
| BBB | 7.5% | CCC- | 65% |
| BBB- | 11% | CC | 70% |
| | | C | 80% |
| | | D | 100% |

Note the jump from A (0.66%) to A- (2.5%) - nearly 4x for a single notch. The
scoring table reflects this: A earns 2 points but A- is not listed, so it falls to
the BBB band in practice. Quote the probability alongside the rating; it makes the
risk concrete in a way the letter grade does not.

The author is explicitly sceptical of the rating agencies ("they do not inspire
the greatest confidence in the world") but considers them cleaner than in
2007-2009. Treat the rating as an input, not a verdict.

Look up the **outlook**, not just the letter: `BBB negative outlook` is materially
different from `BBB stable`. A downgrade below investment grade forces selling by
funds mandated to hold IG only, which raises the cost of financing and, through
that, threatens the dividend.

Small companies may carry no rating at all. That is not automatically bad - use
interest coverage and debt/EBITDA as substitutes, and state that you substituted.

---

## Interpreting the total

| Total | Verdict |
|---|---|
| < 10 | Avoid (only reachable if criteria lack data) |
| 10 - 20 | Acceptable, with question marks |
| > 20 | Solid company |

Reporting rules:

- **Name the question marks.** "14/30, acceptable" is not information.
  "14/30 - loses points on FCF payout (82%) and debt (68%, up from 51% in 2016)"
  is information.
- **A high score is not a buy recommendation.** The score measures business
  quality and dividend safety. Price is an entirely separate decision.
- **Never round up to cross a band.** 19 is 19, not "practically solid".
- **Report any `NO` band or off-table value in the verdict**, regardless of the
  total. A company scoring 24/30 with DGR in the `NO` band fails the strategy.
