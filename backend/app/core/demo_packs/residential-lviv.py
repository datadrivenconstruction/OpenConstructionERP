# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

from app.core.demo_projects import DemoTemplate

# ---------------------------------------------------------------------------
# Partner pack: ukraine-ua - Residential Building, Lviv
# ---------------------------------------------------------------------------
# A ten-storey residential building on a monolithic reinforced concrete frame
# with aerated block infill, the common way housing is built in Lviv today,
# with a shelter in the basement.
#
# Every line names the chapter of the зведений кошторисний розрахунок it sits
# in under the ``zkr`` key (Настанова з визначення вартості будівництва,
# наказ Мінрегіону №281 of 01.11.2021, as amended), next to its DIN 276 cost
# group. Unit rates are all-in direct costs at Lviv 2026 levels in UAH
# excluding ПДВ. The cascade stays inside the wartime ceilings of постанова
# КМУ №1512 (general production costs up to 10, administrative up to 3,
# profit up to 15 percent of direct costs) and adds the risk allowance of
# Додаток 28 for housing.
# ---------------------------------------------------------------------------

TEMPLATE = DemoTemplate(
    demo_id="residential-lviv",
    project_name="Багатоквартирний житловий будинок - Львів, Сихів (Residential Building, Lviv)",
    project_description=(
        "Новий десятиповерховий багатоквартирний житловий будинок на 120 "
        "квартир у Сихівському районі Львова, приблизно 9 600 m2 загальної "
        "площі, монолітний залізобетонний каркас із заповненням з "
        "газобетонних блоків, укриття в підвальному поверсі. New ten-storey "
        "residential building with 120 flats in the Sykhiv district of Lviv, "
        "approx. 9,600 m2 gross floor area, monolithic reinforced concrete "
        "frame with aerated block infill and a basement shelter. Priced at "
        "Lviv 2026 levels in UAH excluding VAT."
    ),
    region="UA",
    classification_standard="din276",
    currency="UAH",
    locale="uk",
    address={
        "street": "вулиця Зубрівська 30",
        "city": "Львів",
        "postcode": "79066",
        "country": "Ukraine",
        "lat": 49.7925,
        "lng": 24.0580,
    },
    validation_rule_sets=["ukraine", "din276", "boq_quality"],
    boq_name="Об'єктний кошторис - Житловий будинок, Сихів (Object estimate)",
    boq_description=(
        "Кошторис за главами зведеного кошторисного розрахунку (Настанова, "
        "наказ Мінрегіону №281) із класифікацією за DIN 276. Ціни Львова "
        "2026 року в гривнях, без ПДВ."
    ),
    boq_metadata={
        "standard": "Настанова з визначення вартості будівництва (наказ №281) / DIN 276",
        "phase": "Кошторисна документація, стадія П (Design stage estimate)",
        "base_date": "2026-Q3",
        "price_level": "Львів 2026 (UAH, без ПДВ)",
    },
    sections=[
        (
            "1",
            "Глава 1 - Підготовка території будівництва (Site preparation)",
            {"din276": "210", "zkr": "1"},
            [
                ("1.01", "Демонтаж існуючих складських будівель (Demolish existing sheds)", "m3", 1800, 260, {"din276": "212", "zkr": "1"}),
                ("1.02", "Вертикальне планування ділянки (Site grading)", "m2", 5200, 55, {"din276": "214", "zkr": "1"}),
            ],
        ),
        (
            "2-310",
            "Глава 2 - Земляні роботи і фундаменти (Earthworks and foundations)",
            {"din276": "320", "zkr": "2"},
            [
                ("2.01", "Розробка ґрунту в котловані екскаватором (Bulk excavation)", "m3", 14000, 185, {"din276": "311", "zkr": "2"}),
                ("2.02", "Зворотна засипка пазух котловану (Backfill)", "m3", 4200, 140, {"din276": "311", "zkr": "2"}),
                ("2.03", "Навантаження і вивезення ґрунту (Load and cart away spoil)", "m3", 9800, 210, {"din276": "311", "zkr": "2"}),
                ("2.04", "Буронабивні палі діаметром 620 мм (Bored piles, 620 mm)", "m", 3600, 3000, {"din276": "323", "zkr": "2"}),
                ("2.05", "Монолітна фундаментна плита з бетону C25/30 (Raft foundation)", "m3", 2100, 5200, {"din276": "322", "zkr": "2"}),
                ("2.06", "Арматура А500С фундаментів (Foundation reinforcement)", "t", 260, 42000, {"din276": "322", "zkr": "2"}),
                ("2.07", "Гідроізоляція фундаментів і стін підвалу (Foundation waterproofing)", "m2", 3400, 620, {"din276": "325", "zkr": "2"}),
            ],
        ),
        (
            "2-340",
            "Глава 2 - Монолітний каркас (Reinforced concrete frame)",
            {"din276": "350", "zkr": "2"},
            [
                ("2.08", "Монолітні колони і діафрагми з бетону C30/37 (Columns and shear walls)", "m3", 1200, 5700, {"din276": "343", "zkr": "2"}),
                ("2.09", "Монолітні перекриття з бетону C25/30 (Floor slabs)", "m3", 2300, 5200, {"din276": "351", "zkr": "2"}),
                ("2.10", "Арматура А500С каркаса (Frame reinforcement)", "t", 480, 42000, {"din276": "351", "zkr": "2"}),
                ("2.11", "Щитова опалубка (System formwork)", "m2", 24000, 350, {"din276": "351", "zkr": "2"}),
                ("2.12", "Збірні залізобетонні сходові марші (Precast stair flights)", "pcs", 22, 38000, {"din276": "351", "zkr": "2"}),
            ],
        ),
        (
            "2-330",
            "Глава 2 - Стіни, фасад і покрівля (Walls, facade and roof)",
            {"din276": "330", "zkr": "2"},
            [
                ("2.13", "Кладка зовнішніх стін з газобетонних блоків D500, 300 мм (Aerated block external walls)", "m3", 2300, 3400, {"din276": "332", "zkr": "2"}),
                ("2.14", "Перегородки з газобетонних блоків, 100 мм (Aerated block partitions)", "m2", 9800, 720, {"din276": "342", "zkr": "2"}),
                ("2.15", "Скріплена система теплоізоляції фасаду, мінеральна вата 150 мм (ETICS, mineral wool)", "m2", 7200, 1550, {"din276": "335", "zkr": "2"}),
                ("2.16", "Металопластикові вікна з енергозберігаючими склопакетами (PVC windows)", "m2", 1650, 4600, {"din276": "334", "zkr": "2"}),
                ("2.17", "Огородження балконів (Balcony balustrades)", "m", 1100, 3200, {"din276": "339", "zkr": "2"}),
                ("2.18", "Вхідні металеві двері квартир (Flat entrance steel doors)", "pcs", 120, 14500, {"din276": "344", "zkr": "2"}),
                ("2.19", "Плоска покрівля з ПВХ мембраною та утепленням (Flat roof, PVC membrane)", "m2", 1050, 1650, {"din276": "363", "zkr": "2"}),
            ],
        ),
        (
            "2-345",
            "Глава 2 - Оздоблювальні роботи та укриття (Finishes and shelter)",
            {"din276": "340", "zkr": "2"},
            [
                ("2.20", "Механізована штукатурка стін (Machine-applied plaster)", "m2", 26000, 300, {"din276": "345", "zkr": "2"}),
                ("2.21", "Стяжка підлоги з тепло- і звукоізоляцією (Insulated floor screed)", "m2", 8000, 560, {"din276": "352", "zkr": "2"}),
                ("2.22", "Оздоблення місць загального користування (Common area finishes)", "m2", 1400, 2000, {"din276": "352", "zkr": "2"}),
                ("2.23", "Облаштування укриття в підвальному поверсі (Basement shelter fit-out)", "m2", 650, 4800, {"din276": "349", "zkr": "2"}),
            ],
        ),
        (
            "2-400",
            "Глава 2 - Інженерні системи (Building services)",
            {"din276": "400", "zkr": "2"},
            [
                ("2.24", "Внутрішні водопровід і каналізація (Water supply and drainage)", "m2", 9600, 650, {"din276": "412", "zkr": "2"}),
                ("2.25", "Індивідуальний тепловий пункт (Heat substation)", "pcs", 1, 3200000, {"din276": "421", "zkr": "2"}),
                ("2.26", "Опалення з поквартирним обліком тепла (Heating with per-flat metering)", "m2", 9600, 800, {"din276": "422", "zkr": "2"}),
                ("2.27", "Вентиляція з механічним витяжним побудженням (Mechanical extract ventilation)", "m2", 9600, 180, {"din276": "431", "zkr": "2"}),
                ("2.28", "Електропостачання та освітлення (Power and lighting)", "m2", 9600, 700, {"din276": "444", "zkr": "2"}),
                ("2.29", "Резервне живлення ліфтів і укриття, дизель-генератор (Standby generator for lifts and shelter)", "pcs", 1, 2000000, {"din276": "442", "zkr": "2"}),
                ("2.30", "Слабкострумні мережі та домофон (Low-current systems and door entry)", "m2", 9600, 160, {"din276": "451", "zkr": "2"}),
                ("2.31", "Пожежна сигналізація та оповіщення (Fire alarm and voice alarm)", "m2", 9600, 210, {"din276": "456", "zkr": "2"}),
                ("2.32", "Пасажирські ліфти 1 000 кг (Passenger lifts, 1,000 kg)", "pcs", 3, 2100000, {"din276": "461", "zkr": "2"}),
            ],
        ),
        (
            "6",
            "Глава 6 - Зовнішні мережі та споруди (External networks)",
            {"din276": "540", "zkr": "6"},
            [
                ("6.01", "Зовнішні мережі водопостачання і каналізації (External water and sewer)", "m", 420, 9500, {"din276": "540", "zkr": "6"}),
                ("6.02", "Трансформаторна підстанція та зовнішні електромережі 0,4 кВ (Substation and external cabling)", "lsum", 1, 5000000, {"din276": "225", "zkr": "6"}),
            ],
        ),
        (
            "7",
            "Глава 7 - Благоустрій та озеленення території (External works and landscaping)",
            {"din276": "500", "zkr": "7"},
            [
                ("7.01", "Проїзди і тротуари з бетонної бруківки (Block paved roads and footpaths)", "m2", 3600, 1000, {"din276": "520", "zkr": "7"}),
                ("7.02", "Озеленення та дитячий майданчик (Planting and playground)", "m2", 2200, 650, {"din276": "570", "zkr": "7"}),
            ],
        ),
        (
            "2-extra",
            "Глава 2 - Додаткові конструктивні роботи та інженерія (Complementary works and services)",
            {"din276": "340", "zkr": "2"},
            [
                ("2.33", "Підвіконня ПВХ (PVC window boards)", "m", 1300, 450, {"din276": "334", "zkr": "2"}),
                ("2.34", "Утеплення перекриття над підвалом (Insulation to basement soffit)", "m2", 1000, 620, {"din276": "354", "zkr": "2"}),
                ("2.35", "Звукоізоляція міжквартирних стін (Sound insulation to party walls)", "m2", 3200, 380, {"din276": "342", "zkr": "2"}),
                ("2.36", "Облицювання цоколя клінкерною плиткою (Clinker tiles to plinth)", "m2", 380, 1900, {"din276": "335", "zkr": "2"}),
                ("2.37", "Козирки над входами (Entrance canopies)", "pcs", 3, 65000, {"din276": "339", "zkr": "2"}),
                ("2.38", "Вхідні двері під'їздів (Entrance doors to stair cores)", "pcs", 3, 42000, {"din276": "334", "zkr": "2"}),
                ("2.39", "Протипожежні двері EI 30 (Fire doors EI 30)", "pcs", 24, 16000, {"din276": "344", "zkr": "2"}),
                ("2.40", "Поштові скриньки та навігація (Mailboxes and wayfinding)", "lsum", 1, 180000, {"din276": "381", "zkr": "2"}),
                ("2.41", "Внутрішні водостоки (Internal rainwater drainage)", "m2", 1050, 420, {"din276": "411", "zkr": "2"}),
                ("2.42", "Насосна станція підвищення тиску (Booster pump station)", "pcs", 1, 650000, {"din276": "412", "zkr": "2"}),
                ("2.43", "Поквартирні лічильники води і тепла (Per-flat water and heat meters)", "pcs", 120, 9500, {"din276": "422", "zkr": "2"}),
                ("2.44", "Блискавкозахист (Lightning protection)", "lsum", 1, 240000, {"din276": "446", "zkr": "2"}),
                ("2.45", "Диспетчеризація ліфтів (Lift monitoring)", "lsum", 1, 320000, {"din276": "461", "zkr": "2"}),
                ("2.46", "Відеоспостереження (CCTV)", "lsum", 1, 280000, {"din276": "456", "zkr": "2"}),
            ],
        ),
        (
            "7b",
            "Глава 7 - Зовнішнє освітлення та майданчики (External lighting and yards)",
            {"din276": "500", "zkr": "7"},
            [
                ("7.03", "Зовнішнє освітлення території (External lighting)", "m2", 5000, 60, {"din276": "540", "zkr": "7"}),
                ("7.04", "Контейнерний майданчик для відходів (Refuse container yard)", "pcs", 1, 350000, {"din276": "550", "zkr": "7"}),
            ],
        ),
        (
            "8",
            "Глава 8 - Тимчасові будівлі і споруди (Temporary buildings and works)",
            {"din276": "390", "zkr": "8"},
            [
                ("8.01", "Тимчасові будівлі, огородження та охорона (Site buildings, hoarding and security)", "month", 26, 200000, {"din276": "391", "zkr": "8"}),
                ("8.02", "Баштовий кран (Tower crane)", "month", 18, 320000, {"din276": "391", "zkr": "8"}),
            ],
        ),
    ],
    # Risk is a percentage of chapters 1 to 12, which hold the general
    # production costs but not profit or administrative costs, so it follows
    # the first line cumulatively and precedes the other two.
    markups=[
        ("Загальновиробничі витрати (General production costs)", 9.0, "overhead", "direct_cost"),
        ("Кошти на покриття ризиків (Risk allowance)", 1.8, "contingency", "cumulative"),
        ("Адміністративні витрати (Administrative costs)", 2.5, "overhead", "direct_cost"),
        ("Кошторисний прибуток (Profit)", 7.0, "profit", "direct_cost"),
        ("ПДВ 20% (VAT)", 20.0, "tax", "cumulative"),
    ],
    total_months=26,
    tender_name="Генеральний підряд - Житловий будинок, Сихів",
    tender_companies=[
        ("Галбуд Інвест ТОВ", "tender@galbud-invest.example", 0.97),
        ("Львівська будівельна група ТОВ", "zakupivli@lviv-bud-group.example", 1.02),
        ("Карпатбудмонтаж ПрАТ", "oferta@karpatbudmontazh.example", 1.05),
    ],
    tender_packages=[
        (
            "Каркас, стіни та фасад (Frame, walls and facade)",
            "Земляні роботи, палі, монолітний каркас, кладка, фасад і покрівля",
            "evaluating",
            [
                ("Галбуд Інвест ТОВ", "tender@galbud-invest.example", 0.97),
                ("Львівська будівельна група ТОВ", "zakupivli@lviv-bud-group.example", 1.02),
                ("Карпатбудмонтаж ПрАТ", "oferta@karpatbudmontazh.example", 1.05),
            ],
        ),
        (
            "Інженерні системи (Building services)",
            "Водопровід, каналізація, опалення, електрика, ліфти і слабкі струми",
            "draft",
            [
                ("Західенергомонтаж ТОВ", "tender@zakhidenergomontazh.example", 1.00),
                ("Теплосервіс Львів ТОВ", "info@teploservis-lviv.example", 1.04),
            ],
        ),
    ],
    project_metadata={
        "address": "вулиця Зубрівська 30, 79066 Львів, Ukraine",
        "client": "ТОВ «Сихів Житло Девелопмент»",
        "architect": "Архітектурна майстерня «Високий Замок»",
        "structural_engineer": "Конструктивне бюро «Галицький каркас»",
        "gfa_m2": 9600,
        "storeys_above": 10,
        "storeys_below": 1,
        "units": 120,
        "consequence_class": "CC2 (ДБН В.1.2-14:2018)",
        "construction_standards": [
            "Настанова з визначення вартості будівництва, наказ Мінрегіону №281 від 01.11.2021",
            "ДБН В.2.2-15:2019 - Житлові будинки. Основні положення",
            "ДБН В.1.2-14:2018 - Загальні принципи забезпечення надійності та конструктивної безпеки",
        ],
        "vat_note": "Усі ціни без ПДВ. ПДВ 20% нараховується на підсумок.",
    },
)
