# Belgium Construction Pack

Configures OpenConstructionERP for the Belgian construction market. Belgium is
a bilingual market where specifications and bills are written in Dutch (bestek /
meetstaat) in Flanders and French (cahier des charges / metrage) in Wallonia,
with Brussels using both. The pack defaults to Dutch and supports both languages
in onboarding and project descriptions. Currency is EUR with 21% BTW/TVA on
new-build and 6% on renovation.

## What makes a Belgian estimate Belgian

A Belgian meetstaat (bill of quantities) is element-based, commonly following
the BB/SfB classification, and structured as a detailed specification (bestek)
with measured quantities and unit rates. Public procurement follows federal
law (Wet Overheidsopdrachten / Loi Marches Publics) and requires a bestek
conforming to the standard template.

Two VAT rates matter for construction. New-build work carries the standard 21
percent. Renovation of a dwelling older than ten years carries the reduced 6
percent rate, and the distinction between the two is a significant part of
project economics. The pack does not set BTW.

Energy performance is regulated through the EPB/PEB framework, and structural
design follows the NBN EN Eurocodes (Belgian adoption).

## What this pack enables

- **Currency EUR** (the pack does not set BTW) and the `belgium`
  estimating methodology, defaulting to Dutch with French support
- **DIN 276 rule set** for classification validation, as the nearest supported
  hierarchy Belgian element-based bills map onto
- **Two demo projects**: an office building in Brussels and a residential
  development in Antwerp, both priced at Belgian 2026 market rates in EUR
  excluding BTW/TVA
- **BB/SfB, EPB/PEB and public procurement regulatory references** in the
  pack metadata

## Standards referenced

- BB/SfB (Belgian SfB classification for building elements)
- Belgisch bestek / meetstaat (Belgian specification and measurement)
- Wet Overheidsopdrachten / Loi Marches Publics (Public Procurement Law)
- EPB/PEB (Energieprestatie / Performance Energetique des Batiments)
- NBN EN standards (Bureau voor Normalisatie, Eurocode-aligned)

These are referenced for interoperability and compliance checking. Nothing in this
pack is legal, tax or regulatory advice.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then Partner
Packs: click Rescan, find "Belgium Construction Pack", then Activate pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=belgium-be openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
