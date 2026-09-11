# Germany Construction Pack

The flagship country pack for German construction estimating. It configures the
workspace the way a German cost estimate is actually built: against DIN 276 cost
groups, structured by VOB Part C trade divisions, exchanged as GAEB DA XML,
priced in euros, and checked against the fee tables an architect needs to render
the Honorarrechnung.

## What makes a German estimate German

A cost estimate in Germany is defined by its Kostengruppe structure. DIN 276
organises construction costs into groups 100 through 800, from Grundstueck
through Finanzierung, and a Kostenberechnung that does not follow DIN 276 is not
a Kostenberechnung a German client or public authority can check. The pack loads
DIN 276:2018 as the classification standard and validates every priced line
against its hierarchy.

The work itself is specified and measured according to the VOB, and which part
matters depends on the question. VOB/A governs procurement, VOB/B governs the
contract conditions, and VOB/C contains the Allgemeine Technische
Vertragsbedingungen (ATVs) - the DIN 18299 series that defines what a trade is,
how its work is described, and how its quantity is measured. A
Leistungsverzeichnis written outside the VOB/C trade structure is not wrong, but
it will not pass through a public tender. The pack loads VOB 2019 and applies
the ATV trade structure to BOQ validation.

Data exchange between estimators, contractors and public clients runs on GAEB DA
XML. The relevant exchange phases are X81 (LV-Uebermittlung), X83
(Angebotsabgabe), X84 (Nebenangebot) and X86 (Auftragserteilung). A German
tender that cannot produce a conformant X83 cannot be submitted electronically,
and most public procurement now requires exactly that. The pack enables GAEB
validation and uses X83 as the default export phase.

Architect and engineer fees follow the HOAI. The 2021 revision made the fee
tables advisory rather than mandatory, but in practice most public clients still
reference them and most offices still calculate against them. The Honorarzone
(I through V) and the anrechenbare Kosten remain the standard language. The pack
loads the HOAI 2021 fee structure and lets the onboarding wizard set the default
Honorarzone.

Tax is straightforward compared to some jurisdictions. The standard
Umsatzsteuer rate is 19 percent, and it applies to construction services
without the withholding complexity found elsewhere. The pack sets the
`de_ust_19` tax template.

## What this pack enables

- **Currency EUR**, the `de_ust_19` tax template and the `germany` estimating
  methodology, with a German and English interface.
- **Two engine rule sets**, `din276` and `gaeb`. The DIN 276 rules check that
  every cost line carries a valid Kostengruppe reference and that the hierarchy
  is consistent. The GAEB rules check that BOQ export conforms to DA XML 3.3.
- **Five validation rule packs** covering DIN 276:2018, GAEB X83/X84/X86,
  VOB 2019 (Parts A, B and C), HOAI 2021 fee structure, and BKI cost
  benchmarks. These are reference material for the estimator; the two rule sets
  above are what the engine runs.
- **A four-step onboarding wizard** that collects the company profile and
  USt-IdNr, the standards and Honorarzone preference, the tax and procurement
  defaults, and creates the workspace. Bilingual German and English.
- **Five demo projects**: a residential build in Berlin, an office building in
  Frankfurt, and three retail market projects in Heidelberg, Heilbronn and
  Karlsruhe. All are structured to DIN 276, measured to VOB/C, and priced at
  regional rates with 19% USt.

## Cost data

Two CWICR cost regions are available: Berlin and Munich. Other German cities
are not yet published. BKI Baukosteninformationszentrum regional factors can be
applied per project to adjust base rates to the local price level.

The BKI database itself is a commercial product and is not redistributed in
this pack. What ships are the plausibility benchmarks - cost-per-square-metre
ranges by building type and Kostengruppe - that let the validation engine flag
a number that falls outside the expected corridor.

## Standards referenced

- DIN 276:2018-12, Kosten im Bauwesen (cost groups KG 100 through 800)
- VOB 2019, Parts A (procurement), B (contract conditions), C (ATVs, DIN 18299 ff.)
- GAEB DA XML 3.3 (exchange phases X81, X83, X84, X86)
- HOAI 2021, Honorarordnung fuer Architekten und Ingenieure (fee scale)
- AHO, Ausschuss der Verbande und Kammern der Ingenieure und Architekten
  fuer die Honorarordnung (project management fee guidance)
- BKI Baukosteninformationszentrum (cost benchmarks by building type and region)

These are referenced for interoperability and compliance checking. Clause,
section and cost-group numbers are interoperability facts and are used as such;
the publishers' own text, tables and rates are not reproduced here. Nothing in
this pack is legal, tax or fee advice.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then
Partner Packs: click Rescan, find "Germany Construction Pack", then Activate
pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=germany-de openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
