# Turkey Construction Pack

A country pack for Turkish construction work. It configures the workspace for
the way a Turkish estimate is built: against the Ministry of Public Works unit
prices (Bayindirlik Bakanligi Birim Fiyat), measured to Turkish standards,
priced in lira, with KDV at the applicable rate.

## What makes a Turkish estimate Turkish

Estimates in Turkey are written against official unit prices published annually
by the Ministry of Environment, Urbanisation and Climate Change (formerly
Bayindirlik Bakanligi). These birim fiyat schedules define the pozlar (item
numbers) and unit rates for every standard construction activity. Iller Bankasi
publishes a parallel set for municipal infrastructure work, and the two are not
interchangeable: the item numbering differs, the specifications differ, and a
rate from the wrong schedule is incorrect, not approximate.

Seismic design is not optional. Turkey sits on the Anatolian plate between the
North Anatolian and East Anatolian fault zones, and the TBDY 2018 (Deprem
Yonetmeligi) governs every new building. The seismic zone affects not just
structural design but also cost: higher zones require more reinforcement, more
testing and more documentation.

KDV (Katma Deger Vergisi) at the standard rate applies to construction
services. Reduced rates exist for certain categories including social housing.
Withholding provisions apply on payments to subcontractors.

## What this pack enables

- **Currency TRY**, the `tr_kdv_20` tax template and the `turkey` estimating
  methodology, with a Turkish interface.
- **One cost catalogue**, `cwicr-tr-istanbul`, resolving to TR_NATIONAL via
  the alias or city index.
- **A three-step onboarding wizard** that collects the company profile and
  tax ID, the specification and price base, and confirms the setup, in Turkish
  and English.
- **A demo project**, `mixed-use-istanbul`: a mixed-use development.

## Cost data

No commercial rate schedule is bundled. The Bayindirlik Bakanligi birim fiyat
lists are published documents with their own terms, and the pack references
them without redistributing the rates.

## Standards referenced

- Bayindirlik Bakanligi Birim Fiyat (Ministry of Public Works unit prices)
- Imar Kanunu (Zoning Law No. 3194)
- Deprem Yonetmeligi 2018 / TBDY (Turkish Building Seismic Code 2018)
- TSE construction standards (Turkish Standards Institution)
- Kamu Ihale Kanunu (Public Procurement Law No. 4734)
- Yapi Denetimi Hakkinda Kanun (Building Inspection Law No. 4708)

These are referenced for interoperability and compliance checking. The
publishers' own text, tables and rates are not reproduced here. Nothing in
this pack is legal or tax advice.

## Review status

The regulatory references are drawn from public sources and are pending review
by a Turkish quantity surveyor before they are relied on for a public tender.
No engine rule set is active yet; when one is built it will carry rules for
birim fiyat item references and pozlar numbering.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then
Partner Packs: click Rescan, find "Turkey Construction Pack", then Activate
pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=turkey-tr openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
