"""Build the ``PartnerPackManifest`` instance for the china-gbt50500 pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.

Standards bundled:
  * GB/T 50500-2013 - 建设工程工程量清单计价规范 (Standard Method of
    Measurement / pricing code for construction works). Drives the
    9-digit national item codes used in the demo BoQ (e.g. 010101001).
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
        "Pre-configured for Chinese contractors and developers: GB/T 50500 "
        "Bill of Quantities pricing code, GB 50854 quantity calculation code, "
        "GB-code structural bundle (GB 50010 / 50011 / 50009 / 50016), "
        "GB/T 50378 green building, and the VAT general tax method (9%). "
        "English + Simplified Chinese UI."
    ),
    default_locale="zh",
    additional_locales={
        "zh": "locales/zh.json",
    },
    cwicr_regions=[
        # Only one Chinese CWICR region is wired in for the demo today.
        # Additional metros are recorded in metadata.preferred_metros for
        # the onboarding UI.
        "cwicr-zh-shanghai",
    ],
    default_currency="CNY",
    default_tax_template="cn_vat_9",
    validation_rule_packs=[
        # Bill of Quantities pricing and measurement
        "gbt50500",            # GB/T 50500-2013 BoQ pricing code
        "gb50854_quantities",  # GB 50854-2013 quantity calculation code
        # Structural codes
        "gb50010_concrete",    # GB 50010-2010 concrete structures
        "gb50011_seismic",     # GB 50011-2010 seismic design
        "gb50009_loads",       # GB 50009-2012 structural loads
        # Building / fire code
        "gb50016_fire",        # GB 50016-2014 fire protection design
        # Green building
        "gbt50378_green",      # GB/T 50378-2019 green building assessment
        # Tax & statutory
        "china_tax_construction",  # VAT 9% + statutory charges (规费)
    ],
    default_modules=[],   # empty = show all (Shape A - no module hiding)
    hidden_modules=[],
    demo_template_ids=["office-shanghai"],
    branding=PartnerBranding(
        primary_color="#DE2910",   # China red (national flag)
        accent_color="#FFDE00",    # China yellow (national flag stars)
        logo_path="logo.svg",
        favicon_path=None,
        powered_by_text=None,      # use default co-branding string
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "CN",
        "country_name_en": "China",
        "country_name_zh": "中国",
        "regulator_refs": [
            "GB/T 50500-2013 (建设工程工程量清单计价规范)",
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
        "boq_code_format": "GB/T 50500 9-digit national item code",
    },
)
