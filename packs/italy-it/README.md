# Italy Construction Pack

A country pack for Italian construction work. It configures the workspace for
the way an Italian estimate is built: against a prezzario regionale, measured
to UNI standards, priced in euro, with IVA at the applicable rate and the
public procurement framework of the Codice dei contratti pubblici.

## What makes an Italian estimate Italian

An Italian estimate is written against a prezzario, and which prezzario depends
on where the work is and who is paying. DEI (Tipografia del Genio Civile)
publishes the national reference, but each of the twenty regions publishes its
own prezzario regionale, and for public works the regional list is the one that
governs. The item numbering differs between regions, the specifications differ,
and a rate from the wrong prezzario is not an approximation, it is the wrong
number.

Public works above EUR 150,000 require SOA attestation under the Codice dei
contratti pubblici (D.Lgs. 36/2023). The SOA category determines what type and
size of work a contractor is qualified to bid on. Below threshold, simplified
procedures apply but the documentation requirements remain.

NTC 2018 (Norme Tecniche per le Costruzioni) is mandatory for all structural
work. Italy has significant seismic risk across much of its territory, and the
NTC zonation affects structural design, testing requirements and cost.

IVA at the standard 22% rate applies to most construction. Renovation and
restoration of residential buildings attracts the reduced 10% rate. New
construction of a prima casa (first home) can qualify for the super-reduced 4%
rate under specific conditions.

## What this pack enables

- **Currency EUR**, the `it_iva_22` tax template and the `italy` estimating
  methodology, with an Italian interface.
- **Two cost bases**: `cwicr-it-rome`, resolving to IT_ROME, and
  `cwicr-it-toscana`, resolving to IT_TOSCANA, the base built from the
  Prezzario dei Lavori Pubblici della Toscana.
- **Regional price lists from the source**: Cost databases, then Import a
  regional price list, reads the file a region publishes (Toscana and
  Lombardia XML, Veneto XML, SIX XML, and the CSV, XLSX and JSON tables of
  Puglia, Campania, Piemonte, Umbria and Lazio, plain or as the ZIP
  downloaded), shows what it holds with its edition and licence, and imports
  it as a catalogue named after the region and edition once confirmed.
- **The `italy` validation rule set**: four prezzario rules run on every
  Italian bill (voce code format, voce reference present, safety costs
  carried separately, labour share documented).
- **A three-step onboarding wizard** that collects the company profile and
  P.IVA, the prezzario and standards selection, and confirms the setup, in
  Italian and English.
- **A demo project**, `residential-rome`: a residential development in Rome.

## Cost data

One regional price list is redistributed, as a derived base: IT_TOSCANA is
built from the 2026 edition of the Prezzario dei Lavori Pubblici della Toscana,
which Regione Toscana publishes as open data. The open-data catalogue record of
that edition states the licence as CC BY 4.0 (the XML file of the 2025 edition
names CC BY 3.0 in its own header). The base carries the attribution "Regione
Toscana, Prezzario dei Lavori Pubblici della Toscana, edizione 2026, CC BY 4.0",
shown wherever the base is offered or loaded.

No other regional list is bundled, and neither is the DEI reference, which is a
commercial publication. A list the user imports is read from the file they
downloaded from the region; each imported item keeps the region, edition and
the licence and attribution the file or its catalogue record states, and the
preview says when a file states no licence at all (Veneto, Lombardia and Lazio
files name none).

## Standards referenced

- Codice dei contratti pubblici (D.Lgs. 36/2023)
- Prezzari regionali DEI (regional price lists)
- NTC 2018 - Norme Tecniche per le Costruzioni (D.M. 17/01/2018)
- UNI standards (construction and building materials)
- Testo Unico Edilizia (D.P.R. 380/2001)
- Codice Civile artt. 1655-1677 (appalto)

These are referenced for interoperability and compliance checking. Apart from
the Toscana base described under Cost data, the publishers' own text, tables
and rates are not reproduced here. Nothing in
this pack is legal or tax advice.

## Review status

The regulatory references are drawn from public sources and are pending review
by an Italian geometra or quantity surveyor before they are relied on for a
public tender. The `italy` engine rule set implements five of the twelve
rules declared in `rule_packs/prezzario_regionale.json`; the other seven are
declared only and do not run yet.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then
Partner Packs: click Rescan, find "Italy Construction Pack", then Activate
pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=italy-it openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
