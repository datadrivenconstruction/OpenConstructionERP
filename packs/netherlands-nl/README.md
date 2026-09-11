# Netherlands Construction Pack

A country pack for construction work in the Netherlands. It configures the
workspace for the Dutch market: NL/SfB classification, euro currency, 21% BTW,
and the two specification systems that divide Dutch construction between civil
engineering (RAW) and building (STABU).

## What this pack configures

- **Currency EUR**, the `nl_btw_21` tax template and the `netherlands`
  estimating methodology, with a Dutch interface.
- **NL/SfB classification** as the default, which is the Dutch adaptation of
  the SfB system used across Nordic and Benelux countries.
- **One CWICR cost region**, `cwicr-nl-amsterdam`, resolving to NL_AMSTERDAM.
- **One demo project**: an office building in Amsterdam.

## Specification systems

Dutch construction runs on two parallel specification standards.

RAW (Rationalisatie en Automatisering in de Grond-, Weg- en Waterbouw) is the
systematic specification for civil engineering work: roads, hydraulic
structures, sewers, earthwork. A RAW bestek is a standardised contract
document with coded items that all Dutch GWW contractors read the same way.

STABU (Stichting Standaardbestek Burger- en Utiliteitsbouw) serves the same
role for building construction. A STABU bestek covers the specification of
materials, workmanship and performance for all building trades.

Many firms work across both sectors. The onboarding wizard lets you enable
either or both.

## Public procurement

Public works above the EU threshold follow the Aanbestedingswet 2012, which
implements the EU procurement directives. The standard tendering forms (ARW)
and model contracts (UAV 2012 for building, UAV-GC 2005 for design-and-build)
are the frameworks a Dutch estimate is written to fit.

## BTW

The standard BTW rate is 21%. A reduced rate of 9% applies to renovation and
maintenance of dwellings older than two years. The pack sets the `nl_btw_21`
template as the default.

## Onboarding

A three-step wizard collects the company profile and KvK number, the
specification standards (RAW, STABU, BENG), and a review step that applies
the configuration. Labels are bilingual Dutch and English.

## Standards referenced

- Aanbestedingswet 2012 (Public Procurement Act)
- Bouwbesluit 2012 (Building Decree)
- RAW systematiek
- STABU besteksystematiek
- NEN standards
- BENG (nearly zero-energy buildings)

These are referenced for interoperability and compliance checking. Nothing in
this pack is legal or tax advice.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then
Partner Packs: click Rescan, find "Netherlands Construction Pack", then
Activate pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=netherlands-nl openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
