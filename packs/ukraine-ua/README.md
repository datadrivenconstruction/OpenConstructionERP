# Ukraine Construction Pack

Configures OpenConstructionERP for the Ukrainian construction market. A
Ukrainian estimate (кошторис) is built under the Настанова з визначення вартості
будівництва: local estimates roll up into object estimates and then into the
зведений кошторисний розрахунок, the summary estimate of twelve chapters. The
pack files every priced line under its chapter, classifies it against DIN 276
for the cost-group view, and prices it in UAH with 20 percent ПДВ.

## What makes a Ukrainian estimate Ukrainian

**The Настанова and its twelve chapters.** Наказ Мінрегіону №281 of 01.11.2021
approved the national cost estimating norms, the Настанова з визначення вартості
будівництва among them, in force since 08.11.2021; it cancelled ДСТУ Б
Д.1.1-1:2013 and the related 2013 norms. The chapters of the summary estimate,
as set out in Зміна №2 (наказ №244 of 01.12.2022), are: 1 site preparation, 2
main objects, 3 ancillary and service objects, 4 energy, 5 transport and
communications, 6 external networks, 7 landscaping, 8 temporary buildings, 9
other works and costs, 10 the client's service and engineering services, 11
training of operating staff, and 12 design, survey, review and author's
supervision. Profit, administrative costs, the risk allowance and inflation are
added after chapter 12, then ПДВ. The pack asks every line for its chapter.

**The cascade under martial law.** The Настанова prices profit and
administrative costs from indicators per labour hour that depend on the
consequence class, and Зміни №5 (наказ №456 of 09.03.2026) and №6 (наказ №1069
of 08.06.2026) brought it in line with постанова КМУ №1512 of 19.11.2025. That
resolution caps general production costs (загальновиробничі витрати) at 10,
administrative costs at 3 and profit at 15 percent of direct costs for the
duration of martial law. The pack's demos carry 9, 2.5 and 7 percent, inside
those ceilings, and the Додаток 28 risk allowance at the design stage: 1.8
percent for housing and 3.0 percent for public buildings. These are editable
starting points, not rates the law fixes.

**ПДВ is 20 percent.** The reduced rates of 14 and 7 percent do not reach
construction work. The first supply of newly built housing is taxable and later
supplies are exempt. No domestic reverse charge for construction services was
found; a contractor invoices ПДВ to its customer.

**Public works go through Закон №922-VIII.** Works with an expected value of 1.5
million hryvnias or more are procured under the public procurement law through
the electronic procurement system, under the martial law procedure of постанова
КМУ №1178.

## What this pack enables

- **Currency UAH** with the `ukraine` estimating methodology and a Ukrainian
  markup stack for every new bill: general production costs 9 percent, the risk
  allowance 1.8 percent on the chapters, administrative costs 2.5 percent,
  profit 7 percent and ПДВ 20 percent. Risk is placed before profit and
  administrative costs because the Настанова takes it on chapters 1 to 12,
  which hold neither
- **The `ukraine` validation rule set**: every priced line names its chapter of
  the summary estimate, and the chapter is one of the twelve, plus the DIN 276
  rules for the cost groups
- **Contract compliance**: a contract in Ukraine is signed against the
  `ua_compliance` pack, which runs the Ukrainian rules with DIN 276 and the
  universal quality checks
- **Four reference documents**: the Настанова and the summary estimate, public
  procurement, the ДБН, and ПДВ on construction
- **Two demo projects**: a residential building in Lviv and a publicly funded
  school with a civil protection shelter in Kyiv, priced at 2026 levels in UAH
  excluding ПДВ
- **A three-step onboarding wizard** in Ukrainian and English

No CWICR cost database covers Ukraine yet, so the pack preloads none.

## Demo price levels

Unit rates are all-in direct costs at 2026 levels, excluding ПДВ, and were set
against published market figures: ready-mixed C25/30 at 3,570 to 5,212 UAH/m3
supplied, A500C reinforcement at about 33,000 UAH/t supplied, aerated block
masonry labour at 800 to 1,500 UAH/m3, ETICS at 1,800 to 2,960 UAH/m2 turnkey
and PVC windows at 4,887 to 7,310 UAH/m2. The estimate wage in 2026 is 37,860
UAH a month in Kyiv and about 20,330 UAH in Lviv. The Lviv building lands at
about 27,300 UAH/m2 and the Kyiv school at about 35,900 UAH/m2 before ПДВ, at
about 51.3 UAH to the euro (NBU, September 2026). For comparison, the
ministry's national indicator for the cost of housing as of 1 April 2026 is
26,623 UAH/m2 including ПДВ (наказ №786 of 16.04.2026), a benchmark for state
housing programmes rather than a market price. These are market indications for
a demo, not an official price index.

## Sources

- Наказ Мінрегіону №281 of 01.11.2021: https://zakon.rada.gov.ua/laws/show/v0281914-21
- Entry into force on 08.11.2021:
  http://ukrbudex.org.ua/galuzevi-novini-ta-podiyi/novunu/koshtorisni-normi-ukrayini-nabrali-chinnosti-08-listopada-20-110
- Зміна №2, chapters of the summary estimate:
  https://radnuk.com.ua/wp-content/uploads/2023/05/knu-zmina-2.pdf
- Додатки 25, 27 and 28 (profit, administrative costs, risk):
  https://radnuk.com.ua/wp-content/uploads/2021/12/dodatok-25.pdf,
  https://radnuk.com.ua/wp-content/uploads/2021/12/dodatok-27.pdf,
  https://radnuk.com.ua/wp-content/uploads/2021/12/dodatok-28.pdf
- Зміна №5: https://mindev.gov.ua/npas/pro-zatverdzhennia-zminy-5-do-koshtorysnykh-norm-ukrainy-u-budivnytstvi
- Зміна №6: https://mininfra.gov.ua/news/minrozvytku-zakripylo-nakazom-onovleni-pravyla-vyznachennia-vartosti-budivnytstva-za-publichni-koshti
- Постанова КМУ №1512 of 19.11.2025: https://zakon.rada.gov.ua/laws/show/1512-2025-%D0%BF
- Закон №922-VIII, public procurement: https://zakon.rada.gov.ua/laws/show/922-19
- Постанова КМУ №1178 of 12.10.2022: https://zakon.rada.gov.ua/go/1178-2022-%D0%BF
- Податковий кодекс України: https://zakon.rada.gov.ua/laws/show/2755-17; the
  2026 rates: https://fakty.com.ua/ua/ukraine/ekonomika/20260107-yakyj-pdv-v-ukrayini-u-2026-roczi-shho-vidomo-pro-rozmir-ta-zminy/;
  first supply of housing: https://kyiv.tax.gov.ua/media-ark/news-ark/631771.html
- ДБН В.1.2-14:2018: https://e-construction.gov.ua/laws_detail/3199634775304307868?doc_type=2
- ДБН В.2.2-15:2019: https://e-construction.gov.ua/laws_detail/3199650971919583106
- ДБН А.2.2-3:2014, archived status: https://e-construction.gov.ua/laws_detail/3192355188719486804
- Housing cost indicator, наказ №786 of 16.04.2026:
  https://mininfra.gov.ua/npas/pro-zatverdzhennia-pokaznykiv-oposeredkovanoi-vartosti-sporudzhennia-zhytla-za-rehionamy-ukrainy-rozrakhovanykh-stanom-na-01-kvitnia-2026-roku
- Market prices: https://pl2t.com/uk/shop/beton-m400-v30-s25-30/,
  https://delay-krasivo.com.ua/uk/kladka-gazobloku/,
  https://domremonta.com.ua/uk/uteplenie-fasadov/,
  https://okna.ua/en/price_list/r-okna

The РЕКН resource norms and other published price data are referenced for
interoperability and compliance checking and are not reproduced here. Nothing in
this pack is legal, tax or regulatory advice.

## Review status

The chapter structure, rates and statutes are drawn from the public sources
above. The ПДВ rates were taken from reporting rather than the text of ст. 193,
and the indicators of Додатки 25 and 27 may have been revised by Зміни №5 and
№6. Pending review by a Ukrainian cost engineer (кошторисник) before they are
relied on for a public tender.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then Partner
Packs: click Rescan, find "Ukraine Construction Pack", then Activate pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=ukraine-ua openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
