# Switzerland Construction Pack

A country pack for Swiss construction estimating. It configures the workspace
the way a Swiss cost estimate is built: against the BKP Baukostenplan, priced
in Swiss francs, contracted under SIA 118 and checked against CRB benchmarks,
with MWST/TVA at the applicable rate.

## What makes a Swiss estimate Swiss

A cost estimate in Switzerland is organised by the BKP (Baukostenplan), the
classification system published by the CRB (Schweizerische Zentralstelle fuer
Baurationalisierung). The BKP divides construction costs into main groups 0
through 9 and three-digit subgroups, and a Kostenvoranschlag or devis that does
not follow BKP is not what a Swiss client, Bauherrenberater or public authority
expects to receive. The element-based variant eBKP (SN 506 511) is gaining
ground for early-phase estimates, while the trade-based BKP remains standard for
detailed Leistungsverzeichnisse.

SIA 451 governs cost planning in building construction (Kostenplanung im
Hochbau / Planification des couts de construction) and defines the cost
estimation phases that correspond to the SIA 112 project phases. The cost plan
structure follows BKP.

Contracts between client and contractor follow SIA 118 (Allgemeine Bedingungen
fuer Bauarbeiten). SIA 118 is the Swiss standard form of contract, analogous in
role to the VOB/B in Germany but with significant differences in risk
allocation, defects liability and payment terms. Most public and private
building works in Switzerland reference SIA 118.

Public procurement follows the BoeB (Bundesgesetz ueber das oeffentliche
Beschaffungswesen) at the federal level and cantonal procurement legislation
(IVoeB) for sub-federal works. Above the WTO/GPA threshold, the process follows
the federal act; below it, cantonal rules apply, and these differ between
cantons.

MWST (Mehrwertsteuer / TVA taxe sur la valeur ajoutee) is 8.1 percent at the
standard rate. A reduced rate of 2.6 percent applies to certain goods. The
accommodation rate of 3.8 percent applies to hotel and lodging services.
Construction services carry the standard rate.

## What this pack enables

- **Currency CHF** (the pack does not set VAT) and the `switzerland`
  estimating methodology, with a German, French and Italian interface.
- **Three validation rule packs** covering SIA 451 cost planning, BKP
  classification structure, and SIA 118 contract conditions.
- **A three-step onboarding wizard** that collects the company profile and
  UID-Nummer, the standards and phase preference, and creates the workspace.
  Trilingual German, French, Italian and English.
- **Two demo projects**: an office building in Zurich and a residential
  development in Lausanne, both structured to BKP and priced at regional
  rates in CHF with 8.1% MWST.

## Cost data

No commercial CRB data is bundled. The CRB cost benchmarks and NPK
Normpositionen-Katalog are published products with their own terms, and the
pack references them without redistributing the rates.

## Standards referenced

- SIA 118:2013, Allgemeine Bedingungen fuer Bauarbeiten
- SIA 451, Kostenplanung im Hochbau
- BKP Baukostenplan (CRB, three-digit trade-based classification)
- eBKP SN 506 511 (element-based variant)
- SIA 102:2020, Leistungen und Honorare der Architekten
- SIA 108:2020, Leistungen und Honorare der Bauingenieure
- SIA 112:2014, Modell Bauplanung (project phases 1-6)
- BoeB / LMP, Bundesgesetz ueber das oeffentliche Beschaffungswesen
- CRB Schweizerische Zentralstelle fuer Baurationalisierung

These are referenced for interoperability and compliance checking. The
publishers' own text, tables and rates are not reproduced here. Nothing in
this pack is legal or tax advice.

## Review status

The regulatory references are drawn from public sources and are pending review
by a Swiss Baukostenplaner or quantity surveyor before they are relied on for
a public submission. No engine rule set is active yet; when one is built it
will carry rules for BKP item references and SIA 451 cost phase validation.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then
Partner Packs: click Rescan, find "Switzerland Construction Pack", then
Activate pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=switzerland-ch openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
