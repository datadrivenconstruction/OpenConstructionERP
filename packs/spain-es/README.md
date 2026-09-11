# Spain Construction Pack

A country pack for Spanish construction work. It configures the workspace for
the way a Spanish estimate is built: against a base de precios from one of the
autonomous communities, exchanged in BC3/FIEBDC-3 format, measured to CTE
standards, priced in euro, with IVA at the applicable rate and the public
procurement framework of the Ley de Contratos del Sector Publico.

## What makes a Spanish estimate Spanish

A Spanish estimate is written against a base de precios, and which one depends
on the autonomous community where the work sits. Madrid, Catalunya, Andalucia,
the Basque Country and each of the other seventeen communities publishes its
own. The item numbering differs, the specifications differ, and a rate from
the wrong base is not an approximation, it is the wrong number.

BC3 (FIEBDC-3) is the standard exchange format. Every base de precios
publishes in it, every measurement software reads and writes it, and a Spanish
contractor expects to receive a presupuesto as a BC3 file alongside the PDF.
The format carries the full cost breakdown: capitulos, partidas, unit prices,
decomposed resources.

The Codigo Tecnico de la Edificacion (CTE) is mandatory for all building work.
EHE-08 governs structural concrete specifically. Spain has moderate to high
seismic risk in the south and southeast, and the NCSE-02 seismic standard
(being replaced by the Eurocode 8 national annex) affects structural costs.

Public procurement above EUR 500,000 requires contractor classification under
the Ley de Contratos del Sector Publico (9/2017). Below threshold, simplified
procedures apply.

IVA at the standard 21% rate applies to most construction. Renovation of
dwellings older than two years attracts the reduced 10% rate. Social housing
can qualify for the super-reduced 4% rate.

## What this pack enables

- **Currency EUR**, the `es_iva_21` tax template and the `spain` estimating
  methodology, with a Spanish interface.
- **One cost catalogue**, `cwicr-es-madrid`, resolving to ES_MADRID.
- **A three-step onboarding wizard** that collects the company profile and
  NIF/CIF, the base de precios and standards selection, and confirms the
  setup, in Spanish and English.
- **A demo project**, `mixed-use-barcelona`: a mixed-use development in
  Barcelona.

## Cost data

No commercial base de precios is bundled. The autonomous community price lists
are published documents with their own terms, and the pack references them
without redistributing the rates.

## Standards referenced

- Ley de Contratos del Sector Publico (Ley 9/2017)
- Codigo Tecnico de la Edificacion (CTE, R.D. 314/2006)
- EHE-08 - Instruccion de Hormigon Estructural
- FIEBDC-3 / BC3 exchange format
- Ley de Ordenacion de la Edificacion (LOE, Ley 38/1999)
- Reglamento General de la Ley de Contratos (R.D. 1098/2001)

These are referenced for interoperability and compliance checking. The
publishers' own text, tables and rates are not reproduced here. Nothing in
this pack is legal or tax advice.

## Review status

The regulatory references are drawn from public sources and are pending review
by a Spanish aparejador or quantity surveyor before they are relied on for a
public tender. No engine rule set is active yet; when one is built it will
carry rules for BC3 item references and capitulo numbering.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then
Partner Packs: click Rescan, find "Spain Construction Pack", then Activate
pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=spain-es openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
