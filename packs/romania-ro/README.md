# Romania Construction Pack

Configures OpenConstructionERP for the Romanian construction market. A Romanian
budget is written as a deviz: a deviz general for the whole investment, a deviz
pe obiect for each object in it, and a deviz ofertă when a contractor prices a
tender. The pack files every priced line under the deviz general chapter it
belongs to, classifies it against DIN 276 for the cost-group view, and prices it
in RON with 21 percent TVA.

## What makes a Romanian estimate Romanian

**The deviz general has six chapters, and the chapter decides who pays.** For a
publicly funded investment the structure is fixed by HG 907/2016: chapter 1 land
and site preparation, 2 utility connections, 3 design and technical assistance,
4 the base investment (4.1 construction and installation works), 5 other costs
(5.1 site organisation, 5.2 fees and charges, 5.3 contingency), and 6
commissioning tests. A cost that cannot be placed in a chapter cannot be
approved or audited, so the pack asks every line for its chapter.

**Prices are built from norme de deviz.** A contractor prices each position
from the consumption norms of the Indicatoare de norme de deviz (indicator C for
buildings, TS for earthworks, and the installation indicators), multiplying
material, labour and plant consumption by current resource prices. The cascade
on the summary adds indirect costs (cheltuieli indirecte), profit, the client's
contingency (cheltuieli diverse și neprevăzute) and TVA. CAM, the 2.25 percent
employer's labour insurance contribution, belongs to the labour cost of each
position and is not a percentage of the bill.

**TVA changed in August 2025.** The standard rate went from 19 to 21 percent and
the 9 and 5 percent rates were replaced by one reduced rate of 11 percent. A
dwelling of up to 120 m2 and 600,000 RON sold to an individual under a contract
signed before 1 August 2025 keeps a transitional 9 percent rate, which Legea
161/2026 extended to 30 September 2026. Construction works are not under the
domestic reverse charge: the list in Codul fiscal art. 331 covers waste, timber,
cereals, electricity, buildings and land taxed by option and some electronics,
not construction services, so a contractor invoices TVA to the client.

**The permit law changed in August 2026.** Legea 169/2026, the new code for
planning, urbanism and construction, came into force on 25 August 2026 and
replaced Legea 50/1991 on building permits and parts of Legea 10/1995 on quality
in construction. Procedures started before that date continue under the old
law. This is taken from legal commentary on the Monitorul Oficial publication
and should be confirmed against the official text.

## What this pack enables

- **Currency RON** with the `romania` estimating methodology: indirect costs 10
  percent, profit 5 percent, contingency 10 percent and TVA 21 percent, the
  national stack the product already carries for Romania
- **The `romania` validation rule set**: every priced line names a deviz general
  chapter, and the chapter is one of those HG 907/2016 defines (4.1, 5.1, 3.8.2
  and so on), plus the DIN 276 rules for the cost groups
- **Contract compliance**: a contract in Romania is signed against the
  `ro_compliance` pack, which runs the Romanian rules with DIN 276 and the
  universal quality checks
- **Four reference documents**: the deviz general, public procurement, building
  permits and quality, and TVA on construction
- **Two demo projects**: a residential block in Cluj-Napoca and an office
  building in Bucharest, priced at 2026 levels in RON excluding TVA
- **The Bucharest CWICR cost database** (`cwicr-ro-bucharest`)
- **A three-step onboarding wizard** in Romanian and English

## Demo price levels

Unit rates are all-in (material, labour and plant) at 2026 levels, excluding
TVA, and were set against published market figures: ready-mixed C25/30 at 500 to
600 RON/m3 supplied with 250 to 450 RON/m3 for placing, reinforcement at 3.8 to
4.8 RON/kg supplied, mechanical excavation at 25 to 60 RON/m3, and plasterboard partitions at 100 to 200 RON/m2. A
mid-range residential block lands at about 1,200 to 1,800 EUR/m2 of gross floor
area and an office building at 1,800 to 2,500 EUR/m2, at about 5.28 RON to the
euro (BNR, September 2026). The minimum gross wage in construction is 4,582 RON
a month. These are market indications for a demo, not an official price index.

## Sources

- HG 907/2016, content of technical-economic documentation:
  https://legislatie.just.ro/public/detaliidocument/185166
- Deviz general chapter headings, from a completed HG 907/2016 form published by
  a county council: https://www.cjmures.ro/Hotariri/Hot2021/deviz_general_hot075_2021.pdf
- Legea 141/2025 amending Codul fiscal art. 291 (TVA 21 and 11 percent, the 9
  percent housing transition): https://static.anaf.ro/static/10/Anaf/legislatie/L_141_2025.pdf
- Legea 161/2026, housing rate extended to 30 September 2026 (legal
  commentary): https://www.juridice.ro/840847/senat-tva-la-locuinte-ramane-9.html
- Codul fiscal art. 331, domestic reverse charge:
  https://www.noulcodfiscal.ro/titlu-7/capitol-14/articol-331.html
- Codul fiscal art. 220^3, CAM 2.25 percent:
  https://www.noulcodfiscal.ro/titlu-5/capitol-9/articol-220-3.html
- Legea 169/2026 replacing Legea 50/1991 (legal commentary):
  https://cscon.ro/catuc-codul-amenajarii-teritoriului-urbanismului-si-constructiilor-ce-aduce-nou/
- Legea 50/1991: https://legislatie.just.ro/Public/DetaliiDocument/1515
- Legea 10/1995: https://legislatie.just.ro/Public/DetaliiDocument/5729
- HG 395/2016, norms for Legea 98/2016 on public procurement:
  https://legislatie.just.ro/Public/DetaliiDocument/179009
- P100-1/2013 seismic design code:
  https://www.mdlpa.ro/userfiles/reglementari/Domeniul_I/I_22_P100_1_2013.pdf
- Construction minimum wage: https://salariile.ro/salariu-minim-constructii-2026
- Market price indications: https://prolist.ro/pret-pentru-lucrari-de-armare-cofrare-si-turnare-beton/,
  https://prolist.ro/pret-pentru-sapatura-mecanizata/,
  https://brig.ro/blog/ghid-complet-preturi-rigips-2026-cat-costa-manopera-si-materialele-in-romania,
  https://brig.ro/cat-costa/constructie-bloc

These are referenced for interoperability and compliance checking. The
Indicatoare de norme de deviz and other published price data are not reproduced
here. Nothing in this pack is legal, tax or regulatory advice.

## Review status

The chapter structure, rates and statutes are drawn from the public sources
above. Pending review by a Romanian cost engineer (devizier) before they are
relied on for a public tender.

## Install

This pack ships inside OpenConstructionERP. Activate it from Modules then Partner
Packs: click Rescan, find "Romania Construction Pack", then Activate pack.

To run a workspace that boots straight into it:

```bash
OE_PACK=romania-ro openconstructionerp serve
```

## License

AGPL-3.0-or-later. OpenConstructionERP is authored and owned by
DataDrivenConstruction.
