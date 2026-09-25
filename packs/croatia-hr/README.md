# Croatia Construction Pack

Configures OpenConstructionERP for the Croatian construction market. A Croatian
estimate is a troškovnik, a priced bill of quantities with all-in unit rates,
and it is priced in EUR (the euro replaced the kuna on 1 January 2023) with
PDV (porez na dodanu vrijednost, VAT) added once, on the recapitulation.

## What makes a Croatian estimate Croatian

A troškovnik groups its items into chapters in a fixed order: construction
works first (pripremni, zemljani, betonski i armiranobetonski, zidarski,
izolaterski radovi), then the finishing trades (limarski, stolarski,
bravarski, keramičarski, podopolagački, soboslikarski i ličilački, fasaderski
radovi), then installations and external works. Every unit rate is all-in:
labour, material, plant, overheads and profit sit inside the rate, so no
separate overhead or profit lines follow the chapters. Each chapter closes with
a total, and the rekapitulacija sums the chapters and adds PDV.

Public works are tendered under the Zakon o javnoj nabavi (NN 120/16, 114/22).
The contracting authority publishes the troškovnik through the Elektronički
oglasnik javne nabave and bidders return it priced without changing it.
Building permits, the construction log and the use permit follow the Zakon o
gradnji (NN 153/13 and amendments).

PDV is 25 percent at the standard rate, which is what construction works are
charged at. The reduced rates are 13 and 5 percent, and 0 percent applies to
the supply and installation of solar panels on residential and public-interest
buildings. Between two taxable persons construction services fall under the
domestic reverse charge. From 1 January 2026 invoices between businesses in the
VAT system are issued as eRačun under EN 16931 (Zakon o fiskalizaciji, NN
89/25).

## What this pack enables

- **Currency EUR** with the `hr_pdv_25` tax template. The platform's dated
  tax table carries PDV at 25 percent as the default rate, with 13, 5 and 0
  percent beside it
- **Zagreb cost database** (`HR_ZAGREB`, EUR) preloaded from the CWICR
  catalogue, with Croatian item descriptions
- **DIN 276 rule set** for classification validation, as the nearest
  supported hierarchy a Croatian troškovnik maps onto
- **Five reference documents** covering the troškovnik, the Building Act,
  public procurement, PDV and e-invoicing, each switching on the bill checks
  that apply
- **Two demo projects**: a residential building in Zagreb and a mixed-use
  office building in Split, both priced at Croatian 2026 market rates in EUR
  excluding PDV
- **Croatian interface** by default, with English available

## Standards referenced

- Zakon o gradnji (NN 153/13, 20/17, 39/19, 125/19)
- Zakon o javnoj nabavi (NN 120/16, 114/22)
- Zakon o porezu na dodanu vrijednost (NN 73/13 and amendments)
- Zakon o fiskalizaciji (NN 89/25) and EN 16931
- GN norms (Prosječne norme u građevinarstvu) for labour and material norms
- Opći tehnički uvjeti za radove na cestama for road works
- HRN EN Eurocodes (Croatian adoption of European structural standards)

These are referenced for interoperability and compliance checking. Nothing in this
pack is legal, tax or regulatory advice.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then Partner
Packs: click Rescan, find "Croatia Construction Pack", then Activate pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=croatia-hr openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
