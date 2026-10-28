# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner-pack demo: 아파트 신축공사 - 서울 장위 (Apartment Building, Seoul)
# ---------------------------------------------------------------------------
# A Korean bill is built the way the cost-calculation method (wonga gyesan)
# lays it out. The measured lines below are the net construction cost,
# sunn gongsa wonga, which is materials (jaeryobi), labour (nomubi) and
# expenses (gyeongbi) rolled into one comprehensive rate per item. On top of
# that come general administrative expenses (ilban gwallibi) and profit
# (iyun), and value-added tax (bugagachise) last, at 10 percent, which is
# the rate for construction works and has not moved since 1977.
#
# WHAT IS INDICATIVE HERE, PLAINLY.
#
# 1. The codes. The standard estimating manual (pyojun pumsem, published by
#    MOLIT and maintained by KICT) is a productivity manual: it states the
#    labour, plant and material quantity required per unit of work, chapter
#    by chapter, and it is the basis every Korean unit-price build-up
#    (irwidaega) is written against. It is not a coded item catalogue in the
#    way GESN or GB 50500 are, so there is no published item number to
#    quote. Every line here carries a code in the shape CC-SS-NNN, chapter,
#    section, item, following the chapter order of the building volume. The
#    chapter number is the part that carries meaning and is the part to read.
#    These codes are SHAPED TO the standard, not QUOTED FROM a specific
#    published edition, and the section and item digits are ours. A Korean
#    estimator should replace them with the irwidaega numbering of whichever
#    edition their own bill is written against.
#
#    Read the section codes with that in mind. Twenty-odd manual chapters are
#    consolidated into the nine bill sections below, so a section code names
#    only the LEADING chapter of its section and its items legitimately span
#    others. Section 4 is coded 07 for masonry but runs into 08 for tanking
#    and 10 for insulation; section 6 is coded 13 and runs into 15 and 16.
#    The item code is the one to trust for a given line.
#
# 2. The rates. Seoul 2026 market levels in won, tax exclusive. They are
#    consistent with each other and of the right order of magnitude for an
#    apartment block of this size, but they are estimates, not extracts from
#    a priced series. A real bill prices labour off the Construction
#    Association of Korea wage survey and materials off a published price
#    journal, both re-issued twice a year, and the answer moves with them.
#
# 3. The profit base. In Korean practice profit is taken on labour plus
#    expenses plus general administrative expenses and explicitly NOT on
#    materials, at up to 15 percent. DemoTemplate markups can only be taken
#    on direct cost or on the cumulative amount, so the profit row below is
#    the equivalent percentage of direct cost for a material share of about
#    55 percent. The money lands in the right place; the sensitivity to
#    material share is lost. Same caveat for the safety and environment
#    rows, which are strictly expense heads inside the net cost rather than
#    additions on top of it.
#
# 4. The safety rate. Occupational safety and health management cost is a
#    statutory percentage of materials plus direct labour, banded by
#    contract value and re-notified by the Ministry of Employment and Labour.
#    The band used here is the one for general building work above the top
#    threshold. Check the notice current on your tender date before reusing.
#
# Won has no minor unit in practice, so every rate below is a whole number of
# won and the line totals are large. Nothing is scaled or abbreviated.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="residential-seoul",
    project_name="장위 아파트 신축공사 - 서울 성북구 (Apartment Building, Jangwi, Seoul)",
    project_description=(
        "서울특별시 성북구 장위동 주택재건축정비사업 구역 내 아파트 1개 동 신축공사. "
        "지상 25층, 지하 2층, 전용면적 84제곱미터형 150세대, 연면적 약 23,800제곱미터 "
        "(지상 약 16,900, 지하 약 6,900). 구조는 국내 공동주택의 표준인 철근콘크리트 "
        "벽식구조로 내력벽이 무량 평슬래브를 직접 지지하며, 지상부에는 기둥과 보가 없고 "
        "지하주차장만 라멘조로 계획하였다. 지하 2개층 주차 182대, 지역난방 온수 바닥난방, "
        "바닥충격음 차단구조 인정 바닥(완충재 30밀리미터 포함 총 두께 210밀리미터). "
        "공사비는 서울 2026년 가격수준, 원화 기준이며 표준품셈에 근거한 일위대가와 "
        "원가계산 방식으로 산출하였다. "
        "New-build apartment block on a housing redevelopment site in Jangwi-dong, "
        "Seongbuk-gu, Seoul. 25 storeys above ground plus 2 basement levels, 150 "
        "dwellings of the 84 m2 net-area type, gross floor area approx. 23,800 m2 "
        "(approx. 16,900 m2 above ground, 6,900 m2 below). The structure is the "
        "reinforced-concrete bearing-wall system that Korean apartment housing is "
        "overwhelmingly built in: load-bearing walls carry flat-plate slabs directly, "
        "there are no frame columns or beams above ground, and only the basement car "
        "park is framed. 182 parking spaces on two basement levels, district-heating "
        "under-floor heating, and a certified floor impact-noise construction 210 mm "
        "deep including a 30 mm resilient layer. Priced at Seoul 2026 levels in won by "
        "the cost-calculation method on unit-price build-ups derived from the standard "
        "estimating manual."
    ),
    region="KR",
    classification_standard="kbim",
    currency="KRW",
    locale="ko",
    project_code="SB-JW-2026-01",
    address={
        "street": "장위로 100 (100 Jangwi-ro)",
        "city": "서울특별시 성북구 (Seongbuk-gu, Seoul)",
        "postcode": "02771",
        "country": "South Korea",
        "lat": 37.6136,
        "lng": 127.0505,
    },
    validation_rule_sets=["boq_quality", "project_completeness"],
    boq_name="공사비 내역서 - 표준품셈 기준 일위대가 (Bill of Quantities)",
    boq_description=(
        "실시설계 도서에 따라 공종별로 작성한 공사비 내역서. 각 항목의 단가는 표준품셈 "
        "품에 시중노임단가와 자재 가격정보를 적용하여 산출한 일위대가로, 재료비·노무비·"
        "경비를 포함한 종합단가이다. 일반관리비와 이윤, 부가가치세는 별도 계상. "
        "Bill of quantities by trade section for the detailed design. Each comprehensive "
        "rate is a unit-price build-up on standard estimating manual outputs, priced with "
        "the market wage survey and published material prices, and covers materials, "
        "labour and expenses. General administrative expenses, profit and VAT are added "
        "separately below."
    ),
    boq_metadata={
        "standard": "표준품셈 (Standard Estimating Manual) 기반 일위대가",
        "phase": "실시설계 내역서 (Detailed design bill of quantities)",
        "base_date": "2026-Q1",
        "price_level": "서울 2026 (Seoul 2026)",
        "pricing_method": "원가계산에 의한 예정가격 산정 (Cost-calculation method)",
    },
    sections=[
        # ── 02/03 가설 및 토공사 (Temporary works and earthworks) ─────
        (
            "01",
            "제1장 가설 및 토공사 (Temporary works and earthworks)",
            {"kbim": "02-00-000"},
            [
                ("01.01", "가설사무소·현장식당 및 가설전기·용수 등 부대시설 (Site offices, canteen, temporary power, water and services)", "식", 1.0, 930_000_000.0, {"kbim": "02-01-010"}),
                ("01.02", "가설방음벽 H=3.0m 및 가설울타리 (Temporary noise barrier H3.0 m and site hoarding)", "m", 430.0, 310_000.0, {"kbim": "02-02-020"}),
                ("01.03", "시스템비계, 안전난간 및 낙하물방지망 (System scaffolding, edge protection and debris netting)", "m2", 17_800.0, 44_000.0, {"kbim": "02-03-030"}),
                ("01.04", "타워크레인 T/C 설치·해체 및 운영 (Tower crane erection, dismantling and operation)", "대·월", 40.0, 22_500_000.0, {"kbim": "02-05-040"}),
                ("01.05", "터파기, 백호 1.0m3 기계굴착 (Bulk excavation by 1.0 m3 backhoe)", "m3", 68_000.0, 6_800.0, {"kbim": "03-01-010"}),
                ("01.06", "잔토 반출 및 사토장 처분, 운반거리 30km (Surplus soil haulage 30 km and disposal)", "m3", 54_000.0, 22_000.0, {"kbim": "03-03-030"}),
                ("01.07", "흙막이 C.I.P 벽체 D=450mm, 근입장 포함 (CIP earth-retaining wall D450 incl. embedment)", "m", 11_200.0, 86_000.0, {"kbim": "03-05-020"}),
                ("01.08", "흙막이 버팀보·어스앵커 및 계측관리 (Struts, earth anchors and instrumentation)", "본", 340.0, 1_780_000.0, {"kbim": "03-05-050"}),
                ("01.09", "되메우기, 층다짐 및 원지반 정리 (Backfill, layered compaction and subgrade trimming)", "m3", 15_500.0, 8_500.0, {"kbim": "03-02-040"}),
            ],
        ),
        # ── 04 기초 및 파일공사 (Piling and foundations) ───────────────
        (
            "02",
            "제2장 기초 및 파일공사 (Piling and foundations)",
            {"kbim": "04-00-000"},
            [
                ("02.01", "P.H.C 파일 D=500mm, 매입공법 S.I.P (PHC pile D500, SIP embedded method)", "m", 24_000.0, 68_000.0, {"kbim": "04-02-030"}),
                ("02.02", "파일 두부정리 및 두부보강 (Pile head trimming and head reinforcement)", "본", 780.0, 185_000.0, {"kbim": "04-02-070"}),
                ("02.03", "파일 동재하시험 및 정재하시험 (Dynamic and static pile load testing)", "개소", 14.0, 4_200_000.0, {"kbim": "04-02-090"}),
                ("02.04", "버림콘크리트 및 밑창콘크리트 18MPa (Blinding and sub-base concrete 18 MPa)", "m3", 780.0, 108_000.0, {"kbim": "04-01-020"}),
                ("02.05", "기초 매트 콘크리트 24MPa, 두께 1,200mm (Mat foundation concrete 24 MPa, 1200 mm)", "m3", 4_200.0, 122_000.0, {"kbim": "05-03-010"}),
                ("02.06", "기초 및 지하 피트 방수, 방수보호층 포함 (Tanking to raft and pits, with protection layer)", "m2", 4_600.0, 62_000.0, {"kbim": "08-01-030"}),
            ],
        ),
        # ── 05 철근콘크리트공사, 벽식구조 (RC, bearing-wall system) ────
        (
            "03",
            "제3장 철근콘크리트공사 - 벽식구조 (Reinforced concrete, bearing-wall system)",
            {"kbim": "05-00-000"},
            [
                ("03.01", "내력벽 콘크리트 27MPa, 벽식구조 (Bearing-wall concrete 27 MPa, wall-slab system)", "m3", 5_600.0, 138_000.0, {"kbim": "05-03-040"}),
                ("03.02", "무량 평슬래브 콘크리트 24MPa, 두께 210mm (Flat-plate slab concrete 24 MPa, 210 mm, beamless)", "m3", 4_900.0, 128_000.0, {"kbim": "05-03-060"}),
                ("03.03", "지하주차장 기둥·보 콘크리트 27MPa, 라멘조 (Basement column and beam concrete 27 MPa, framed)", "m3", 2_300.0, 132_000.0, {"kbim": "05-03-050"}),
                ("03.04", "계단실 및 승강로 콘크리트 24MPa (Stair core and lift shaft concrete 24 MPa)", "m3", 620.0, 152_000.0, {"kbim": "05-03-080"}),
                ("03.05", "고층부 콘크리트 압송 및 동절기 보양 (Concrete pumping to height and winter protection)", "m3", 8_400.0, 9_500.0, {"kbim": "05-03-100"}),
                ("03.06", "철근 가공·조립 SD400, HD10-HD25 (Reinforcement SD400 HD10 to HD25, cut, bend and fix)", "t", 2_180.0, 1_285_000.0, {"kbim": "05-02-010"}),
                ("03.07", "철근 가공·조립 SD500 대구경, 지하 기둥 (Reinforcement SD500 large diameter, basement columns)", "t", 180.0, 1_360_000.0, {"kbim": "05-02-030"}),
                ("03.08", "벽체 개구부 보강근 및 모서리 보강근 (Opening trim bars and corner reinforcement to bearing walls)", "t", 95.0, 1_420_000.0, {"kbim": "05-02-060"}),
                ("03.09", "알루미늄 거푸집, 세대 내부 벽·슬래브 (Aluminium formwork to dwelling walls and slabs)", "m2", 51_000.0, 34_000.0, {"kbim": "05-01-070"}),
                ("03.10", "갱폼 거푸집, 외벽 및 발코니 (Gang formwork to external walls and balconies)", "m2", 13_500.0, 52_000.0, {"kbim": "05-01-080"}),
                ("03.11", "재래식 합판거푸집, 지하층 및 코어 (Conventional plywood panel formwork, basement and cores)", "m2", 16_800.0, 29_000.0, {"kbim": "05-01-030"}),
                ("03.12", "슬래브 동바리 및 서포트 설치·해체 (Slab shoring and props, erect and strike)", "m2", 22_000.0, 12_000.0, {"kbim": "05-01-090"}),
                ("03.13", "지하 외벽 지수판 및 후타설 이음부 (Waterstops and post-cast joints to basement walls)", "m", 1_850.0, 96_000.0, {"kbim": "05-03-120"}),
            ],
        ),
        # ── 07/08/10 조적·방수 및 단열공사 (Masonry, tanking, insulation)
        (
            "04",
            "제4장 조적·방수 및 단열공사 (Masonry, waterproofing and insulation)",
            {"kbim": "07-00-000"},
            [
                ("04.01", "세대 내부 경량벽체, A.L.C 블록 t=100mm (Internal ALC block partitions, 100 mm)", "m2", 14_500.0, 58_000.0, {"kbim": "07-02-020"}),
                ("04.02", "시멘트벽돌 조적, 지하층 및 공용부 (Cement brick masonry, basement and common areas)", "m2", 6_200.0, 52_000.0, {"kbim": "07-01-010"}),
                ("04.03", "지하 외벽 및 피트 방수, 개량아스팔트 시트 2겹 (Basement wall and pit tanking, 2-ply modified bitumen)", "m2", 9_800.0, 46_000.0, {"kbim": "08-02-020"}),
                ("04.04", "욕실·발코니 액체방수 및 도막방수 (Liquid and coating waterproofing, bathrooms and balconies)", "m2", 11_200.0, 32_000.0, {"kbim": "08-03-040"}),
                ("04.05", "외벽 단열재, 준불연 경질우레탄보드 t=135mm (External wall insulation, semi-non-combustible urethane board 135 mm)", "m2", 16_400.0, 42_000.0, {"kbim": "10-01-020"}),
                ("04.06", "옥상 단열 및 우레탄 도막방수 2회 (Roof insulation and two-coat urethane membrane)", "m2", 1_250.0, 78_000.0, {"kbim": "08-04-030"}),
            ],
        ),
        # ── 11/14/15 창호·유리 및 외부마감 (Windows and external finishes)
        (
            "05",
            "제5장 창호·유리 및 외부마감공사 (Windows, glazing and external finishes)",
            {"kbim": "11-00-000"},
            [
                ("05.01", "발코니 외부 창호, PVC 이중창 로이복층유리 (External balcony windows, uPVC double sash, Low-E IGU)", "m2", 3_200.0, 395_000.0, {"kbim": "11-02-030"}),
                ("05.02", "거실·침실 시스템창호 및 방화유리창 (System windows and fire-rated glazing to living areas)", "m2", 1_850.0, 445_000.0, {"kbim": "11-02-060"}),
                ("05.03", "세대 현관 방화문 갑종, 디지털 도어록 포함 (Dwelling entrance fire door Class A, with digital lock)", "EA", 150.0, 1_380_000.0, {"kbim": "11-01-040"}),
                ("05.04", "공용부 방화문·방화셔터 및 옥상 출입문 (Common-area fire doors, shutters and roof access doors)", "EA", 240.0, 1_150_000.0, {"kbim": "11-01-070"}),
                ("05.05", "세대 방충망 및 발코니 방범 난간 (Insect screens and balcony security railings to dwellings)", "세대", 150.0, 480_000.0, {"kbim": "11-03-020"}),
                ("05.06", "외벽 창호 주위 실링 및 코킹 (External sealant and caulking around openings)", "m", 8_600.0, 18_000.0, {"kbim": "11-04-010"}),
                ("05.07", "외벽 도장, 노출콘크리트 위 탄성 수성도료 (External wall finish, elastomeric paint on fair-faced concrete)", "m2", 15_800.0, 34_000.0, {"kbim": "15-02-030"}),
                ("05.08", "저층부 석재 및 금속패널 외벽 마감 (Stone and metal-panel cladding to lower storeys)", "m2", 2_400.0, 285_000.0, {"kbim": "14-02-050"}),
                ("05.09", "옥상 파라펫, 발코니 난간 및 안전난간 (Roof parapet, balcony balustrades and guard rails)", "m", 3_600.0, 168_000.0, {"kbim": "14-04-030"}),
            ],
        ),
        # ── 13/15/16 내부마감공사 (Internal finishes) ──────────────────
        (
            "06",
            "제6장 내부마감공사 (Internal finishes)",
            {"kbim": "13-00-000"},
            [
                ("06.01", "바닥충격음 차단구조 인정 바닥, 완충재 30mm + 경량기포 40mm + 마감모르타르 40mm (Certified floor impact-noise build-up, 30 mm resilient layer, 40 mm foamed concrete, 40 mm finishing mortar)", "m2", 12_900.0, 64_000.0, {"kbim": "13-01-050"}),
                ("06.02", "세대 바닥 강마루 및 걸레받이 (Engineered wood flooring and skirting to dwellings)", "m2", 10_800.0, 78_000.0, {"kbim": "16-02-030"}),
                ("06.03", "발코니 및 다용도실 바닥·벽 타일 (Balcony and utility room floor and wall tiling)", "m2", 4_200.0, 62_000.0, {"kbim": "13-04-010"}),
                ("06.04", "세대 벽체 석고보드 2겹 및 실크벽지 (Two-layer plasterboard lining and vinyl wallcovering, dwellings)", "m2", 42_000.0, 42_000.0, {"kbim": "16-03-020"}),
                ("06.05", "천장 석고보드, 도배 및 커튼박스 (Plasterboard ceilings, papering and curtain boxes)", "m2", 12_900.0, 46_000.0, {"kbim": "16-04-010"}),
                ("06.06", "세대 내부 목문, 문틀 및 철물 (Internal timber doors, frames and ironmongery, dwellings)", "EA", 1_050.0, 420_000.0, {"kbim": "16-05-020"}),
                ("06.07", "주방 가구·상판 및 붙박이장 (Kitchen units, worktops and fitted wardrobes)", "세대", 150.0, 8_600_000.0, {"kbim": "16-06-040"}),
                ("06.08", "신발장, 거실 아트월 및 몰딩 (Shoe cabinet, living-room feature wall and mouldings)", "세대", 150.0, 1_850_000.0, {"kbim": "16-06-070"}),
                ("06.09", "욕실 타일, 위생도기 및 천장재 (Bathroom tiling, sanitaryware and ceilings)", "세대", 150.0, 6_200_000.0, {"kbim": "13-04-030"}),
                ("06.10", "공용부 계단실·복도 타일 및 도장 (Common-area stair and corridor tiling and painting)", "m2", 9_400.0, 96_000.0, {"kbim": "13-04-060"}),
                ("06.11", "계단실 논슬립 및 핸드레일 (Stair nosings and handrails to common stairs)", "m", 1_850.0, 88_000.0, {"kbim": "14-04-060"}),
                ("06.12", "지하주차장 바닥 에폭시 및 천장 흡음뿜칠 (Basement car park epoxy floor and acoustic spray to soffit)", "m2", 13_800.0, 42_000.0, {"kbim": "15-04-020"}),
                ("06.13", "1층 로비 및 커뮤니티시설 인테리어 마감 (Ground-floor lobby and community facility fit-out)", "m2", 1_150.0, 480_000.0, {"kbim": "16-07-010"}),
            ],
        ),
        # ── 17 기계설비 및 소방공사 (Mechanical and fire protection) ───
        (
            "07",
            "제7장 기계설비 및 소방공사 (Mechanical, plumbing and fire protection)",
            {"kbim": "17-00-000"},
            [
                ("07.01", "세대 바닥난방 온수배관 및 분배기 (Under-floor heating pipework and manifolds, dwellings)", "세대", 150.0, 3_850_000.0, {"kbim": "17-03-020"}),
                ("07.02", "지역난방 열교환기계실 및 기계실 배관 (District-heating substation and plant-room pipework)", "식", 1.0, 1_450_000_000.0, {"kbim": "17-03-060"}),
                ("07.03", "급수·급탕 배관 및 부스터펌프 (Domestic cold and hot water pipework with booster set)", "m", 8_600.0, 96_000.0, {"kbim": "17-01-030"}),
                ("07.04", "오배수 및 통기배관, 저소음 이중관 (Soil, waste and vent pipework, low-noise twin-wall)", "m", 7_400.0, 88_000.0, {"kbim": "17-02-020"}),
                ("07.05", "도시가스 배관, 계량기 및 세대 인입 (Town gas pipework, meters and dwelling connections)", "세대", 150.0, 780_000.0, {"kbim": "17-04-020"}),
                ("07.06", "세대 위생기구 및 급배수 기구 설치 (Sanitary fixtures and connections, dwellings)", "세대", 150.0, 2_450_000.0, {"kbim": "17-02-070"}),
                ("07.07", "세대 환기설비, 전열교환형 (Dwelling ventilation, heat-recovery type)", "세대", 150.0, 2_850_000.0, {"kbim": "17-05-040"}),
                ("07.08", "주방·욕실 배기덕트 및 공동배기 입상관 (Kitchen and bathroom extract ductwork and common risers)", "세대", 150.0, 1_150_000.0, {"kbim": "17-05-060"}),
                ("07.09", "지하주차장 급배기 및 제연설비 (Basement supply, exhaust and smoke-control system)", "m2", 6_900.0, 68_000.0, {"kbim": "17-05-080"}),
                ("07.10", "옥내소화전 및 스프링클러 설비 (Indoor fire hydrants and sprinkler system)", "m2", 23_800.0, 42_000.0, {"kbim": "17-06-030"}),
                ("07.11", "소방펌프실, 소화수조 및 가압송수장치 (Fire pump room, tanks and pressurisation set)", "식", 1.0, 680_000_000.0, {"kbim": "17-06-060"}),
            ],
        ),
        # ── 18/19 전기 및 정보통신설비공사 (Electrical and telecom) ────
        (
            "08",
            "제8장 전기 및 정보통신설비공사 (Electrical and telecommunications)",
            {"kbim": "18-00-000"},
            [
                ("08.01", "수변전설비, 특고압 22.9kV 수전 및 변압기 (HV substation, 22.9 kV incoming and transformers)", "식", 1.0, 1_120_000_000.0, {"kbim": "18-01-020"}),
                ("08.02", "비상발전기 500kW 및 자동절체반 (Standby generator 500 kW and automatic transfer switch)", "대", 1.0, 380_000_000.0, {"kbim": "18-01-060"}),
                ("08.03", "간선 및 분전반, 세대 분전반 포함 (Rising mains and distribution boards incl. dwelling boards)", "식", 1.0, 980_000_000.0, {"kbim": "18-02-030"}),
                ("08.04", "세대 내 전등·전열 배관배선 및 기구 (Dwelling lighting and power wiring, containment and fittings)", "세대", 150.0, 4_200_000.0, {"kbim": "18-03-020"}),
                ("08.05", "공용부 및 지하주차장 LED 조명 (Common-area and basement car park LED lighting)", "EA", 4_200.0, 165_000.0, {"kbim": "18-03-070"}),
                ("08.06", "자동화재탐지설비 및 비상방송설비 (Automatic fire detection and emergency broadcast)", "m2", 23_800.0, 18_500.0, {"kbim": "18-05-020"}),
                ("08.07", "홈네트워크, 월패드 및 세대 통신 인입 (Home network, wall pads and dwelling telecom services)", "세대", 150.0, 2_650_000.0, {"kbim": "19-02-030"}),
                ("08.08", "피뢰설비, 접지 및 등전위본딩 (Lightning protection, earthing and equipotential bonding)", "식", 1.0, 185_000_000.0, {"kbim": "18-06-010"}),
                ("08.09", "전기차 충전설비, 완속 및 급속 (Electric-vehicle charging points, slow and fast)", "대", 20.0, 3_850_000.0, {"kbim": "18-04-050"}),
                ("08.10", "CCTV, 출입통제 및 주차관제설비 (CCTV, access control and parking management)", "식", 1.0, 620_000_000.0, {"kbim": "19-03-040"}),
            ],
        ),
        # ── 20/21 승강기·부대토목 및 조경 (Lifts, external works) ──────
        (
            "09",
            "제9장 승강기·부대토목 및 조경공사 (Lifts, external works and landscaping)",
            {"kbim": "20-00-000"},
            [
                ("09.01", "승객용 승강기 13인승, 기계실 없는 방식 (Passenger lift, 13-person, machine-room-less)", "대", 3.0, 185_000_000.0, {"kbim": "20-01-020"}),
                ("09.02", "비상용 겸용 승강기 및 화물용 승강기 (Fire-fighting lift and goods lift)", "대", 2.0, 245_000_000.0, {"kbim": "20-01-050"}),
                ("09.03", "단지 내 도로 및 소방차 진입로 포장 (Estate roads and fire-appliance access paving)", "m2", 3_200.0, 92_000.0, {"kbim": "21-02-030"}),
                ("09.04", "옥외 우수·오수 관로 및 상수도 인입 (External storm and foul mains, water service connection)", "m", 1_250.0, 285_000.0, {"kbim": "21-03-020"}),
                ("09.05", "단지 옥외 조명 및 보안등 (Estate external lighting and security lighting)", "EA", 180.0, 620_000.0, {"kbim": "21-03-060"}),
                ("09.06", "조경 식재, 교목·관목 및 지피식물 (Landscape planting, trees, shrubs and ground cover)", "m2", 3_400.0, 165_000.0, {"kbim": "21-05-040"}),
                ("09.07", "어린이놀이터, 운동시설 및 옥외 시설물 (Children's playground, fitness area and site furniture)", "식", 1.0, 480_000_000.0, {"kbim": "21-06-020"}),
                ("09.08", "단지 옹벽, 담장 및 옥외 계단 (Estate retaining walls, boundary walls and external steps)", "m", 420.0, 680_000.0, {"kbim": "21-04-010"}),
            ],
        ),
    ],
    # Korean cost-calculation build-up, in the order a wonga gyesan sheet
    # reads it. The measured lines above are the net construction cost, so
    # only what sits above them appears here. Safety and environment are
    # expense heads that a Korean sheet lists inside the net cost, computed
    # as a percentage of materials plus direct labour; taking them on direct
    # cost here reproduces the money without needing a labour split the
    # template cannot carry. Profit is legally taken on labour, expenses and
    # general administrative expenses and NOT on materials, at up to 15
    # percent, which for a material share around 55 percent is the 7.5
    # percent of direct cost shown. VAT is 10 percent on the cumulative.
    markups=[
        ("산업안전보건관리비 (Occupational safety and health management cost 1.97%)", 1.97, "other", "direct_cost"),
        ("환경보전비 (Environmental conservation cost 0.4%)", 0.4, "other", "direct_cost"),
        ("일반관리비 (General administrative expenses 5.5%)", 5.5, "overhead", "direct_cost"),
        ("이윤 (Profit 7.5%)", 7.5, "profit", "direct_cost"),
        ("부가가치세 (Value-added tax, VAT 10%)", 10.0, "tax", "cumulative"),
    ],
    total_months=30,
    tender_name="아파트 신축공사 종합건설 도급 (Main building contract)",
    tender_companies=[
        ("도담종합건설 (Dodam General Construction)", "tender@dodam-const.example", 0.98),
        ("해솔건설산업 (Haesol Construction and Industry)", "bid@haesol-const.example", 1.03),
        ("가온누리종합건설 (Gaonnuri General Construction)", "tender@gaonnuri-const.example", 1.01),
    ],
    tender_packages=[
        (
            "골조공사 (Structural frame)",
            "파일, 매트기초, 벽식 내력벽과 무량 평슬래브, 지하주차장 라멘조 및 거푸집 일체.",
            "evaluating",
            [
                ("도담종합건설 (Dodam General Construction)", "tender@dodam-const.example", 0.98),
                ("해솔건설산업 (Haesol Construction and Industry)", "bid@haesol-const.example", 1.03),
                ("아름드리건설 (Areumduri Construction)", "tender@areumduri-const.example", 1.01),
            ],
        ),
        (
            "창호 및 외부마감공사 (Windows and external finishes)",
            "발코니 이중창, 시스템창호, 방화문, 외벽 도장 및 저층부 석재·금속패널 마감.",
            "issued",
            [
                ("온새미창호산업 (Onsaemi Window Industry)", "tender@onsaemi-win.example", 0.99),
                ("맑은뜰건설 (Malgeunddeul Construction)", "bid@malgeunddeul.example", 1.04),
                ("이든종합건설 (Ideun General Construction)", "tender@ideun-const.example", 1.02),
            ],
        ),
        (
            "기계설비 및 소방공사 (Mechanical and fire protection)",
            "지역난방 열교환기계실, 세대 바닥난방, 급배수, 환기 및 소화설비 일체.",
            "evaluating",
            [
                ("새라온설비 (Saeraon Mechanical Services)", "tender@saeraon-mep.example", 0.99),
                ("푸른뫼기계설비 (Pureunmoe Mechanical Engineering)", "bid@pureunmoe-mep.example", 1.05),
                ("너울설비산업 (Neoul Mechanical Industry)", "tender@neoul-mep.example", 1.02),
            ],
        ),
        (
            "전기·정보통신공사 (Electrical and telecommunications)",
            "수변전설비, 비상발전기, 간선 및 분전반, 조명, 자동화재탐지 및 홈네트워크.",
            "issued",
            [
                ("별하람전기공사 (Byeolharam Electrical Works)", "tender@byeolharam-el.example", 0.98),
                ("늘품전기공사 (Neulpum Electrical Works)", "bid@neulpum-el.example", 1.03),
                ("다온정보통신 (Daon Information and Communication)", "tender@daon-ict.example", 1.02),
            ],
        ),
    ],
    schedule_activities=[
        ("착공 및 가설공사 (Mobilisation and temporary works)", "2026-04-01", "2026-06-30"),
        ("흙막이 및 터파기 (Excavation support and bulk excavation)", "2026-05-01", "2026-09-30"),
        ("파일 및 기초공사 (Piling and foundations)", "2026-08-01", "2026-12-31"),
        ("지하층 골조 (Basement structure)", "2026-11-01", "2027-03-31"),
        ("지상 골조, 벽식구조 (Superstructure, bearing-wall system)", "2027-03-01", "2028-01-31"),
        ("조적 및 방수·단열공사 (Masonry, waterproofing and insulation)", "2027-07-01", "2028-03-31"),
        ("창호 및 외부마감공사 (Windows and external finishes)", "2027-09-01", "2028-05-31"),
        ("기계설비 및 소방 배관 (Mechanical and fire-protection first fix)", "2027-08-01", "2028-06-30"),
        ("전기·정보통신 배선 (Electrical and telecom first fix)", "2027-08-01", "2028-06-30"),
        ("내부마감 및 바닥충격음 차단구조 (Internal finishes and floor impact-noise construction)", "2028-01-01", "2028-07-31"),
        ("승강기 설치 및 시운전 (Lift installation and commissioning)", "2028-02-01", "2028-06-30"),
        ("부대토목 및 조경공사 (External works and landscaping)", "2028-04-01", "2028-08-31"),
        ("시운전, 사용검사 및 준공 (Commissioning, completion inspection and handover)", "2028-07-01", "2028-09-30"),
    ],
    project_metadata={
        "address": "서울특별시 성북구 장위로 100 (100 Jangwi-ro, Seongbuk-gu, Seoul 02771, South Korea)",
        "client": "해온마을 주택재건축정비사업조합 (Haeon Maeul Housing Redevelopment Association)",
        "architect": "여울건축사사무소 (Yeoul Architects)",
        "structural_engineer": "터울구조엔지니어링 (Teoul Structural Engineering)",
        "quantity_surveyor": "한터적산엔지니어링 (Hanteo Cost Engineering)",
        "gfa_m2": 23800,
        "site_area_m2": 8400,
        "storeys": "지상 25층, 지하 2층 (25 above ground, 2 basements)",
        "basement_levels": 2,
        "dwellings": 150,
        "dwelling_type": "전용면적 84 m2형, 계단실형 판상형 (84 m2 net-area type, stair-core plan)",
        "parking_spaces": 182,
        "structure_system": (
            "철근콘크리트 벽식구조, 무량 평슬래브 두께 210mm, 지하주차장은 라멘조. "
            "RC bearing-wall system with 210 mm flat-plate slabs and no frame columns or "
            "beams above ground; the basement car park is a conventional RC frame."
        ),
        "construction_standards": [
            "KDS 41 건축구조기준 (Korean Design Standard, building structures)",
            "KDS 14 20 콘크리트구조 설계기준 (Concrete structures design code)",
            "KCS 41 건축공사 표준시방서 (Korean Construction Specification, building works)",
            "주택건설기준 등에 관한 규정 (Regulations on housing construction standards)",
            "건축물의 에너지절약설계기준, 중부2지역 (Energy saving design standard, central zone 2)",
            "공동주택 바닥충격음 차단구조의 인정 및 관리기준 (Floor impact-noise construction certification)",
        ],
        "estimating_method": (
            "표준품셈 품에 시중노임단가와 자재 가격정보를 적용한 일위대가를 작성하고, "
            "국가를 당사자로 하는 계약에 관한 법령의 예정가격 작성기준에 따른 원가계산 방식으로 "
            "총공사비를 산정. Unit-price build-ups on standard estimating manual outputs, "
            "totalled by the cost-calculation method used for public works pricing."
        ),
        "regulator": (
            "국토교통부 및 서울특별시 성북구 (사업계획승인, 착공신고, 사용검사), "
            "한국부동산원 공사비 검증. MOLIT and the Seongbuk-gu office of the Seoul "
            "Metropolitan Government for housing approval, commencement filing and "
            "completion inspection; construction-cost verification by the Korea Real "
            "Estate Board."
        ),
        "price_source_note": (
            "노무비는 대한건설협회 건설업 임금실태조사 시중노임단가, 자재비는 발간 가격정보지 "
            "기준이며 두 자료 모두 연 2회 갱신된다. 본 팩의 단가는 그 수준을 따른 추정치이지 "
            "특정 회차의 발췌가 아니다. Labour is priced off the Construction Association of "
            "Korea wage survey and materials off a published price journal, both re-issued "
            "twice a year. The rates here follow that level but are estimates, not extracts."
        ),
        "markup_base_note": (
            "이윤은 노무비, 경비 및 일반관리비의 합계에 대하여 계상하며 재료비에는 계상하지 "
            "않는다. 본 템플릿의 할증 행은 직접공사비 기준만 지원하므로 재료비 비중 약 55%를 "
            "가정한 등가 요율로 표기하였다. Profit is taken on labour, expenses and general "
            "administrative expenses and never on materials. The markup rows here can only "
            "take a percentage of direct cost, so the profit rate shown is the equivalent "
            "for a material share of about 55 percent."
        ),
        "currency_note": (
            "원화는 실무상 보조단위를 쓰지 않으므로 모든 단가는 원 단위 정수이다. "
            "Won has no minor unit in practice, so every unit rate is a whole number of won."
        ),
        "floor_impact_noise": (
            "바닥구조 총 두께 210mm, 완충재 30mm + 경량기포콘크리트 40mm + 마감모르타르 40mm + "
            "슬래브 210mm 위 구성으로 경량·중량 충격음 성능 인정 구조를 적용. Certified floor "
            "impact-noise build-up over the structural slab: 30 mm resilient layer, 40 mm "
            "lightweight foamed concrete and 40 mm finishing mortar."
        ),
        "contract": "총액 확정 도급계약, 원가계산에 의한 예정가격 기준 (Lump-sum main contract priced by the cost-calculation method)",
        "headline_cost_krw": "도급공사비 약 570억원 (부가세 별도, 연면적 기준 평당 약 792만원), 총공사비 약 627억원. Contract sum approx. KRW 57.0 billion excluding VAT, approx. KRW 62.7 billion including it, which is about 7.92 million won per pyeong of gross floor area.",
    },
    budget_boq_name="실행예산 내역서 - 서울 2026 (Control budget)",
    planned_budget=57_000_000_000.0,
    actual_spend_ratio=0.38,
    spi_override=0.97,
    cpi_override=1.02,
)
