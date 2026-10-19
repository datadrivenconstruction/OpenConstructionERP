# Czech Republic Construction Pack

Configures OpenConstructionERP for the Czech construction market. The Czech
estimating tradition is built on TSKP (Tridnik stavebnich konstrukci a praci),
a work classification system that structures both project budgets (rozpocet)
and price databases. Currency is CZK with 21% DPH on construction services.

## What makes a Czech estimate Czech

A Czech rozpocet (construction budget) is structured by TSKP groups, which
classify building works into a hierarchy of construction and work types.
Price databases from providers like URS or RTS supply unit rates keyed to
TSKP codes, and a rozpocet that cannot be read against those codes cannot
be checked against any published price level.

Public procurement follows Zakon 134/2016 Sb. (the Public Procurement Act)
and the associated decree 169/2016 Sb. that governs pricing of public
construction works. The Stavebni zakon (Building Act) 283/2021 Sb. defines
the building permit and control framework.

DPH (dan z pridane hodnoty, VAT) on construction services is 21 percent at
the standard rate, with a reduced 12 percent rate applying to certain housing
works. The pack does not set DPH.

## What this pack enables

- **Currency CZK** (the pack does not set DPH) and the `czechia`
  estimating methodology
- **DIN 276 rule set** for classification validation, as the nearest supported
  hierarchy Czech TSKP-structured bills map onto
- **Two demo projects**: an office building in Prague and a residential
  development in Brno, both priced at Czech 2026 market rates in CZK
  excluding DPH
- **CSN, TSKP and public procurement regulatory references** in the pack
  metadata

## Standards referenced

- CSN 73 standards (Ceske technicke normy, construction)
- TSKP (Tridnik stavebnich konstrukci a praci)
- Zakon 134/2016 Sb. (Public Procurement Act)
- Stavebni zakon 283/2021 Sb. (Building Act)
- Vyhlaska 169/2016 Sb. (Public works contracts pricing)
- CSN EN Eurocodes (Czech adoption of European structural standards)

These are referenced for interoperability and compliance checking. Nothing in this
pack is legal, tax or regulatory advice.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then Partner
Packs: click Rescan, find "Czech Republic Construction Pack", then Activate pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=czechia-cz openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
