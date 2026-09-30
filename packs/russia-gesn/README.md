# Russia Construction Pack

A country pack for the Russian market. It configures the workspace the way a
Russian estimate is actually built: against a published norm base, with the
resource decomposition every norm carries, at a stated price level, with
overhead and estimated profit normed on payroll, presented as a twelve-chapter
summary in roubles.

## What makes a Russian estimate Russian

An estimate here is not a description of work with a price beside it. Each line
cites a norm in the federal base, and the norm states what a unit of that work
consumes: man-hours at a given grade, machine-hours of given plant, quantities
of given materials. The price is assembled from those quantities and a price
book afterwards, which is why the same norm serves every region and every year.

Three consequences follow, and they are what this pack is about.

The code is the load-bearing field. `08-04-001-21` is collection, section,
table, norm, four fixed-width zero-padded fields. A line without a code has a
price and no derivation, and a state client will not accept a derivation it
cannot follow back to a published norm.

The date is part of the number. Roubles in an estimate belong to a price level,
and the current cost is reached by applying a conversion index for the region,
the quarter and the kind of work. Two estimates differing by a factor of five
may be the same estimate at two price levels. Nothing about an out-of-date
total looks wrong, which is why the level is declared rather than inferred.

The markups hang off payroll. Overhead and estimated profit are normed against
wages, not against direct cost. A trade with little labour and expensive
material carries a small markup and a labour-heavy trade carries a large one,
which is the opposite of what a percentage of direct cost produces. This is the
part a reader from another market gets wrong most often.

## What this pack enables

- **Classification** against the GESN/FER norm code, which is what the
  `HU`-style registry entry for `RU` already resolved to. Four-field code, the
  shape validated by the engine and published in the pack's own documentation
  so a reader and the rule cannot drift.
- **Five validation rules** under the `gesn` rule set: the code must be
  present, it must have the right shape, a line citing a norm should carry its
  resource decomposition, that decomposition must include labour hours, and the
  estimate must say which price level its figures are in.
- **The national markup stack**, four lines: overhead, estimated profit,
  unforeseen costs on the running total, VAT on everything. Until this pack the
  stack was written into the platform and unreachable, because no country was
  mapped to it.
- **The twelve summary-estimate chapters** as the cost breakdown dimension, so
  temporary works, developer supervision and design fees each have a place to
  go instead of being folded into the building.
- **Rouble at two decimals**, VAT at 22 percent (the rate from 1 January 2026), and a Russian interface,
  because the application ships a Russian bundle and this pack selects it.
- **A cost database to price against**: 55,719 St Petersburg items in roubles,
  already carrying the GESN/FER classification, available from the marketplace
  as `cwicr-ru-stpetersburg`.

## Install

```bash
pip install -e packs/russia-gesn
```

Restart the API. The core discovers the entry point at boot, validates the
manifest and applies the overrides. The onboarding wizard replaces the default
first-login steps with the six in `onboarding.yaml`.

## The norm code

```
CC-SS-TTT-NN
08-04-001-21
```

| Field | Russian | What it names |
|---|---|---|
| `CC` | сборник | The collection |
| `SS` | раздел | The section within the collection |
| `TTT` | таблица | The table within the section |
| `NN` | норма | The norm within the table |

The published base nests six levels deep (collection, division, section,
subsection, table, norm) and only four of them are addressable, which is why a
four-field code can still sit six levels down. The families `ГЭСН`, `ГЭСНм`,
`ГЭСНп`, `ГЭСНр`, `ФЕР` and `ТЕР` share the shape, so a code alone does not say
which family it came from; the estimate says that once, at document level.

The shape was measured rather than assumed. A published base of 2604 norms was
read in full and every code in it matches the pattern the engine compiles.

## Standards and statutes referenced

- Приказ Минстроя России от 04.08.2020 № 421/пр, methodology for determining
  estimated construction cost
- Приказ Минстроя России от 21.12.2020 № 812/пр, overhead norms
- Приказ Минстроя России от 11.12.2020 № 774/пр, estimated profit norms
- Градостроительный кодекс РФ, статья 8.3, estimate norms and prices
- Постановление Правительства РФ от 05.03.2007 № 145, review of estimated cost
- ФГИС ЦС, the state price information system

## Language

The pack sets the interface to Russian, which the application ships. That is
worth saying because it is not automatic: a pack can only select a locale the
application already has, and one that declares a language with no bundle behind
it promises an interface it cannot deliver and falls back to English silently.
The Hungarian pack in this repository declares English for that exact reason.

## Review status

The norm code shape and the resource decomposition are derived from a published
GESN base read in full: 2604 norms across ten collections, no norm with an
empty resource list, four resources per norm at the median. The markup
structure is the national stack the platform already carried, cited in its own
source to the orders above.

The statutory references are drawn from public sources and are pending review
by a Russian cost engineer before they are relied on for a state contract. Each
rule-pack document states its own review status for the same reason: a document
derived from a file and one drawn from a statute are not the same kind of
claim, and shipping both without saying which is which is the part that would
mislead.

## License

AGPL-3.0-or-later, the same as the platform.
