# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The regional markup table, and the one map that says which country uses it.

This is the canonical stack a bill gets seeded with, and it is the only place
the platform states what a national markup convention contains. It used to live
inside ``app.modules.boq.service`` next to the code that reads it, which was
fine while it had exactly one reader. It has two now: the methodology catalogue
in :mod:`app.modules.methodology.templates` derives its country templates from
this table rather than restating them, so that a country cannot be priced two
ways by two engines that both claim to describe it.

That second reader is why this module exists as its own file, and it comes with
a constraint. Standard library only: no ``app.*`` imports, no SQLAlchemy, no
Pydantic, nothing that ``templates.py`` is not allowed to pull in. The
methodology catalogue is loadable standalone on Python 3.11 for its unit tests
and must stay that way, and a single convenience import here would end that
without any test going red until somebody runs the local interpreter. Put a
helper that needs the ORM in ``service.py``, not here.

What the table is NOT: a claim that these percentages are regulated figures.
They are documented, defensible starting points for a medium commercial
building, and every seeded line is editable in-app the moment it lands.
"""

from __future__ import annotations

__all__ = [
    "DEFAULT_MARKUP_TEMPLATES",
    "REGION_BY_COUNTRY",
    "NON_SINGLE_TAX_REGIONS",
    "CONSTRUCTION_TIER_COUNTRIES",
    "resolve_region_lines",
    "region_lines_for_country",
    "region_key_for_country",
]


# ── Regional markup templates ────────────────────────────────────────────────
#
# Based on industry standards for medium commercial building projects.
# Percentages applied to direct cost unless noted; tax items are cumulative.
# Sources: VOB/HOAI, NRM1/RICS, US cost index/AIA, BATIPRIX, FIDIC, CPWD, AIQS,
# MLIT, TCU/SINAPI, Byggakademin, ГЭСН/МДС, 建标[2013]44号, 조달청.
#
# ``apply_to`` is NOT a stylistic choice and these templates deliberately do not
# agree on it. ``cumulative`` means direct cost plus EVERY preceding line, so a
# ``cumulative`` line placed after the profit line earns the contractor a margin
# on its own allowance. Whether that is right depends on the market:
#
#   * A bond or a tax is levied on the contract value the client actually signs,
#     which does include overhead and profit. ``cumulative`` is correct there.
#   * A contingency is an allowance against cost risk. Charging profit on it
#     inflates the bid by a margin on money nobody expects to spend, so it must
#     NOT sit on a base containing profit - unless the market's own standard
#     method says otherwise, which for UK and RU it does (see those blocks).
#
# Before you normalise these six-line stacks to one shape, read the per-region
# note. ``tests/unit/test_boq_service_pure_helpers.py`` pins the intent of every
# region, so a new template that compounds contingency onto profit fails until
# its entry there is updated deliberately.

DEFAULT_MARKUP_TEMPLATES: dict[str, list[dict[str, object]]] = {
    # ── Germany / Austria / Switzerland ─────────────────────────────────
    # VOB/B Zuschlagskalkulation, EFB Preisblatt 221
    "DACH": [
        {
            "name": "Baustellengemeinkosten (BGK)",
            "category": "overhead",
            "percentage": "10.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Allgemeine Geschäftskosten (AGK)",
            "category": "overhead",
            "percentage": "8.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "Wagnis (W)",
            "category": "contingency",
            "percentage": "2.0",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        {
            "name": "Gewinn (G)",
            "category": "profit",
            "percentage": "3.0",
            "apply_to": "direct_cost",
            "sort_order": 3,
        },
        {
            "name": "Mehrwertsteuer (MwSt.)",
            "category": "tax",
            "percentage": "19.0",
            "apply_to": "cumulative",
            "sort_order": 4,
        },
    ],
    # ── United Kingdom ──────────────────────────────────────────────────
    # RICS NRM1/NRM2, UK cost index Elemental Standard Form
    # The two risk lines are ``cumulative`` after profit ON PURPOSE. NRM1 builds
    # the cost plan as works cost estimate, then main contractor's overheads and
    # profit, and only then risk allowances, so under that method the risk base
    # legitimately contains the contractor's margin. This is the opposite of the
    # US block below and both are correct in their own market.
    "UK": [
        {
            "name": "Main Contractor's Preliminaries",
            "category": "overhead",
            "percentage": "13.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Main Contractor's Overheads",
            "category": "overhead",
            "percentage": "5.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "Main Contractor's Profit",
            "category": "profit",
            "percentage": "5.0",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        {
            "name": "Design Development Risk",
            "category": "contingency",
            "percentage": "3.0",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
        {
            "name": "Construction Contingency",
            "category": "contingency",
            "percentage": "3.0",
            "apply_to": "cumulative",
            "sort_order": 4,
        },
        {
            "name": "VAT",
            "category": "tax",
            "percentage": "20.0",
            "apply_to": "cumulative",
            "sort_order": 5,
        },
    ],
    # ── United States ───────────────────────────────────────────────────
    # US cost index / AIA / CSI MasterFormat Division 01
    "US": [
        {
            "name": "General Conditions (Div. 01)",
            "category": "overhead",
            "percentage": "8.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "General Contractor Overhead",
            "category": "overhead",
            "percentage": "7.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "General Contractor Profit",
            "category": "profit",
            "percentage": "5.0",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        {
            "name": "General Liability Insurance",
            "category": "insurance",
            "percentage": "1.0",
            "apply_to": "direct_cost",
            "sort_order": 3,
        },
        # ``cumulative`` is deliberate and correct here: a payment and
        # performance bond is written against the contract sum, so the premium
        # base includes general conditions, overhead, profit and insurance.
        {
            "name": "Performance & Payment Bond",
            "category": "bond",
            "percentage": "1.5",
            "apply_to": "cumulative",
            "sort_order": 4,
        },
        # Both contingencies are ``direct_cost`` and must stay that way. They
        # were ``cumulative``, which put the general contractor's profit line
        # (sort_order 2) inside the contingency base and charged a 5 % margin on
        # an allowance that exists precisely because the money may never be
        # spent. US practice carries contingency in the cost of work, under the
        # fee, not on top of it. Do not "tidy" these to match the bond above.
        {
            "name": "Design Contingency",
            "category": "contingency",
            "percentage": "5.0",
            "apply_to": "direct_cost",
            "sort_order": 5,
        },
        {
            "name": "Construction Contingency",
            "category": "contingency",
            "percentage": "3.0",
            "apply_to": "direct_cost",
            "sort_order": 6,
        },
    ],
    # ── France ──────────────────────────────────────────────────────────
    # Méthode du Déboursé Sec, BATIPRIX, Code des marchés publics
    "FR": [
        {
            "name": "Frais de chantier (FC)",
            "category": "overhead",
            "percentage": "10.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Frais généraux (FG)",
            "category": "overhead",
            "percentage": "15.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "Bénéfice et aléas (B&A)",
            "category": "profit",
            "percentage": "8.0",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        {
            "name": "TVA",
            "category": "tax",
            "percentage": "20.0",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
    ],
    # ── Gulf / UAE ──────────────────────────────────────────────────────
    # FIDIC Red Book, AECOM ME Handbook
    "GULF": [
        {
            "name": "Preliminaries & General (P&G)",
            "category": "overhead",
            "percentage": "13.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Contractor Overhead",
            "category": "overhead",
            "percentage": "5.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "Contractor Profit",
            "category": "profit",
            "percentage": "7.0",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        {
            "name": "Insurance (CAR + TPL)",
            "category": "insurance",
            "percentage": "0.5",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
        {
            "name": "Performance Bond",
            "category": "bond",
            "percentage": "0.5",
            "apply_to": "cumulative",
            "sort_order": 4,
        },
        {
            "name": "VAT",
            "category": "tax",
            "percentage": "5.0",
            "apply_to": "cumulative",
            "sort_order": 5,
        },
    ],
    # ── India ───────────────────────────────────────────────────────────
    # UNRATIFIED: the contingency line is ``cumulative`` after profit, the shape
    # corrected in the US block. Left as written because no ordering source was
    # confirmed either way, not because it was checked and endorsed.
    # CPWD Works Manual 2019, DSR, IS:7272
    "IN": [
        {
            "name": "Site Overhead / Establishment",
            "category": "overhead",
            "percentage": "7.5",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Head Office Overhead",
            "category": "overhead",
            "percentage": "7.5",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "Contractor's Profit",
            "category": "profit",
            "percentage": "7.5",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        {
            "name": "Contingency",
            "category": "contingency",
            "percentage": "3.0",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
        {
            "name": "Labour Cess (BOCW)",
            "category": "other",
            "percentage": "1.0",
            "apply_to": "cumulative",
            "sort_order": 4,
        },
        {
            "name": "GST",
            "category": "tax",
            "percentage": "18.0",
            "apply_to": "cumulative",
            "sort_order": 5,
        },
    ],
    # ── Australia ───────────────────────────────────────────────────────
    # UNRATIFIED: three ``cumulative`` allowances sit after the margin line, so
    # they carry contractor margin the way the US block no longer does. Left as
    # written because no ordering source was confirmed, not because it is known
    # to be right. The "Escalation Allowance" here is also a flat percentage
    # standing in for time-based escalation; the price-index module holds the
    # real date-to-date arithmetic.
    # AIQS ACMM, AS 4000
    "AU": [
        {
            "name": "Contractor's Preliminaries",
            "category": "overhead",
            "percentage": "13.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Contractor's Margin (OH&P)",
            "category": "profit",
            "percentage": "10.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "Design Contingency",
            "category": "contingency",
            "percentage": "5.0",
            "apply_to": "cumulative",
            "sort_order": 2,
        },
        {
            "name": "Construction Contingency",
            "category": "contingency",
            "percentage": "3.0",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
        {
            "name": "Escalation Allowance",
            "category": "contingency",
            "percentage": "3.0",
            "apply_to": "cumulative",
            "sort_order": 4,
        },
        {
            "name": "GST",
            "category": "tax",
            "percentage": "10.0",
            "apply_to": "cumulative",
            "sort_order": 5,
        },
    ],
    # ── Japan ───────────────────────────────────────────────────────────
    # 公共建築工事共通費積算基準 (MLIT)
    "JP": [
        {
            "name": "\u5171\u901a\u4eee\u8a2d\u8cbb (Common Temporary)",
            "category": "overhead",
            "percentage": "7.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "\u73fe\u5834\u7ba1\u7406\u8cbb (Site Management)",
            "category": "overhead",
            "percentage": "12.0",
            "apply_to": "cumulative",
            "sort_order": 1,
        },
        {
            "name": "\u4e00\u822c\u7ba1\u7406\u8cbb\u7b49 (General Admin & Profit)",
            "category": "profit",
            "percentage": "7.0",
            "apply_to": "cumulative",
            "sort_order": 2,
        },
        {
            "name": "\u6d88\u8cbb\u7a0e (Consumption Tax)",
            "category": "tax",
            "percentage": "10.0",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
    ],
    # ── Brazil ──────────────────────────────────────────────────────────
    # BDI per TCU Acórdão 2.622/2013, SINAPI
    "BR": [
        {
            "name": "Administra\u00e7\u00e3o Central (AC)",
            "category": "overhead",
            "percentage": "5.5",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Despesas Financeiras (DF)",
            "category": "other",
            "percentage": "1.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "Seguros (S)",
            "category": "insurance",
            "percentage": "0.5",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        {
            "name": "Garantias (G)",
            "category": "bond",
            "percentage": "0.5",
            "apply_to": "direct_cost",
            "sort_order": 3,
        },
        {
            "name": "Riscos e Imprevistos (R)",
            "category": "contingency",
            "percentage": "1.0",
            "apply_to": "direct_cost",
            "sort_order": 4,
        },
        {
            "name": "Lucro (L)",
            "category": "profit",
            "percentage": "7.5",
            "apply_to": "cumulative",
            "sort_order": 5,
        },
        {
            "name": "PIS + COFINS",
            "category": "tax",
            "percentage": "3.65",
            "apply_to": "cumulative",
            "sort_order": 6,
        },
        {
            "name": "ISS",
            "category": "tax",
            "percentage": "3.0",
            "apply_to": "cumulative",
            "sort_order": 7,
        },
    ],
    # ── Scandinavia / Nordic ────────────────────────────────────────────
    # Byggakademin (SE), AB 04, NS 3420 (NO)
    "NORDIC": [
        {
            "name": "Arbetsplatsomkostnader (APO)",
            "category": "overhead",
            "percentage": "15.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Centralomkostnader (CO)",
            "category": "overhead",
            "percentage": "8.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "Vinst (V)",
            "category": "profit",
            "percentage": "5.0",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        {
            "name": "Risk (R)",
            "category": "contingency",
            "percentage": "3.0",
            "apply_to": "direct_cost",
            "sort_order": 3,
        },
        {
            "name": "MOMS",
            "category": "tax",
            "percentage": "25.0",
            "apply_to": "cumulative",
            "sort_order": 4,
        },
    ],
    # ── Russia / CIS ────────────────────────────────────────────────────
    # The contingency line is ``cumulative`` after profit ON PURPOSE: the
    # summary estimate calculation takes unforeseen costs on the total of the
    # preceding chapters, which already carry the overhead and profit lines.
    # МДС 81-35.2004, Приказ Минстроя 812/пр, 774/пр
    # НР/СП norms applied to ФОТ; effective % of direct costs shown here.
    "RU": [
        {
            "name": "\u041d\u0430\u043a\u043b\u0430\u0434\u043d\u044b\u0435 \u0440\u0430\u0441\u0445\u043e\u0434\u044b (\u041d\u0420)",
            "category": "overhead",
            "percentage": "16.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "\u0421\u043c\u0435\u0442\u043d\u0430\u044f \u043f\u0440\u0438\u0431\u044b\u043b\u044c (\u0421\u041f)",
            "category": "profit",
            "percentage": "7.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "\u041d\u0435\u043f\u0440\u0435\u0434\u0432\u0438\u0434\u0435\u043d\u043d\u044b\u0435 \u0440\u0430\u0441\u0445\u043e\u0434\u044b",
            "category": "contingency",
            "percentage": "2.0",
            "apply_to": "cumulative",
            "sort_order": 2,
        },
        {
            "name": "\u041d\u0414\u0421",
            "category": "tax",
            "percentage": "20.0",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
    ],
    # ── China ───────────────────────────────────────────────────────────
    # 建标[2013]44号, regional 定额
    #
    # 建标[2013]44号 states what a construction price is made of twice, in
    # parallel, and the two statements are alternatives rather than layers of
    # one another. By cost element (费用构成要素) the price is labour, material,
    # plant, enterprise management fee, profit, statutory charges and tax. By
    # price formation (造价形成) it is bill items, preliminaries, other items,
    # statutory charges and tax. A stack that takes some of its lines from one
    # axis and some from the other counts the same money under two names and
    # reads to a Chinese estimator as neither convention. This one used to.
    #
    # Under 清单计价 the enterprise management fee and profit belong inside the
    # 综合单价 rather than beside the bill heads, because a bill item's rate
    # already carries them. They are therefore the first two lines, and what
    # they build out of the labour, material and plant a position stores is
    # 分部分项工程费.
    #
    # They are still bill-level rows all the same, because there is nowhere
    # else to put them. ``BOQMarkup`` cannot carry a percentage that informs a
    # unit rate without also applying it to the bill, so ordering them first
    # and categorising them as the rate's own composition is as close as this
    # schema gets. A Chinese estimator reading the bill still sees them as
    # siblings of the heads, and somewhere to declare a unit-rate composition
    # is the change that would actually finish this.
    #
    # Every base here stays ``direct_cost`` on purpose. Chinese practice
    # commonly takes a 总价措施项目 or a statutory percentage on 分部分项工程费
    # rather than on bare direct cost, which would make those two lines
    # ``cumulative``. But that base is set provincially, some provinces take it
    # on the labour component alone, and the text that would settle it could
    # not be obtained. Changing it reprices every newly seeded Chinese bill, so
    # it is a decision to take on evidence rather than a tidy-up to fold into a
    # categorisation fix.
    #
    # The categories are read by something other than the bill. The
    # per-position price analysis derives a unit rate's overhead and profit
    # from the categories of the bill's markup lines, so a bill head left in
    # the ``overhead`` category is pulled into the 综合单价 analysis as if it
    # were part of the rate. 措施项目费 is a head and not a rate component and
    # is categorised ``other`` for that reason. Before this it was ``overhead``
    # and the analysis sheet reported sixteen percent of overhead on a Chinese
    # bill whose management fee is eight.
    #
    # 规费 is a placeholder and is meant to be read as one. The charge is real
    # and mandatory, but it is set provincially and itemised (社会保险费,
    # 住房公积金, and where it still applies 工程排污费), so no single national
    # percentage is right anywhere; five is an order of magnitude to start
    # editing from. The line is kept rather than dropped: the text of
    # GB/T 50500-2024 could not be obtained, and not having read a repeal is
    # not the same as having read a retention.
    "CN": [
        {
            "name": "\u4f01\u4e1a\u7ba1\u7406\u8d39 (Enterprise management fee)",
            "category": "overhead",
            "percentage": "8.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "\u5229\u6da6 (Profit)",
            "category": "profit",
            "percentage": "5.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "\u63aa\u65bd\u9879\u76ee\u8d39 (Preliminaries)",
            "category": "other",
            "percentage": "8.0",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        {
            "name": "\u89c4\u8d39 (Statutory charges)",
            "category": "other",
            "percentage": "5.0",
            "apply_to": "direct_cost",
            "sort_order": 3,
        },
        {
            "name": "\u589e\u503c\u7a0e (VAT)",
            "category": "tax",
            "percentage": "9.0",
            "apply_to": "cumulative",
            "sort_order": 4,
        },
    ],
    # ── South Korea ─────────────────────────────────────────────────────
    # 조달청 예정가격작성기준, 계약예규
    "KR": [
        {
            "name": "\uac04\uc811\ub178\ubb34\ube44 (Indirect Labor)",
            "category": "overhead",
            "percentage": "8.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "\uc0b0\uc5c5\uc548\uc804\ubcf4\uac74\uad00\ub9ac\ube44 (Safety & Health)",
            "category": "overhead",
            "percentage": "2.15",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "\uae30\ud0c0\uacbd\ube44 (Other Expenses)",
            "category": "overhead",
            "percentage": "6.5",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        {
            "name": "\uc77c\ubc18\uad00\ub9ac\ube44 (General Admin)",
            "category": "overhead",
            "percentage": "6.0",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
        {
            "name": "\uc774\uc724 (Profit)",
            "category": "profit",
            "percentage": "10.0",
            "apply_to": "cumulative",
            "sort_order": 4,
        },
        {
            "name": "\ubd80\uac00\uac00\uce58\uc138 (VAT)",
            "category": "tax",
            "percentage": "10.0",
            "apply_to": "cumulative",
            "sort_order": 5,
        },
    ],
    # ── Hungary ─────────────────────────────────────────────────────────
    # Egységes magasépítési ágazati tételrend, and the cover summary the
    # packs/hungary-hu rule pack ``hu_anyag_dij_bontas`` states: the chapters
    # total to a net anyag and a net díj figure, those add to the net subtotal,
    # the tartalékkeret is taken on that subtotal, and ÁFA closes the sheet.
    #
    # Two decisions in the stack are the Hungarian ones and not stylistic.
    # ``tartalékkeret`` is ``direct_cost`` because the summary takes it on the
    # net anyag-plus-díj subtotal, which is the base before the contractor's
    # margin, so the general rule in the header and the national method agree
    # here rather than pulling apart the way they do for UK and RU. ÁFA is
    # ``cumulative`` because it is levied on the contract value the client
    # signs, which does contain the margin.
    #
    # The ÁFA figure is statutory. The other three are working defaults taken
    # from the shipped Hungarian demos, because the tartalékkeret is agreed per
    # contract rather than set nationally, and overhead and margin are the
    # contractor's own. What this row asserts is the shape - which lines exist,
    # in what order, on which base - not that a Hungarian job carries exactly
    # eight percent overhead.
    "HU": [
        {
            "name": "Általános költség",
            "category": "overhead",
            "percentage": "8.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Nyereség",
            "category": "profit",
            "percentage": "6.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "Tartalékkeret",
            "category": "contingency",
            "percentage": "5.0",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        {
            "name": "ÁFA",
            "category": "tax",
            "percentage": "27.0",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
    ],
    # ── Italy ───────────────────────────────────────────────────────────
    # Computo metrico estimativo. Two things here are Italian rather than
    # generic. ``Utile d'impresa`` is cumulative because the contractor's
    # margin is taken on the works plus the general expenses, not on the works
    # alone. And ``oneri della sicurezza`` is a line in its own right, carried
    # as ``other`` rather than as overhead, because safety costs are not
    # subject to the tender discount: they are quoted and paid in full, and
    # folding them into an overhead percentage would lose the one property
    # that makes them a separate line on an Italian bill.
    "IT": [
        {
            "name": "Spese generali",
            "category": "overhead",
            "percentage": "15.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Utile d'impresa",
            "category": "profit",
            "percentage": "10.0",
            "apply_to": "cumulative",
            "sort_order": 1,
        },
        {
            "name": "Oneri della sicurezza non soggetti a ribasso",
            "category": "other",
            "percentage": "2.5",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        {
            "name": "IVA",
            "category": "tax",
            "percentage": "22.0",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
    ],
    # ── Spain ───────────────────────────────────────────────────────────
    # Mediciones y presupuesto. Both percentages are taken on the presupuesto
    # de ejecución material, so both are ``direct_cost``; the pair of them is
    # what turns the material execution budget into the contract budget, and
    # Spanish public works regulation fixes the shape of exactly these two
    # lines rather than leaving them to the estimator.
    "ES": [
        {
            "name": "Gastos generales",
            "category": "overhead",
            "percentage": "13.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Beneficio industrial",
            "category": "profit",
            "percentage": "6.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "IVA",
            "category": "tax",
            "percentage": "21.0",
            "apply_to": "cumulative",
            "sort_order": 2,
        },
    ],
    # ── Netherlands ─────────────────────────────────────────────────────
    # RAW / STABU begroting. The stack is a ladder on purpose: site overheads
    # are taken on the direct works, head-office overheads on the works plus
    # site overheads, and the insurance and the combined profit-and-risk line
    # on everything before them. That laddering is the Dutch convention and is
    # why four of the five lines are cumulative.
    "NL": [
        {
            "name": "Algemene bouwplaatskosten (ABK)",
            "category": "overhead",
            "percentage": "8.5",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Algemene kosten (AK)",
            "category": "overhead",
            "percentage": "6.0",
            "apply_to": "cumulative",
            "sort_order": 1,
        },
        {
            "name": "CAR-verzekering en bankgarantie",
            "category": "insurance",
            "percentage": "0.6",
            "apply_to": "cumulative",
            "sort_order": 2,
        },
        {
            "name": "Winst en risico (W&R)",
            "category": "profit",
            "percentage": "4.5",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
        {
            "name": "BTW",
            "category": "tax",
            "percentage": "21.0",
            "apply_to": "cumulative",
            "sort_order": 4,
        },
    ],
    # ── Poland ──────────────────────────────────────────────────────────
    # Kosztorys budowlany. ``Rezerwa`` is cumulative and therefore sits on a
    # base containing profit, which is the opposite of the general rule in the
    # header. It is recorded that way because a Polish reserve for unforeseen
    # works is taken on the net contract value rather than on bare cost, and
    # ``CONTINGENCY_ON_PROFIT_BY_DESIGN`` in the pure-helpers test carries the
    # same statement so the shape cannot drift back without a decision.
    "PL": [
        {
            "name": "Koszty pośrednie (Kp)",
            "category": "overhead",
            "percentage": "18.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Zysk (Z)",
            "category": "profit",
            "percentage": "8.0",
            "apply_to": "cumulative",
            "sort_order": 1,
        },
        {
            "name": "Rezerwa na roboty nieprzewidziane",
            "category": "contingency",
            "percentage": "3.0",
            "apply_to": "cumulative",
            "sort_order": 2,
        },
        {
            "name": "Podatek VAT",
            "category": "tax",
            "percentage": "23.0",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
    ],
    # ── Türkiye ─────────────────────────────────────────────────────────
    # Birim fiyat. The single 25 percent line is not a shortcut for two lines
    # that should be split: the Turkish unit-price tradition quotes the
    # contractor's profit and general expenses as one combined percentage, and
    # splitting it here would invent a division the market does not make. It
    # is filed as overhead because that is the wider half of what it covers,
    # so this region has no line categorised as profit, on purpose.
    "TR": [
        {
            "name": "Müteahhit kârı ve genel giderler",
            "category": "overhead",
            "percentage": "25.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "KDV",
            "category": "tax",
            "percentage": "20.0",
            "apply_to": "cumulative",
            "sort_order": 1,
        },
    ],
    # ── Argentina ───────────────────────────────────────────────────────
    # Analisis de precios and the coeficiente resumen, the multiplier an
    # Argentine estimator applies to the costo neto to reach the precio de
    # venta. Ley 13.064 de Obras Publicas is the public works frame; price
    # movement is handled by redeterminacion de precios, not by a markup line,
    # which is why there is no escalation row here (the price-index module holds
    # the date-to-date arithmetic, the same division the AU block records).
    #
    # Beneficio is ``cumulative`` because the coeficiente resumen is a PRODUCT
    # of factors rather than a sum of percentages: the margin is taken on the
    # costo neto plus the gastos generales, not on the bare cost. That is the
    # same reason the Italian ``Utile d'impresa`` is cumulative.
    #
    # No contingency line, on purpose. The Argentine coefficient carries gastos
    # generales, beneficio and impuestos; a separate imprevistos head is not
    # part of the standard shape, so inventing one would be a line the estimator
    # has to notice and delete.
    #
    # ── Ingresos Brutos: read this before shipping the line ──────────────
    #
    # IIBB is a provincial turnover tax charged on the invoiced amount, hence
    # ``cumulative``, and it is genuinely part of what an Argentine coeficiente
    # resumen contains. It is filed ``other`` rather than ``tax`` so that the
    # region keeps exactly one tax line and the project VAT override lands on
    # IVA alone. The precedent for a statutory levy filed ``other`` is the
    # Indian "Labour Cess (BOCW)" line, and the precedent for keeping a
    # provincially-set number as an editable placeholder is the Chinese 规费
    # line.
    #
    # What is NOT confirmed is the property that makes the 规费 precedent apply.
    # 规费 was kept because the charge is real and mandatory everywhere and only
    # its rate varies. For IIBB the rate varies AND the treatment of
    # construction varies: provinces have exempted or reduced it for
    # construction activity at different times, so 3.0 may be an overcharge
    # rather than a mis-estimate in some jurisdictions. That is the reason this
    # paragraph exists instead of the line just shipping.
    #
    # Three ways to take it, and this is a decision rather than a default:
    #   1. As written. The shape is Argentine, 3.0 is a placeholder to edit, one
    #      tax line, no NON_SINGLE_TAX_REGIONS entry needed.
    #   2. Drop the line. Then the AR stack is gastos generales, beneficio, IVA,
    #      which is honest but is the neutral method under Argentine names, and
    #      arguably fails ``test_a_country_without_a_national_stack_does_not_
    #      claim_one`` in spirit if not in letter.
    #   3. File it ``tax`` and add AR to ``NON_SINGLE_TAX_REGIONS`` with the
    #      reason that IIBB is provincial and IVA federal. Most accurate,
    #      costliest: the project VAT override then stops working for Argentina
    #      entirely, which for a 21 percent IVA is a real loss.
    # Shipped as 1 because it keeps the override working and states its own
    # uncertainty in the line's own comment.
    "AR": [
        {
            "name": "Gastos generales",
            "category": "overhead",
            "percentage": "15.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Beneficio",
            "category": "profit",
            "percentage": "10.0",
            "apply_to": "cumulative",
            "sort_order": 1,
        },
        # Provincial, and a placeholder rather than a rate. See the note above:
        # the province sets it and some have relieved construction of it.
        {
            "name": "Ingresos Brutos (IIBB)",
            "category": "other",
            "percentage": "3.0",
            "apply_to": "cumulative",
            "sort_order": 2,
        },
        {
            "name": "IVA",
            "category": "tax",
            "percentage": "21.0",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
    ],
    # ── Belgium ─────────────────────────────────────────────────────────
    # Meetstaat / métré, priced as a Low Countries staartkosten ladder: site
    # costs on the direct works, head-office general costs on the works plus
    # site costs, and profit-and-risk on everything before it. The ladder is the
    # sourced part. Belgian and Dutch practice both compute the winst-en-risico
    # mark-up over the total contract sum INCLUDING the general costs rather
    # than over the bare direct cost, which is what makes the last two lines
    # ``cumulative``.
    #
    # Be clear about what this block is and is not. It is NOT a distinctly
    # Belgian norm. Belgium regulates how public works contracts are executed
    # and revised, through the Wet Overheidsopdrachten and the KB of 14 January
    # 2013, and it regulates measurement through the typebestekken, but none of
    # those prescribes the composition of a contractor's mark-up. The arithmetic
    # shape here is the one Belgium shares with the Netherlands, and the
    # existing NL block states the same ladder.
    #
    # It gets its own key rather than a ``"BE": "NL"`` row for one reason that
    # is about the market and not about the arithmetic: Belgium is bilingual and
    # a bill in Dutch only reads wrong to the French-speaking half of it. The
    # repository already takes this position elsewhere, ``tax_configurations``
    # names the Belgian levy "VAT Standard (BTW/TVA)" with both translations. If
    # you would rather not carry a second near-identical ladder, ``"BE": "NL"``
    # is defensible and the cost of it is Dutch-only line names on Walloon
    # bills. My recommendation is the separate key.
    #
    # The BTW/TVA figure is statutory. The three percentages are working
    # defaults and are explicitly NOT Belgian-sourced: the figures available for
    # a staartkosten split of roughly 8 / 6 / 4 come from Dutch-market material,
    # and are adjusted here only by judgement. Treat them as a starting point to
    # edit, which is what every line in this table is.
    #
    # Not modelled, and deliberately: prijsherziening / révision des prix, the
    # mandatory price-revision formula in Belgian public works. It is a formula
    # over published wage and material indices, not a percentage of the works,
    # so a number here would be an invention. The price-index module is where
    # that arithmetic belongs.
    "BE": [
        {
            "name": "Werfkosten / Frais de chantier",
            "category": "overhead",
            "percentage": "10.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Algemene kosten / Frais généraux (AK)",
            "category": "overhead",
            "percentage": "8.0",
            "apply_to": "cumulative",
            "sort_order": 1,
        },
        {
            "name": "Winst en risico / Bénéfice et risque (W&R)",
            "category": "profit",
            "percentage": "5.0",
            "apply_to": "cumulative",
            "sort_order": 2,
        },
        {
            "name": "BTW / TVA",
            "category": "tax",
            "percentage": "21.0",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
    ],
    # ── Canada ──────────────────────────────────────────────────────────
    # CCDC 2 stipulated price contract, CCDC 221 performance bond and CCDC 222
    # labour and material payment bond, MasterFormat Division 01. Canada shares
    # the North American cost-plan shape and its own contract and bond family;
    # see the long note above for why it is a separate region rather than a
    # second country mapped to US.
    #
    # NO TAX LINE, deliberately, and Canada is in ``NON_SINGLE_TAX_REGIONS``
    # with the reason. Unlike the US, the reason is the rate and not the base:
    # GST and HST are charged on the contract sum, so the line would belong
    # here if there were one honest number to put in it, and there are seven.
    #
    # Both contingencies are ``direct_cost`` for the reason the US block spells
    # out at length: a Canadian construction manager carries contingency inside
    # the cost of the work, under the fee, and charging the contractor's profit
    # on an allowance that may never be spent inflates the bid. Do not tidy them
    # to match the bond above, which is ``cumulative`` correctly because a bond
    # premium is written against the contract price.
    #
    # Every percentage here is a working default for a medium commercial
    # building, not a regulated figure. The one with a stated reason behind its
    # value rather than its existence is the bond: 1.0 rather than the US 1.5,
    # because the common Canadian public requirement is a 50 percent performance
    # bond plus a 50 percent labour and material payment bond, where the US
    # block is priced for the 100/100 pair.
    "CA": [
        {
            "name": "General Requirements (Div. 01)",
            "category": "overhead",
            "percentage": "8.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Head Office Overhead",
            "category": "overhead",
            "percentage": "7.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "Contractor's Profit",
            "category": "profit",
            "percentage": "5.0",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        {
            "name": "General Liability & Builder's Risk Insurance",
            "category": "insurance",
            "percentage": "1.0",
            "apply_to": "direct_cost",
            "sort_order": 3,
        },
        {
            "name": "Performance & Payment Bonds (CCDC 221/222)",
            "category": "bond",
            "percentage": "1.0",
            "apply_to": "cumulative",
            "sort_order": 4,
        },
        {
            "name": "Design Contingency",
            "category": "contingency",
            "percentage": "5.0",
            "apply_to": "direct_cost",
            "sort_order": 5,
        },
        {
            "name": "Construction Contingency",
            "category": "contingency",
            "percentage": "3.0",
            "apply_to": "direct_cost",
            "sort_order": 6,
        },
    ],
    # ── Chile ───────────────────────────────────────────────────────────
    # Analisis de precio unitario, and IVA per the Ley sobre Impuesto a las
    # Ventas y Servicios.
    #
    # RELATION TO ``chile_apu``: this stack IS that cascade, line for line, on
    # purpose. ``_CHILE_APU_TEMPLATE`` runs costo directo, then imprevistos on
    # the costo directo, then gastos generales on cost plus imprevistos, then
    # utilidades on everything before it, then IVA on the lot. Written in bill
    # terms that is one ``direct_cost`` line followed by three ``cumulative``
    # ones, because ``cumulative`` means direct cost plus every preceding line,
    # which is exactly what each APU step's base list spells out.
    #
    # The rates are the APU template's own rates, unchanged, and that is the
    # point of the exercise: the whole reason ``markup_templates.py`` exists as
    # its own module is so "a country cannot be priced two ways by two engines
    # that both claim to describe it". Chile currently is, because the flat
    # template reaches its total by a different road. After this it is not.
    #
    # Imprevistos ships at 0.0 rather than being omitted, and the reason is
    # stated in the APU template and carried over verbatim in intent: tenders
    # that carry a contingency put it on the costo directo before utilidades,
    # and tenders that do not would have to notice a line we invented and remove
    # it, so the line exists and is empty rather than absent or guessed.
    #
    # Note what this shape means for the header rule: Chilean imprevistos is
    # both ``direct_cost`` AND ordered before the profit line, so the general
    # rule and the national method agree here rather than pulling apart the way
    # they do for UK and RU.
    #
    # Labels are unaccented to match ``chile_apu`` exactly. Two catalogues
    # describing one country in wording that differs is the contradiction this
    # block is trying to close.
    "CL": [
        {
            "name": "Imprevistos",
            "category": "contingency",
            "percentage": "0.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Gastos generales",
            "category": "overhead",
            "percentage": "13.0",
            "apply_to": "cumulative",
            "sort_order": 1,
        },
        {
            "name": "Utilidades",
            "category": "profit",
            "percentage": "8.0",
            "apply_to": "cumulative",
            "sort_order": 2,
        },
        {
            "name": "IVA",
            "category": "tax",
            "percentage": "19.0",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
    ],
    # ── Colombia ────────────────────────────────────────────────────────
    # AIU: administracion, imprevistos, utilidad. The three letters a Colombian
    # contract quotes its markup as. IVA per Decreto 1372 de 1992.
    #
    # RELATION TO ``colombia_aiu``: same three lines, same rates, same bases.
    # Each letter is a share OF THE COSTO DIRECTO and none of them sees the
    # others, so all three are ``direct_cost`` and NOTHING here compounds. A
    # tender that says "AIU 27% (A=20, I=2, U=5)" means exactly 27 percent of
    # the direct cost, and a cumulative cascade would hand the client a number
    # they did not ask for. This is also why the imprevistos line is not a
    # contingency-on-profit case despite being the most likely candidate of the
    # six: it is not on profit, it is beside it.
    #
    # NO TAX LINE, and Colombia needs a ``NON_SINGLE_TAX_REGIONS`` entry for it.
    # The reason is the base, not the rate. IVA on a construction contract over
    # immovable property falls on the utilidad alone, so at the AIU above it is
    # 19 percent of 5 percent, about 0.95 percent of the direct cost, and not 19
    # percent of 127 percent. A bill-level line can be taken on direct cost or
    # on the running total and neither of those is "the utilidad", so the honest
    # move is to carry no line rather than carry a wrong one. The argument has
    # the same shape as the US entry, which also has no tax line because the
    # base is wrong rather than the number.
    #
    # What that costs, stated so nobody discovers it later: a seeded Colombian
    # bill total is about 0.95 percent light against the invoice. Where the tax
    # has to appear on the estimate, ``colombia_aiu`` is the template to install,
    # because a cascade step can name ``utilidad`` as its base and a bill markup
    # line cannot. The alternative considered and rejected was a ``direct_cost``
    # line at 0.95: it is only right while utilidad is exactly 5, and it goes
    # silently wrong the first time a user edits the U in AIU, which is the
    # failure mode this module exists to avoid.
    "CO": [
        {
            "name": "Administracion",
            "category": "overhead",
            "percentage": "20.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Imprevistos",
            "category": "contingency",
            "percentage": "2.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "Utilidad",
            "category": "profit",
            "percentage": "5.0",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
    ],
    # ── Czechia ─────────────────────────────────────────────────────────
    # Soupis stavebních prací, dodávek a služeb s výkazem výměr per vyhláška
    # č. 169/2016 Sb., priced from a cenová soustava (ÚRS or RTS) and classified
    # by TSKP.
    #
    # The Czech decision in this stack is the ``cumulative`` base on the two VRN
    # lines, and it is the one thing here that is genuinely national rather than
    # generic. § 11 of the vyhláška requires vedlejší a ostatní náklady, the
    # costs that are not inside the items of the bill but arise from the work,
    # to be listed separately from the object items: site establishment,
    # operation and removal, difficult conditions arising from the location,
    # restrictions in built-up areas. Czech estimating takes those as a
    # percentage of základní rozpočtové náklady, the priced object items, not of
    # bare direct cost. The two lines above them are what turns direct cost into
    # ZRN in this schema, so ``cumulative`` on the VRN lines is what puts them on
    # the base that vyhláška-driven practice actually uses.
    #
    # They are categorised ``other`` rather than ``overhead`` for the reason the
    # CN block gives: the per-position price analysis derives a unit rate's
    # overhead and profit from these categories, and a VRN line is a bill head,
    # not a component of a unit rate. Filing them as overhead would report
    # 16.5 % of overhead on a Czech bill whose režie is twelve.
    #
    # Now the honest problem, and it is the same one the CN block has. Under a
    # cenová soustava the výrobní režie, správní režie and zisk are ALREADY
    # inside the ÚRS or RTS unit rate. A Czech bill priced from those rates and
    # then seeded with lines 0 and 1 counts that money twice. They are here
    # anyway, first and on direct cost, because ``BOQMarkup`` has nowhere to
    # declare a unit-rate composition, and because a bill priced from bare
    # resources rather than from a cenová soustava recovers nothing without
    # them. A Czech estimator importing ÚRS rates should delete lines 0 and 1,
    # and somewhere to declare a unit-rate composition is the change that would
    # actually finish this.
    #
    # The DPH figure is statutory. The režie figure is a working default and is
    # a CONVERTED one, in the same sense as the RU block: Czech režie norms are
    # applied to the labour and machinery components, not to material, so no
    # single percentage of total direct cost is right for every job. Twelve is
    # an effective figure for a normal material-to-labour ratio and is an order
    # of magnitude to start editing from, not a norm.
    #
    # Zisk is left on ``direct_cost``. Czech calculation practice computes it
    # from a cost base that includes režie, which would make it ``cumulative``
    # the way the Italian utile d'impresa is, but the ÚRS calculation formula
    # that would settle it could not be obtained, and changing it reprices every
    # newly seeded Czech bill. That is a decision to take on evidence, not a
    # tidy-up to fold into this block.
    "CZ": [
        {
            "name": "Výrobní a správní režie",
            "category": "overhead",
            "percentage": "12.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Zisk",
            "category": "profit",
            "percentage": "8.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "Zařízení staveniště (VRN)",
            "category": "other",
            "percentage": "3.0",
            "apply_to": "cumulative",
            "sort_order": 2,
        },
        {
            "name": "Územní a provozní vlivy (VRN)",
            "category": "other",
            "percentage": "1.5",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
        {
            "name": "DPH",
            "category": "tax",
            "percentage": "21.0",
            "apply_to": "cumulative",
            "sort_order": 4,
        },
    ],
    # ── Greece ──────────────────────────────────────────────────────────
    # Public works budget under Ν. 4412/2016, priced from the ΝΕΤ unit price
    # schedules (ΝΕΤ ΟΙΚ, ΟΔΟ, ΥΔΡ, ΗΛΜ) and the ΕΤΕΠ specifications.
    #
    # This is the most strongly sourced stack of the six, because in Greece the
    # two percentages are set by law rather than by the estimator.
    #
    # ΓΕ & ΟΕ, Γενικά έξοδα και όφελος εργολάβου, general expenses and the
    # contractor's profit, is a single combined 18 % on the works cost for
    # public works. It is one line and not two because Greek law states it as
    # one, exactly as the TR block keeps müteahhit kârı ve genel giderler whole;
    # splitting it would invent a division the market does not make. It is filed
    # as ``overhead`` because ΓΕ is the wider half, so this region, like TR, has
    # no line categorised ``profit``, on purpose. Read the CONTINGENCY ON PROFIT
    # section at the top of this file before changing that category: it is
    # load-bearing for a test.
    #
    # Απρόβλεπτα is 15 %, taken on the works cost PLUS ΓΕ & ΟΕ. Verified against
    # a published municipal budget rather than inferred:
    #
    #     Συνολική δαπάνη εργασιών          161,892.60
    #     ΓΕ και ΟΕ 18 %                     29,140.67   = 161,892.60 x 0.18
    #     Συνολική αξία των εργασιών        191,033.27
    #     Απρόβλεπτα 15 %                    28,654.99   = 191,033.27 x 0.15
    #     Σύνολο                            219,688.26
    #
    # So it is ``cumulative``, and its base contains the contractor's profit,
    # which is inside the ΓΕ & ΟΕ line above it.
    #
    # Two qualifications on the sourced figures, both real.
    #
    # The 18 % binds works funded from the public investment programme. Private
    # Greek works are not bound by it and have historically been quoted higher.
    # The shape asserted here is the public works one because that is the one
    # with a norm behind it, and this table's stated scope, a medium commercial
    # building, may well be private. A private Greek job is a case for editing
    # the percentage, not for a second stack.
    #
    # The Απρόβλεπτα percentage is conditional on project size: 9 % for works at
    # or above the EU procurement threshold, 15 % below it. 15 is used here
    # because a medium commercial building normally falls below that threshold.
    # A large Greek job should be edited to 9.
    #
    # ΦΠΑ is 24 %, the standard rate, in force since 1 June 2016. Greece is not
    # in ``tax_configurations.json`` and not in ``app/core/tax.py``, so unlike
    # the other five this rate is sourced rather than taken from our own tables:
    # Greek VAT Code Ν. 2859/2000 as amended by Ν. 4389/2016, corroborated
    # against the Greek Ministry of Economy and Finance VAT guide and PwC
    # Worldwide Tax Summaries for Greece, both read 2026-09-02. Construction
    # services are standard-rated. The VAT suspension that keeps coming up in
    # Greek sources is on sales of newly built property, not on construction
    # services, and does not reach a bill of quantities. If GR is added to
    # ``app/core/tax.py`` or to the seed table later, that becomes the single
    # source and this figure should defer to it.
    #
    # Two standard lines of a Greek budget are deliberately absent. Αναθεώρηση,
    # price revision, is a formula over published index coefficients budgeted as
    # a lump sum, not a percentage of the works, so any number here would be
    # invented; the price-index module holds that arithmetic. Έκπτωση, the
    # tender discount, is negative and belongs to tender evaluation rather than
    # to the estimate.
    "GR": [
        {
            "name": "\u0393\u0395 & \u039f\u0395 (General expenses and contractor profit)",
            "category": "overhead",
            "percentage": "18.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "\u0391\u03c0\u03c1\u03cc\u03b2\u03bb\u03b5\u03c0\u03c4\u03b1 (Contingency)",
            "category": "contingency",
            "percentage": "15.0",
            "apply_to": "cumulative",
            "sort_order": 1,
        },
        {
            "name": "\u03a6\u03a0\u0391 (VAT)",
            "category": "tax",
            "percentage": "24.0",
            "apply_to": "cumulative",
            "sort_order": 2,
        },
    ],
    # ── Indonesia ───────────────────────────────────────────────────────
    # Rencana Anggaran Biaya built on AHSP, Permen PUPR No. 8 Tahun 2023
    # (Analisa Harga Satuan Pekerjaan), with SMKK per Permen PUPR 10/2021.
    #
    # ``Biaya Umum dan Keuntungan`` is one line and not two on purpose. The
    # regulation states a single combined ceiling, general costs and profit
    # together at most fifteen percent, and does not divide it. Splitting it
    # here would invent a division the market does not make, which is the same
    # decision the TR block records, and it is filed as ``overhead`` for the
    # same reason: general costs are the wider half of what it covers. So this
    # region has no line categorised as profit, on purpose.
    #
    # Fifteen is the regulatory ceiling rather than an average. Indonesian
    # government estimates are commonly priced at the ceiling, which is why it
    # is the useful default, but a reader should know it is a maximum and not a
    # norm before treating it as one.
    #
    # BUK belongs inside the AHSP unit rate, not beside the bill heads: an
    # AHSP takes labour, material and equipment, applies BUK to that, and the
    # sum is the harga satuan. It is a bill-level row here for exactly the
    # reason the CN block gives at length, that ``BOQMarkup`` cannot carry a
    # percentage which informs a unit rate without also applying it to the
    # bill, and ordering it first is as close as this schema gets. Our rates
    # come from a cost database and do not already contain it, so applying it
    # at bill level does not double count.
    #
    # ``Biaya SMKK`` is a real and mandatory line on an Indonesian bill and is
    # carried as ``other`` on the same footing as the Italian oneri della
    # sicurezza: it is quoted in its own right rather than folded into an
    # overhead percentage. The percentage is the weak part and should be read
    # as one. SMKK is itemised in practice, personal protective equipment,
    # signage, a certified safety officer, induction, so no percentage is the
    # regulated figure; two is an order of magnitude to start editing from and
    # scales with the job's risk class.
    #
    # PPN 11.0 needs its mechanism stated or the next reader will "fix" it to
    # 12. PMK 131/2024 sets the statutory rate at 12 percent but computes the
    # tax on an adjusted base of 11/12 of the price for everything that is not
    # a luxury good, so 12 percent of 11/12 is an effective 11 percent, and
    # construction services take the effective rate. Writing 12 here would
    # overstate an Indonesian bill by nine percent of its tax line.
    # Sourced from PMK No. 131 of 2024 as reported by ASEAN Briefing and
    # several Indonesian tax practices, read 2026-09-02. This agrees with the
    # ``vat="11"`` already hardcoded for Indonesia in the methodology catalogue.
    "ID": [
        {
            "name": "Biaya Umum dan Keuntungan (General costs and profit)",
            "category": "overhead",
            "percentage": "15.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Biaya SMKK (Construction safety management)",
            "category": "other",
            "percentage": "2.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "PPN",
            "category": "tax",
            "percentage": "11.0",
            "apply_to": "cumulative",
            "sort_order": 2,
        },
    ],
    # ── Israel ──────────────────────────────────────────────────────────
    # The interministerial General Specification for Building Works, known as
    # the Blue Book, which the Dekel price book states every item is subject to
    # including its methods of measurement; the Dekel price book itself
    # (edition of March 2024) for what a unit rate contains; VAT at the
    # standard rate in force, sourced on the tax line itself below.
    #
    # This stack has no ``profit`` line and that is the Israeli statement, not
    # an omission. The Dekel pricing assumptions say the rates in chapters 01
    # to 68 include material plus labour plus profit, and that a unit price
    # covers the direct costs and the indirect costs, site overhead, company
    # overhead and contractor profit, needed to perform the item complete. An
    # Israeli bill priced from the price book therefore carries the trade
    # contractor's margin inside every rate, and what the main contractor adds
    # on top is the single ``תוספת קבלן ראשי``, whose percentage the price
    # book's own guidance chapter sets by project size, region and scope. It is
    # categorised ``overhead`` for the same reason the TR line is: it is one
    # figure the market does not split, and splitting it here would invent a
    # division. Consequence worth knowing before this ships: the per position
    # price analysis will report zero profit on an Israeli bill, which is the
    # honest reading when the rate already carries it, and the wrong reading if
    # a user prices Israeli work from net direct cost instead. Say so in the
    # release note.
    #
    # A block with no ``profit`` line at all already ships: TR is in
    # ``REGION_BY_COUNTRY`` carrying one combined overhead and profit line and
    # no profit line of its own. So ``_derive_country_template`` is exercised on
    # this shape today and the IL row needs nothing new from it.
    #
    # ``בדיקות מעבדה`` at 2.0 is the one sourced percentage in this
    # block. The price book's assumptions state that testing required by the
    # Israeli standards and performed in accredited laboratories is the
    # contractor's cost up to 2.0 percent of the project value, and that beyond
    # 2.0 percent the client pays unless the contract says otherwise. That is a
    # price book assumption rather than a statute, and it is quoted as such.
    #
    # 12.0 and 5.0 are working defaults and neither is sourced. Twelve is
    # carried unchanged from the flat ``israel`` template so that adding IL to
    # the map does not move a number a user already sees. Five is the table's
    # own neutral contingency; Israeli early stage estimates commonly carry
    # more, up to ten, but no published method sets it.
    #
    # No escalation line, deliberately. Israeli contracts handle price movement
    # by linkage to the building inputs index published by the Central Bureau
    # of Statistics, which is date-to-date arithmetic on a published series and
    # not a percentage. A flat stand-in would be less honest here than in the
    # AU block, because in Israel the mechanism is the norm rather than the
    # exception. The price-index module is where this belongs.
    "IL": [
        {
            "name": "\u05ea\u05d5\u05e1\u05e4\u05ea \u05e7\u05d1\u05dc\u05df \u05e8\u05d0\u05e9\u05d9 (Main contractor's addition)",
            "category": "overhead",
            "percentage": "12.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "\u05d1\u05d3\u05d9\u05e7\u05d5\u05ea \u05de\u05e2\u05d1\u05d3\u05d4 (Laboratory testing)",
            "category": "other",
            "percentage": "2.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "\u05d1\u05dc\u05ea\u05d9 \u05e6\u05e4\u05d5\u05d9 \u05de\u05e8\u05d0\u05e9 (Unforeseen)",
            "category": "contingency",
            "percentage": "5.0",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        # 18.0 since 2025-01-01, when Israel raised the standard rate from
        # 17 under the 2025 Economic Arrangements Law.
        #
        # What stood here was 17.0, with a note saying our own
        # effective-dated table stated the same. That was true and both
        # were wrong: the seed carried the 17 window with no end date, so
        # it read as the rate in force, and a note that checks one stale
        # table against another agrees with itself. The seed now closes 17
        # at 2024-12-31 and opens 18 the next day, and the methodology
        # catalogue had said 18 all along.
        #
        # This line carries no date of its own, which is the part of the
        # old note worth keeping. It is the percentage a newly seeded bill
        # starts at, so it has to be the rate in force now. Bills already
        # seeded keep what they were created with, and the question of what
        # the rate was on a given date is answered by the effective-dated
        # seed rather than here.
        {
            "name": "\u05de\u05e2\u05f4\u05de (VAT)",
            "category": "tax",
            "percentage": "18.0",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
    ],
    # ── Kenya ───────────────────────────────────────────────────────────
    # Bills follow the Standard Method of Measurement of Building Works in the
    # RICS lineage as adopted by the Architectural Association of Kenya and the
    # Institute of Quantity Surveyors of Kenya, so preliminaries are a measured
    # section and the substitute-not-addition statement in the NG block applies
    # here word for word. Two things are Kenyan rather than inherited: the
    # construction levy and the tax rate.
    #
    # THE NCA LEVY IS THE REASON THIS COUNTRY GETS A ROW. The National
    # Construction Authority Act, No. 41 of 2011 (now Cap. 118) and the
    # National Construction Authority Regulations, 2014 (Legal Notice 74 of
    # 2014) impose a construction levy of 0.5 percent of the contract sum on
    # any works exceeding five million shillings, payable before the works
    # commence, recoverable as a civil debt after three months and enforceable
    # by suspension of the contractor's registration. It is levied on the
    # contract value the parties sign, so it is ``cumulative``, which is the
    # bond and tax reasoning in the table header rather than an exception to it.
    #
    # It is categorised ``other`` and not ``tax``, exactly as the Indian
    # ``Labour Cess (BOCW)`` line is, because it is a statutory construction
    # levy and not a consumption tax. That is also what keeps Kenya out of
    # ``NON_SINGLE_TAX_REGIONS``: the gate counts lines whose category is
    # ``tax``, and this block has one.
    #
    # One honesty note about who pays it. The Regulations put the levy on the
    # owner, not the contractor: the owner notifies the Authority of the award
    # and pays before commencement. So it belongs on a client side cost plan
    # and a contractor pricing a tender would delete it. It is included because
    # this table seeds a project's bill and a Kenyan project does carry the
    # cost; a contractor-only stack would not.
    #
    # Ordering artefact, stated rather than hidden: the levy sits before the
    # tax line because every block in this table ends with its tax line, which
    # puts the levy inside the VAT base. VAT is not chargeable on a levy the
    # owner pays to the Authority, so this overstates the tax by 16 percent of
    # 0.5 percent, that is 0.08 percent of the contract sum. Putting the levy
    # after VAT trades that for an identical 0.08 percent error in the other
    # direction, because the levy base would then contain the VAT. The schema
    # has no way to exclude one line from another's base, so one of the two is
    # unavoidable and this is the one that keeps the tax line last.
    #
    # VAT is 16 percent under the Value Added Tax Act, 2013, the standard rate
    # since that Act and the rate the Kenya Revenue Authority applies to
    # construction services. Kenya is NOT in our effective-dated table, so this
    # figure is sourced externally, and Kenya should be added to
    # ``tax_configurations.json`` alongside this change.
    #
    # Overhead 12 and profit 10 are working defaults carried unchanged from the
    # flat ``kenya`` template, on the same reasoning as Nigeria. The 5.0
    # contingency is convention, not a published figure.
    "KE": [
        {
            "name": "Preliminaries",
            "category": "overhead",
            "percentage": "12.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Contractor's Overheads and Profit",
            "category": "profit",
            "percentage": "10.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "Contingency",
            "category": "contingency",
            "percentage": "5.0",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        {
            "name": "NCA Construction Levy",
            "category": "other",
            "percentage": "0.5",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
        {
            "name": "VAT",
            "category": "tax",
            "percentage": "16.0",
            "apply_to": "cumulative",
            "sort_order": 4,
        },
    ],
    # ── Morocco ─────────────────────────────────────────────────────────
    # Decree 2-22-431 on public procurement, which prescribes the bordereau des
    # prix and the détail estimatif and the sous-détail des prix behind them;
    # TVA at the 20 percent standard rate. Morocco is NOT in our effective-dated
    # tax table and the rate is sourced below rather than read from it.
    #
    # This is the French method in French, which is why the line names are the
    # FR block's line names. It is NOT the FR block, because the FR figures are
    # a French cost structure and Morocco's are not; the Morocco section below
    # the templates records that argument in full.
    #
    # Every percentage here is carried unchanged in total from the flat
    # ``morocco`` template in ``methodology/templates.py`` (overhead 12, profit
    # 8, TVA 20), so adding MA to the map renames the lines and splits the
    # overhead without repricing anything a Moroccan user sees today.
    #
    # The 5 / 7 split of the 12 between site and head office is NOT sourced. It
    # is the FR block's own proportion (10 against 15) rounded onto a total of
    # 12. Only the total is anchored. A reader holding a real Moroccan figure
    # for the division should overwrite both numbers, keeping the sum at 12.
    #
    # No contingency line, deliberately: bénéfice et aléas already carries the
    # risk allowance, which is what the aléas half of the name is. Adding a
    # separate contingency would allow for the same risk twice.
    "MA": [
        {
            "name": "Frais de chantier (FC)",
            "category": "overhead",
            "percentage": "5.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Frais généraux (FG)",
            "category": "overhead",
            "percentage": "7.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "Bénéfice et aléas (B&A)",
            "category": "profit",
            "percentage": "8.0",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        {
            "name": "TVA",
            "category": "tax",
            "percentage": "20.0",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
    ],
    # ── Malaysia ────────────────────────────────────────────────────────
    # Malaysian Standard Method of Measurement of Building Works, second
    # edition (SMM2, Institution of Surveyors Malaysia, 2000), JKR standard
    # bills of quantities.
    #
    # THIS REGION CARRIES NO BILL-LEVEL TAX LINE AND MUST STAY THAT WAY. It is
    # listed in ``NON_SINGLE_TAX_REGIONS`` below with the reason; the argument
    # is set out there rather than repeated here. Do not add a Malaysian VAT
    # line: there is no Malaysian VAT. ``app/core/tax.py`` already says so and
    # raises ``VATNotApplicable`` for MY rather than returning a rate, and
    # ``test_a_region_carries_one_tax_line_or_says_why_not`` asserts that a
    # region named in ``NON_SINGLE_TAX_REGIONS`` does not have exactly one tax
    # line, so adding one line here fails that test rather than sliding past
    # it.
    #
    # SMM2 states that the rates set against bill items are full inclusive
    # rates covering, among other things, establishment charges and profit. So
    # in the market as tendered, the contractor's overhead and profit are in
    # the works rates and not beside the bill heads, and only Preliminaries and
    # the sums are genuinely bill-level. The margin line is carried here all
    # the same, for the reason the CN and ID blocks give: ``BOQMarkup`` has
    # nowhere to put a percentage that informs a unit rate, and our rates come
    # from a cost database that does not already contain a margin, so applying
    # it at bill level does not double count. Preliminaries, by contrast, is
    # bill-level in its own right: it is Bill No. 1 of a Malaysian bill of
    # quantities and is priced as such.
    #
    # Categorisation follows the AU block for the same reason SG does: the
    # stack names its overhead separately, so the combined margin line is
    # ``profit``.
    #
    # All three percentages are working defaults. SMM2 is a measurement
    # standard and states no percentages at all, so there is no Malaysian
    # figure to be faithful to here; the shape is what this row asserts.
    #
    # ONE REPO EDIT GOES WITH THIS ROW AND NOTHING FAILS IF IT IS MISSED.
    # In ``app/modules/methodology/templates.py`` the ``malaysia`` entry of
    # ``_MORE_COUNTRY_TEMPLATES`` passes ``vat="6"`` and
    # ``tax_label="SST"``. ``_reconcile_with_region_table`` rebuilds the
    # cascade steps from this table but does not touch ``vat_rate``, so
    # once MY is mapped here the catalogue ships ``"vat_rate": "6"`` with
    # no tax step behind it, and that field is documented as the VAT
    # percentage or ``None`` when VAT is modelled purely as a cascade step.
    # It should become ``vat="0"``, which is what the US entry does for the
    # same reason. No test catches it: the single-tax-step check returns
    # early once a region has no single tax line, which is this region
    # exactly. That is why it is written down here instead.
    "MY": [
        {
            "name": "Preliminaries (Bill No. 1)",
            "category": "overhead",
            "percentage": "12.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Contractor's Overheads and Profit",
            "category": "profit",
            "percentage": "8.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "Contingency Sum",
            "category": "contingency",
            "percentage": "5.0",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
    ],
    # ── Nigeria ─────────────────────────────────────────────────────────
    # Building and Engineering Standard Method of Measurement, fourth revised
    # edition (BESMM4(R)), published by the Nigerian Institute of Quantity
    # Surveyors and required for bills of quantities in Nigeria from 1 March
    # 2021; VAT at 7.5 percent from our own effective-dated table, in force
    # since 2020-02-01.
    #
    # BESMM4(R) measures preliminaries as a section of the bill, so the same
    # statement the ZA block makes applies here: the Preliminaries line is a
    # substitute for an unmeasured preliminaries section, not an addition to a
    # measured one, and a bill that carries its own preliminaries section must
    # have this line deleted.
    #
    # Both percentages are working defaults carried unchanged from the flat
    # ``nigeria`` template in ``methodology/templates.py`` (overhead 12, profit
    # 10), so adding NG to the map adds the contingency line and the national
    # naming without repricing anything a Nigerian user sees today. The 5.0
    # contingency is the figure Nigerian bills conventionally carry as a
    # provisional sum; it is not set by BESMM or by statute.
    #
    # Not modelled, and an estimator will look for it: the 5 percent
    # withholding tax on construction contracts is deducted at source from each
    # payment and credited against the contractor's income tax. It reduces cash
    # received, it does not add to the bill, so it is not a markup line. The
    # Industrial Training Fund contribution is assessed on payroll rather than
    # on the contract sum and is likewise not a bill level charge. The 1
    # percent Nigerian Content Development levy applies to oil and gas
    # contracts and has no place in a building stack.
    "NG": [
        {
            "name": "Preliminaries",
            "category": "overhead",
            "percentage": "12.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Contractor's Overheads and Profit",
            "category": "profit",
            "percentage": "10.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "Contingency",
            "category": "contingency",
            "percentage": "5.0",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        {
            "name": "VAT",
            "category": "tax",
            "percentage": "7.5",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
    ],
    # ── New Zealand ─────────────────────────────────────────────────────
    # NZS 3910 conditions of contract and its Schedule of Prices, which carries
    # Preliminary and General as a priced section in its own right, NZS 4202
    # standard method of measurement, NZIQS elemental cost planning.
    #
    # Why this is not "NZ": "AU". The two markets do share the preliminaries
    # plus single-margin tradition, and folding NZ into the AU region would even
    # work mechanically, since AU has one tax line and the GST override would
    # swap 10 for 15. It is refused for one reason: the AU block is marked
    # UNRATIFIED, its three allowances are ``cumulative`` after the margin line,
    # and no ordering source was ever confirmed for it. Mapping NZ to AU would
    # propagate an ordering nobody has stood behind into a second market and
    # make it look twice as attested as it is.
    #
    # The contingency is ``direct_cost`` and this is a CHOICE, not a citation.
    # No New Zealand text was obtained that states whether a construction
    # contingency is taken before or after the contractor's margin, so the
    # header's general rule applies by default: profit stays out of the
    # contingency base. That is the conservative direction (it prices lower and
    # it is the shape the US block was corrected to) and it is recorded here as
    # unsourced so a New Zealand quantity surveyor can overturn it on evidence
    # rather than have to discover it.
    #
    # GST 15.0 is statutory and comes from our own tables. P&G, margin and the
    # contingency are working defaults for a medium commercial building. The
    # margin is one line, not two, because New Zealand tenders quote the
    # contractor's overhead and profit as a single margin the way Australia
    # does; splitting it would invent a division the market does not make.
    "NZ": [
        {
            "name": "Preliminary & General (P&G)",
            "category": "overhead",
            "percentage": "12.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Contractor's Margin (OH&P)",
            "category": "profit",
            "percentage": "10.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "Construction Contingency",
            "category": "contingency",
            "percentage": "5.0",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        {
            "name": "GST",
            "category": "tax",
            "percentage": "15.0",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
    ],
    # ── Peru ────────────────────────────────────────────────────────────
    # Presupuesto de obra as the Reglamento de la Ley de Contrataciones del
    # Estado requires it to be presented: costo directo, gastos generales,
    # utilidad, then IGV, each as its own stated figure rather than folded into
    # a rate. Reglamento Nacional de Edificaciones for the measurement side.
    #
    # Three lines is a national stack here and not the neutral method wearing
    # Peruvian names, which is the distinction
    # ``test_a_country_without_a_national_stack_does_not_claim_one`` polices.
    # The Spanish block is the precedent: it is also exactly three lines
    # (gastos generales, beneficio industrial, IVA) and it counts because the
    # regulation fixes the shape of those specific lines rather than leaving
    # them to the estimator. Peru is the same case. What makes it Peruvian is
    # that the presupuesto MUST separate these heads and that the tender is
    # compared on them.
    #
    # Both markup lines are ``direct_cost``: gastos generales and utilidad are
    # each a percentage of the costo directo in the standard presupuesto, and
    # neither is taken on the other. IGV is ``cumulative`` because it is levied
    # on the contract value.
    #
    # No contingency and no escalation line. Peruvian price movement runs
    # through formulas polinomicas and cost variation is settled by adicionales
    # de obra, both of which are contractual routes rather than presupuesto
    # heads, so a percentage here would misdescribe how a Peruvian job absorbs
    # them. The price-index module is where escalation lives, as for AU and AR.
    #
    # IGV 18.0 is statutory and from our own tables. The other two are working
    # defaults for a medium commercial building: gastos generales commonly runs
    # in the low teens and utilidad in the high single figures, but the figure
    # is the contractor's own and is bid, so what this row asserts is the shape
    # and not the number.
    "PE": [
        {
            "name": "Gastos Generales",
            "category": "overhead",
            "percentage": "12.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Utilidad",
            "category": "profit",
            "percentage": "8.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "IGV",
            "category": "tax",
            "percentage": "18.0",
            "apply_to": "cumulative",
            "sort_order": 2,
        },
    ],
    # ── Philippines ─────────────────────────────────────────────────────
    # DPWH detailed unit price analysis and the Approved Budget for the
    # Contract guidelines. DPWH is a public works standard rather than a
    # commercial building code, but it is the only published Philippine
    # estimating method and private quantity surveying practice follows its
    # shape, so it is what a Philippine bill is recognisably built from.
    #
    # The method is estimated direct cost, then a mark-up stated as two
    # percentages of EDC, then VAT. Both mark-up percentages are banded by EDC
    # and the bands are published: up to one million pesos gives OCM 13 and
    # profit 15, one to five million gives 12 and 14, five to ten gives 12 and
    # 13, ten to twenty gives 11 and 12, twenty to fifty gives 11 and 11, and
    # above fifty million gives 10 and 10. The band chosen here is the last
    # one, above fifty million pesos, because that is where a medium commercial
    # building sits. Naming the band is the point: the figures below are
    # sourced, not typical, and they are wrong for a small job in a way that is
    # easy to check and correct.
    #
    # There is no contingency line and that is not an omission. OCM stands for
    # Overhead, Contingencies and Miscellaneous, so the contingency is inside
    # the first line by definition. Adding a separate contingency line to this
    # stack would count the same allowance twice.
    #
    # Both mark-up lines are ``direct_cost`` because the guidelines state them
    # as percentages of EDC, and the total mark-up is the sum of the two
    # applied to EDC rather than one applied on top of the other. VAT is
    # ``cumulative`` because the guidelines compute it as 12 percent of EDC
    # plus the peso value of the mark-up.
    #
    # VAT 12.0 is the statutory rate under the National Internal Revenue Code
    # and is the rate the guidelines themselves use in the mark-up computation.
    # It is worth naming what it is not: the five percent figure that appears
    # around Philippine government contracts is the final withholding VAT the
    # agency deducts at payment, a collection mechanic, not the rate the
    # contract is priced at. This matches the ``vat="12"`` already hardcoded
    # for the Philippines in the methodology catalogue.
    "PH": [
        {
            "name": "OCM (Overhead, Contingencies and Miscellaneous)",
            "category": "overhead",
            "percentage": "10.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Profit",
            "category": "profit",
            "percentage": "10.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "VAT",
            "category": "tax",
            "percentage": "12.0",
            "apply_to": "cumulative",
            "sort_order": 2,
        },
    ],
    # ── Portugal ────────────────────────────────────────────────────────
    # Medições e orçamento. The Portuguese build-up separates the two halves of
    # indirect cost that other markets often merge: estaleiro, the cost of
    # establishing, running and dismantling the site, and custos indiretos de
    # estrutura, the share of the company's own running costs the job carries.
    # Those two on top of the direct cost give the custo total, and the margin
    # is taken on that, which is why Margem de lucro is ``cumulative`` and the
    # two overheads are not.
    #
    # Imprevistos is ``direct_cost`` and is ordered AFTER the margin on purpose.
    # Ordering it after means the margin's own base is the custo total without
    # the contingency, and keeping it on direct cost means the contingency's
    # base has no margin in it. Both halves of the general rule in the header
    # hold at once, and Portugal needs no exception recorded anywhere. Do not
    # "tidy" this by moving it to sort_order 2, which would put the contingency
    # inside the margin base.
    #
    # The IVA figure is statutory. The other four are working defaults. Sources
    # consulted on Portuguese estimating practice agree on the SHAPE, that a
    # price is direct cost plus estaleiro plus structure costs, adjusted by a
    # margin and an allowance for the unforeseen, and give margins anywhere from
    # 5 to 20 % with a worked example at 10 % margin and 3 % imprevistos. None
    # of them fixes a national figure, because there is none to fix: these are
    # the contractor's own numbers. What this row asserts is which lines exist,
    # in what order, on which base.
    "PT": [
        {
            "name": "Estaleiro",
            "category": "overhead",
            "percentage": "8.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Custos indiretos de estrutura",
            "category": "overhead",
            "percentage": "7.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "Margem de lucro",
            "category": "profit",
            "percentage": "10.0",
            "apply_to": "cumulative",
            "sort_order": 2,
        },
        {
            "name": "Imprevistos",
            "category": "contingency",
            "percentage": "3.0",
            "apply_to": "direct_cost",
            "sort_order": 3,
        },
        {
            "name": "IVA",
            "category": "tax",
            "percentage": "23.0",
            "apply_to": "cumulative",
            "sort_order": 4,
        },
    ],
    # ── Romania ─────────────────────────────────────────────────────────
    # Devize per HG 907/2016, standard forms F1, F2 and F3. F3, the list of work
    # quantities by category, is the Romanian bill of quantities and its
    # recapitulation is an explicit ladder rather than a set of parallel
    # percentages on one base:
    #
    #     T1 = cheltuieli directe (materiale, manoperă, utilaj, transport)
    #     T2 = T1 + alte cheltuieli directe
    #     T3 = T2 + cheltuieli indirecte, taken as I % of T2
    #     T4 = T3 + profit, taken as p % of T3
    #
    # Profit is therefore ``cumulative``: its base is direct plus indirect
    # costs, by the form, not by our choice. Cheltuieli indirecte is the first
    # line and takes ``direct_cost``, which is T2.
    #
    # Cheltuieli diverse și neprevăzute is ``cumulative`` and lands on a base
    # containing profit. This is the CONTINGENCY ON PROFIT case declared at the
    # top of this file and it needs an entry in
    # ``CONTINGENCY_ON_PROFIT_BY_DESIGN``. The reason is that the allowance
    # belongs to the deviz general, the investor's budget, where it is taken on
    # the sum of the chapters, and chapter 4 of that budget is exactly the total
    # of the F3 bills. So it layers on top of a total that already carries the
    # contractor's indirect costs and profit. This is layering, not the
    # two-parallel-axes error the CN block warns about: the deviz general wraps
    # the object devize rather than restating them a second way.
    #
    # What is sourced and what is not. HG 907/2016 caps the allowance rather
    # than setting it, at 10 % for new construction and 20 % for interventions
    # on existing buildings, so the 10.0 here is the cap for the case this table
    # describes and a Romanian estimator will recognise it as such. The 10 % and
    # 5 % on indirect costs and profit are NOT statutory: they are the near
    # universal default in Romanian devize software and in worked examples of
    # the F3 form, which is a strong convention and not a regulated figure. The
    # TVA figure is statutory.
    #
    # Not modelled: CAM, the contribuția asiguratorie pentru muncă, which sits
    # in "alte cheltuieli directe" at 2.25 %. It is levied on the manoperă
    # component alone, so expressing it as a percentage of total direct cost
    # would be wrong for every job with a different labour share, in the same
    # way the RU block flags for НР/СП on ФОТ. Leave it inside the direct cost
    # the positions carry.
    "RO": [
        {
            "name": "Cheltuieli indirecte",
            "category": "overhead",
            "percentage": "10.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Profit",
            "category": "profit",
            "percentage": "5.0",
            "apply_to": "cumulative",
            "sort_order": 1,
        },
        {
            "name": "Cheltuieli diverse și neprevăzute",
            "category": "contingency",
            "percentage": "10.0",
            "apply_to": "cumulative",
            "sort_order": 2,
        },
        {
            "name": "TVA",
            "category": "tax",
            "percentage": "21.0",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
    ],
    # ── Singapore ───────────────────────────────────────────────────────
    # SISV Singapore Standard Method of Measurement, PSSCOC and SIA form
    # bills of quantities.
    #
    # Say plainly what is Singaporean here and what is not. The measurement
    # tradition is British-derived: a separately priced Preliminaries bill,
    # all-in works rates, prime cost and provisional sums, and a stated
    # contingency sum. What is Singaporean is that a PSSCOC-form bill of
    # quantities carries the contingency sum as a priced line rather than
    # leaving risk to the cost plan, and that the tax is GST at 9.
    #
    # This block deliberately does NOT copy the UK stack. NRM1 orders risk
    # allowances after the main contractor's overheads and profit, which is
    # why the UK block has two ``cumulative`` contingency lines. NRM1 is a UK
    # cost-planning method and no source was found saying Singapore plans that
    # way, so borrowing its ordering would be inventing a method for this
    # market out of a neighbouring one.
    #
    # Preliminaries is ``overhead`` and the margin line is ``profit``, matching
    # the AU block, which is the file's existing precedent for a British-derived
    # market that names its preliminaries separately and then carries one
    # combined margin. Where a stack does not name overhead separately, the
    # combined line goes the other way and is filed as ``overhead`` (see TR,
    # and ID and TH below).
    #
    # The GST figure is ours and statutory. The other three are working
    # defaults: preliminaries and margin are the contractor's own, and a
    # contingency sum is agreed per contract. What this row asserts is the
    # shape, not that a Singapore job carries exactly twelve percent
    # preliminaries.
    "SG": [
        {
            "name": "Preliminaries",
            "category": "overhead",
            "percentage": "12.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Contractor's Overheads and Profit",
            "category": "profit",
            "percentage": "8.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "Contingency Sum",
            "category": "contingency",
            "percentage": "5.0",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        {
            "name": "GST",
            "category": "tax",
            "percentage": "9.0",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
    ],
    # ── Thailand ────────────────────────────────────────────────────────
    # หลักเกณฑ์การคำนวณราคากลางงานก่อสร้าง, the Comptroller General's
    # Department mid-price rules, and the Factor F tables issued under them.
    # The current table is announcement ว481 of 26 June 2026, at six percent
    # loan interest.
    #
    # Thailand does not build a stack. It publishes one multiplier: the mid
    # price of a job is direct cost times Factor F, and Factor F is defined as
    # covering ค่าอำนวยการ, ดอกเบี้ย, กำไร and ภาษี, that is operating cost,
    # interest, profit and tax. The four components are named in the definition
    # and are NOT published as separate percentages; the tables give F alone,
    # banded by direct cost and conditioned on the loan interest rate, the
    # advance payment percentage and the retention percentage.
    #
    # So this row is two lines and not four. Splitting the composite into its
    # four named components would invent a division the tables do not make,
    # which is the decision the TR block records. What is unbundled is only the
    # tax, because Factor F includes VAT at seven percent inside it and this
    # schema needs one tax line per region for the project override to have
    # somewhere to land. The combined line is filed as ``overhead`` because it
    # is not split, so this region has no line categorised as profit, on
    # purpose, exactly as TR has none.
    #
    # The number is checkable and here is the check. A Factor F table for
    # งานอาคาร at six percent interest, zero advance payment, zero retention
    # and seven percent VAT reads 1.2943 at ten million baht of direct cost,
    # 1.2159 at fifty million and 1.2049 at one hundred million. Stripping the
    # tax gives a pre-tax markup of F / 1.07, which is 20.9 percent at ten
    # million, 13.6 at fifty and 12.6 at one hundred. The 13.5 below is the
    # figure for a medium commercial building in the middle of that range, and
    # it reproduces the published multiplier: 1.135 x 1.07 = 1.2145, which sits
    # between the fifty million band at 1.2159 and the sixty million band at
    # 1.2061. If someone edits this line, that arithmetic is how to tell
    # whether the new value is still a Thai number.
    #
    # Two honest limits on that. The banding is real and steep, so a small job
    # genuinely carries a much higher markup than 13.5 and a large one a lower
    # one; a single percentage cannot express a table. And the F values above
    # were read from a Thai public-sector procurement worksheet at six percent
    # interest rather than from ว481 itself, which could not be opened. The
    # interest condition matches the current announcement and the magnitudes
    # are right, but they are not transcribed from the announcement.
    #
    # VAT 7.0 is the reduced rate, not the statutory one. The Revenue Code sets
    # ten percent and a royal decree has held it at seven continuously since
    # 1997, renewed annually; Royal Decree No. 799 B.E. 2568 carried it to 30
    # September 2026 and a further extension to 30 September 2027 was approved
    # by cabinet on 27 July 2026. Seven is used because thirty-four years of
    # unbroken renewal is not a temporary measure in any useful sense, and
    # because Factor F itself is computed on seven. This is the opposite call
    # to the Vietnamese one above and the difference is deliberate: the Thai
    # reduction has no end anyone plans around, the Vietnamese one has a date.
    # This matches the ``vat="7"`` already hardcoded for Thailand in the
    # methodology catalogue.
    "TH": [
        {
            # ค่าอำนวยการ ดอกเบี้ยและกำไร, operating cost, interest and profit
            "name": ("ค่าอำนวยการ ดอกเบี้ยและกำไร (Operating cost, interest and profit)"),
            "category": "overhead",
            "percentage": "13.5",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            # ภาษีมูลค่าเพิ่ม, value added tax
            "name": "ภาษีมูลค่าเพิ่ม (VAT)",
            "category": "tax",
            "percentage": "7.0",
            "apply_to": "cumulative",
            "sort_order": 1,
        },
    ],
    # ── Vietnam ─────────────────────────────────────────────────────────
    # Thông tư 11/2021/TT-BXD, dự toán xây dựng công trình, as amended by
    # Thông tư 14/2023/TT-BXD.
    #
    # This is the most strongly regulated shape of the six. The circular states
    # the construction cost estimate as direct cost, then chi phí gián tiếp
    # built from three named components, then thu nhập chịu thuế tính trước,
    # then VAT. It also states each component's base, which is what makes the
    # ``apply_to`` column here sourced rather than inferred:
    #
    #   * chi phí chung (C), chi phí nhà tạm (Ln) and chi phí một số công việc
    #     không xác định được khối lượng từ thiết kế (Tt) are each a percentage
    #     of direct cost, so all three are ``direct_cost``. C has two norm forms:
    #     the circular applies it to direct cost for công trình dân dụng
    #     and to labour cost for some work types, so the row below states
    #     the direct-cost form, the way the RU block states an effective
    #     percentage of direct cost for norms written against a payroll
    #     base.
    #   * thu nhập chịu thuế tính trước (TL) is a percentage of direct cost
    #     plus indirect cost, T + GT. ``cumulative`` means direct cost plus
    #     every preceding line, and the three preceding lines are exactly GT,
    #     so ``cumulative`` reproduces the circular's base exactly rather than
    #     approximately.
    #   * thuế GTGT is levied on the pre-tax contract value, so ``cumulative``.
    #
    # Tt is categorised ``contingency`` because that is what it is, an
    # allowance for work whose quantity cannot be taken off the design. Note
    # that it therefore sits BEFORE the margin line, which is the opposite of
    # the UK and PL orderings, and it is the circular that puts it there.
    #
    # THE SHAPE IS SOURCED, THE FOUR PERCENTAGES ARE NOT. The circular sets
    # them in Appendix tables 3.1 through 3.5, banded by work type and by
    # pre-tax construction cost in the approved total investment, with no
    # interpolation. Those tables could not be obtained, so the figures below
    # are working defaults in the published bands for công trình dân dụng and
    # are NOT transcribed values. Anyone with the appendix in front of them
    # should replace all four and delete this paragraph. Do not read them as
    # regulated numbers.
    #
    # TL is the one of the four with a retrieved figure behind it. A
    # Vietnamese secondary source states that thu nhập chịu thuế tính trước
    # is fixed at 6 percent of T plus GT, and 6.0 is written below on that
    # basis. 5.5 is the band widely quoted for civil works under the
    # predecessor circular and is the figure this row carried first. Neither
    # was checked against Appendix Table 3.5. So TL is better founded than
    # the other three and still not a transcribed value.
    #
    # VAT 10.0 is the statutory rate and is used deliberately in preference to
    # the 8 percent that is in force today. Resolution 204/2025/QH15 cut the
    # rate by two points from 1 July 2025 to 31 December 2026, and this table
    # has no date axis and is copied into a bill row that is then hand-edited,
    # so a rate that expires inside the life of most bills seeded from it is
    # the worse of the two errors. The reduction is also not uniform across a
    # construction bill: metals and prefabricated metal products are excluded
    # and stay at 10. A Vietnamese bill priced today for eligible work should
    # have this line edited to 8. This matches the ``vat="10"`` already
    # hardcoded for Vietnam in the methodology catalogue.
    "VN": [
        {
            "name": "Chi phí chung (General costs)",
            "category": "overhead",
            "percentage": "6.5",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Chi phí nhà tạm (Temporary site facilities)",
            "category": "overhead",
            "percentage": "1.1",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "Chi phí không xác định được khối lượng (Undefined-quantity works)",
            "category": "contingency",
            "percentage": "2.5",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        {
            "name": "Thu nhập chịu thuế tính trước (Pre-determined taxable income)",
            "category": "profit",
            "percentage": "6.0",
            "apply_to": "cumulative",
            "sort_order": 3,
        },
        {
            "name": "Thuế GTGT (VAT)",
            "category": "tax",
            "percentage": "10.0",
            "apply_to": "cumulative",
            "sort_order": 4,
        },
    ],
    # ── South Africa ────────────────────────────────────────────────────
    # ASAQS Standard System of Measuring Building Work for buildings and
    # SANS 1200 for civils; JBCC Principal Building Agreement edition 6.2 for
    # the preliminaries; Contract Price Adjustment Provisions (CPAP, the
    # Haylett formula) on the work group indices Statistics South Africa
    # publishes; Value-Added Tax Act 89 of 1991 for the tax line.
    #
    # WHICH THING THE P&G LINE MODELS, because the brief is right that these
    # are not the same thing. Under ASAQS and JBCC the preliminaries are a
    # priced section of the bill, Bill No 1, measured item by item and priced
    # as fixed charges, value related charges and time related charges so that
    # a variation or a delay adjusts the right third of them. A percentage is
    # none of that. So the line below is a SUBSTITUTE for a preliminaries
    # section that has not been measured yet, which is the state every bill is
    # in at the moment it is seeded, and it is NOT an addition to a measured
    # one. A bill that carries a real Bill No 1 must have this line deleted,
    # and both shipped ZA demos are the worked example of what happens when it
    # is not (see FINDING 2). Somewhere to declare that a bill already prices
    # its own preliminaries is the change that would actually finish this; the
    # same gap the CN block describes for unit rate composition.
    #
    # The two percentages that are not allowances are anchored, not invented.
    # ``methodology/templates.py`` already ships the flat ``south_africa``
    # template at overhead 12 and profit 8, and the two demos price 11.0 / 8.0
    # (Johannesburg, building) and 12.5 / 8.5 (Cape Town, civils). Twelve and
    # eight is the figure all three already agree on, so adding ZA to
    # ``REGION_BY_COUNTRY`` supersedes the flat template without moving the
    # numbers a South African user sees today. What the row adds is the two
    # allowance lines and the national line names.
    #
    # "Contractor's Overheads & Profit" is one line because the South African
    # market quotes it as one, and it is categorised ``profit`` rather than
    # ``overhead``. That is the opposite of the choice the TR block makes for
    # its combined line, on purpose: the Turkish figure is dominated by genel
    # giderler with no separately priced site overhead beside it, whereas here
    # the P&G line above already carries the site overhead, so what is left in
    # the O&P line is predominantly margin. The categories are read by the per
    # position price analysis, which is why this is a decision and not a label.
    #
    # CPAP is ``other`` and not ``overhead``, and this diverges from both demos
    # deliberately. The demos file escalation as ``overhead``, and the CN block
    # records what that costs: the price analysis derives a unit rate's
    # overhead from the categories of the bill's markup lines, so a 4.5 percent
    # escalation line sitting in ``overhead`` reports a South African bill as
    # carrying 16.5 percent overhead when the contractor's is 12. It is also
    # the only ``cumulative`` line before the tax: CPAP adjusts the value of
    # work certified, and that value contains the preliminaries and the
    # contractor's mark-up because they are in the priced bill. Two caveats,
    # both stated rather than fixed. The formula excludes certain amounts
    # (provisional sums, materials on site) that a flat percentage cannot
    # exclude, and because the base here is cumulative rather than the demos'
    # direct cost, 4.5 percent lands as about 5.4 percent of direct cost. Like
    # the AU "Escalation Allowance" it is a flat percentage standing in for
    # time-based escalation; the price-index module holds the real date-to-date
    # arithmetic.
    #
    # CPAP is contract-specific in a way the seed cannot know. JBCC runs both
    # with and without contract price adjustment, and a fixed price contract
    # carries no CPAP line at all. So this line is deleted on a fixed price
    # bill, exactly as the P&G line is deleted when preliminaries are measured.
    # It is seeded rather than omitted because both shipped demos carry it.
    #
    # The contingency is ``direct_cost``. No South African standard method
    # orders it onto a base containing profit, so the general rule governs, and
    # both demos already carry it that way.
    "ZA": [
        {
            "name": "Preliminaries & General (P&Gs)",
            "category": "overhead",
            "percentage": "12.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Contractor's Overheads & Profit",
            "category": "profit",
            "percentage": "8.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "Contract Price Adjustment (CPAP)",
            "category": "other",
            "percentage": "4.5",
            "apply_to": "cumulative",
            "sort_order": 2,
        },
        {
            "name": "Construction Contingency",
            "category": "contingency",
            "percentage": "6.0",
            "apply_to": "direct_cost",
            "sort_order": 3,
        },
        {
            "name": "VAT",
            "category": "tax",
            "percentage": "15.0",
            "apply_to": "cumulative",
            "sort_order": 4,
        },
    ],
    # ── Default (generic international) ─────────────────────────────────
    # The fallback for every region without a template of its own, so it can
    # appeal to no national standard method and follows the general rule: the
    # contingency stays off any base that contains profit.
    "DEFAULT": [
        {
            "name": "Site Overhead",
            "category": "overhead",
            "percentage": "10.0",
            "apply_to": "direct_cost",
            "sort_order": 0,
        },
        {
            "name": "Head Office Overhead",
            "category": "overhead",
            "percentage": "5.0",
            "apply_to": "direct_cost",
            "sort_order": 1,
        },
        {
            "name": "Profit",
            "category": "profit",
            "percentage": "5.0",
            "apply_to": "direct_cost",
            "sort_order": 2,
        },
        {
            "name": "Contingency",
            "category": "contingency",
            "percentage": "5.0",
            "apply_to": "direct_cost",
            "sort_order": 3,
        },
    ],
}

# ── Which country reads which stack ──────────────────────────────────────────
#
# A region key above is a convention, not a border. DACH is the German
# Zuschlagskalkulation, and Austria and Switzerland cost a job that way too;
# GULF is the GCC preliminaries-and-general tradition shared by its members;
# NORDIC is the Swedish APO/CO structure the other three read without
# translation. The rest are single-country conventions that happen to be named
# after the country.
#
# A country is in this map when the table genuinely states its national method.
# A country that is absent is not an oversight and must not be added to make a
# catalogue look complete: absence is the honest answer that we ship the
# neutral international method for that market, and the methodology catalogue
# says exactly that in the template it builds. Adding a country here changes
# the numbers a bill is seeded with for that market, so it is a data decision,
# not a mapping tidy-up.
#
# Russia was the one stack in the table above that no country reached. The
# lines were written, cited to МДС 81-35.2004 and Приказ Минстроя 812/пр, and
# unreachable, because this map had no ``RU`` line: ``region_lines_for_country``
# answered ``None``, so a Russian project was offered the neutral international
# method and told, correctly, that it was the neutral international method. The
# criterion above is whether the table states the country's national method,
# and for Russia it does. ``test_every_stack_is_reachable_from_some_country``
# now asserts the direction that was missing.
REGION_BY_COUNTRY: dict[str, str] = {
    "AT": "DACH",
    "CH": "DACH",
    "DE": "DACH",
    "GB": "UK",
    "US": "US",
    "FR": "FR",
    "AE": "GULF",
    "KW": "GULF",
    "QA": "GULF",
    "SA": "GULF",
    "IN": "IN",
    "AU": "AU",
    "JP": "JP",
    "BR": "BR",
    "DK": "NORDIC",
    "FI": "NORDIC",
    "NO": "NORDIC",
    "SE": "NORDIC",
    "CN": "CN",
    "KR": "KR",
    "RU": "RU",
    "HU": "HU",
    "IT": "IT",
    "ES": "ES",
    "NL": "NL",
    "PL": "PL",
    "TR": "TR",
    # ── The twenty-two markets added in one pass ─────────────────────────
    # Grouped by continent only for reading; the table itself is flat and the
    # order here has no meaning beyond that. Every one of these countries had a
    # methodology template that said of itself that it carried the neutral
    # international method rather than a national convention, which is exactly
    # the state this table exists to end.
    "PT": "PT",
    "BE": "BE",
    "CZ": "CZ",
    "RO": "RO",
    "GR": "GR",
    # Ireland reads the UK stack rather than getting one of its own. The
    # measurement convention, the bill structure and the preliminaries practice
    # are the same tradition, and the one number that differs, VAT at 13.5 on
    # construction services against 20, is exactly what the per-project rate
    # override is for. A separate IE stack would be the UK stack retyped, which
    # is how two descriptions of one convention start to disagree.
    "IE": "UK",
    "ZA": "ZA",
    "IL": "IL",
    "NG": "NG",
    "KE": "KE",
    "MA": "MA",
    "SG": "SG",
    "ID": "ID",
    "VN": "VN",
    "MY": "MY",
    "TH": "TH",
    "PH": "PH",
    "CA": "CA",
    "NZ": "NZ",
    "AR": "AR",
    "CL": "CL",
    "CO": "CO",
    "PE": "PE",
}

# Regions whose tax lines a single country VAT rate cannot stand in for, and
# why. Everywhere else a region carries exactly one tax line, so swapping its
# percentage for the rate the payer actually faces is a complete statement:
# that is what the per-project ``default_vat_rate`` override does, and it is
# how one DACH stack serves Germany at 19, Austria at 20 and Switzerland at
# 8.1. These cannot be served that way, so nothing overrides them and their
# own rates stand. That is enforced in :func:`resolve_region_lines`, which
# every caller that prices comes through, rather than being left to each
# caller to remember: it was left to each caller once, and the bill-seeding
# path did not remember.
#
# ``tests/unit/test_one_country_one_markup_stack.py`` walks every region and
# fails on any region with a tax-line count other than one that is not listed
# here, so a fifteenth region with two levies has to state its reason before it
# can ship rather than silently taking one country's rate twice.
# Countries where construction is charged at a tier of its own, so the rate on
# a bill of quantities is NOT the country's headline rate, and why.
#
# The distinction only became load-bearing when the bill started resolving a
# country's rate from the effective-dated tax seed. That table answers "what is
# this country's standard VAT rate", which is the right question almost
# everywhere and the wrong one here: it returns China's headline 13, and a
# Chinese bill of quantities is priced at 9. Taking the seed's answer would
# replace a correct construction rate with a correct general one, which is the
# worst shape a wrong number can have, because both figures are defensible and
# only one of them is about building work.
#
# So these countries keep the rate written on their own regional stack, which
# is where the construction tier is recorded. A per-project override still
# wins, because a project that states its rate has answered the question
# itself.
#
# ``tests/pg/test_a_bill_is_priced_at_its_own_countrys_vat.py`` pins this set
# in both directions: a country added here without a tier to justify it fails,
# and a country whose bill stops matching its seed rate without being named
# here fails too.
CONSTRUCTION_TIER_COUNTRIES: dict[str, str] = {
    "CN": (
        "China's headline VAT rate is 13, which is what the seed's is_default row carries, and "
        "construction and building services are charged at the 9 tier the seed carries as "
        "VAT_RED. Both figures are right about different questions and 9 is the one a bill of "
        "quantities asks"
    ),
}

NON_SINGLE_TAX_REGIONS: dict[str, str] = {
    "CA": (
        "GST is federal at 5 and every province either replaces it with a harmonised HST or "
        "stacks its own PST, QST or RST on top, so the rate on a contract sum is 5, 11, 12, 13, "
        "14, 14.975 or 15 depending on the province and no single number is any of them"
    ),
    "MY": (
        "SST is two taxes and neither is a VAT on the contract sum: sales tax is levied at "
        "manufacture or import and sits in the material price inside the unit rate, while the "
        "service tax on construction work applies only to non-residential work above a "
        "registration threshold, so no one percentage is right for every Malaysian bill"
    ),
    "CO": (
        "IVA on a construction contract over immovable property is levied on the utilidad alone "
        "rather than on the contract sum, and a bill-level line can only be taken on direct cost "
        "or on the running total, so neither base can express it"
    ),
    "US": (
        "sales tax is levied on materials at the point of purchase and sits in the unit rate, "
        "not on the contract sum, so a US stack carries no bill-level tax line at all"
    ),
    "BR": (
        "PIS + COFINS is federal and ISS is municipal, two levies at two statutory rates, "
        "so one VAT number cannot stand in for both"
    ),
    "DEFAULT": ("the neutral stack names no jurisdiction, so it names no consumption tax either"),
}


def resolve_region_lines(region_key: str, *, vat_rate: str | None = None) -> list[dict[str, object]]:
    """Return a region's markup lines in seeding order, with VAT swapped in.

    The single reader of :data:`DEFAULT_MARKUP_TEMPLATES` for anything that
    prices. Both engines come through here, which is the point: the rule for
    what a country's stack contains is written once, and a change to it moves
    both at the same time instead of moving one and leaving the other to be
    discovered by a customer comparing two totals.

    The VAT rule is the one the per-project override has always applied: when a
    rate is supplied, every line in the ``tax`` category takes it, EXCEPT in a
    region listed in :data:`NON_SINGLE_TAX_REGIONS`, where a single number
    cannot describe the levies and the region's own rates stand.

    That exception used to live in :func:`region_lines_for_country` alone, so
    it held for the methodology catalogue and not for the bill. Only one region
    carries more than one tax line, and it is the region where getting this
    wrong is loudest: a Brazilian stack is PIS + COFINS at 3.65 and ISS at 3,
    and an override applied to both took the bill's tax from 6.65 percent to
    twice whatever number was typed. Our own shipped tax seed names 18 as
    Brazil's default, so 18 was the number a user had every reason to type, and
    the bill it produced charged 36.

    The caller therefore no longer decides this, which is the point of the
    guard sitting here: a rule that has to be remembered by every caller is a
    rule that will be true in one of them.

    Args:
        region_key: A key of :data:`DEFAULT_MARKUP_TEMPLATES`, case-insensitive.
            An unknown key falls back to ``DEFAULT``, matching how a bill has
            always been seeded for a region nobody wrote a stack for.
        vat_rate: Percentage as a decimal string, e.g. ``"19"`` or ``"8.1"``.
            ``None`` leaves the region's own tax rates alone. ``"0"`` is a real
            rate and does override, because a zero-rated jurisdiction is a
            statement, not a missing value.

    Returns:
        Fresh dicts in ``sort_order``, so a caller may mutate them freely. Each
        carries the template's own keys plus ``vat_override``, which is ``True``
        exactly on the lines whose percentage this call replaced. In a
        multi-levy region that is every line's ``False`` even when a rate was
        supplied, so a bill can be read back and shown to carry the market's
        own rates rather than a substituted one.
    """
    key = region_key.upper()
    template = DEFAULT_MARKUP_TEMPLATES.get(key, DEFAULT_MARKUP_TEMPLATES["DEFAULT"])
    # An unknown key fell back to DEFAULT above, so ask the guard about the key
    # that actually chose the template rather than the one that was passed in.
    if key not in DEFAULT_MARKUP_TEMPLATES:
        key = "DEFAULT"
    if key in NON_SINGLE_TAX_REGIONS:
        vat_rate = None
    lines: list[dict[str, object]] = []
    for entry in sorted(template, key=lambda e: int(e.get("sort_order", 0))):  # type: ignore[arg-type]
        line = dict(entry)
        swapped = vat_rate is not None and line.get("category") == "tax"
        if swapped:
            line["percentage"] = vat_rate
        line["vat_override"] = swapped
        lines.append(line)
    return lines


def region_lines_for_country(country_code: str, *, vat_rate: str | None = None) -> list[dict[str, object]] | None:
    """Return the national stack for a country, or ``None`` if we do not have one.

    ``None`` is a real answer and callers must carry it as one. It means the
    table states no convention for that market, and the honest thing to offer
    there is the neutral international method described as the neutral
    international method. Substituting the ``DEFAULT`` stack here would hide
    that distinction behind a stack that looks national and is not, which is
    the failure this whole arrangement exists to end.

    Args:
        country_code: ISO 3166-1 alpha-2, case-insensitive.
        vat_rate: The country's standard consumption-tax rate as a decimal
            string. Applied only where the region carries a single tax line;
            see :data:`NON_SINGLE_TAX_REGIONS` for the ones that do not.

    Returns:
        The region's lines as :func:`resolve_region_lines` returns them, or
        ``None`` when the country has no entry in :data:`REGION_BY_COUNTRY`.
    """
    region_key = REGION_BY_COUNTRY.get(country_code.upper())
    if region_key is None:
        return None
    # The multi-levy guard used to be applied here. It now lives in
    # ``resolve_region_lines``, where the bill-seeding caller reaches it too.
    return resolve_region_lines(region_key, vat_rate=vat_rate)


def region_key_for_country(country_code: str | None) -> str:
    """Return the markup region a project's country belongs to.

    This is the seeding counterpart to :func:`region_lines_for_country`, and it
    answers a deliberately different question. That function returns ``None``
    for a market whose national convention the table does not state, because a
    caller asking "what is this country's method" must be able to hear "we do
    not claim one". This function is asked "which stack do we seed a bill
    with", and there a bill has to be seeded with something, so an unstated
    market resolves to ``DEFAULT``: the neutral international stack, which is
    what every bill in the product was seeded with before regions existed.

    An empty string and ``None`` both mean the project names no country, and
    both land on ``DEFAULT``. They must not land on ``DACH``. That is not a
    hypothetical: ``country_code`` carried ``NOT NULL DEFAULT 'DE'`` until
    revision ``v3319``, so before it a project whose creator named no country
    was indistinguishable from one in Germany, and deriving a region from the
    column would have quoted an unstated market with German site overheads,
    German profit and German VAT with nothing on screen saying so.

    Args:
        country_code: ISO 3166-1 alpha-2, case-insensitive, or ``None``.

    Returns:
        A key of :data:`DEFAULT_MARKUP_TEMPLATES`, always resolvable.
    """
    country = (country_code or "").strip().upper()
    return REGION_BY_COUNTRY.get(country, "DEFAULT")
