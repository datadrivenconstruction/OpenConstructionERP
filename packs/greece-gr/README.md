# Greece Construction Pack

Configures OpenConstructionERP for the Greek construction market. A Greek budget
(προϋπολογισμός) prices every line from an article of the national unified price
lists, the Νέα Ενιαία Τιμολόγια (ΝΕΤ), and then adds the public works cascade:
general expenses and contractor profit, contingency and ΦΠΑ. The pack keeps the
ΝΕΤ article on every line next to a DIN 276 cost group and prices in EUR with 24
percent ΦΠΑ.

## What makes a Greek estimate Greek

**Every line names its ΝΕΤ article.** The ΝΕΤ are six price lists approved in
2017 (ΦΕΚ Β 1746/2017): building works (ΟΙΚ), roads (ΟΔΟ), hydraulic works
(ΥΔΡ), ports (ΛΙΜ), electromechanical works (ΗΛΜ) and landscaping (ΠΡΣ). They
are mandatory for estimating the value of a public works contract. An article
code opens with its chapter: `ΟΙΚ 32.01.06` is C25/30 concrete in chapter 32,
`ΟΙΚ 38.20.02` is B500C reinforcement in chapter 38, `ΟΙΚ 46.01.02` is a
half-brick wall in chapter 46. Work the lists do not cover is priced as a new
article (νέο άρθρο), written `ΝΑΟΙΚ`, `ΝΑΗΛΜ` and so on, in the chapter it
belongs to. Plumbing and electrical items in building budgets still often use
the older ΑΤΗΕ articles, such as `ΑΤΗΕ 8151.1`.

**The cascade is set by law for public works.** Ν. 4412/2016 adds general
expenses and contractor profit (ΓΕ&ΟΕ) at 18 percent on the works (art. 53
§7θ), then contingency (απρόβλεπτα) on the works plus ΓΕ&ΟΕ at 15 percent for a
contract below the EU threshold or 9 percent at or above it (art. 156 §3α), then
cost-plus items and the price revision allowance, and ΦΠΑ on the whole. ΝΕΤ unit
prices therefore exclude ΓΕ&ΟΕ, contingency and ΦΠΑ. The order was checked
against the arithmetic of a published municipal budget.

**ΦΠΑ is 24 percent, with island rates.** The VAT code in force is Ν. 5144/2024,
which replaced Ν. 2859/2000. Art. 26 sets 24 percent standard and 13, 6 and 4
percent reduced rates; on the islands it allows rates 30 percent lower (17, 9,
4 and 3), extended from 1 January 2026 to more North Aegean and Dodecanese
islands. Construction services are standard-rated. Between private businesses
there is no reverse charge for construction: art. 45 §4 applies it only where
the state or a public body owns the works and is itself taxable with a right to
deduct. The optional suspension of VAT on sales of new buildings runs to 31
December 2026 and concerns the sale of the property, not the contractor's
invoice.

## What this pack enables

- **Currency EUR** with the `greece` estimating methodology, and the public
  works cascade the product already carries for Greece: ΓΕ&ΟΕ 18 percent,
  απρόβλεπτα 15 percent and ΦΠΑ 24 percent
- **The Greek ΦΠΑ rates in the dated tax table**: 24 percent standard, 13 and 6
  percent reduced, so a Greek project is priced at 24 percent from the seed
  rather than from a fallback
- **The `greece` validation rule set**: every priced line carries its ΝΕΤ
  article, and the article has the price list's shape and opens a real ΟΙΚ
  chapter, plus the DIN 276 rules for the cost groups. A code typed with Latin
  lookalike letters (`OIK 32.01.06`) is read as the Greek one
- **Contract compliance**: a contract in Greece is signed against the
  `gr_compliance` pack, which runs the Greek rules with DIN 276 and the
  universal quality checks
- **Four reference documents**: the ΝΕΤ price lists, public works contracts,
  the building code and permits, and ΦΠΑ on construction
- **Two demo projects**: an apartment building in Athens and a public primary
  school in Thessaloniki, priced at 2026 levels in EUR excluding ΦΠΑ
- **A three-step onboarding wizard** in Greek and English

The pack names no CWICR region. The Greek cost base is registered as
`GR_NATIONAL`, and the pack resolver matches only the last token of a region
slug, which `national` shares with several other countries' bases; the Greek
base can be selected in the cost database screen.

## Demo price levels

Unit prices are ΝΕΤ-style direct costs at 2026 levels, excluding ΓΕ&ΟΕ,
contingency and ΦΠΑ. They were set against a published March 2025 regional
budget from Heraklion, which prices C25/30 concrete at 101 EUR/m3 for placing,
formwork at 15.70 EUR/m2, B500C reinforcement at 1.07 EUR/kg, machine excavation
at 17.89 EUR/m3, a one-brick wall at 33.50 EUR/m2, plaster at 14 EUR/m2, tiles
at 36 EUR/m2 and ETICS at 50 EUR/m2, plus market prices for thermally broken
aluminium windows from about 280 EUR/m2. With the cascade the apartment building
lands at about 1,480 EUR/m2 and the school at about 1,540 EUR/m2 before ΦΠΑ,
inside the 1,300 to 2,300 EUR/m2 an insurer's 2025 reinstatement table gives for
standard to good apartment buildings.

Lines coded `ΟΙΚ` use articles whose number and description were read in the
published budgets above. Lines coded `ΝΑΟΙΚ` or `ΝΑΗΛΜ` are new articles written
for the demo in the right chapter; their numbers are the demo's own and are not
ΝΕΤ article numbers. These are indications for a demo, not an official price
list.

## Sources

- Υ.Α. ΔΝΣγ/οικ.35577/ΦΝ 466/2017 (ΦΕΚ Β 1746/2017), approval of the ΝΕΤ:
  https://www.e-nomothesia.gr/demosia-erga/upourgike-apophase-dnsg-oik-35577-phn-466-2017.html
- ΝΕΤ ΟΙΚ descriptive price list, chapter structure (TEE seminar copy):
  https://tkm.tee.gr/wp-content/uploads/2024/02/04.%CE%91.-%CE%95%CE%A1%CE%93%CE%91-OIK-%CE%A0%CE%B5%CF%81%CE%B9%CE%B3%CF%81%CE%B1%CF%86%CE%B9%CE%BA%CF%8C-%CE%A4%CE%B9%CE%BC%CE%BF%CE%BB%CF%8C%CE%B3%CE%B9%CE%BF.pdf
- Ν. 4412/2016, public contracts: https://www.taxheaven.gr/law/4412/2016;
  consolidated text for art. 53 and 156: https://eadhsy.gr/n4412/n4412fulltextlinks.html
- Published budgets used for article codes, the cascade and 2025 prices:
  https://www.crete.gov.gr/wp-content/uploads/2025/03/5-%CE%A0%CE%A1%CE%9F%CE%A5%CE%A0%CE%9F%CE%9B%CE%9F%CE%93%CE%99%CE%A3%CE%9C%CE%9F%CE%A3-%CE%9A%CE%95_s.pdf,
  https://messolonghi.gov.gr/wp-content/uploads/2020/03/%CE%9C%CE%B5%CE%BB%CE%AD%CF%84%CE%B7-48_2019.pdf,
  https://www.ktyp.gr/wp-content/uploads/timologio-prosforas_npiagogeia-Triandrias_30.06.2025.pdf
- Ν. 5144/2024, VAT code, art. 26: https://www.e-nomothesia.gr/kat-oikonomia/n-5144-2024.html
- Ν. 5144/2024 art. 45, reverse charge: https://www.taxheaven.gr/law/5144/2024/arthro/45
- Island rates from 1 January 2026, AADE circular Ε.2113/2025:
  https://www.taxheaven.gr/news/72524/dieykriniseis-kai-paradeigmata-gia-toys-meiwmenoys-syntelestes-fpa-apo-01012026
- Suspension of VAT on new buildings, Ν. 5246/2025:
  https://www.e-nomothesia.gr/kat-oikonomia/n-5246-2025.html
- Ν. 4067/2012, building regulation (ΝΟΚ):
  https://www.kodiko.gr/nomothesia/document/117459/nomos-4067-2012
- Ν. 4495/2017, building permits: https://support.e-nomothesia.gr/nomos-4495-2017.html
- Eurocodes, ΔΙΠΑΔ/οικ.372/2014:
  https://www.elinyae.gr/ethniki-nomothesia/ya-dipadoik3722014-fek-1457b-562014
- ΚΕΝΑΚ, ΔΕΠΕΑ/οικ.178581/2017:
  https://www.elinyae.gr/ethniki-nomothesia/ya-depeaoik1785812017-fek-2367b-1272017
- Whole-building cost per m2, 2025:
  https://www.aig.com.gr/content/dam/aig/emea/greece/documents/single-members/applications/consumer/construction_cost_2025.pdf.coredownload.pdf
- Aluminium windows, 2026 market prices:
  https://www.psaxnwmastora.gr/blog/poso-kostizei-allagi-koufomaton-2026

Several official portals refused automated access, so some statutes were read
on consolidated-law sites. The ΝΕΤ price lists and other published price data
are referenced for interoperability and compliance checking and are not
reproduced here. Nothing in this pack is legal, tax or regulatory advice.

## Review status

The chapter structure, rates and statutes are drawn from the public sources
above. Pending review by a Greek engineer who prices public works before they
are relied on for a tender.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then Partner
Packs: click Rescan, find "Greece Construction Pack", then Activate pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=greece-gr openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
