# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner-pack demo: 独栋别墅 - 苏州太湖 (Detached Villa, Suzhou Taihu)
# ---------------------------------------------------------------------------
# Bill of Quantities prepared to the Chinese national standard
# GB 50500-2013, the pricing code for bill of quantities valuation of
# construction works.
#
# WHY 2013 AND NOT 2024. GB/T 50500-2024 superseded this edition from
# 2025-09-01, and the 2024 measurement standards GB/T 50854-2024 through
# GB/T 50862-2024 replaced the measurement family on the same date. We
# could not obtain either text, so we cannot state what conformance to
# them requires and this bill does not claim it. The label follows what
# we can verify rather than what is newest, and it moves the day the
# 2024 text is in hand.
#
# This bill covers a luxury detached villa with landscaped garden near
# Taihu Lake, Suzhou. The scope includes earthworks, reinforced-concrete
# frame, high-end interior fit-out, full MEP, swimming pool, and garden
# landscaping. Comprehensive unit rates are Suzhou 2026 market prices.
#
# Descriptions are bilingual (Chinese + English). No em-dashes anywhere;
# plain ASCII hyphens only.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="villa-suzhou",
    project_name="独栋别墅 - 苏州太湖 (Detached Villa, Suzhou Taihu)",
    project_description=(
        "新建独栋别墅，位于苏州太湖新城滨湖区域，地上 3 层、地下 1 层（含车库）。"
        "总建筑面积约 1,280 平方米（地上约 920 平方米，地下约 360 平方米），"
        "含室内恒温泳池、独立庭院约 2,800 平方米。钢筋混凝土框架结构，"
        "外墙石材干挂与铝板幕墙，全屋地暖、中央空调、新风系统。"
        "室内精装修标准为高端住宅级，天然石材及实木饰面。"
        "抗震设防烈度 6 度（GB 50011-2010）。"
        "造价按苏州 2026 年价格水平、GB 50500-2013 计价规范编制，"
        "建安工程费约人民币 2,580 万元。 "
        "New-build luxury detached villa near Taihu Lake, Suzhou Lakefront "
        "New Town. 3 storeys above grade plus 1 basement level (incl. garage). "
        "Gross floor area approx. 1,280 m2 (approx. 920 m2 above grade, "
        "360 m2 below), with indoor heated pool and landscaped garden of "
        "approx. 2,800 m2. Reinforced-concrete frame; dry-hung stone and "
        "aluminium-panel facade; underfloor heating, central A/C and "
        "mechanical ventilation throughout. Interior fit-out to luxury "
        "residential standard with natural stone and solid timber finishes. "
        "Seismic design intensity 6 to GB 50011-2010. "
        "Priced at Suzhou 2026 levels on GB 50500-2013. "
        "Construction cost approx. CNY 25.8 million."
    ),
    region="CN",
    classification_standard="gb50500",
    currency="CNY",
    locale="zh",
    address={
        "street": "太湖大道 1288 号 (1288 Taihu Boulevard)",
        "city": "苏州 (Suzhou)",
        "postcode": "215164",
        "country": "China",
        "lat": 31.2580,
        "lng": 120.5850,
    },
    validation_rule_sets=["gbt50500", "boq_quality", "project_completeness"],
    boq_name="工程量清单 - GB 50500-2013 (Bill of Quantities - Villa)",
    boq_description=(
        "按 GB 50500-2013《建设工程工程量清单计价规范》编制的独栋别墅工程量清单，"
        "综合单价含人工、材料、机械、管理费及利润，苏州 2026 年价。 "
        "Bill of Quantities to GB 50500-2013 for a detached villa; "
        "comprehensive unit rates include labour, materials, plant, "
        "overheads and profit, Suzhou 2026 price level."
    ),
    boq_metadata={
        "standard": "GB 50500-2013",
        "phase": "施工图预算 (Construction drawing budget)",
        "base_date": "2026-Q1",
        "price_level": "苏州 2026 (Suzhou 2026)",
    },
    sections=[
        # -- 0101 土石方工程 (Earthworks) -----------------------------------
        (
            "0101",
            "土石方工程 (Earthworks)",
            {"gb50500": "0101"},
            [
                ("0101.1", "平整场地 (Site clearance and grading)", "m2", 4200, 8.50, {"gb50500": "010101001"}),
                ("0101.2", "挖基坑土方，地下一层 (Pit excavation, 1 basement)", "m3", 2800, 32.00, {"gb50500": "010101004"}),
                ("0101.3", "土方外运，运距 10km 内 (Soil haulage and disposal, within 10 km)", "m3", 2200, 35.00, {"gb50500": "010103002"}),
                ("0101.4", "基坑回填土，分层夯实 (Backfill, layered and compacted)", "m3", 1200, 28.00, {"gb50500": "010103001"}),
                ("0101.5", "室内回填级配碎石 (Graded crushed-stone fill under floors)", "m3", 480, 85.00, {"gb50500": "010103001"}),
                ("0101.6", "泳池基坑开挖及回填 (Pool excavation and backfill)", "m3", 320, 42.00, {"gb50500": "010101004"}),
            ],
        ),
        # -- 0102 地基处理与桩基工程 (Foundation treatment) ------------------
        (
            "0102",
            "地基处理与桩基工程 (Foundation treatment and piling)",
            {"gb50500": "0102"},
            [
                ("0102.1", "预应力管桩 PHC AB400-95 (PHC pile AB400-95)", "m", 2400, 165.00, {"gb50500": "010301001"}),
                ("0102.2", "接桩焊接 (Pile welding splice)", "个", 48, 280.00, {"gb50500": "010301002"}),
                ("0102.3", "试桩及静载试验 (Test pile and static load test)", "组", 3, 28000.00, {"gb50500": "010302007"}),
                ("0102.4", "截桩头 (Pile head trimming)", "根", 48, 320.00, {"gb50500": "010301004"}),
            ],
        ),
        # -- 0103 混凝土及钢筋混凝土工程 (Cast-in-situ RC) ------------------
        (
            "0103",
            "混凝土及钢筋混凝土工程 (Cast-in-situ reinforced concrete)",
            {"gb50500": "0103"},
            [
                ("0103.1", "垫层混凝土 C15 (Blinding concrete C15)", "m3", 120, 480.00, {"gb50500": "010401001"}),
                ("0103.2", "筏板基础混凝土 C35 抗渗 P6 (Raft foundation C35, P6)", "m3", 380, 620.00, {"gb50500": "010501004"}),
                ("0103.3", "框架柱混凝土 C40 (Frame column concrete C40)", "m3", 185, 680.00, {"gb50500": "010502001"}),
                ("0103.4", "框架梁混凝土 C35 (Frame beam concrete C35)", "m3", 220, 650.00, {"gb50500": "010503002"}),
                ("0103.5", "现浇楼板混凝土 C30 (Suspended slab concrete C30)", "m3", 320, 620.00, {"gb50500": "010505001"}),
                ("0103.6", "楼梯混凝土 C30 (Staircase concrete C30)", "m3", 42, 880.00, {"gb50500": "010506001"}),
                ("0103.7", "地下室外墙混凝土 C35 抗渗 P6 (Basement wall C35, P6)", "m3", 165, 680.00, {"gb50500": "010504001"}),
                ("0103.8", "泳池池壁混凝土 C35 抗渗 P8 (Pool wall C35, P8)", "m3", 48, 750.00, {"gb50500": "010504001"}),
                ("0103.9", "钢筋 HRB400 (Reinforcement HRB400)", "t", 185, 5650.00, {"gb50500": "010515001"}),
                ("0103.10", "模板工程 (Formwork)", "m2", 6200, 58.00, {"gb50500": "011702011"}),
            ],
        ),
        # -- 0104 砌筑工程 (Masonry) ----------------------------------------
        (
            "0104",
            "砌筑工程 (Masonry)",
            {"gb50500": "0104"},
            [
                ("0104.1", "蒸压加气混凝土砌块墙 200mm (AAC block wall 200 mm)", "m3", 320, 480.00, {"gb50500": "010402001"}),
                ("0104.2", "蒸压加气混凝土砌块墙 100mm 隔墙 (AAC block partition 100 mm)", "m2", 580, 92.00, {"gb50500": "010402001"}),
                ("0104.3", "构造柱及过梁混凝土 (Constructional columns and lintels)", "m3", 28, 920.00, {"gb50500": "010507001"}),
                ("0104.4", "砌体拉结筋 (Masonry tie bars)", "t", 3.2, 6200.00, {"gb50500": "010515003"}),
            ],
        ),
        # -- 0105 屋面及防水工程 (Roofing and waterproofing) -----------------
        (
            "0105",
            "屋面及防水工程 (Roofing and waterproofing)",
            {"gb50500": "0105"},
            [
                ("0105.1", "坡屋面水泥彩瓦 (Pitched roof, cement colour tiles)", "m2", 520, 185.00, {"gb50500": "010901001"}),
                ("0105.2", "屋面 SBS 改性沥青卷材防水 (SBS membrane waterproofing)", "m2", 520, 85.00, {"gb50500": "010902001"}),
                ("0105.3", "屋面挤塑板保温 80mm (Roof XPS insulation 80 mm)", "m2", 520, 55.00, {"gb50500": "011001001"}),
                ("0105.4", "地下室底板及侧墙卷材防水 (Basement raft/wall membrane waterproofing)", "m2", 1850, 78.00, {"gb50500": "010903001"}),
                ("0105.5", "卫生间聚氨酯防水 (PU waterproofing, bathrooms)", "m2", 280, 62.00, {"gb50500": "010904001"}),
                ("0105.6", "泳池防水及马赛克饰面 (Pool waterproofing and mosaic finish)", "m2", 320, 480.00, {"gb50500": "010904002"}),
                ("0105.7", "天沟及落水管，铜质 (Copper gutter and downpipes)", "m", 120, 520.00, {"gb50500": "010901004"}),
            ],
        ),
        # -- 0106 门窗工程 (Doors and windows) -------------------------------
        (
            "0106",
            "门窗工程 (Doors and windows)",
            {"gb50500": "0106"},
            [
                ("0106.1", "实木入户门，防盗 (Solid timber entrance door, security)", "樘", 2, 28000.00, {"gb50500": "010801001"}),
                ("0106.2", "实木室内门含五金 (Solid timber internal door with hardware)", "樘", 32, 5800.00, {"gb50500": "010801001"}),
                ("0106.3", "铝合金断桥隔热中空 Low-E 窗 (Aluminium thermal-break DGU Low-E window)", "m2", 280, 850.00, {"gb50500": "010807001"}),
                ("0106.4", "铝合金折叠门，客厅通庭院 (Aluminium folding door, living to garden)", "m2", 28, 1850.00, {"gb50500": "010807001"}),
                ("0106.5", "钢质防火门乙级，车库 (Steel fire door Class B, garage)", "樘", 2, 2280.00, {"gb50500": "010802003"}),
                ("0106.6", "天窗，电动开启 (Rooflight, motorised opening)", "樘", 4, 12000.00, {"gb50500": "010805001"}),
                ("0106.7", "实木楼梯栏杆 (Solid timber stair balustrade)", "m", 38, 1850.00, {"gb50500": "010901005"}),
            ],
        ),
        # -- 0107 楼地面装饰工程 (Floor finishes) ----------------------------
        (
            "0107",
            "楼地面装饰工程 (Floor finishes)",
            {"gb50500": "0107"},
            [
                ("0107.1", "天然大理石地面，客厅及门厅 (Natural marble floor, living and entrance)", "m2", 280, 850.00, {"gb50500": "011102001"}),
                ("0107.2", "实木地板，卧室 (Solid timber floor, bedrooms)", "m2", 320, 520.00, {"gb50500": "011103001"}),
                ("0107.3", "瓷砖地面，厨房及卫生间 (Tile floor, kitchen and bathrooms)", "m2", 180, 185.00, {"gb50500": "011102003"}),
                ("0107.4", "花岗岩地面，车库 (Granite floor, garage)", "m2", 120, 280.00, {"gb50500": "011102001"}),
                ("0107.5", "地下室环氧地坪 (Epoxy floor, basement)", "m2", 240, 95.00, {"gb50500": "011101006"}),
                ("0107.6", "水泥砂浆找平层 (Cement-mortar levelling screed)", "m2", 1280, 32.00, {"gb50500": "011101001"}),
                ("0107.7", "石材踢脚线 (Stone skirting)", "m", 680, 62.00, {"gb50500": "011105002"}),
                ("0107.8", "室外花岗岩台阶及坡道 (External granite steps and ramp)", "m2", 85, 380.00, {"gb50500": "011102001"}),
            ],
        ),
        # -- 0108 墙柱面及天棚装饰工程 (Wall and ceiling finishes) -----------
        (
            "0108",
            "墙柱面及天棚装饰工程 (Wall, column and ceiling finishes)",
            {"gb50500": "0108"},
            [
                ("0108.1", "内墙抹灰 (Internal plaster)", "m2", 3200, 38.00, {"gb50500": "011201001"}),
                ("0108.2", "内墙乳胶漆含腻子 (Internal emulsion paint, incl. putty)", "m2", 2800, 32.00, {"gb50500": "011406001"}),
                ("0108.3", "墙面瓷砖，厨卫 (Wall tiles, kitchen and bathrooms)", "m2", 480, 165.00, {"gb50500": "011204004"}),
                ("0108.4", "护墙板，实木 (Timber wall panelling)", "m2", 380, 850.00, {"gb50500": "011204001"}),
                ("0108.5", "背景墙石材，客厅 (Feature stone wall, living room)", "m2", 42, 1200.00, {"gb50500": "011204003"}),
                ("0108.6", "石膏板吊顶含造型 (Plasterboard ceiling with profiles)", "m2", 920, 145.00, {"gb50500": "011302001"}),
                ("0108.7", "实木格栅天花 (Timber-batten ceiling)", "m2", 120, 580.00, {"gb50500": "011302003"}),
                ("0108.8", "外墙石材干挂 (External dry-hung stone cladding)", "m2", 680, 850.00, {"gb50500": "011209003"}),
                ("0108.9", "外墙铝板幕墙 (External aluminium-panel facade)", "m2", 280, 920.00, {"gb50500": "011209002"}),
                ("0108.10", "外墙保温岩棉板 80mm (External rock-wool insulation 80 mm)", "m2", 960, 85.00, {"gb50500": "011001002"}),
            ],
        ),
        # -- 0109 给排水工程 (Plumbing) --------------------------------------
        (
            "0109",
            "给排水工程 (Plumbing)",
            {"gb50500": "0109"},
            [
                ("0109.1", "给水管 PPR (Water supply pipe, PPR)", "m", 580, 62.00, {"gb50500": "030101001"}),
                ("0109.2", "热水管 PPR 保温 (Hot water pipe, PPR insulated)", "m", 320, 85.00, {"gb50500": "030101002"}),
                ("0109.3", "排水管 HDPE (Drainage pipe, HDPE)", "m", 420, 78.00, {"gb50500": "030102001"}),
                ("0109.4", "卫生洁具，高端品牌 (Sanitary fittings, premium)", "套", 18, 8500.00, {"gb50500": "030104001"}),
                ("0109.5", "泳池循环过滤设备 (Pool circulation and filtration)", "项", 1, 185000.00, {"gb50500": "030106001"}),
                ("0109.6", "泳池加热及恒温系统 (Pool heating and temperature control)", "项", 1, 120000.00, {"gb50500": "030106001"}),
                ("0109.7", "雨水收集利用系统 (Rainwater harvesting system)", "项", 1, 85000.00, {"gb50500": "030102003"}),
            ],
        ),
        # -- 0110 暖通空调工程 (HVAC) ----------------------------------------
        (
            "0110",
            "暖通空调工程 (HVAC installation)",
            {"gb50500": "0110"},
            [
                ("0110.1", "地源热泵机组 (Ground-source heat pump unit)", "台", 1, 280000.00, {"gb50500": "030202002"}),
                ("0110.2", "室内风机盘管 (Indoor fan-coil units)", "台", 24, 4800.00, {"gb50500": "030201004"}),
                ("0110.3", "全热交换新风机组 (ERV fresh-air unit)", "台", 4, 28000.00, {"gb50500": "030201002"}),
                ("0110.4", "地暖盘管 PE-RT (Underfloor heating PE-RT coils)", "m2", 920, 95.00, {"gb50500": "030203002"}),
                ("0110.5", "地源热泵地埋管 (GSHP ground loop)", "m", 2400, 85.00, {"gb50500": "030202002"}),
                ("0110.6", "铜管连接及保温 (Copper pipe connections and insulation)", "m", 480, 165.00, {"gb50500": "030203001"}),
                ("0110.7", "除湿机，泳池区 (Dehumidifier, pool area)", "台", 1, 42000.00, {"gb50500": "030201005"}),
            ],
        ),
        # -- 0111 电气工程 (Electrical) --------------------------------------
        (
            "0111",
            "电气工程 (Electrical installation)",
            {"gb50500": "0111"},
            [
                ("0111.1", "配电箱及断路器 (Distribution boards and MCBs)", "项", 1, 85000.00, {"gb50500": "030404017"}),
                ("0111.2", "电力电缆 YJV (Power cable, YJV)", "m", 3200, 65.00, {"gb50500": "030408001"}),
                ("0111.3", "管内穿线 (Conduit wiring)", "m", 8500, 12.50, {"gb50500": "030411004"}),
                ("0111.4", "LED 灯具及装饰灯 (LED and decorative luminaires)", "套", 280, 1850.00, {"gb50500": "030412001"}),
                ("0111.5", "户外庭院照明 (Outdoor garden lighting)", "套", 42, 2800.00, {"gb50500": "030412003"}),
                ("0111.6", "智能家居系统 (Smart home system)", "项", 1, 320000.00, {"gb50500": "030705003"}),
                ("0111.7", "安防监控系统 (Security CCTV system)", "项", 1, 85000.00, {"gb50500": "030701001"}),
                ("0111.8", "光伏发电系统 15kW (PV power system 15 kW)", "项", 1, 120000.00, {"gb50500": "030409002"}),
            ],
        ),
        # -- 0112 室外景观工程 (Landscaping) ---------------------------------
        (
            "0112",
            "室外景观工程 (Landscaping and external works)",
            {"gb50500": "0112"},
            [
                ("0112.1", "庭院花岗岩铺装 (Garden granite paving)", "m2", 680, 285.00, {"gb50500": "040101001"}),
                ("0112.2", "景观石材花池 (Landscape stone planters)", "m", 120, 420.00, {"gb50500": "040102001"}),
                ("0112.3", "乔木种植 (Tree planting)", "株", 45, 2800.00, {"gb50500": "040201001"}),
                ("0112.4", "灌木及地被 (Shrubs and ground cover)", "m2", 1200, 85.00, {"gb50500": "040202001"}),
                ("0112.5", "草坪铺设 (Turf laying)", "m2", 800, 28.00, {"gb50500": "040203001"}),
                ("0112.6", "景观水池及喷泉 (Feature pond and fountain)", "项", 1, 185000.00, {"gb50500": "040301001"}),
                ("0112.7", "围墙及院门 (Boundary wall and gate)", "m", 180, 1850.00, {"gb50500": "040401001"}),
                ("0112.8", "室外给排水管道 (External water supply and drainage)", "m", 280, 95.00, {"gb50500": "030102004"}),
                ("0112.9", "室外照明及景观灯 (External lighting and landscape lights)", "套", 28, 3200.00, {"gb50500": "030412003"}),
            ],
        ),
    ],
    markups=[
        ("企业管理费 (Enterprise management fee)", 5.0, "overhead", "direct_cost"),
        ("规费 - 社会保险及公积金 (Statutory charges - social insurance and housing fund)", 7.8, "statutory", "direct_cost"),
        ("利润 (Profit)", 5.0, "profit", "direct_cost"),
        ("安全文明施工费 (Safe and civilised construction fee)", 3.5, "safety", "direct_cost"),
        ("增值税 (VAT, general method 9%)", 9.0, "tax", "cumulative"),
    ],
    total_months=18,
    tender_name="独栋别墅 - 苏州太湖 (Villa construction tender, Suzhou Taihu)",
    tender_companies=[
        ("苏州园林建设集团 (Suzhou Garden Construction Group)", "tender@suzhouyuanlin.example", 0.97),
        ("南通四建集团 (Nantong No.4 Construction Group)", "bids@nt4jian.example", 1.03),
        ("江苏龙信建设集团 (Jiangsu Longxin Construction Group)", "tender@longxin.example", 1.01),
    ],
    budget_boq_name="别墅施工图预算 (Villa construction budget)",
    planned_budget=25_800_000.0,
    actual_spend_ratio=0.52,
    spi_override=1.02,
    cpi_override=0.98,
    project_metadata={
        "project_type": "独栋别墅 / Detached Villa",
        "gfa_m2": 1280,
        "garden_m2": 2800,
        "storeys": "地上 3 层，地下 1 层 (3 above grade, 1 basement)",
        "structure_system": "钢筋混凝土框架 (RC frame)",
        "pool": "室内恒温泳池 12m x 5m (Indoor heated pool 12 m x 5 m)",
        "seismic_design": "抗震设防烈度 6 度 (GB 50011-2010, intensity 6)",
        "energy_system": "地源热泵 + 光伏 15kW (GSHP + PV 15 kW)",
        "design_codes": (
            "GB 50010 (混凝土结构), GB 50011 (抗震), GB 50009 (荷载), "
            "GB 50016 (建筑防火), JGJ 26 (居住建筑节能)"
        ),
        "pricing_standard": "GB 50500-2013《建设工程工程量清单计价规范》",
        "measurement_standard": "GB 50854-2013《房屋建筑与装饰工程工程量计算规范》",
        "sustainability": "被动式低能耗住宅 + 海绵城市措施 (Passive house + sponge city)",
        "tax_note": (
            "清单综合单价为不含税直接费；增值税按一般计税方法 9% 单列。 "
            "BoQ comprehensive unit rates are tax-exclusive direct cost; VAT "
            "at 9% (general tax method) is shown as a separate line."
        ),
        "headline_cost_cny": "约人民币 2,580 万元 (approx. CNY 25.8 million)",
    },
)
