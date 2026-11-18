# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Regional configuration for China.

The platform already carried China almost everywhere - a zh locale, two seeded
Chinese demo projects, GB 50500 markup templates, a Chinese partner pack - and
nowhere did anything declare what measurement system a Chinese project uses.
``app.core.regional_packs`` resolves that from the packs' own ``countries``
lists, so a project in a country no pack claims resolves to ``None``, and
``BOQUnitSystemConsistencyRule`` returns an empty result on ``None``. The rule
was therefore silent on every Chinese bill: not passing, not failing, absent.
This pack is what makes it speak.

On the standard edition. GB/T 50500-2024 superseded GB 50500-2013 from
2025-09-01, together with the GB/T 50854-2024 to GB/T 50862-2024 measurement
family. We hold neither text, so this pack names the edition whose content we
can actually verify rather than the newest one, exactly as the two Chinese demo
projects do. Note the prefix when reading the pair: the 2013 edition is GB, a
mandatory code, and the 2024 edition is GB/T, a recommended standard.
"""

from decimal import Decimal
from typing import Any

from app.core.item_codes import editions as item_code_editions

PACK_CONFIG: dict[str, Any] = {
    # ── Identity ─────────────────────────────────────────────────────────────
    "region_code": "CN",
    "countries": ["CN"],
    "default_currency": "CNY",
    "supported_currencies": ["CNY"],
    "default_locale": "zh",
    "measurement_system": "metric",
    "paper_size": "A4",
    "date_format": "YYYY-MM-DD",
    "number_format": "1,234.56",
    # ── Standards ────────────────────────────────────────────────────────────
    "standards": [
        {
            "code": "GB_50500",
            "name": "GB 50500-2013 - 建设工程工程量清单计价规范",
            "description": (
                "Code for bill of quantities valuation of construction works. Prescribes the "
                "bill format, the nine-digit item coding and the comprehensive unit rate that "
                "carries labour, materials, plant, overheads and profit in one figure."
            ),
        },
        {
            "code": "GB_50854_FAMILY",
            "name": "GB 50854 to GB 50862 - 工程量计算规范 (measurement rules)",
            "description": (
                "The measurement family that sits under GB 50500, one code per work type: "
                "GB 50854 building and decoration works, GB 50856 general installation works, "
                "GB 50857 municipal works, and the remainder of the 50854-50862 range."
            ),
        },
        {
            "code": "GB_50300",
            "name": "GB 50300-2013 - 建筑工程施工质量验收统一标准",
            "description": "Unified standard for acceptance of construction quality of building works.",
        },
        {
            "code": "GB_50011",
            "name": "GB 50011-2010 - 建筑抗震设计规范",
            "description": "Code for seismic design of buildings; sets the fortification intensity a design works to.",
        },
        {
            "code": "GB_T_50378",
            "name": "GB/T 50378 - 绿色建筑评价标准",
            "description": "Assessment standard for green building, rated one to three stars.",
        },
    ],
    # ── Cost data references ─────────────────────────────────────────────────
    "cost_database_references": [
        {
            "code": "NATIONAL_QUOTA",
            "name": "全国统一建筑工程基础定额 - National unified basic quota",
            "description": (
                "The national consumption quota for labour, material and plant per unit of work. "
                "Provinces issue their own priced quota on top of it, so a rate is only "
                "meaningful together with the province and the year it belongs to."
            ),
        },
        {
            "code": "PROVINCIAL_QUOTA",
            "name": "省级消耗量定额 - Provincial consumption quota",
            "description": (
                "Each province and directly administered municipality publishes its own priced "
                "quota, for example for Shanghai, Guangdong or Beijing. This is the level a "
                "comprehensive unit rate is normally built from."
            ),
        },
        {
            "code": "COST_INFORMATION",
            "name": "工程造价信息 - Construction cost information bulletins",
            "description": (
                "Material and plant prices published periodically by provincial and municipal "
                "cost management stations; the usual source for adjusting a quota rate to a "
                "current price level."
            ),
        },
    ],
    # ── Contract types ───────────────────────────────────────────────────────
    "contract_types": [
        {
            "code": "GF_2017_0201",
            "name": "GF-2017-0201 - 建设工程施工合同(示范文本)",
            "description": "Model construction contract issued for building and civil works.",
        },
        {
            "code": "GF_2020_0216",
            "name": "GF-2020-0216 - 建设项目工程总承包合同(示范文本)",
            "description": "Model design-build / EPC contract for whole-project general contracting.",
        },
        {
            "code": "UNIT_PRICE",
            "name": "单价合同 - Unit price contract",
            "description": "Payment on measured quantities at the tendered comprehensive unit rates.",
        },
        {
            "code": "LUMP_SUM",
            "name": "总价合同 - Lump sum contract",
            "description": "Fixed price for the whole defined scope.",
        },
        {
            "code": "FIDIC_CN",
            "name": "FIDIC Conditions (adapted for China)",
            "description": "Used on internationally funded and cross-border projects.",
        },
    ],
    # ── Tax rules (增值税 / VAT) ──────────────────────────────────────────────
    #
    # Each row carries its own window. The VAT Law (in force 2026-01-01) keeps
    # 13 / 9 / 6 and the 3% collection rate; the 1% for small taxpayers is a
    # temporary reduction that ends 2027-12-31 (MOF/STA Ann. 2026 No.10).
    "tax_rules": [
        {
            "code": "CN_VAT_13",
            "name": "增值税 - 13% (goods)",
            "type": "vat",
            "rate_pct": "13",
            "effective_from": "2019-04-01",
            "effective_to": None,
            "description": (
                "Rate on goods, including goods sold together with their installation "
                "(prefabricated parts, machinery, steel structure)."
            ),
        },
        {
            "code": "CN_VAT_9",
            "name": "增值税 - 9% (construction services)",
            "type": "vat",
            "rate_pct": "9",
            "effective_from": "2019-04-01",
            "effective_to": None,
            "description": "Rate for construction and installation services under the general method.",
            "note": "This is the rate a works contract normally carries.",
        },
        {
            "code": "CN_VAT_6",
            "name": "增值税 - 6% (other services)",
            "type": "vat",
            "rate_pct": "6",
            "effective_from": "2016-05-01",
            "effective_to": None,
            "description": "Design, supervision, cost consultancy and other services.",
        },
        {
            "code": "CN_VAT_3_SIMPLIFIED",
            "name": "增值税 - 3% 简易计税 (simplified method)",
            "type": "vat",
            "rate_pct": "3",
            "effective_from": "2016-05-01",
            "effective_to": None,
            "description": (
                "Collection rate of the simplified method. Only an eligible project may elect it: "
                "labour-only work (清包工) and old projects (老项目) until 2027-12-31, and employer-supplied "
                "(甲供) projects only if they were already on it before 2026-01-01. See simplified_elections."
            ),
        },
        {
            "code": "CN_VAT_1_SMALL",
            "name": "增值税 - 1% (small taxpayers, reduced collection rate)",
            "type": "vat",
            "rate_pct": "1",
            "effective_from": "2026-01-01",
            "effective_to": "2027-12-31",
            "description": "The 3% collection rate reduced to 1% for small-scale taxpayers, until 2027-12-31.",
        },
    ],
    # ── Payment milestones (typical) ─────────────────────────────────────────
    "payment_templates": [
        {
            "code": "PROGRESS_PAYMENT",
            "name": "工程进度款 - Progress payment",
            "description": "Interim payment on measured progress, the usual monthly cycle on a works contract.",
            "fields": [
                "period",
                "measured_value",
                "advance_recovery",
                "retention_pct",
                "retention_amount",
                "previous_payments",
                "net_amount_due",
                "vat",
                "total_payable",
            ],
        },
        {
            "code": "SETTLEMENT",
            "name": "竣工结算 - Final settlement",
            "description": "Final measurement and settlement of the contract sum on completion.",
        },
    ],
    # ── Chinese number grouping ──────────────────────────────────────────────
    "number_system": {
        "name": "Chinese numbering system",
        "description": "Groups by four digits: 万 is 10,000 and 亿 is 100,000,000.",
        "examples": [
            {"value": 10000, "formatted": "10,000", "word": "1 万"},
            {"value": 100000000, "formatted": "100,000,000", "word": "1 亿"},
        ],
    },
    # ── Units (metric defaults, written the way a bill writes them) ──────────
    #
    # These are the words, not the Latin short codes, because that is what a
    # GB 50500 bill contains and what an estimator types. A pack that
    # prescribes a unit the validation vocabulary cannot read is how the rule
    # went blind on the Russian market, so the pairing is pinned by
    # ``test_the_china_pack_declares_its_default_units_in_chinese``.
    "default_units": {
        "length": "米",
        "area": "平方米",
        "volume": "立方米",
        "weight": "千克",
        "temperature": "°C",
    },
    # ── VAT rates ────────────────────────────────────────────────────────────
    #
    # "standard" is the 9% construction-services rate rather than the 13% goods
    # rate: this is the figure a works contract is priced with, and it is the
    # one a bill total needs. China has two low rates, 9 and 6, so "reduced"
    # here only means the services rate; the per-line answer is in
    # ``tax_categories`` below, which is what the rules read.
    "vat_rates": {
        "CN": {
            "standard": Decimal("0.09"),
            "reduced": Decimal("0.06"),
            "zero": Decimal("0.00"),
        },
    },
}

# ── VAT and GB/T 50500-2024 data the neutral engines are fed with ────────────
#
# Sources (read 2026-11-18): S1 VAT Law 2024-12-25; S2 Decree 826; S3 MOF/STA
# Ann. 2026 No.10; S4 Ann. 2026 No.13; S5 Ann. 2026 No.14 (read through the
# Jiangsu Tax Bureau explainer only); S6 STA Ann. 2024 No.11; S7 Shanghai
# application rules 2025 for GB/T 50500-2024; S8 Guangdong 2025 No.24. The
# standard text itself is not held: structure and codes only, our own wording.
CN_TAX: dict[str, Any] = {
    "sources": {
        "S1": "VAT Law of the PRC (2024-12-25, in force 2026-01-01)",
        "S2": "Decree 826, VAT Law Implementing Regulations (in force 2026-01-01)",
        "S3": "MOF/STA Announcement 2026 No.10",
        "S4": "MOF/STA Announcement 2026 No.13",
        "S5": "MOF/STA Announcement 2026 No.14 (secondary reading, verify)",
        "S6": "STA Announcement 2024 No.11 (fully digitalised e-invoices)",
        "S7": "GB/T 50500-2024 via Shanghai application rules 2025 (沪建标定〔2025〕521号)",
        "S8": "Guangdong 粤标定函〔2025〕24号 cl.4 (secondary reading)",
    },
    # Effective-dated categories a bill line or an invoice line is assigned to.
    "tax_categories": [
        {"code": "works", "kind": "works", "rate_pct": "9", "effective_from": "2019-04-01", "source": "S1 Art.10"},
        {"code": "goods", "kind": "goods", "rate_pct": "13", "effective_from": "2019-04-01", "source": "S1 Art.10"},
        {
            "code": "goods_installed",
            "kind": "goods",
            "rate_pct": "13",
            "effective_from": "2026-01-01",
            "source": "S4 sec.3",
        },
        {
            "code": "services",
            "kind": "services",
            "rate_pct": "6",
            "effective_from": "2016-05-01",
            "source": "S1 Art.10",
        },
        {
            "code": "simplified",
            "kind": "simplified",
            "rate_pct": "3",
            "effective_from": "2016-05-01",
            "source": "S1 Art.11",
        },
        {
            "code": "small_taxpayer",
            "kind": "simplified",
            "rate_pct": "1",
            "effective_from": "2026-01-01",
            "effective_to": "2027-12-31",
            "source": "S3",
        },
        {"code": "exempt", "kind": "exempt", "rate_pct": "0", "effective_from": "2016-05-01", "source": "S1"},
    ],
    # Rates a line of a given kind may carry on a general-method bill.
    "expected_rates_by_kind": {"works": ["9"], "goods": ["13"], "services": ["6"]},
    # Who may elect the 3% simplified method, and until when.
    "simplified_elections": [
        {
            "basis": "labour_only",
            "label_zh": "清包工",
            "valid_to": "2027-12-31",
            "source": "S3 sec.3(1)",
        },
        {
            "basis": "old_project",
            "label_zh": "老项目",
            "permit_start_before": "2016-04-30",
            "valid_to": "2027-12-31",
            "source": "S3 sec.3(1)",
        },
        {
            "basis": "employer_supplied",
            "label_zh": "甲供工程",
            # No new election on a contract dated on or after this day;
            # projects already on the simplified method before it continue.
            "no_new_election_from": "2026-01-01",
            "grandfathered": True,
            "source": "S3 sec.5(6)",
        },
    ],
    "simplified_lock_months": 36,
    "small_taxpayer_threshold_cny": "5000000",
    # 预缴: (gross received - subcontract paid) / (1 + rate) x prepay rate.
    "prepayment": {
        "general_pct": "2",
        "simplified_pct": "3",
        "general_tax_rate_pct": "9",
        "simplified_tax_rate_pct": "3",
        "source": "S5",
        "verified": False,
    },
    # Editions of the bill standard, from core/country_data/item_code_patterns.json.
    # A project stores its own; one that states none takes the newest edition in
    # force on the day it was created.
    "editions": item_code_editions("gb50500"),
    "default_edition_key": "gb50500@2024",
    # The heads a tender total is made of, in order. ``vat_base`` marks the
    # heads the VAT is charged on.
    "estimate_structures": {
        "gb50500@2013": [
            {"key": "fenbu", "label_zh": "分部分项工程费", "vat_base": True},
            {"key": "cuoshi", "label_zh": "措施项目费", "vat_base": True},
            {"key": "qita", "label_zh": "其他项目费", "vat_base": True},
            {"key": "guifei", "label_zh": "规费", "vat_base": True},
            {"key": "shuijin", "label_zh": "税金", "vat_base": False},
        ],
        "gb50500@2024": [
            {"key": "fenbu", "label_zh": "分部分项工程项目清单", "vat_base": True},
            {"key": "cuoshi", "label_zh": "措施项目清单", "vat_base": True},
            {"key": "qita", "label_zh": "其他项目清单", "vat_base": True},
            {"key": "zengzhishui", "label_zh": "增值税", "vat_base": False},
        ],
    },
    # Kinds of line inside 其他项目. Only the specialist prime-cost sum is
    # priced VAT-inclusive (S7 2.0.18); the rest are tax-exclusive (S7 3.1.9).
    "other_item_kinds": [
        {"key": "provisional_sum", "label_zh": "暂列金额", "tax_inclusive": False},
        {"key": "daywork", "label_zh": "计日工", "tax_inclusive": False},
        {"key": "main_contractor_service", "label_zh": "总承包服务费", "tax_inclusive": False},
        {"key": "specialist_pc_sum", "label_zh": "专业工程暂估价", "tax_inclusive": True},
    ],
    # Item code patterns per edition live in core/country_data/item_code_patterns.json
    # (one source for the bill rules and this pack); see app.core.item_codes.
    "item_code_scope": "sub_project",
    # Provincial overlays. Only what a source states; the rest stays null and
    # is marked "verify" in the pack README.
    "provinces": {
        "CN-SH": {
            "name_zh": "上海",
            "risk_bands_pct": {"labour": "3", "main_materials": "5", "other": "8"},
            "tender_switch_date": None,
            "source": "S7 4.2.4, 3.3.5",
        },
        "CN-GD": {
            "name_zh": "广东",
            "guifei_folded": True,
            "guifei_split": {"social_insurance": "labour", "other": "management_fee"},
            "tender_switch_date": None,
            "cities": {"Shenzhen": {"name_zh": "深圳", "tender_switch_date": "2026-01-01"}},
            "source": "S8 cl.4; Shenzhen notice 2025-11-07",
        },
    },
    # 数电票 profile (S6). Number = YY + 2-digit bureau + channel digit + 15-digit serial.
    "fapiao": {
        "number_pattern": r"^\d{20}$",
        "special_business_tag": "建筑服务",
        "required_construction_fields": ["site_location", "project_name"],
        "red_letter": {"mechanism": "红字确认单", "confirmation_void_after_hours": 72},
        "unverified_fields": ["cross_region_flag", "land_vat_project_no"],
    },
}
