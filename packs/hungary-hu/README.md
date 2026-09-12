# Hungary Construction Pack

Pre-configures OpenConstructionERP for the Hungarian market: the item order a
Hungarian bill of quantities is written against, the material and fee split it
is priced in, and the summary cascade it is totalled through. Built from
Hungarian workbooks in production use rather than from a description of them,
so a Hungarian estimator opening a bill recognises it on the first screen.

> Developed in collaboration with **Kocsis Tamas** /
> [BIM Control](https://www.bimcontrol.hu/) — domain expertise for Hungarian
> construction standards, item orders and estimating workflows.

## What makes a Hungarian bill Hungarian

Two things, and both are in this pack.

**Every priced line is quoted twice.** Once as material (anyag) and once as fee
(díj, meaning labour and plant). The two are totalled separately per
sub-chapter, per chapter and on the cover sheet, and a client comparing
tenderers compares both columns, not their sum. Design fees are fee only, a
supply line is material only, so the rule is never that both must be present:
it is that the two halves are the rate. That is what the validation engine
checks.

**The structure is prescribed, not chosen.** Building works follow a
seventeen-chapter sectoral item order with a nine-segment code. Infrastructure
works for a state developer follow a different order, where each line carries a
structure code, a row number and an item number unique within the project,
alongside tag columns resolved against dictionaries shipped with the project.
In public procurement the structure is a requirement rather than a habit: a
tender the client cannot compare line by line is a tender the client cannot
lawfully evaluate.

## What this pack enables

- Currency HUF at whole units. The forint has no minor unit in practice, and
  two decimals on a Hungarian bill are a conversion artefact rather than a
  price
- The Hungarian estimating method, with contingency (tartalékkeret) and VAT
  (ÁFA) applied in that order on the cover summary
- The `tetelrend` classification standard, so a project in Hungary is
  classified against its own item order rather than against a Central European
  default
- Four validation rules under the `hungary` rule set: the item-code shape, the
  chapter, the material and fee split, and the uniqueness of the per-project
  item number
- Six reference documents covering both item orders, the money structure,
  public procurement, the electronic construction log and VAT
- Import of both Hungarian workbook shapes, including the split prices, the
  chapter tree, the tag codes and the programme dates
- A bilingual onboarding wizard, so the terms an estimator decides on are the
  Hungarian ones

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then
Packs: click Rescan, find "Hungary Construction Pack", then Apply.

To run a workspace that boots straight into it:

```bash
OE_PACK=hungary-hu openconstructionerp serve
```

## The building item order

Codes read `MA-CC-SS-II`, up to nine segments joined with hyphens: `MA` for
building works, a two-digit chapter, then sub-chapter and item levels as deep
as the bill needs. `MA-01-11-01` is chapter 01 general costs, sub-chapter 11
site setup, item 01 temporary roads and bridges. Each chapter carries a `99` or
`199` catch-all.

| | | | |
|---|---|---|---|
| 01 general and ancillary costs | 02 preparatory works | 03 earthworks and foundations | 04 structural works |
| 05 envelope and external trades | 06 architectural and finishing trades | 07 interior fit-out | 08 heritage and restoration |
| 09 mechanical services | 10 fire protection and suppression | 11 electrical power | 12 extra-low voltage |
| 13 building automation | 14 specialist technology | 15 lifts and lifting equipment | 16 external works |
| 17 handover | | | |

## Standards and statutes referenced

- 2015. évi CXLIII. törvény a közbeszerzésekről, and 322/2015. Korm. rendelet
  on the procurement of construction works
- 191/2009. Korm. rendelet az építőipari kivitelezési tevékenységről, and the
  state-operated electronic construction log (e-építési napló)
- 2007. évi CXXVII. törvény az általános forgalmi adóról: 27 percent standard
  rate, a reduced rate for specified new residential property, and the domestic
  reverse charge for construction and installation services between taxable
  persons

## Language

The pack runs in English. OpenConstructionERP ships no Hungarian interface
bundle, and a pack cannot conjure one: a `default_locale` the application has
no strings for resolves back to English regardless, so declaring `hu` here
would promise a Hungarian interface and quietly deliver an English one. The
Hungarian vocabulary the pack does carry sits where it is read, in the
onboarding wizard and in the reference documents. A Hungarian interface bundle
is a separate piece of work with its own quality bar, and this pack does not
pretend to have done it.

## Review status

The item orders, the code shapes and the money structure are derived from
Hungarian workbooks in production use, developed in collaboration with
Kocsis Tamas ([BIM Control](https://www.bimcontrol.hu/)). The statutory
references are drawn from public sources. Nothing in this pack reproduces a
third party's cost catalogue, item texts or software identifiers.

## License

AGPL-3.0-or-later, the same as the platform.
