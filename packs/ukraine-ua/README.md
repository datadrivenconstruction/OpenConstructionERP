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
of 08.06.2026) brought it in line with постанова КМУ №1512 of 19.11.2025.
Пункт 1 of that resolution covers construction paid for with budget funds,
funds of state and communal enterprises or state-guaranteed loans, for the
duration of martial law. Its підпункт 4 sets general production costs
(загальновиробничі витрати) at 10, administrative costs at 3 and profit at 15
percent of direct costs in the investor's estimate (інвесторська кошторисна
документація), and caps them at not more than 10, 3 and 15 percent at the
stage of the contract price and settlements. Construction paid for privately
is outside пункт 1.

The risk allowance is set by Додаток 28 to the Настанова (пункт 4.40), as a
percentage of chapters 1 to 12. Its table 2, for the design stage П and
individual projects, gives 1.8 percent for housing (row 3) and 3.0 percent for
public buildings other than housing (row 2).

Which of the pack's figures come from a clause and which do not:

| Line | Pack value | Source |
|---|---|---|
| ПДВ | 20 % | Податковий кодекс, п. 193.1 пп. «а» |
| Risk allowance, housing / public | 1.8 % / 3.0 % | Настанова, Додаток 28, table 2, rows 3 and 2 |
| General production costs | 9 % | No clause. КМУ №1512 п. 1 пп. 4 caps it at 10 % in a contract price |
| Administrative costs | 2.5 % | No clause. КМУ №1512 п. 1 пп. 4 caps it at 3 % in a contract price |
| Profit | 7 % | No clause. КМУ №1512 п. 1 пп. 4 caps it at 15 % in a contract price |

The 9, 2.5 and 7 percent are a contractor's editable starting points, chosen
below the caps; they are not official figures. A publicly funded investor's
estimate uses exactly 10, 3 and 15 percent, and a privately funded estimate
derives these lines from the Настанова's own indicators.

**ПДВ is 20 percent.** Податковий кодекс п. 193.1 sets the basic rate at 20
percent (пп. «а»), 7 percent for medicines, medical devices, clinical trials and
certain cultural services (пп. «в») and 14 percent for listed agricultural goods
(пп. «г»); none of the reduced rates names construction work, so it is taxed at
the basic rate (п. 194.1). Under п. 197.1.14 the supply of housing is exempt
except its first supply, and the first supply includes the construction of such
housing for a customer. No domestic reverse charge for construction services
was found; a contractor invoices ПДВ to its customer.

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
a demo, not an official price index. Both demos carry a contractor's markups,
so the Kyiv school is a contract price under the caps of КМУ №1512 п. 1 пп. 4,
not the investor's estimate.

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
- Постанова КМУ №1512 of 19.11.2025, as amended by №526 of 24.04.2026 and
  №1073 of 26.08.2026, п. 1 пп. 4 read in the official text:
  https://zakon.rada.gov.ua/laws/show/1512-2025-%D0%BF
- Закон №922-VIII, public procurement: https://zakon.rada.gov.ua/laws/show/922-19
- Постанова КМУ №1178 of 12.10.2022: https://zakon.rada.gov.ua/go/1178-2022-%D0%BF
- Податковий кодекс України, пп. 193.1, 194.1 and 197.1.14, read in the
  official text: https://zakon.rada.gov.ua/laws/show/2755-17; the tax service
  on first supply of housing: https://kyiv.tax.gov.ua/media-ark/news-ark/631771.html
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

The ПДВ rates (Податковий кодекс пп. 193.1, 194.1, 197.1.14) and the
wartime rates of постанова КМУ №1512 (п. 1 пп. 4) were read in the official
texts on zakon.rada.gov.ua in September 2026. Додаток 28 was read in its 2021
published text and may have been revised by Зміни №5 and №6, as may the
indicators of Додатки 25 and 27. Pending review by a Ukrainian cost engineer
(кошторисник) before any of it is relied on for a public tender.

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
