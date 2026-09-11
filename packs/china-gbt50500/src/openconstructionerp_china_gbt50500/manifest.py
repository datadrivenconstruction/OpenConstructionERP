"""Build the ``PartnerPackManifest`` instance for the china-gbt50500 pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.

Validation this pack switches on:
  * ``gbt50500`` - two rules in the core engine, both over the bill of
    quantities item code. One requires the code to be present on every
    position, the other requires it to be a 9-digit or 12-digit numeric
    national code. That is the whole of what the engine checks.

Two spellings, and they are not interchangeable. ``gbt50500`` is the
engine rule set: it is the rule ids, the ``standard`` attribute on the
two rule classes, the message keys in four locales and the entry in
``validation_rule_sets`` below. ``gb50500`` is the classification
standard: it is what the registry calls the standard, what
``classification_order`` hands to the section path builder, and
therefore the key a cost item's ``classification`` dict has to use. The
demo bills were keyed with the rule set name until 2026-08, which meant
the two rules read them correctly and no Chinese cost item ever produced
a section path. The rules now read either spelling, so a bill stored
before that change still validates.

Reference documents. Seven ``rule_packs/*.json`` files, declared below.
They are read by a person rather than by the engine, and each carries a
``review_status`` saying how far it has been checked. They exist because
the things a Chinese bill does differently are not things a foreign
estimator finds out by looking at one: the comprehensive unit rate
excludes the statutory charges and the tax, the quantity is net and the
waste is priced in the rate, and two of the five bills may not be
discounted in a tender at all.

Standards the demo data is written against. These are reference context
for the reader; no engine rules exist behind them today:
  * GB 50500-2013 - 建设工程工程量清单计价规范 (pricing code for
    construction works). Drives the 9-digit national item codes used in
    the demo BoQ (e.g. 010101001).
  * GB 50854-2013 - 房屋建筑与装饰工程工程量计算规范 (quantity
    calculation code for buildings and decoration works).
  * GB 50010-2010 - 混凝土结构设计规范 (code for design of concrete
    structures).
  * GB 50011-2010 - 建筑抗震设计规范 (code for seismic design of
    buildings).
  * GB 50009-2012 - 建筑结构荷载规范 (load code for building
    structures).
  * GB 50016-2014 - 建筑设计防火规范 (code for fire protection design
    of buildings).
  * GB/T 50378-2019 - 绿色建筑评价标准 (assessment standard for green
    building).

Edition. The pack states GB 50500-2013 because that is the edition the
shipped item codes were authored against and the only one whose text we
have. GB/T 50500-2024 superseded it from 2025-09-01, along with the
GB/T 50854-2024 measurement family; neither text could be obtained, so
the pack does not claim conformance to them. Note the prefix while
reading the two: the 2013 edition is GB, a mandatory code, and the 2024
edition is GB/T, a recommended standard.

Tax model:
  * cn_vat_9 - VAT general tax method (一般计税) at 9% output VAT on
    construction services, shown as a separate cumulative line on top of
    the tax-exclusive direct cost. Enterprise management fee, statutory
    charges (规费), profit and the safe/civilised-construction fee are
    taken on the direct cost per the Shanghai cost build-up.

CWICR regions:
  * Only ``cwicr-zh-shanghai`` is wired in for the demo. Additional
    metros (Beijing / Shenzhen / Guangzhou / Chengdu) are listed in
    ``metadata.preferred_metros`` so the onboarding wizard can pre-fill
    the dropdown when those marketplace entries land.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="china-gbt50500",
    partner_name="China Construction Pack (中国建筑工程包)",
    partner_url=None,
    pack_version="0.1.0",
    description=(
        "Pre-configured for Chinese contractors and developers: Simplified "
        "Chinese and English UI, CNY as the default currency, the VAT "
        "general tax method (9%) as the default tax template, Shanghai cost "
        "data and a Shanghai office-tower demo project. Validation covers "
        "the GB 50500 bill of quantities item code: it has to be present, "
        "and it has to be a 9-digit or 12-digit national code."
    ),
    default_locale="zh",
    # No pack-shipped vocabulary overlay. A zh overlay is wanted for this pack
    # and the file has never been written; the entry used to sit here naming
    # ``locales/zh.json``, so every read of it was a 404. The Chinese UI does
    # not depend on it - ``default_locale`` below resolves against the core zh
    # locale, and this map only ever layers pack-specific wording on top of
    # that. Put the entry back on the day the file lands, not before.
    additional_locales={},
    cwicr_regions=[
        # Only one Chinese CWICR region is wired in for the demo today.
        # Additional metros are recorded in metadata.preferred_metros for
        # the onboarding UI.
        "cwicr-zh-shanghai",
    ],
    default_currency="CNY",
    default_tax_template="cn_vat_9",
    # The regional markup table states the Chinese national build-up, and
    # ``_reconcile_with_region_table`` derives the methodology from it. Naming
    # it here is what makes a project created from this pack open on that
    # build-up rather than on the neutral international one.
    default_methodology="china",
    # Reference documents. These are read by a person, not by the engine: each
    # states what a Chinese bill does and why, and each carries a review_status
    # saying how far it has been checked. Only the first is backed by engine
    # rules today, and it names them in enables_rule_ids.
    validation_rule_packs=[
        "cn_gb50500_qingdan_bianma",  # the twelve-digit item code and the five required elements
        "cn_qingdan_wubu_jiegou",  # the five bills a tender price is made of
        "cn_zonghe_danjia",  # what the comprehensive unit rate contains, and what it does not
        "cn_gb50854_gongchengliang",  # net measurement, and where the waste goes instead
        "cn_guifei_anquanwenming",  # the two fees that may not be discounted
        "cn_zengzhishui_jianzhu",  # VAT: general method 9%, simplified method 3%
        "cn_zhaobiao_jiesuan",  # the bid ceiling, and how the price moves afterwards
    ],
    validation_rule_sets=[
        "gbt50500",  # GB 50500-2013 item code: presence and 9/12-digit format
        #
        # Planned, not built, and deliberately not listed above. Each of
        # these would need rules written in the core engine; none exists
        # there today and this pack ships no reference pack files either:
        # gb50854_quantities (GB 50854-2013 quantity calculation),
        # gb50010_concrete (GB 50010-2010), gb50011_seismic (GB 50011-2010),
        # gb50009_loads (GB 50009-2012), gb50016_fire (GB 50016-2014),
        # gbt50378_green (GB/T 50378-2019) and china_tax_construction
        # (VAT 9% plus statutory charges). Add a slug back on the day its
        # rules land, not before.
    ],
    default_modules=[],  # empty = show all (Shape A - no module hiding)
    hidden_modules=[],
    demo_template_ids=["office-shanghai", "residential-shenzhen", "renovation-guangzhou", "villa-suzhou"],
    branding=PartnerBranding(
        primary_color="#DE2910",  # China red (national flag)
        accent_color="#FFDE00",  # China yellow (national flag stars)
        # This pack ships no logo.svg. The UI draws a monogram in the two
        # colours above, which is the intended look for a pack without one;
        # naming a file that is not here only made the endpoint 404.
        logo_path=None,
        favicon_path=None,
        powered_by_text=None,  # use default co-branding string
    ),
    # Chinese-first, six steps. It asks about the things a workspace configured
    # from a European default gets wrong: the five bills, the two fees that may
    # not be discounted, and which of the two tax methods the contract is on.
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "CN",
        "country_name_en": "China",
        "country_name_zh": "中国",
        "regulator_refs": [
            "GB 50500-2013 (建设工程工程量清单计价规范)",
            "GB 50854-2013 (房屋建筑与装饰工程工程量计算规范)",
            "GB 50010-2010 (混凝土结构设计规范)",
            "GB 50011-2010 (建筑抗震设计规范)",
            "GB 50009-2012 (建筑结构荷载规范)",
            "GB 50016-2014 (建筑设计防火规范)",
            "GB/T 50378-2019 (绿色建筑评价标准)",
            "增值税一般计税方法 9% (VAT general tax method)",
            "规费 (statutory charges)",
        ],
        "support_email": "info@datadrivenconstruction.io",
        # Pre-defined city presets surfaced in the onboarding wizard. The
        # corresponding CWICR regional cost databases arrive in marketplace
        # updates; for now only Shanghai is wired in.
        "preferred_metros": [
            {"city": "Shanghai", "city_zh": "上海", "cwicr_slug": "cwicr-zh-shanghai"},
            {"city": "Beijing", "city_zh": "北京", "cwicr_slug": None},
            {"city": "Shenzhen", "city_zh": "深圳", "cwicr_slug": None},
            {"city": "Guangzhou", "city_zh": "广州", "cwicr_slug": None},
            {"city": "Chengdu", "city_zh": "成都", "cwicr_slug": None},
        ],
        # VAT general tax method output rate for construction services.
        "vat_general_method_rate": 9.0,
        # National item code format used in the BoQ (GB/T 50500): 9 digits.
        "boq_code_format": "GB 50500-2013 9-digit national item code",
    },
)
