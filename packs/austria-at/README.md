# Austria Construction Pack

A country pack for Austrian construction estimating. It configures the
workspace the way an Austrian cost estimate is built: against the OENORM
classification, priced in euro, tendered under OENORM B 2061, cost-planned
under OENORM B 1801 and exchanged electronically via OENORM A 2063, with
USt at the applicable rate.

## What makes an Austrian estimate Austrian

An Austrian estimate is organised around the OENORM standards published by
Austrian Standards International (ASI). OENORM B 1801-1 governs cost planning
in building construction (Kosten im Hoch- und Tiefbau) and defines the cost
groups and phases that structure the Kostenschaetzung, Kostenberechnung and
Kostenanschlag as the design progresses.

Tendering follows OENORM B 2061, which defines how unit prices are built up
from direct costs (Einzelkosten der Teilleistungen), site overheads
(Baustellengemeinkosten), business overheads (Geschaeftsgemeinkosten), risk
and profit. This K-Blatt (Kalkulationsformblatt) structure is specific to
Austria and differs from both the German VOB and the Swiss SIA approach.

Electronic data exchange for bills of quantities uses OENORM A 2063, which
defines the XML format for transmitting LV positions between clients,
consultants and contractors. A 2063 occupies the same niche as GAEB DA XML
in Germany and is the mandatory format for electronic submissions in Austrian
public procurement.

Contract conditions follow OENORM B 2110 for private works and OENORM B 2118
where the Bundesvergabegesetz (BVergG 2018) applies. Public procurement above
the EU thresholds is governed by the BVergG, which implements the EU
procurement directives. Below threshold, simplified procedures apply but the
OENORM contract conditions remain the standard reference.

USt (Umsatzsteuer) is 20 percent at the standard rate. A reduced rate of
10 percent applies to certain residential and renovation works.

## What this pack enables

- **Currency EUR** (the pack does not set VAT) and the `austria` estimating
  methodology, with a German and English interface.
- **Three validation rule packs** covering OENORM B 2061 tendering and pricing,
  OENORM B 1801 cost planning, and OENORM A 2063 data exchange.
- **A three-step onboarding wizard** that collects the company profile and
  UID-Nummer, the standards and contract preference, and creates the workspace.
  Bilingual German and English.
- **Two demo projects**: an office building in Vienna and a residential
  development in Salzburg, both structured to OENORM and priced at regional
  rates in EUR with 20% USt.

## Cost data

No commercial OENORM data is bundled. The standard descriptions and reference
prices are published products with their own terms, and the pack references
them without redistributing the rates.

## Standards referenced

- OENORM B 2061, Preisermittlung fuer Bauleistungen (tendering and pricing)
- OENORM B 1801-1, Kosten im Hoch- und Tiefbau (cost planning)
- OENORM A 2063, Datenaustausch (electronic data exchange for tendering)
- OENORM B 2110, Allgemeine Vertragsbestimmungen fuer Bauleistungen
- OENORM B 2118, Allgemeine Vertragsbestimmungen unter Anwendung des BVergG
- Bundesvergabegesetz BVergG 2018 (Federal Procurement Act)
- Austrian Standards International (ASI)

These are referenced for interoperability and compliance checking. The
publishers' own text, tables and rates are not reproduced here. Nothing in
this pack is legal or tax advice.

## Review status

The regulatory references are drawn from public sources and are pending review
by an Austrian Baukalkulator or Ziviltechniker before they are relied on for a
public submission. No engine rule set is active yet; when one is built it will
carry rules for OENORM item references and K-Blatt pricing validation.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then
Partner Packs: click Rescan, find "Austria Construction Pack", then Activate
pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=austria-at openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
