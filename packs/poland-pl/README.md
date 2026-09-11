# Poland Construction Pack

A country pack for construction work in Poland. It configures the workspace
for the Polish market: DIN 276 classification (Poland follows the German
tradition for cost grouping), PLN currency, 23% VAT, and the norm catalogue
system (KNR, KNNR) that underpins Polish cost estimation.

## What this pack configures

- **Currency PLN**, the `pl_vat_23` tax template and the `poland` estimating
  methodology, with a Polish interface.
- **DIN 276 classification** as the default cost grouping, which is the
  standard used in Polish practice following the German DIN tradition.
- **One CWICR cost region**, `cwicr-pl-warsaw`, resolving to PL_WARSAW.
- **One demo project**: a residential building in Warsaw.

## Norm catalogues

Polish cost estimation is built on norm catalogues that specify the labour
hours, material quantities and equipment time for every unit of construction
work. KNR (Katalog Nakladow Rzeczowych) is the standard set of catalogues
maintained since the 1980s and updated periodically. KNNR (Kosztorysowe Normy
Nakladow Rzeczowych) is the updated series of cost estimation norms.

A Polish kosztorys (cost estimate) is assembled by multiplying quantities from
the design by norms from the catalogue, then applying current unit prices for
labour, materials and equipment. The three standard estimate types are the
kosztorys inwestorski (investor estimate, for budget planning), the kosztorys
ofertowy (tender estimate, for bidding) and the kosztorys powykonawczy
(as-built estimate, for final settlement).

## Public procurement

Public works follow Prawo zamowien publicznych (PZP), the Polish public
procurement law implementing the EU procurement directives. The kosztorys
inwestorski is the investor's reference estimate required by the regulation
on determining the value of construction works. The format is prescribed by
the Rozporzadzenie w sprawie kosztorysu inwestorskiego.

## VAT

The standard VAT rate is 23%. A reduced rate of 8% applies to construction and
renovation services for residential buildings up to 300 square metres of usable
area. The pack sets the `pl_vat_23` template as the default.

## Onboarding

A three-step wizard collects the company profile and NIP, the norm catalogues
(KNR, KNNR) and classification preferences, and a review step that applies the
configuration. Labels are bilingual Polish and English.

## Standards referenced

- Prawo zamowien publicznych (PZP, Public Procurement Law)
- Prawo budowlane (Construction Law)
- KNR (Katalog Nakladow Rzeczowych)
- KNNR (Kosztorysowe Normy Nakladow Rzeczowych)
- Rozporzadzenie w sprawie kosztorysu inwestorskiego

These are referenced for interoperability and compliance checking. Nothing in
this pack is legal or tax advice.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then
Partner Packs: click Rescan, find "Poland Construction Pack", then Activate
pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=poland-pl openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
