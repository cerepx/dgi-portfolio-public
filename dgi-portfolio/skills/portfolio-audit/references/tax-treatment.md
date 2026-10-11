# Dividend tax treatment - Romanian resident, US holdings

Not tax advice. This documents how the sheet should model the tax so the numbers
are internally consistent, and flags what needs a professional.

## Rate history

| Year of receipt | Romanian dividend tax | Net factor |
|---|---|---|
| 2021 - 2022 | 5% | 0.95 |
| 2023 | 8% | 0.92 |
| 2024 - 2025 | 10% | 0.90 |
| 2026 onwards | **16%** | **0.84** |

The increase from 10% to 16% takes effect 1 January 2026. It applies to all
dividend payers, resident or non-resident, individual or corporate.

## Why 0.84 and not 0.9 x 0.84

For a Romanian tax resident holding US equities there are two layers, and they do
not multiply:

1. **US withholding at source: 10%** under the treaty, provided a valid W-8BEN is
   on file with the broker. Without it, the statutory 30% applies - worth checking
   at the broker if the numbers do not tie out.
2. **Romanian tax on the gross dividend**, declared through Declarația Unică, with
   a **credit for the foreign tax already paid**, capped at the Romanian tax due.

So the total is the Romanian rate, not the sum:

| | 10% Romanian rate | 16% Romanian rate |
|---|---|---|
| US withheld | 10% | 10% |
| Romanian tax on gross | 10% | 16% |
| Credit for US tax | -10% | -10% |
| Additional to Romania | 0% | 6% |
| **Total effective** | **10%** | **16%** |
| **Net factor** | **0.90** | **0.84** |

The single factor 0.84 is therefore correct as the going-forward total. The error
is not the number - it is the scope.

## The scope error

Column `P` is a **cumulative historical total** covering every payment since the
position was opened. Replacing `0.9` with `0.84` across the whole string
retroactively re-taxes 2024-2025 income at 16% and understates what was actually
received - by 6.67% on every pre-2026 payment.

Wrong:

```
=0.84*(2.565+2.57+2.57+2.625+2.625+2.625+2.635+ ... )
```

Correct in principle:

```
=0.9*(payments received before 2026) + 0.84*(payments received in 2026 or later)
```

But a flat string of summed numbers carries **no dates**. There is no way to
determine which of those figures landed in 2026. The formula cannot be split
correctly in its current shape.

**This is the strongest argument for restructuring column `P`** - stronger than
readability, stronger than DGR. Without dates, correct taxation is not merely
inconvenient, it is impossible.

## Target structure

A `Dividends received` sheet, one row per payment:

| Column | Content |
|---|---|
| A | Ex-dividend date |
| B | Payment date |
| C | Ticker |
| D | Gross dividend per share |
| E | Shares held at payment |
| F | Gross amount = D x E |
| G | Tax rate applied (looked up from the payment year) |
| H | Net amount = F x (1 - G) |
| I | Currency |
| J | FX rate to RON on payment date |

Column `P` in `MyShares` then becomes:

```
=SUMIFS('Dividends received'!H:H, 'Dividends received'!C:C, B2)
```

The tax rate in `G` should itself be a lookup on the payment year against a small
rates table, not a typed constant - so the next rate change is one cell, not
seventeen formulas.

## What this unlocks

| Capability | Blocked today | Why |
|---|---|---|
| Correct per-year taxation | yes | no payment dates |
| Real DGR from own data | yes | no per-share amounts separated from share count |
| Declarația Unică figures | yes | gross is unrecoverable, FX rate per payment date missing |
| Detecting a dividend cut | yes | cannot compare payment n to payment n-1 |
| Correct yield on cost over time | yes | cannot attribute income to a period |
| Special vs regular dividend | yes | indistinguishable in a flat sum |

Six capabilities, one structural cause.

## Declarația Unică

Foreign dividend income is self-declared. The relevant figures are the **gross**
amount and the **foreign tax withheld**, converted to RON at the BNR rate on the
date of receipt. The current sheet stores neither the gross nor the FX rate, which
is why the declaration has to be reassembled from broker statements every year.

Column `J` in the target structure exists for this reason.

## Open questions for a tax advisor

Flag these rather than asserting an answer:

1. **Dividends declared in 2025 but paid in 2026.** For an individual reporting
   foreign dividend income, the year of receipt normally governs, which would put
   them at 16%. Confirm before relying on it.
2. **Non-US positions.** `SXR8` is Irish-domiciled and accumulating - it
   distributes nothing, so no dividend tax arises, but the accumulated amount is
   still taxed on disposal. `BVBETF` is Romanian and taxed under domestic rules.
   Neither follows the US treaty path.
3. **W-8BEN status per broker.** If any broker withheld 30% rather than 10%, the
   net factor for those payments is wrong regardless of the year.
4. **Whether the broker's withholding is reclaimable** where it exceeded the treaty
   rate.

## Sources

- [EY: 2026 brings a significant increase from 10% to 16% in dividend income tax](https://www.bursa.ro/ey-anul-2026-aduce-o-crestere-semnificativa-de-la-10-procente-la-16-procente-a-impozitelor-pe-veniturile-din-dividende-27565856)
- [Economica.net: Dividend tax rises to 16% from 1 January 2026](https://www.economica.net/impozitul-pe-dividende-creste-la-16-de-la-1-ianuarie-2026-cati-bani-va-lua-statul-in-plus_850834.html)
- [Europa Liberă: Fiscal changes from 1 January 2026](https://romania.europalibera.org/a/33623696.html)
