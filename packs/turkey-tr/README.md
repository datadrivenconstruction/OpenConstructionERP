# Turkey Construction Pack

Pre-configures OpenConstructionERP for work in Türkiye: the poz numbers a
Turkish bill of quantities is written against, the units it is measured in,
the combined profit and general expenses line it is totalled through, KDV, the
public holiday calendar and the lira.

## What makes a Turkish bill Turkish

**Every line cites a poz number.** The numbers come from the unit-price book
(İnşaat ve Tesisat Birim Fiyatları) that the Yüksek Fen Kurulu Başkanlığı of
the Çevre, Şehircilik ve İklim Değişikliği Bakanlığı publishes each year with
its analyses. A number has three groups, `NN.NNN.NNNN`, and the first group is
the chapter of the book:

| Chapter | Turkish | English |
|---|---|---|
| 10 | Rayiçler | Resource prices: labour, materials, transport |
| 15 | İnşaat | Building works |
| 19 | Makine saatlik ücret analizleri | Hourly plant cost analyses |
| 25 | Mekanik tesisat | Mechanical installation |
| 35 | Elektrik tesisatı | Electrical installation |

So `15.150.1005` is a concrete item, `25.305.1104` a plastic waste pipe and
`35.150.3101` a halogen-free cable. Other public bodies publish their own
lists in the same shape under other first groups. Older contracts still carry
the previous `NN.NNN/N` numbering, and an item the book does not have is
numbered by the bill itself as an own item (özel poz) and priced by its own
analysis.

**The 25 percent is added once.** Contractor profit and general expenses
(yüklenici kârı ve genel giderler) are a single combined 25 percent, set by
Article 11 of the Yapım İşleri İhaleleri Uygulama Yönetmeliği for prices that
do not yet contain it. A published unit price already contains it; the
analysis cost underneath does not. A bill priced at analysis cost adds the
25 percent once on its summary. A bill priced from the published unit prices
must not add it again. The pack's markup stack carries the line, so remove it
from a bill whose rates are the published ones.

**KDV has three rates.** 20 percent is the general rate, 10 percent applies
to the supplies on list (II) and 1 percent to those on list (I) of Karar
2007/13033, as last changed by Karar 7346 with effect from 10 July 2023.
Which supplies sit on the lists is a question for an accountant and is not
encoded here.

## What this pack enables

- Currency TRY at two decimals, a Turkish interface and the `turkey`
  estimating method: 25 percent profit and general expenses, then KDV.
- The `birimfiyat` classification, so a line is coded with its poz number.
- Ten validation rules under the `birimfiyat` rule set: a poz number is
  present, it is well formed, its chapter is one a publisher uses, the unit is
  one the book measures in, one poz number is not measured in two units or
  priced at two rates within a bill, an own item carries its analysis, and the
  25 percent is not applied twice. The last two look each Ministry poz up in
  the installed national cost base: the line is measured in the unit the book
  defines the poz in, and the line's rate is set beside the published price.
  The rate check only states the difference, because a tender discount below
  the published price is ordinary; it raises a warning only past a percentage
  set in `rule_packs/bayindirlik_unit_prices.json`, which ships unset. It does
  not know which year's book the base holds, compares in TRY only, and says so
  once, instead of passing, when the base is not installed or is switched to
  another market. Three further checks stay planned, not built: the document
  lists them and why.
- Five reference documents: the unit-price book, the mechanical and electrical
  general technical specifications with the fire regulation, the public
  procurement law, the earthquake code and the Turkish standards. Only the
  first runs rules; the other four are reference only.
- The national cost base, `cwicr-tr-national`, which carries poz numbers.
- The Turkish public holidays, with Ramazan Bayramı and Kurban Bayramı on the
  dates the Diyanet İşleri Başkanlığı publishes, for 2025 to 2033.
- A demo project, `mixed-use-istanbul`.
- A bilingual onboarding script. Nothing in the product renders it yet, so it
  documents the choices a Turkish setup involves and changes no setting.

The pack hides no module. Every module stays visible to every user.

## What the platform provides, outside this pack

Tevkifat, stopaj, the e-Fatura file and the hakediş are features of
OpenConstructionERP itself. The pack configures none of them and they work
with or without it.

- Withheld VAT (KDV tevkifatı), income tax withholding (stopaj) and stamp duty
  (damga vergisi) are computed from dated rate tables and shown with their
  basis, rate and legal reference. A person chooses the category on the
  document and the figures are confirmed by a person before they count; a
  figure whose input is missing is held, never printed as zero.
- The hakediş progress payment certificate is computed for unit price and
  lump sum contracts and printed in Turkish, English or both.
- A UBL-TR e-Fatura file is written unsigned, with a validation report, for a
  licensed integrator to sign and submit. Signing, submission and any
  connection to an integrator or to the revenue administration are not built,
  and acceptance of the file by an integrator has not been confirmed.
- The site registers and the daily diary export as a PDF or a workbook in
  Turkish or English.

The rates, fractions and thresholds behind the first item are under the same
review as this pack, stated below, and some are still marked unconfirmed in
the data.

## A variant for one trade

`turkey-tr-mep` is this pack with the menu and module set of a mechanical,
electrical and plumbing contractor laid over it. It is built from this pack's
manifest when it is loaded, so a correction made here reaches it, and it
cannot be installed without this pack. An installation runs one of the two.

## Who the reference documents are for

The mechanical and electrical specifications and the unit-price book apply to
any contractor. The public procurement document applies only to tenders let by
public bodies, and the earthquake code and the standards document are
structural: an installation contractor working for private owners can leave
those three switched off.

## Cost data

The pack loads one cost base, the national one (`TR_NATIONAL`). It is built
from the official state unit-price lists: item texts in Turkish only, prices
in TRY, and the 2025 edition for the Ministry books. Mechanical installation
(chapter 25) and electrical installation (chapter 35) are both in it, each
item with its resource breakdown. Its prices are the published ones, so they
already contain the 25 percent.

It is the public-sector reference, not a market price database. For
mechanical and electrical work it does not contain:

- brands, models or supplier quotations: every item is a generic specification
- precision cooling units for data halls
- chillers above about 1,700 kW
- busbar trunking
- medium voltage equipment
- UPS above about 600 kVA and generator sets above about 1,750 kVA
- building management systems
- testing and commissioning as priced items

Price the main plant of a private project from supplier quotations and use
the base for pipework, cable, fixtures and installation labour.

Licence terms of the price base: see the cost base registry.

## Standards and statutes referenced

- İnşaat ve Tesisat Birim Fiyatları, Çevre, Şehircilik ve İklim Değişikliği
  Bakanlığı, Yüksek Fen Kurulu Başkanlığı
- Yapım İşleri İhaleleri Uygulama Yönetmeliği, Madde 11
- 3065 sayılı Katma Değer Vergisi Kanunu, Karar 2007/13033 and Karar 7346
- 2429 sayılı Ulusal Bayram ve Genel Tatiller Hakkında Kanun
- 6102 sayılı Türk Ticaret Kanunu, Madde 1530 (payment terms between
  commercial enterprises)
- Makina Tesisatı Genel Teknik Şartnamesi and Elektrik Tesisatı Genel Teknik
  Şartnamesi
- Binaların Yangından Korunması Hakkında Yönetmelik (2007/12937)
- 4734 sayılı Kamu İhale Kanunu and 4735 sayılı Kamu İhale Sözleşmeleri Kanunu
- 4708 sayılı Yapı Denetimi Hakkında Kanun
- Türkiye Bina Deprem Yönetmeliği 2018 (TBDY)
- Türk Standardları Enstitüsü (TSE) standards

These are referenced for interoperability and checking. The publishers' own
text, tables and prices are not reproduced here. Nothing in this pack is legal
or tax advice.

## Language

Installing the pack switches the interface to Turkish (`default_locale` is
`tr`). The pack brings no strings of its own for that: the Turkish interface
is the bundle OpenConstructionERP ships, and anyone can switch to another
language at any time. The pack's own Turkish vocabulary sits where it is read,
in the onboarding script and in the reference documents.

## Review status

The numbering, the units and the rates are drawn from the published
legislation and from the structure of the unit-price book. They are pending
review by a Turkish quantity surveyor and a Turkish accountant, and should not
be relied on for a tender or a tax filing before that review.

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
