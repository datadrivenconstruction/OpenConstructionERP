from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner-pack demo: 商务办公楼 - 上海陆家嘴 (Office Tower, Shanghai Lujiazui)
# ---------------------------------------------------------------------------
# 工程量清单按中国国家标准 GB/T 50500-2013《建设工程工程量清单计价规范》编制，
# 采用九位国标项目编码（例如 010101001）。综合单价为上海 2026 年市场价（CNY），
# 适用上海陆家嘴金融贸易区一栋甲级写字楼。各分部分项工程项目编码记录在
# classification 字典中（键名 "gbt50500"）。
#
# Bill of Quantities prepared to the Chinese national standard
# GB/T 50500-2013 (Standard Method of Measurement / pricing code for
# construction works), using the 9-digit national item codes (e.g.
# 010101001). Comprehensive unit rates are Shanghai 2026 market prices
# in CNY for a Grade A office tower in the Lujiazui Financial District.
# Each item carries its GB/T 50500 project code in the classification
# dict under the key "gbt50500". Descriptions are bilingual (Chinese +
# English). No em-dashes anywhere; plain ASCII hyphens only.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="office-shanghai",
    project_name="商务办公楼 - 上海陆家嘴 (Office Tower, Shanghai Lujiazui)",
    project_description=(
        "新建一栋甲级商务办公楼，地上 32 层、地下 3 层，建筑高度约 148 米，"
        "总建筑面积约 86,000 平方米（地上约 68,000 平方米，地下约 18,000 平方米）。"
        "钢筋混凝土核心筒 + 钢管混凝土框架结构，幕墙采用单元式中空 Low-E 玻璃。"
        "抗震设防烈度 7 度，按 GB 50011-2010 设计。绿色建筑三星级（GB/T 50378），"
        "LEED 金级目标。造价按上海 2026 年价格水平、GB/T 50500-2013 计价规范编制，"
        "工程总造价约人民币 18 亿元。 "
        "New-build Grade A office tower, 32 storeys above grade plus 3 "
        "basement levels, building height approx. 148 m. Gross floor area "
        "approx. 86,000 m2 (approx. 68,000 m2 above grade, 18,000 m2 below). "
        "Reinforced-concrete core wall with concrete-filled steel-tube (CFST) "
        "frame; unitised double-glazed Low-E curtain wall. Seismic design "
        "intensity 7 to GB 50011-2010. Three-star Green Building (GB/T 50378), "
        "LEED Gold target. Priced at Shanghai 2026 levels on GB/T 50500-2013. "
        "Headline construction cost approx. CNY 1.8 billion."
    ),
    region="CN",
    classification_standard="gbt50500",
    currency="CNY",
    locale="zh",
    address={
        "street": "陆家嘴环路 1000 号 (1000 Lujiazui Ring Road)",
        "city": "上海 (Shanghai)",
        "postcode": "200120",
        "country": "China",
        "lat": 31.2336,
        "lng": 121.5055,
    },
    validation_rule_sets=["gbt50500", "boq_quality", "project_completeness"],
    boq_name="工程量清单 - GB/T 50500-2013 (Bill of Quantities)",
    boq_description=(
        "按 GB/T 50500-2013《建设工程工程量清单计价规范》编制的分部分项工程量清单，"
        "综合单价含人工、材料、机械、管理费及利润，上海 2026 年价。 "
        "Bill of Quantities to GB/T 50500-2013; comprehensive unit rates "
        "include labour, materials, plant, overheads and profit, Shanghai "
        "2026 price level."
    ),
    boq_metadata={
        "standard": "GB/T 50500-2013",
        "phase": "施工图预算 / 招标工程量清单 (Tender BoQ)",
        "base_date": "2026-Q1",
        "price_level": "上海 2026 (Shanghai 2026)",
    },
    sections=[
        # ── 0101 土石方工程 (Earthworks) ──────────────────────────────
        (
            "0101",
            "土石方工程 (Earthworks)",
            {"gbt50500": "0101"},
            [
                ("0101.1", "平整场地 (Site clearance and grading)", "m2", 4200, 8.50, {"gbt50500": "010101001"}),
                ("0101.2", "挖一般土方，机械开挖 (General excavation, machine)", "m3", 162000, 28.00, {"gbt50500": "010101002"}),
                ("0101.3", "挖基坑土方，深基坑三层地下室 (Deep pit excavation, 3 basements)", "m3", 58000, 42.00, {"gbt50500": "010101004"}),
                ("0101.4", "土方外运，运距 10km 内 (Soil haulage and disposal, within 10 km)", "m3", 195000, 35.00, {"gbt50500": "010103002"}),
                ("0101.5", "基坑回填土，分层夯实 (Backfill, layered and compacted)", "m3", 26000, 32.00, {"gbt50500": "010103001"}),
                ("0101.6", "室内回填级配砂石 (Graded sand-gravel fill under floors)", "m3", 8200, 95.00, {"gbt50500": "010103001"}),
                ("0101.7", "基坑降水井点 (Wellpoint dewatering of pit)", "项", 1, 2850000.00, {"gbt50500": "010103004"}),
                ("0101.8", "岩土工程勘察与地质报告 (Geotechnical investigation report)", "项", 1, 680000.00, {"gbt50500": "010101001"}),
            ],
        ),
        # ── 0103 桩基工程 (Piling) ────────────────────────────────────
        (
            "0103",
            "桩基工程 (Piling and foundations)",
            {"gbt50500": "0103"},
            [
                ("0103.1", "钻孔灌注桩 D=1000mm，C40 水下混凝土 (Bored cast-in-situ pile D1000, C40)", "m", 18600, 1850.00, {"gbt50500": "010302001"}),
                ("0103.2", "钻孔灌注桩 D=800mm (Bored cast-in-situ pile D800)", "m", 9200, 1280.00, {"gbt50500": "010302001"}),
                ("0103.3", "桩基钢筋笼制作安装 HRB400 (Pile cage reinforcement HRB400)", "t", 1450, 6850.00, {"gbt50500": "010302001"}),
                ("0103.4", "灌注桩泥浆护壁与外运 (Slurry wall support and disposal)", "m3", 22000, 65.00, {"gbt50500": "010302001"}),
                ("0103.5", "截桩头 (Pile head trimming)", "根", 320, 480.00, {"gbt50500": "010301004"}),
                ("0103.6", "单桩竖向抗压静载试验 (Static load test of pile)", "组", 12, 38500.00, {"gbt50500": "010302007"}),
                ("0103.7", "地下连续墙 800mm 厚 (Diaphragm wall 800 mm thick)", "m2", 12800, 1650.00, {"gbt50500": "010201007"}),
                ("0103.8", "三轴搅拌桩止水帷幕 (Triaxial mixing-pile water cutoff)", "m3", 14500, 420.00, {"gbt50500": "010201013"}),
            ],
        ),
        # ── 0104 混凝土及钢筋混凝土工程 (Cast-in-situ RC) ─────────────
        (
            "0104",
            "混凝土及钢筋混凝土工程 (Cast-in-situ reinforced concrete)",
            {"gbt50500": "0104"},
            [
                ("0104.1", "垫层混凝土 C15 (Blinding concrete C15)", "m3", 1850, 520.00, {"gbt50500": "010401001"}),
                ("0104.2", "筏板基础混凝土 C40 抗渗 P8 (Raft foundation C40, P8)", "m3", 22000, 685.00, {"gbt50500": "010501004"}),
                ("0104.3", "核心筒剪力墙混凝土 C60 (Core-wall shear-wall concrete C60)", "m3", 18500, 820.00, {"gbt50500": "010504001"}),
                ("0104.4", "钢管混凝土柱 C60 (CFST column concrete C60)", "m3", 6200, 880.00, {"gbt50500": "010502001"}),
                ("0104.5", "框架梁混凝土 C40 (Frame beam concrete C40)", "m3", 14800, 720.00, {"gbt50500": "010503002"}),
                ("0104.6", "现浇楼板混凝土 C35 (Suspended slab concrete C35)", "m3", 26500, 680.00, {"gbt50500": "010505001"}),
                ("0104.7", "楼梯混凝土 C30 (Staircase concrete C30)", "m3", 880, 920.00, {"gbt50500": "010506001"}),
                ("0104.8", "地下室外墙混凝土 C40 抗渗 P8 (Basement RC wall C40, P8)", "m3", 9600, 760.00, {"gbt50500": "010504001"}),
                ("0104.9", "现浇构件钢筋 HRB400 (Reinforcement HRB400, in-situ)", "t", 24800, 5950.00, {"gbt50500": "010515001"}),
                ("0104.10", "现浇构件钢筋 HRB500 大直径 (Reinforcement HRB500, large dia.)", "t", 6800, 6280.00, {"gbt50500": "010515001"}),
                ("0104.11", "墙柱模板，钢框胶合板 (Wall/column formwork, steel-framed ply)", "m2", 142000, 68.00, {"gbt50500": "011702011"}),
                ("0104.12", "梁板模板，高大支模 (Beam/slab formwork, high shoring)", "m2", 198000, 75.00, {"gbt50500": "011702014"}),
                ("0104.13", "混凝土泵送及养护 (Concrete pumping and curing)", "m3", 92000, 38.00, {"gbt50500": "010515001"}),
                ("0104.14", "后浇带及微膨胀混凝土 (Post-cast strip, expansive concrete)", "m3", 1200, 1150.00, {"gbt50500": "010508001"}),
            ],
        ),
        # ── 0105 砌筑工程 (Masonry) ───────────────────────────────────
        (
            "0105",
            "砌筑工程 (Masonry)",
            {"gbt50500": "0105"},
            [
                ("0105.1", "蒸压加气混凝土砌块墙 200mm (AAC block wall 200 mm)", "m3", 9800, 480.00, {"gbt50500": "010402001"}),
                ("0105.2", "蒸压加气混凝土砌块墙 100mm 隔墙 (AAC block partition 100 mm)", "m2", 18500, 92.00, {"gbt50500": "010402001"}),
                ("0105.3", "烧结页岩砖墙，地下室及设备间 (Fired shale brick wall, basement/plant)", "m3", 2400, 620.00, {"gbt50500": "010401003"}),
                ("0105.4", "砌体加固钢筋及拉结筋 (Masonry tie bars and reinforcement)", "t", 96, 6450.00, {"gbt50500": "010515003"}),
                ("0105.5", "构造柱、过梁、圈梁混凝土 (Constructional columns, lintels, ring beams)", "m3", 1850, 880.00, {"gbt50500": "010507001"}),
                ("0105.6", "填充墙顶斜砌及塞缝 (Infill wall top wedging and grouting)", "m", 12800, 22.00, {"gbt50500": "010402001"}),
            ],
        ),
        # ── 0108 门窗工程 (Doors and windows) ─────────────────────────
        (
            "0108",
            "门窗工程 (Doors and windows)",
            {"gbt50500": "0108"},
            [
                ("0108.1", "木质夹板门，含五金 (Timber flush door with hardware)", "樘", 1850, 1450.00, {"gbt50500": "010801001"}),
                ("0108.2", "钢质防火门，甲级 (Steel fire door, Class A)", "樘", 420, 2850.00, {"gbt50500": "010802003"}),
                ("0108.3", "钢质防火门，乙级 (Steel fire door, Class B)", "樘", 680, 2280.00, {"gbt50500": "010802003"}),
                ("0108.4", "电动伸缩门及车库卷帘门 (Motorised gate and garage roller shutter)", "樘", 8, 28500.00, {"gbt50500": "010803001"}),
                ("0108.5", "玻璃感应自动门，大堂入口 (Glass automatic door, lobby entrance)", "樘", 12, 38500.00, {"gbt50500": "010805002"}),
                ("0108.6", "铝合金内门连窗，办公隔间 (Aluminium internal door/screen, offices)", "m2", 2200, 720.00, {"gbt50500": "010807001"}),
                ("0108.7", "防火卷帘门，电动 (Fire-rated roller shutter, motorised)", "m2", 480, 1280.00, {"gbt50500": "010803001"}),
            ],
        ),
        # ── 0109 屋面及防水工程 (Roofing and waterproofing) ───────────
        (
            "0109",
            "屋面及防水工程 (Roofing and waterproofing)",
            {"gbt50500": "0109"},
            [
                ("0109.1", "屋面 SBS 改性沥青卷材防水，双层 (SBS membrane roof waterproofing, 2-ply)", "m2", 3200, 88.00, {"gbt50500": "010902001"}),
                ("0109.2", "屋面挤塑聚苯板保温 100mm (Roof XPS insulation 100 mm)", "m2", 3200, 65.00, {"gbt50500": "011001001"}),
                ("0109.3", "屋面细石混凝土保护层 40mm (Roof fine-aggregate concrete topping 40 mm)", "m2", 3200, 42.00, {"gbt50500": "010902004"}),
                ("0109.4", "地下室底板及侧墙卷材防水 (Basement raft/wall membrane waterproofing)", "m2", 28500, 78.00, {"gbt50500": "010903001"}),
                ("0109.5", "卫生间及设备房聚氨酯防水涂膜 (PU coating waterproofing, toilets/plant)", "m2", 8600, 58.00, {"gbt50500": "010904001"}),
                ("0109.6", "种植屋面排（蓄）水板及覆土 (Green-roof drainage board and soil)", "m2", 1200, 165.00, {"gbt50500": "010902007"}),
                ("0109.7", "金属屋面镀铝锌板，设备层 (Metal roof Al-Zn sheet, plant level)", "m2", 680, 285.00, {"gbt50500": "010901003"}),
            ],
        ),
        # ── 0111 楼地面装饰工程 (Floor finishes) ──────────────────────
        (
            "0111",
            "楼地面装饰工程 (Floor finishes)",
            {"gbt50500": "0111"},
            [
                ("0111.1", "水泥砂浆找平层 (Cement-mortar levelling screed)", "m2", 62000, 32.00, {"gbt50500": "011101001"}),
                ("0111.2", "防静电架空地板，机房 (Raised access floor, server rooms)", "m2", 1800, 480.00, {"gbt50500": "011104002"}),
                ("0111.3", "石材地面，大堂及电梯厅 (Stone flooring, lobby and lift halls)", "m2", 4200, 685.00, {"gbt50500": "011102001"}),
                ("0111.4", "地砖地面，公共走道及卫生间 (Tile flooring, corridors and toilets)", "m2", 12800, 165.00, {"gbt50500": "011102003"}),
                ("0111.5", "块毯地面，办公区 (Carpet-tile flooring, office areas)", "m2", 38000, 145.00, {"gbt50500": "011104001"}),
                ("0111.6", "环氧自流平地面，车库及设备房 (Epoxy self-levelling floor, garage/plant)", "m2", 16500, 95.00, {"gbt50500": "011101006"}),
                ("0111.7", "石材踢脚线 (Stone skirting)", "m", 8600, 58.00, {"gbt50500": "011105002"}),
                ("0111.8", "金刚砂耐磨地坪，卸货区 (Emery hardener floor, loading dock)", "m2", 2200, 68.00, {"gbt50500": "011101006"}),
            ],
        ),
        # ── 0112 墙柱面及天棚装饰工程 (Plaster and wall finishes) ─────
        (
            "0112",
            "墙柱面及天棚装饰工程 (Plaster, wall and ceiling finishes)",
            {"gbt50500": "0112"},
            [
                ("0112.1", "内墙水泥砂浆抹灰 (Internal cement-mortar plaster)", "m2", 142000, 38.00, {"gbt50500": "011201001"}),
                ("0112.2", "外墙抹灰，幕墙背衬部位 (External plaster, behind curtain wall)", "m2", 8600, 52.00, {"gbt50500": "011201001"}),
                ("0112.3", "内墙乳胶漆两遍含腻子 (Internal emulsion paint, 2 coats incl. putty)", "m2", 156000, 28.00, {"gbt50500": "011406001"}),
                ("0112.4", "石材干挂墙面，大堂 (Dry-hung stone wall cladding, lobby)", "m2", 3200, 685.00, {"gbt50500": "011204003"}),
                ("0112.5", "墙面瓷砖，卫生间及茶水间 (Wall tiling, toilets and pantries)", "m2", 14500, 145.00, {"gbt50500": "011204004"}),
                ("0112.6", "矿棉板吊顶，办公区 (Mineral-fibre ceiling, office areas)", "m2", 42000, 95.00, {"gbt50500": "011302001"}),
                ("0112.7", "石膏板吊顶，公共区及走道 (Plasterboard ceiling, public areas)", "m2", 18500, 118.00, {"gbt50500": "011302001"}),
                ("0112.8", "铝合金方通格栅吊顶，大堂 (Aluminium baffle ceiling, lobby)", "m2", 2800, 385.00, {"gbt50500": "011302002"}),
                ("0112.9", "单元式玻璃幕墙，中空 Low-E (Unitised glass curtain wall, DGU Low-E)", "m2", 32000, 1850.00, {"gbt50500": "011209001"}),
                ("0112.10", "铝板幕墙，裙楼及设备层 (Aluminium-panel curtain wall, podium/plant)", "m2", 6800, 980.00, {"gbt50500": "011209002"}),
                ("0112.11", "石材幕墙，裙楼立面 (Stone curtain wall, podium facade)", "m2", 3600, 1280.00, {"gbt50500": "011209003"}),
                ("0112.12", "外墙铝合金遮阳格栅 (External aluminium sun-shading fins)", "m2", 4200, 620.00, {"gbt50500": "011209001"}),
            ],
        ),
        # ── 0304 电气设备安装工程 (Electrical) ───────────────────────
        (
            "0304",
            "电气设备安装工程 (Electrical installation)",
            {"gbt50500": "0304"},
            [
                ("0304.1", "10kV 箱式变电站，2x2000kVA (10kV package substation, 2x2000 kVA)", "项", 1, 6850000.00, {"gbt50500": "030404017"}),
                ("0304.2", "柴油发电机组 1600kW 含并机柜 (Diesel genset 1600 kW with sync panel)", "台", 2, 2850000.00, {"gbt50500": "030409001"}),
                ("0304.3", "低压配电柜及双电源切换 (LV switchgear and ATS)", "项", 1, 4250000.00, {"gbt50500": "030404017"}),
                ("0304.4", "母线槽 4000A 垂直供电 (Busduct 4000 A, vertical risers)", "m", 1850, 2850.00, {"gbt50500": "030408001"}),
                ("0304.5", "电力电缆敷设，YJV 铜芯 (Power cable laying, YJV copper)", "m", 92000, 85.00, {"gbt50500": "030408001"}),
                ("0304.6", "桥架及线槽，热镀锌 (Cable tray and trunking, hot-dip galv.)", "m", 38000, 95.00, {"gbt50500": "030411001"}),
                ("0304.7", "管内穿线及配电支线 (Conduit wiring and final circuits)", "m", 285000, 12.50, {"gbt50500": "030411004"}),
                ("0304.8", "LED 灯具，办公及公共区 (LED luminaires, office and public)", "套", 18500, 285.00, {"gbt50500": "030412001"}),
                ("0304.9", "应急照明及疏散指示 (Emergency lighting and exit signs)", "套", 3200, 165.00, {"gbt50500": "030412004"}),
                ("0304.10", "防雷接地及等电位联结 (Lightning protection and equipotential bonding)", "项", 1, 1280000.00, {"gbt50500": "030409002"}),
                ("0304.11", "火灾自动报警系统 (Automatic fire-alarm system)", "项", 1, 3850000.00, {"gbt50500": "030904001"}),
                ("0304.12", "综合布线及智能化集成 (Structured cabling and BMS integration)", "项", 1, 5650000.00, {"gbt50500": "030502001"}),
                ("0304.13", "安防监控及门禁系统 (CCTV and access-control system)", "项", 1, 2850000.00, {"gbt50500": "030503001"}),
            ],
        ),
        # ── 0306 给排水、采暖、燃气及通风空调工程 (Plumbing/HVAC) ────
        (
            "0306",
            "给排水、暖通空调工程 (Plumbing, HVAC and ventilation)",
            {"gbt50500": "0306"},
            [
                ("0306.1", "给水管道，钢塑复合管 (Water-supply piping, steel-plastic composite)", "m", 28500, 95.00, {"gbt50500": "031001001"}),
                ("0306.2", "排水管道，柔性铸铁管 (Drainage piping, flexible cast iron)", "m", 22000, 128.00, {"gbt50500": "031001005"}),
                ("0306.3", "雨水管道及虹吸排水 (Rainwater and siphonic drainage)", "m", 4800, 145.00, {"gbt50500": "031001006"}),
                ("0306.4", "卫生器具及配件安装 (Sanitary fixtures and fittings)", "组", 1850, 1280.00, {"gbt50500": "031004003"}),
                ("0306.5", "消火栓系统及管网 (Fire-hydrant system and pipework)", "项", 1, 3650000.00, {"gbt50500": "030901001"}),
                ("0306.6", "自动喷淋灭火系统 (Automatic sprinkler system)", "m2", 86000, 95.00, {"gbt50500": "030901002"}),
                ("0306.7", "生活水泵及变频供水设备 (Domestic pumps and VFD water-supply set)", "项", 1, 1850000.00, {"gbt50500": "031003013"}),
                ("0306.8", "离心式冷水机组，2x1200RT (Centrifugal chiller, 2x1200 RT)", "台", 2, 4850000.00, {"gbt50500": "030701003"}),
                ("0306.9", "冷却塔及冷冻冷却水泵 (Cooling towers and chilled/condenser pumps)", "项", 1, 3850000.00, {"gbt50500": "030701011"}),
                ("0306.10", "组合式空调机组及新风机组 (AHU and fresh-air handling units)", "台", 48, 185000.00, {"gbt50500": "030701004"}),
                ("0306.11", "风机盘管，办公区 (Fan-coil units, office areas)", "台", 1650, 6850.00, {"gbt50500": "030701005"}),
                ("0306.12", "镀锌钢板风管制作安装 (Galvanised-steel ductwork)", "m2", 42000, 165.00, {"gbt50500": "030702001"}),
                ("0306.13", "防排烟风机及加压送风系统 (Smoke-extract and pressurisation fans)", "项", 1, 2650000.00, {"gbt50500": "030703001"}),
                ("0306.14", "客梯及消防电梯，1.75m/s (Passenger and fire lifts, 1.75 m/s)", "台", 24, 1280000.00, {"gbt50500": "030601001"}),
                ("0306.15", "自动扶梯，裙楼商业 (Escalators, podium retail)", "台", 6, 850000.00, {"gbt50500": "030601002"}),
            ],
        ),
    ],
    # 中国工程造价取费：按上海 2026 取费标准，企业管理费、规费、利润、安全文明施工费
    # 按直接费取费，增值税（销项）按累计金额取费（一般计税 9%）。
    # Chinese construction cost build-up: enterprise management, statutory
    # charges, profit and safe/civilised-construction fees are taken on the
    # direct cost; VAT (output) is taken on the cumulative amount (general
    # tax method 9%).
    markups=[
        ("安全文明施工费 (Safe and civilised construction fee 2.5%)", 2.5, "overhead", "direct_cost"),
        ("企业管理费 (Enterprise management fee 5%)", 5.0, "overhead", "direct_cost"),
        ("规费 (Statutory charges 3%)", 3.0, "overhead", "direct_cost"),
        ("利润 (Profit 7%)", 7.0, "profit", "direct_cost"),
        ("增值税 (Value-added tax, VAT 9%)", 9.0, "tax", "cumulative"),
    ],
    total_months=20,
    tender_name="土建及机电总承包 (Civil and MEP main contract)",
    tender_companies=[
        ("中建八局 (China Construction Eighth Engineering Division)", "tender@cscec8b.com.cn", 0.98),
        ("上海建工 (Shanghai Construction Group)", "bids@scg.com.cn", 1.03),
        ("中铁上海工程局 (China Railway Shanghai Engineering Bureau)", "tender@crshj.com", 1.01),
    ],
    project_metadata={
        "address": "上海市浦东新区陆家嘴环路 1000 号 (1000 Lujiazui Ring Road, Pudong, Shanghai 200120)",
        "client": "上海陆家嘴金融贸易区开发股份有限公司 (Shanghai Lujiazui Finance & Trade Zone Development Co., Ltd.)",
        "architect": "华东建筑设计研究院 (East China Architectural Design & Research Institute, ECADI)",
        "structural_consultant": "华东建筑设计研究院结构所 (ECADI Structural Division)",
        "gfa_m2": 86000,
        "storeys": "地上 32 层，地下 3 层 (32 above grade, 3 basements)",
        "building_height_m": 148,
        "structure_system": "钢筋混凝土核心筒 + 钢管混凝土框架 (RC core wall + CFST frame)",
        "seismic_design": "抗震设防烈度 7 度 (GB 50011-2010, intensity 7)",
        "design_codes": "GB 50010 (混凝土结构), GB 50011 (抗震), GB 50009 (荷载), GB 50016 (建筑防火), GB 50352 (民用建筑设计统一标准)",
        "pricing_standard": "GB/T 50500-2013《建设工程工程量清单计价规范》 (Standard Method of Measurement)",
        "measurement_standard": "GB 50854-2013《房屋建筑与装饰工程工程量计算规范》 (Quantity calculation code)",
        "sustainability": "绿色建筑三星级 (GB/T 50378 Three-star); LEED 金级目标 (LEED Gold target)",
        "tax_note": (
            "清单综合单价为不含税直接费；增值税按一般计税方法 9% 单列。 "
            "BoQ comprehensive unit rates are tax-exclusive direct cost; VAT "
            "at 9% (general tax method) is shown as a separate line."
        ),
        "statutory": (
            "施工图审查、消防设计审查、人防工程及竣工验收备案按上海市住建委要求办理。 "
            "Drawing review, fire-design review, civil-defence works and "
            "completion filing per the Shanghai Housing & Urban-Rural "
            "Construction Commission."
        ),
        "headline_cost_cny": "约人民币 18 亿元 (approx. CNY 1.8 billion)",
    },
    tender_packages=[
        (
            "桩基及地下室结构 (Piling and basement structure)",
            "钻孔灌注桩、地下连续墙、止水帷幕、筏板及地下室混凝土结构",
            "evaluating",
            [
                ("中建八局 (China Construction Eighth Engineering Division)", "tender@cscec8b.com.cn", 0.98),
                ("上海建工 (Shanghai Construction Group)", "bids@scg.com.cn", 1.03),
                ("中铁上海工程局 (China Railway Shanghai Engineering Bureau)", "tender@crshj.com", 1.01),
            ],
        ),
        (
            "主体结构及砌筑 (Superstructure and masonry)",
            "核心筒、钢管混凝土柱、框架梁板、楼梯及填充墙砌筑",
            "evaluating",
            [
                ("上海建工 (Shanghai Construction Group)", "bids@scg.com.cn", 0.99),
                ("中建三局 (China Construction Third Engineering Bureau)", "tender@cscec3b.com.cn", 1.04),
                ("龙信建设 (Longxin Construction Group)", "bids@longxin.com.cn", 1.02),
            ],
        ),
        (
            "幕墙及外立面 (Curtain wall and facade)",
            "单元式玻璃幕墙、铝板幕墙、石材幕墙及外遮阳系统",
            "evaluating",
            [
                ("江河幕墙 (Jangho Curtain Wall)", "tender@jangho.com", 0.98),
                ("中南幕墙 (Zhongnan Curtain Wall)", "bids@zhongnan.com.cn", 1.05),
                ("方大幕墙 (Fangda Curtain Wall)", "tender@fangda.com.cn", 1.01),
            ],
        ),
        (
            "机电安装 (MEP installation)",
            "给排水、消防、暖通空调、电气、智能化及电梯安装",
            "evaluating",
            [
                ("上海安装工程集团 (Shanghai Installation Engineering Group)", "tender@siegc.com", 0.99),
                ("中建电子 (China Construction Electronic Engineering)", "bids@ccee.com.cn", 1.04),
                ("华电机电 (Huadian Electromechanical)", "tender@huadianjd.com", 1.02),
            ],
        ),
        (
            "精装修 (Interior fit-out)",
            "大堂、电梯厅、公共走道及标准层办公区精装修",
            "evaluating",
            [
                ("金螳螂建筑装饰 (Gold Mantis Construction Decoration)", "tender@goldmantis.com", 0.98),
                ("亚厦装饰 (Yasha Decoration)", "bids@yashagroup.com", 1.05),
                ("洪涛装饰 (Hongtao Decoration)", "tender@hongtao.com.cn", 1.02),
            ],
        ),
    ],
    budget_boq_name="施工图预算 - GB/T 50500-2013 (Control Budget)",
    planned_budget=1_800_000_000.0,
    actual_spend_ratio=0.45,
    spi_override=0.98,
    cpi_override=1.02,
)
