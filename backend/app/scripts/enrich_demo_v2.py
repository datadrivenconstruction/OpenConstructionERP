"""Phase 2 deep enrichment of the 5 demo projects.

This complements ``seed_demo_v2.py``: that script created the projects,
contacts, tasks, finance, BIM models. This script adds:

  * One DWG drawing per project (uploaded via API)
  * One PDF takeoff document per project (uploaded via API)
  * Rich BOQ content (sections + 3-5 leaves each), ~30-50 positions per
    project, with proper locale-aware text + classification codes.
  * BIM-element ↔ BOQ-position links (5-50 elements per leaf).
  * DWG-annotation ↔ BOQ-position links (5-10 leaves)
  * PDF-measurement ↔ BOQ-position links (4-6 leaves)
  * Schedule activities (5-8 per project, with 4D EAC links)
  * RFIs (3-5 per project)
  * Change orders (2-3 per project + 1-3 line items each)
  * Cost snapshots (baseline + current)
  * Two extra validation reports per project (BOQ-quality + BIM-compliance)

Idempotent: every row written is tagged in metadata with
``source: enrich_v2`` and a stable ``slot`` so re-runs skip already-present
rows. The script never deletes anything.

Usage::

    cd backend && python -m app.scripts.enrich_demo_v2

Backend must be running on http://localhost:8000.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import pathlib
import sqlite3
import sys
import time
import traceback
import uuid
from typing import Any

import httpx

# Force UTF-8 for Windows consoles; otherwise CN/DE strings blow up.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ── Configuration ────────────────────────────────────────────────────────

BASE = "http://localhost:8000"
ADMIN_EMAIL = "demo@openestimator.io"
ADMIN_PASSWORD = "DemoPass1234!"

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
BACKEND_DIR = REPO_ROOT / "backend"
DB_PATH = BACKEND_DIR / "openestimate.db"

CAD_SOURCE_DIR = pathlib.Path(
    r"C:\Users\Artem Boiko\Downloads\cad2data-Revit-IFC-DWG-DGN-main"
    r"\cad2data-Revit-IFC-DWG-DGN-main\Sample_Projects\test"
)

# Stable tag we put in metadata.source for everything we create here.
SOURCE_TAG = "enrich_v2"

TODAY = dt.date.today()


# ── Project specs ────────────────────────────────────────────────────────

# (key, project_id, locale, currency, dwg_file, pdf_file, section_specs)
# section_specs: list of (section_code, section_label, leaves)
# leaves: list of (leaf_label, unit, regional_rate, classification_dict, bim_element_type_filter)
#   bim_element_type_filter: substring or list of substrings. If list, any
#   element type containing any substring matches.

# Rotation of CAD/PDF files across the 5 projects
DWG_FILES = {
    "us": ("Example_House_Project_DDC.dwg", "civil_example-imperial.dwg"),
    "de": ("architectural_example-imperial.dwg", "Example_House_Project_DDC.dwg"),
    "es": ("Example_House_Project_DDC.dwg", "architectural_example-imperial.dwg"),
    "br": ("civil_example-imperial.dwg", "Example_House_Project_DDC.dwg"),
    "cn": ("architectural_example-imperial.dwg", "civil_example-imperial.dwg"),
}
PDF_FILES = {
    "us": "Housing design standards LPG.pdf",
    "de": "Housing design standards2 LPG.pdf",
    "es": "Housing design standards LPG.pdf",
    "br": "Housing design standards2 LPG.pdf",
    "cn": "Housing design standards LPG.pdf",
}

# Per-locale BOQ section + leaf templates. Each section has:
#   (section_code, section_label, [leaves])
# Each leaf is:
#   (description, unit, unit_rate, classification, element_type_match)
# element_type_match is a list — the leaf links to BIM elements whose
# element_type contains any of those substrings.
PROJECT_SPECS: dict[str, dict[str, Any]] = {
    "us": {
        "project_id": "9486f966-fbc8-42df-b52a-a807ef339d27",
        "locale": "en",
        "currency": "USD",
        "boq_name": "Bill of Quantities — Main Trades",
        "boq_description": "Element-by-element quantity takeoff derived from the BIM model, organized per MasterFormat division.",
        "sections": [
            ("03 30 00", "Cast-in-Place Concrete", [
                ("Concrete walls — 5,000 psi cast-in-place", "sf", 28.50, {"masterformat": "03 30 00", "csi": "Division 03"}, ["Wall"]),
                ("Concrete slabs on grade — 6 in thick", "sf", 12.00, {"masterformat": "03 30 00"}, ["Slab"]),
                ("Concrete footings — spread + strip", "cy", 285.00, {"masterformat": "03 31 00"}, ["Footing"]),
                ("Concrete columns — 24x24 in", "ea", 1450.00, {"masterformat": "03 30 00"}, ["Column"]),
            ]),
            ("04 20 00", "Unit Masonry", [
                ("CMU walls — 8 in nominal", "sf", 18.50, {"masterformat": "04 22 00"}, ["WallStandard"]),
                ("Brick veneer — modular", "sf", 24.00, {"masterformat": "04 21 00"}, ["WallStandard"]),
            ]),
            ("05 12 00", "Structural Steel Framing", [
                ("Wide flange beams — A992 grade 50", "lf", 65.00, {"masterformat": "05 12 00"}, ["Beam"]),
                ("Steel members — secondary framing", "ea", 185.00, {"masterformat": "05 12 00"}, ["Member"]),
                ("Curtain wall mullions — alum", "lf", 75.00, {"masterformat": "08 44 16"}, ["Mullion"]),
            ]),
            ("05 50 00", "Metal Fabrications", [
                ("Steel railings — guard, picket", "lf", 95.00, {"masterformat": "05 52 00"}, ["Railing"]),
                ("Stair stringers — channel form", "ea", 1150.00, {"masterformat": "05 51 00"}, ["Stair"]),
            ]),
            ("07 50 00", "Membrane Roofing", [
                ("TPO roofing membrane — 60 mil", "sf", 14.00, {"masterformat": "07 54 23"}, ["Roof"]),
            ]),
            ("08 11 00", "Metal Doors and Frames", [
                ("Hollow-metal doors — 3'-0\"x7'-0\"", "ea", 950.00, {"masterformat": "08 11 13"}, ["Door"]),
                ("Door openings — frame allowance", "ea", 285.00, {"masterformat": "08 11 00"}, ["Opening"]),
            ]),
            ("08 50 00", "Windows", [
                ("Aluminum-frame windows — fixed", "ea", 720.00, {"masterformat": "08 51 13"}, ["Window"]),
                ("Curtain wall panels — IGU", "sf", 105.00, {"masterformat": "08 44 13"}, ["CurtainPanel", "Curtain Panels", "Panel"]),
            ]),
            ("09 50 00", "Ceilings", [
                ("Suspended acoustical ceiling tile", "sf", 8.50, {"masterformat": "09 51 13"}, ["Ceiling", "Covering"]),
            ]),
            ("12 50 00", "Furnishings", [
                ("Office furniture — workstation pkg", "ea", 480.00, {"masterformat": "12 56 00"}, ["Furnishing", "Furniture"]),
            ]),
            ("01 10 00", "General Requirements", [
                ("Spaces — informational rollup", "sf", 0.10, {"masterformat": "01 10 00"}, ["Space"]),
                ("Coordination & meetings — lump", "ls", 25000.00, {"masterformat": "01 31 00"}, []),
            ]),
            ("31 10 00", "Site Clearing", [
                ("Site grading & clearing — lump", "ls", 18500.00, {"masterformat": "31 10 00"}, []),
            ]),
        ],
    },
    "de": {
        "project_id": "000be1c4-75e2-4be6-a0da-950ae8e2a801",
        "locale": "de",
        "currency": "EUR",
        "boq_name": "Leistungsverzeichnis — Hauptgewerke",
        "boq_description": "Element-Mengenermittlung aus dem BIM-Modell, gegliedert nach Kostengruppen DIN 276.",
        "sections": [
            ("320", "Gründung", [
                ("Streifenfundamente C25/30 inkl. Bewehrung", "m³", 285.00, {"din276": "322"}, ["Footing"]),
                ("Bodenplatte 25 cm C30/37 wasserundurchlässig", "m²", 110.00, {"din276": "324"}, ["Slab"]),
            ]),
            ("330", "Außenwände", [
                ("Stahlbetonwand 24 cm C30/37 mit Schalung", "m²", 95.00, {"din276": "331"}, ["Wall", "WallStandard"]),
                ("Wärmedämmverbundsystem 14 cm Mineralwolle", "m²", 78.00, {"din276": "335"}, ["Wall"]),
                ("Fenster Holz-Alu, 3-fach Verglasung", "Stk", 720.00, {"din276": "334"}, ["Window"]),
                ("Vorhangfassade — Pfosten-Riegel-System", "m²", 380.00, {"din276": "334"}, ["CurtainPanel", "Member"]),
            ]),
            ("340", "Innenwände", [
                ("Tragende Innenwand Stahlbeton 20 cm", "m²", 88.00, {"din276": "341"}, ["Wall"]),
                ("Innentüren CPL, 1-flügelig 88,5 cm", "Stk", 420.00, {"din276": "344"}, ["Door"]),
                ("Türöffnungen — Zargenpauschale", "Stk", 145.00, {"din276": "344"}, ["Opening"]),
            ]),
            ("350", "Decken", [
                ("Stahlbetondecke 22 cm C25/30 zweiseitig gespannt", "m²", 110.00, {"din276": "351"}, ["Slab"]),
                ("Treppenanlage Stahlbeton inkl. Geländer", "Stk", 4200.00, {"din276": "351"}, ["Stair"]),
                ("Geländer Stahl, feuerverzinkt", "m", 145.00, {"din276": "352"}, ["Railing"]),
            ]),
            ("360", "Dächer", [
                ("Flachdachabdichtung 2-lagig + Dämmung 22 cm", "m²", 165.00, {"din276": "361"}, ["Roof"]),
            ]),
            ("370", "Baukonstruktive Einbauten", [
                ("Allgemeine Ausstattung, Möblierung", "Stk", 280.00, {"din276": "611"}, ["Furnishing"]),
            ]),
            ("390", "Sonstige Maßnahmen", [
                ("Tragende Bauteile — sonstige Träger", "m", 1450.00, {"din276": "331"}, ["Beam"]),
                ("Hilfsgeometrie und virtuelle Elemente", "Stk", 25.00, {"din276": "390"}, ["Virtual"]),
            ]),
            ("100", "Grundstück / Spaces", [
                ("Räume — informativ (BGF Rollup)", "m²", 0.10, {"din276": "100"}, ["Space"]),
                ("Beschriftungen / Annotation", "Stk", 0.00, {"din276": "100"}, ["Annotation"]),
            ]),
        ],
    },
    "es": {
        "project_id": "444a80b3-e667-402c-ae8b-60875c2cc2e9",
        "locale": "es",
        "currency": "EUR",
        "boq_name": "Mediciones y Presupuesto — Obras Principales",
        "boq_description": "Mediciones automáticas extraídas del modelo BIM, organizadas por capítulos según la estructura del proyecto.",
        "sections": [
            ("1.1", "Movimiento de tierras y cimentación", [
                ("Hormigón armado HA-25 en zapatas", "m³", 245.00, {"custom": "1.1.1"}, ["Footing"]),
                ("Solera de hormigón HA-25, e=15 cm", "m²", 92.00, {"custom": "1.1.2"}, ["Slab"]),
                ("Replanteo y nivelación general", "ud", 850.00, {"custom": "1.1.3"}, []),
            ]),
            ("1.2", "Estructura de hormigón", [
                ("Muro de hormigón armado HA-30, e=24 cm", "m²", 105.00, {"custom": "1.2.1"}, ["Wall", "WallStandard"]),
                ("Pilares de hormigón armado", "ud", 1250.00, {"custom": "1.2.2"}, ["Column"]),
                ("Vigas de hormigón armado HA-30", "m", 78.00, {"custom": "1.2.3"}, ["Beam"]),
            ]),
            ("1.3", "Forjados y losas", [
                ("Forjado unidireccional, canto 30 cm", "m²", 92.00, {"custom": "1.3.1"}, ["Slab"]),
                ("Escalera de hormigón armado", "ud", 3800.00, {"custom": "1.3.2"}, ["Stair"]),
            ]),
            ("1.4", "Cubiertas", [
                ("Cubierta plana invertida, lámina EPDM", "m²", 138.00, {"custom": "1.4.1"}, ["Roof"]),
            ]),
            ("1.5", "Cerramientos exteriores", [
                ("Fachada de fábrica vista de ladrillo", "m²", 95.00, {"custom": "1.5.1"}, ["WallStandard"]),
                ("Carpintería exterior aluminio RPT", "ud", 380.00, {"custom": "1.5.2"}, ["Window"]),
                ("Muro cortina — paneles de vidrio", "m²", 320.00, {"custom": "1.5.3"}, ["CurtainPanel", "Curtain Panels"]),
            ]),
            ("1.6", "Carpintería interior", [
                ("Puerta de paso DM lacada blanca", "ud", 380.00, {"custom": "1.6.1"}, ["Door"]),
                ("Huecos de paso — premarcos", "ud", 95.00, {"custom": "1.6.2"}, ["Opening"]),
            ]),
            ("1.7", "Acabados y revestimientos", [
                ("Falso techo de placa de yeso laminado", "m²", 28.00, {"custom": "1.7.1"}, ["Ceiling", "Covering"]),
            ]),
            ("1.8", "Equipamiento", [
                ("Mobiliario y equipamiento general", "ud", 240.00, {"custom": "1.8.1"}, ["Furnishing"]),
                ("Barandillas de acero inoxidable", "m", 145.00, {"custom": "1.8.2"}, ["Railing"]),
            ]),
            ("1.9", "Instalaciones (informativo)", [
                ("Espacios y zonificación — informativo", "m²", 0.10, {"custom": "1.9.1"}, ["Space"]),
                ("Elementos auxiliares — montantes muro cortina", "m", 75.00, {"custom": "1.9.2"}, ["Member", "Mullion"]),
            ]),
        ],
    },
    "br": {
        "project_id": "3e365738-e7bf-4a5c-822a-8cb694774774",
        "locale": "pt",
        "currency": "BRL",
        "boq_name": "Planilha Orçamentária — Serviços Principais",
        "boq_description": "Quantitativos extraídos do modelo BIM, organizados por macro-serviços segundo padrão SINAPI.",
        "sections": [
            ("01.01", "Serviços preliminares", [
                ("Locação e topografia da obra", "vb", 4200.00, {"custom": "01.01.001"}, []),
                ("Instalação do canteiro de obras", "vb", 18500.00, {"custom": "01.01.002"}, []),
            ]),
            ("01.02", "Fundações", [
                ("Fundação direta — sapatas de concreto", "m³", 740.00, {"custom": "01.02.001"}, ["Foundation"]),
                ("Lastro de concreto magro e=5 cm", "m²", 92.00, {"custom": "01.02.002"}, []),
            ]),
            ("01.03", "Estrutura de concreto", [
                ("Pilares estruturais de concreto armado", "un", 3200.00, {"custom": "01.03.001"}, ["Column"]),
                ("Lajes maciças de concreto armado", "m²", 220.00, {"custom": "01.03.002"}, ["Floors", "Slab"]),
                ("Vigas de concreto armado", "m", 280.00, {"custom": "01.03.003"}, ["Beam"]),
            ]),
            ("01.04", "Alvenaria e fechamentos", [
                ("Alvenaria de bloco cerâmico 14 cm", "m²", 165.00, {"custom": "01.04.001"}, ["Wall"]),
                ("Pele de vidro / fachada cortina", "m²", 850.00, {"custom": "01.04.002"}, ["Curtain Wall Panels", "Panel"]),
                ("Montantes de fachada metálicos", "m", 285.00, {"custom": "01.04.003"}, ["Curtain Wall Mullions", "Mullion"]),
            ]),
            ("01.05", "Cobertura e impermeabilização", [
                ("Cobertura impermeabilizada com manta EPDM", "m²", 285.00, {"custom": "01.05.001"}, ["Roof"]),
            ]),
            ("01.06", "Esquadrias", [
                ("Porta interna em madeira maciça", "un", 920.00, {"custom": "01.06.001"}, ["Door"]),
                ("Janela em alumínio com vidro temperado", "un", 850.00, {"custom": "01.06.002"}, ["Window"]),
            ]),
            ("01.07", "Acabamentos internos", [
                ("Forro de gesso acartonado", "m²", 78.00, {"custom": "01.07.001"}, ["Ceilings", "Ceiling"]),
            ]),
            ("01.08", "Equipamentos e mobiliário", [
                ("Mobiliário fixo — armários planejados", "un", 540.00, {"custom": "01.08.001"}, ["Furniture"]),
                ("Guarda-corpos em aço pintado", "m", 285.00, {"custom": "01.08.002"}, ["Stairs Railing", "Railing"]),
                ("Instalações elétricas — luminárias", "un", 320.00, {"custom": "01.08.003"}, ["Lighting"]),
            ]),
            ("01.09", "Hidráulica e instalações", [
                ("Aparelhos sanitários — louça e metais", "un", 1850.00, {"custom": "01.09.001"}, ["Plumbing"]),
                ("Tubulações e conexões — diversas", "vb", 22000.00, {"custom": "01.09.002"}, ["Wire", "Fluids"]),
            ]),
            ("01.10", "Diversos / informativo", [
                ("Ambientes e zoneamento — informativo", "m²", 0.10, {"custom": "01.10.001"}, ["Rooms"]),
                ("Modelos genéricos e itens auxiliares", "un", 60.00, {"custom": "01.10.002"}, ["Generic"]),
            ]),
        ],
    },
    "cn": {
        "project_id": "a34e46e5-3b6c-4228-85af-1df2a6b09ec0",
        "locale": "zh",
        "currency": "CNY",
        "boq_name": "工程量清单 — 主要分部分项",
        "boq_description": "由 BIM 模型自动提取的工程量,按主要分部分项组织。",
        "sections": [
            ("甲", "土建结构工程", [
                ("钢筋混凝土剪力墙 C30, 厚度 240mm", "m²", 480.00, {"custom": "甲.1"}, ["Walls", "Wall"]),
                ("钢筋混凝土柱 C30, 截面 600x600", "根", 8500.00, {"custom": "甲.2"}, ["Structural Columns", "Column"]),
                ("钢筋混凝土梁 C30", "m", 380.00, {"custom": "甲.3"}, ["Structural Framing", "Beam"]),
                ("钢筋混凝土楼板 C30, 厚度 120mm", "m²", 320.00, {"custom": "甲.4"}, ["Floors", "Slab"]),
            ]),
            ("乙", "幕墙与外围护工程", [
                ("玻璃幕墙板单元 (含五金)", "块", 1850.00, {"custom": "乙.1"}, ["Curtain Wall Panels"]),
                ("幕墙竖向龙骨 — 铝合金型材", "m", 285.00, {"custom": "乙.2"}, ["Curtain Wall Mullions"]),
                ("幕墙横向龙骨", "m", 245.00, {"custom": "乙.3"}, ["Curtain Grids Wall"]),
                ("屋面幕墙网格", "m", 280.00, {"custom": "乙.4"}, ["Curtain Grids Roof"]),
            ]),
            ("丙", "门窗工程", [
                ("木门 + 五金 — 标准房间门", "樘", 1850.00, {"custom": "丙.1"}, ["Doors"]),
                ("断桥铝合金窗 (含玻璃)", "樘", 2400.00, {"custom": "丙.2"}, ["Windows"]),
            ]),
            ("丁", "楼梯及栏杆", [
                ("楼梯踏步及防滑条", "m", 480.00, {"custom": "丁.1"}, ["Stairs Sketch Riser Lines"]),
                ("楼梯边界放样线 — 信息化处理", "m", 0.50, {"custom": "丁.2"}, ["Stairs Sketch Boundary Lines"]),
                ("楼梯栏杆 + 立柱 (栏杆扶手成套)", "m", 685.00, {"custom": "丁.3"}, ["Stairs Railing"]),
                ("栏杆立柱", "根", 220.00, {"custom": "丁.4"}, ["Stairs Railing Baluster"]),
            ]),
            ("戊", "顶棚与装饰", [
                ("吊顶 — 矿棉板吊顶", "m²", 165.00, {"custom": "戊.1"}, ["Ceilings"]),
                ("通用模型 / 装饰构件", "件", 240.00, {"custom": "戊.2"}, ["Generic Model"]),
            ]),
            ("己", "机电与设备", [
                ("照明灯具 — 标准房间配置", "套", 480.00, {"custom": "己.1"}, ["Lighting Fixtures"]),
                ("家具 (含办公及生活)", "件", 1850.00, {"custom": "己.2"}, ["Furniture"]),
            ]),
            ("庚", "总图及配套", [
                ("停车位 / 划线", "个", 850.00, {"custom": "庚.1"}, ["Parking"]),
                ("房间 / 空间 — 信息汇总", "m²", 0.10, {"custom": "庚.2"}, ["Rooms"]),
            ]),
        ],
    },
}


# Locale-specific formatting helpers
LOCALE_PROGRESS = {
    "en": ("Q1 — site mobilization", "Q2 — substructure complete", "Q3 — superstructure to L3"),
    "de": ("KW10 — Baustelleneinrichtung", "KW20 — Rohbau Gründung", "KW30 — Rohbau bis 3.OG"),
    "es": ("Trim. 1 — implantación", "Trim. 2 — cimentación", "Trim. 3 — estructura"),
    "pt": ("Trim. 1 — canteiro", "Trim. 2 — fundações", "Trim. 3 — estrutura"),
    "zh": ("第一阶段 — 进场", "第二阶段 — 基础结构", "第三阶段 — 上部结构"),
}


# RFI templates per locale
RFI_TEMPLATES: dict[str, list[tuple[str, str, str | None]]] = {
    "en": [
        ("Clearance between curtain wall anchor and perimeter beam",
         "Drawing A-301 shows 50mm clearance but structural BIM gives 35mm. Please confirm acceptable tolerance.", "answered"),
        ("Substitution request — TPO membrane manufacturer",
         "Architect-specified manufacturer has 14-week lead time. Approved equal alternate?", "open"),
        ("Foundation — pile cap reinforcement at column line D-3",
         "Conflicting rebar layouts between drawings S-201 and S-203. Which shall govern?", "answered"),
        ("Door schedule clarification — type HM-3 hardware group",
         "Door HM-3 missing closer in hardware group on schedule sheet. Please confirm.", "closed"),
        ("MEP coordination — duct routing through transfer beam at L3",
         "Mechanical drawings show 18in duct passing through structural transfer beam. Coordination needed.", "open"),
    ],
    "de": [
        ("Lichte Höhe zwischen Pfosten und Brüstung",
         "Detail D-22 zeigt 1,10 m, Statik fordert 1,15 m. Bitte freigeben oder Anpassung anweisen.", "answered"),
        ("Materialwahl — Wärmepumpe statt Fernwärme",
         "Wirtschaftlichkeitsvergleich liegt vor. Bauherrenentscheid bis Werkplanung erforderlich.", "open"),
        ("Bewehrung Bodenplatte — Achse 3-A",
         "Statik-Plan und Schalplan widersprüchlich. Welcher gilt?", "answered"),
        ("Türliste — Zargenmaße TX-12",
         "TX-12 in Türliste ohne Zargen-Detail. Bitte ergänzen.", "closed"),
    ],
    "es": [
        ("Distancia entre anclaje de muro cortina y viga perimetral",
         "El plano A-301 muestra 50mm pero el BIM estructural da 35mm. Confirmar tolerancia.", "answered"),
        ("Solicitud de sustitución — sistema de aerotermia",
         "Comparativa económica entregada. Decisión del promotor antes de visado.", "open"),
        ("Cimentación — armado en encepado pilar 3-D",
         "Discrepancia entre planos S-201 y S-203. ¿Cuál prevalece?", "answered"),
        ("Memoria de calidades — pavimento baños",
         "El plano dice gres porcelánico, pero la memoria menciona porcelánico rectificado.", "closed"),
    ],
    "pt": [
        ("Compatibilidade entre ancoragem da pele de vidro e viga",
         "Detalhamento estrutural mostra 30mm e desenho de fachada exige 50mm. Confirmar.", "answered"),
        ("Substituição — sistema de climatização",
         "Análise comparativa apresentada. Decisão do contratante necessária.", "open"),
        ("Fundação — armadura no bloco do pilar P-12",
         "Pranchas estruturais com indicações divergentes. Qual prevalece?", "answered"),
        ("Esquadrias internas — kit de ferragens",
         "Tipo PI-3 sem mola hidráulica no caderno. Confirmar.", "closed"),
    ],
    "zh": [
        ("幕墙锚固件与外圈梁的间距",
         "建筑图A-301标注50mm,结构BIM给出35mm,请确认允差。", "answered"),
        ("材料替代申请 — 屋面防水膜厂家",
         "设计指定厂家供货周期长。是否可批准等同替代?", "open"),
        ("基础 — D-3轴桩承台配筋",
         "S-201与S-203两张图配筋不一致,以哪张为准?", "answered"),
        ("门窗表 — HM-3型号五金组",
         "HM-3门表中漏闭门器,请补充确认。", "closed"),
    ],
}


# Change order templates per locale
CO_TEMPLATES: dict[str, list[tuple[str, str, float, list[tuple[str, str, float, float]]]]] = {
    # (code_suffix, title, total_cost_impact, [(item_desc, unit, qty, rate)])
    "en": [
        ("CO-001", "Owner-requested upgrade — premium curtain wall glazing", 145000.00, [
            ("Upgrade IGU to triple-pane low-e", "sf", 4200.0, 28.50),
            ("Additional structural anchorage", "ea", 24.0, 850.00),
        ]),
        ("CO-002", "Field-found unsuitable soil — additional excavation", 38500.00, [
            ("Unsuitable soil removal & disposal", "cy", 285.0, 95.00),
            ("Engineered fill replacement", "cy", 285.0, 42.50),
        ]),
    ],
    "de": [
        ("NA-001", "Bauherrenwunsch — höherwertige Fassadenverglasung", 28500.00, [
            ("Upgrade auf 3-fach Verglasung Ug 0,5", "m²", 240.0, 95.00),
            ("Zusatzaufwand Befestigung Pfostenrieg", "Stk", 18.0, 320.00),
        ]),
        ("NA-002", "Erschwerte Gründung — Bodenaustausch", 18200.00, [
            ("Bodenaustausch unterhalb Bodenplatte", "m³", 145.0, 95.00),
            ("Verdichtetes Trag- und Frostschutzmaterial", "m³", 145.0, 30.00),
        ]),
    ],
    "es": [
        ("CO-001", "Modificación a petición del promotor — calidad acabados", 12500.00, [
            ("Mejora pavimento gres porcelánico", "m²", 180.0, 45.00),
            ("Sanitarios gama alta", "ud", 6.0, 720.00),
        ]),
        ("CO-002", "Imprevistos en cimentación — refuerzo zapatas", 8800.00, [
            ("Excavación adicional", "m³", 32.0, 85.00),
            ("Hormigón armado adicional HA-25", "m³", 14.0, 245.00),
        ]),
    ],
    "pt": [
        ("CT-001", "Modificação a pedido do contratante — pele de vidro premium", 38500.00, [
            ("Substituição por vidro insulado low-e", "m²", 85.0, 320.00),
            ("Ancoragens estruturais adicionais", "un", 18.0, 685.00),
        ]),
        ("CT-002", "Solo inadequado — substituição em parte do terreno", 22000.00, [
            ("Remoção e bota-fora de solo mole", "m³", 95.0, 145.00),
            ("Aterro estabilizado granular", "m³", 95.0, 85.00),
        ]),
    ],
    "zh": [
        ("BG-001", "业主变更 — 幕墙玻璃升级为三玻两腔", 285000.00, [
            ("玻璃升级 Low-E 三玻两腔", "块", 320.0, 580.00),
            ("增加幕墙锚固构件", "件", 80.0, 1250.00),
        ]),
        ("BG-002", "地基不良 — 软基处理", 86500.00, [
            ("软土外运及处置", "m³", 220.0, 185.00),
            ("级配碎石回填", "m³", 220.0, 95.00),
        ]),
    ],
}


SCHEDULE_TEMPLATES: dict[str, list[tuple[str, str, int, int]]] = {
    # (wbs_code, name, days_offset_from_project_start, duration_days)
    "en": [
        ("01", "Site mobilization & preparation", 0, 14),
        ("02", "Excavation & site grading", 14, 21),
        ("03", "Foundations & substructure", 30, 45),
        ("04", "Structural concrete & steel frame", 60, 90),
        ("05", "Building envelope & curtain wall", 130, 75),
        ("06", "MEP rough-in & coordination", 150, 90),
        ("07", "Interior fit-out & finishes", 220, 90),
        ("08", "Commissioning & turnover", 310, 30),
    ],
    "de": [
        ("01", "Baustelleneinrichtung", 0, 10),
        ("02", "Erdarbeiten & Aushub", 10, 18),
        ("03", "Gründung & Bodenplatte", 25, 35),
        ("04", "Rohbau & Tragwerk", 55, 80),
        ("05", "Fassade & Außenhülle", 120, 60),
        ("06", "TGA-Installation", 140, 75),
        ("07", "Innenausbau", 200, 80),
        ("08", "Inbetriebnahme & Übergabe", 285, 25),
    ],
    "es": [
        ("01", "Implantación de obra", 0, 10),
        ("02", "Movimiento de tierras", 10, 14),
        ("03", "Cimentación", 22, 28),
        ("04", "Estructura de hormigón", 48, 60),
        ("05", "Cerramientos y fachada", 100, 50),
        ("06", "Instalaciones", 115, 70),
        ("07", "Acabados interiores", 175, 60),
        ("08", "Recepción y entrega", 240, 20),
    ],
    "pt": [
        ("01", "Mobilização do canteiro", 0, 12),
        ("02", "Movimentação de terra", 12, 18),
        ("03", "Fundações", 28, 35),
        ("04", "Estrutura de concreto", 58, 85),
        ("05", "Pele de vidro e vedação", 120, 70),
        ("06", "Instalações elétrica/hidráulica", 140, 75),
        ("07", "Acabamentos internos", 200, 80),
        ("08", "Comissionamento e entrega", 285, 25),
    ],
    "zh": [
        ("01", "进场及临建", 0, 14),
        ("02", "土方与基础开挖", 14, 21),
        ("03", "基础工程", 30, 45),
        ("04", "主体结构施工", 60, 100),
        ("05", "幕墙及外围护", 145, 80),
        ("06", "机电安装", 165, 90),
        ("07", "精装修", 240, 90),
        ("08", "竣工验收", 320, 30),
    ],
}


# ── HTTP / Auth helpers ─────────────────────────────────────────────────


async def login(client: httpx.AsyncClient) -> dict[str, str]:
    r = await client.post(
        "/api/v1/users/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    r.raise_for_status()
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ── Direct SQLite helpers ───────────────────────────────────────────────


def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def get_demo_user_id(conn: sqlite3.Connection) -> str:
    cur = conn.cursor()
    cur.execute("SELECT id FROM oe_users_user WHERE email = ?", (ADMIN_EMAIL,))
    row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"Demo user not found: {ADMIN_EMAIL}")
    return row[0]


def get_bim_model_id(conn: sqlite3.Connection, project_id: str) -> str | None:
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM oe_bim_model WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
        (project_id,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def get_or_create_boq(conn: sqlite3.Connection, project_id: str, name: str, description: str) -> str:
    cur = conn.cursor()
    cur.execute("SELECT id FROM oe_boq_boq WHERE project_id = ? LIMIT 1", (project_id,))
    row = cur.fetchone()
    if row:
        return row[0]
    boq_id = str(uuid.uuid4())
    now = dt.datetime.utcnow().isoformat()
    cur.execute(
        """INSERT INTO oe_boq_boq
        (id, project_id, name, description, status, is_locked, metadata, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)""",
        (boq_id, project_id, name, description, "draft", json.dumps({"source": SOURCE_TAG}), now, now),
    )
    conn.commit()
    return boq_id


def already_enriched(conn: sqlite3.Connection, project_id: str, boq_id: str) -> bool:
    """Determine whether enrich_v2 has already populated this project's BOQ.

    We check for at least one position whose metadata contains ``source =
    enrich_v2``. If yes, skip the entire run for this project.
    """
    cur = conn.cursor()
    # Count positions with source tag
    cur.execute(
        """SELECT COUNT(*) FROM oe_boq_position
        WHERE boq_id = ? AND json_extract(metadata, '$.source') = ?""",
        (boq_id, SOURCE_TAG),
    )
    n = cur.fetchone()[0]
    return n > 0


def fetch_bim_elements_by_match(
    conn: sqlite3.Connection, model_id: str, type_substrings: list[str], limit: int = 60
) -> list[tuple[str, dict, dict]]:
    """Return (id, properties, quantities) for BIM elements whose
    element_type contains ANY of the given substrings.

    If type_substrings is empty, returns an empty list (used for sections
    that don't link to BIM, e.g. lump-sum site work).
    """
    if not type_substrings:
        return []
    cur = conn.cursor()
    where_clauses = " OR ".join(["element_type LIKE ?" for _ in type_substrings])
    params = [f"%{s}%" for s in type_substrings]
    cur.execute(
        f"""SELECT id, properties, quantities FROM oe_bim_element
        WHERE model_id = ? AND ({where_clauses})
        LIMIT ?""",
        (model_id, *params, limit),
    )
    rows: list[tuple[str, dict, dict]] = []
    for r in cur.fetchall():
        try:
            props = json.loads(r[1]) if r[1] else {}
        except Exception:
            props = {}
        try:
            qts = json.loads(r[2]) if r[2] else {}
        except Exception:
            qts = {}
        rows.append((r[0], props, qts))
    return rows


def aggregate_quantity(elements: list[tuple[str, dict, dict]], unit: str) -> float:
    """Aggregate a single quantity from BIM element list, for a given unit."""
    if not elements:
        return 0.0
    # Map unit → quantity-key candidates in oe_bim_element.quantities
    unit_l = unit.lower()
    keys: list[str]
    if unit_l in {"m2", "m²", "sf", "ft²"}:
        keys = ["area", "Area", "GrossArea", "NetArea", "GrossSideArea", "NetSideArea"]
    elif unit_l in {"m3", "m³", "cy"}:
        keys = ["volume", "Volume", "GrossVolume", "NetVolume"]
    elif unit_l in {"m", "lf", "ft", "lm"}:
        keys = ["length", "Length", "Perimeter"]
    else:
        keys = []  # ea, un, Stk, etc. → count
    total = 0.0
    for _, _props, qts in elements:
        if not keys:
            total += 1.0
            continue
        for k in keys:
            v = qts.get(k)
            if v is None:
                continue
            try:
                total += float(v)
                break
            except Exception:
                continue
        else:
            # No quantity key matched — count it as 1 unit so it isn't 0
            total += 1.0
    # Convert sf <-> m² / cy <-> m³ rough conversion if needed (BIM
    # values are usually metric — for imperial-unit projects we leave the
    # numeric value but keep the imperial unit label, since this is demo
    # data and the rates are also calibrated to imperial).
    if unit_l == "sf":
        total *= 10.7639  # m² → sf
    elif unit_l == "cy":
        total *= 1.30795  # m³ → cy
    elif unit_l == "lf":
        total *= 3.28084  # m → lf
    return round(total, 2)


# ── DWG / PDF upload ─────────────────────────────────────────────────────


async def ensure_dwg_drawing(
    client: httpx.AsyncClient, headers: dict, project_id: str, dwg_path: pathlib.Path,
    conn: sqlite3.Connection,
) -> str | None:
    """Upload a DWG drawing if none with our source tag exists for this project."""
    cur = conn.cursor()
    cur.execute(
        """SELECT id FROM oe_dwg_takeoff_drawing
        WHERE project_id = ? AND json_extract(metadata, '$.source') = ?
        LIMIT 1""",
        (project_id, SOURCE_TAG),
    )
    row = cur.fetchone()
    if row:
        return row[0]
    if not dwg_path.exists():
        print(f"  ! DWG file missing: {dwg_path.name}")
        return None
    try:
        with dwg_path.open("rb") as fh:
            files = {"file": (dwg_path.name, fh.read(), "application/octet-stream")}
        r = await client.post(
            "/api/v1/dwg_takeoff/drawings/upload/",
            params={"project_id": project_id, "name": f"Site Plan — {dwg_path.stem}"},
            files=files,
            headers=headers,
            timeout=120.0,
        )
        if r.status_code >= 400:
            print(f"  ! DWG upload failed {r.status_code}: {r.text[:200]}")
            return None
        drawing_id = r.json()["id"]
        # Tag the drawing as enrich_v2 so we can find it on re-runs
        cur.execute(
            "UPDATE oe_dwg_takeoff_drawing SET metadata = json_patch(coalesce(metadata,'{}'), ?) WHERE id = ?",
            (json.dumps({"source": SOURCE_TAG}), drawing_id),
        )
        conn.commit()
        return drawing_id
    except Exception as exc:
        print(f"  ! DWG upload exception: {exc}")
        return None


async def ensure_pdf_document(
    client: httpx.AsyncClient, headers: dict, project_id: str, pdf_path: pathlib.Path,
    conn: sqlite3.Connection,
) -> str | None:
    cur = conn.cursor()
    cur.execute(
        """SELECT id FROM oe_takeoff_document
        WHERE project_id = ? AND json_extract(metadata, '$.source') = ?
        LIMIT 1""",
        (project_id, SOURCE_TAG),
    )
    row = cur.fetchone()
    if row:
        return row[0]
    if not pdf_path.exists():
        print(f"  ! PDF file missing: {pdf_path.name}")
        return None
    try:
        with pdf_path.open("rb") as fh:
            files = {"file": (pdf_path.name, fh.read(), "application/pdf")}
        r = await client.post(
            "/api/v1/takeoff/documents/upload/",
            params={"project_id": project_id},
            files=files,
            headers=headers,
            timeout=120.0,
        )
        if r.status_code >= 400:
            print(f"  ! PDF upload failed {r.status_code}: {r.text[:200]}")
            return None
        doc_id = r.json()["id"]
        cur.execute(
            "UPDATE oe_takeoff_document SET metadata = json_patch(coalesce(metadata,'{}'), ?) WHERE id = ?",
            (json.dumps({"source": SOURCE_TAG}), doc_id),
        )
        conn.commit()
        return doc_id
    except Exception as exc:
        print(f"  ! PDF upload exception: {exc}")
        return None


# ── BOQ insertion ────────────────────────────────────────────────────────


def insert_boq_content(
    conn: sqlite3.Connection, boq_id: str, project_id: str, model_id: str,
    spec: dict, demo_user_id: str,
) -> tuple[int, int, int]:
    """Insert sections + leaves + BIM links into the database.

    Returns (sections_inserted, leaves_inserted, bim_links_inserted).
    """
    cur = conn.cursor()
    sections_n = 0
    leaves_n = 0
    links_n = 0
    sort_order = 0
    leaf_ids: list[str] = []  # collect for cross-module references

    # Find existing sections (so we can skip if re-run produced one earlier
    # without metadata tag, but we'll still rely on metadata.source check.
    cur.execute(
        "SELECT ordinal, id FROM oe_boq_position WHERE boq_id = ? AND unit = 'section'",
        (boq_id,),
    )
    existing_section_by_ord = {r[0]: r[1] for r in cur.fetchall()}

    now = dt.datetime.utcnow().isoformat()

    for section_code, section_label, leaves in spec["sections"]:
        # Section row
        if section_code in existing_section_by_ord:
            section_id = existing_section_by_ord[section_code]
        else:
            section_id = str(uuid.uuid4())
            cur.execute(
                """INSERT INTO oe_boq_position
                (id, boq_id, parent_id, ordinal, description, unit, quantity,
                 unit_rate, total, classification, source, cad_element_ids,
                 validation_status, metadata, sort_order, version, created_at, updated_at)
                VALUES (?, ?, NULL, ?, ?, 'section', '0', '0', '0', '{}',
                        'manual', '[]', 'pending', ?, ?, 0, ?, ?)""",
                (
                    section_id, boq_id, section_code, section_label,
                    json.dumps({"source": SOURCE_TAG, "kind": "section"}),
                    sort_order, now, now,
                ),
            )
            sections_n += 1
        sort_order += 1

        for li, leaf in enumerate(leaves, start=1):
            desc, unit, rate, classification, type_match = leaf
            # Aggregate qty from BIM elements
            elements = fetch_bim_elements_by_match(conn, model_id, type_match, limit=60)
            qty = aggregate_quantity(elements, unit)
            if qty <= 0:
                # Sane default for unrelated lump items (site work etc.)
                qty = 1.0
            total = round(qty * rate, 2)

            ordinal = f"{section_code}.{li:03d}" if "." in section_code or section_code.isdigit() or section_code in {"甲", "乙", "丙", "丁", "戊", "己", "庚"} else f"{section_code} - {li:02d}"
            # Choose source label
            source_label = "cad_import" if elements else ("dwg_takeoff" if li % 3 == 0 else "manual")
            classif = dict(classification or {})
            classif["section"] = section_code

            leaf_id = str(uuid.uuid4())
            cad_ids_list = [eid for eid, _, _ in elements][:50]

            cur.execute(
                """INSERT INTO oe_boq_position
                (id, boq_id, parent_id, ordinal, description, unit, quantity,
                 unit_rate, total, classification, source, confidence,
                 cad_element_ids, validation_status, metadata, sort_order, version,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'passed', ?, ?, 0, ?, ?)""",
                (
                    leaf_id, boq_id, section_id, ordinal, desc, unit,
                    f"{qty:.4f}", f"{rate:.4f}", f"{total:.4f}",
                    json.dumps(classif), source_label,
                    "high" if elements else None,
                    json.dumps(cad_ids_list),
                    json.dumps({
                        "source": SOURCE_TAG,
                        "section_code": section_code,
                        "bim_element_count": len(elements),
                        "type_match": type_match,
                    }),
                    sort_order, now, now,
                ),
            )
            leaves_n += 1
            sort_order += 1
            leaf_ids.append(leaf_id)

            # Insert bim_boq_link rows for each element
            for eid, _props, _qts in elements:
                link_id = str(uuid.uuid4())
                try:
                    cur.execute(
                        """INSERT INTO oe_bim_boq_link
                        (id, boq_position_id, bim_element_id, link_type, confidence,
                         rule_id, created_by, metadata, created_at, updated_at)
                        VALUES (?, ?, ?, 'auto', 'high', ?, ?, ?, ?, ?)""",
                        (
                            link_id, leaf_id, eid, "enrich_v2_match",
                            demo_user_id, json.dumps({"source": SOURCE_TAG}),
                            now, now,
                        ),
                    )
                    links_n += 1
                except sqlite3.IntegrityError:
                    # Unique on (boq_position_id, bim_element_id) — skip
                    pass

    conn.commit()
    return sections_n, leaves_n, links_n


def get_leaf_ids(conn: sqlite3.Connection, boq_id: str) -> list[tuple[str, str, str, str]]:
    """Return list of (id, ordinal, description, unit) for all leaf positions."""
    cur = conn.cursor()
    cur.execute(
        """SELECT id, ordinal, description, unit FROM oe_boq_position
        WHERE boq_id = ? AND unit != 'section'
        ORDER BY sort_order""",
        (boq_id,),
    )
    return [(r[0], r[1], r[2], r[3]) for r in cur.fetchall()]


def get_section_ids(conn: sqlite3.Connection, boq_id: str) -> list[tuple[str, str, str]]:
    cur = conn.cursor()
    cur.execute(
        """SELECT id, ordinal, description FROM oe_boq_position
        WHERE boq_id = ? AND unit = 'section'
        ORDER BY sort_order""",
        (boq_id,),
    )
    return [(r[0], r[1], r[2]) for r in cur.fetchall()]


# ── DWG annotation links ────────────────────────────────────────────────


def insert_dwg_annotations(
    conn: sqlite3.Connection, project_id: str, drawing_id: str | None,
    leaf_rows: list[tuple[str, str, str, str]], demo_user_id: str,
) -> int:
    """Create 5-10 DWG annotations linked to BOQ leaf positions."""
    if drawing_id is None or not leaf_rows:
        return 0
    cur = conn.cursor()
    # Only create if not already present
    cur.execute(
        """SELECT COUNT(*) FROM oe_dwg_takeoff_annotation
        WHERE drawing_id = ? AND json_extract(metadata, '$.source') = ?""",
        (drawing_id, SOURCE_TAG),
    )
    if cur.fetchone()[0] >= 5:
        return 0
    targets = leaf_rows[: min(8, len(leaf_rows))]
    now = dt.datetime.utcnow().isoformat()
    n = 0
    for i, (leaf_id, ordinal, desc, unit) in enumerate(targets):
        ann_id = str(uuid.uuid4())
        x0 = 100 + i * 60
        y0 = 100 + (i % 3) * 80
        geometry = {
            "type": "rectangle",
            "x": x0, "y": y0, "width": 50, "height": 30,
            "page": 1,
        }
        ann_type = "rectangle" if i % 2 == 0 else "polyline"
        cur.execute(
            """INSERT INTO oe_dwg_takeoff_annotation
            (id, project_id, drawing_id, drawing_version_id, annotation_type,
             geometry, text, color, line_width, thickness, layer_name,
             measurement_value, measurement_unit, linked_boq_position_id,
             created_by, metadata, created_at, updated_at)
            VALUES (?, ?, ?, NULL, ?, ?, ?, '#3b82f6', 2, 2.0, 'TAKEOFF_LINK',
                    ?, ?, ?, ?, ?, ?, ?)""",
            (
                ann_id, project_id, drawing_id, ann_type,
                json.dumps(geometry),
                f"{ordinal} — {desc[:60]}",
                round(10 + i * 2.5, 2), unit, leaf_id, demo_user_id,
                json.dumps({"source": SOURCE_TAG, "leaf_ordinal": ordinal}),
                now, now,
            ),
        )
        n += 1
    conn.commit()
    return n


# ── PDF measurements ─────────────────────────────────────────────────────


def insert_pdf_measurements(
    conn: sqlite3.Connection, project_id: str, doc_id: str | None,
    leaf_rows: list[tuple[str, str, str, str]], demo_user_id: str,
) -> int:
    if doc_id is None or not leaf_rows:
        return 0
    cur = conn.cursor()
    cur.execute(
        """SELECT COUNT(*) FROM oe_takeoff_measurement
        WHERE project_id = ? AND document_id = ? AND json_extract(metadata, '$.source') = ?""",
        (project_id, doc_id, SOURCE_TAG),
    )
    if cur.fetchone()[0] >= 4:
        return 0
    n = 0
    targets = leaf_rows[: min(6, len(leaf_rows))]
    now = dt.datetime.utcnow().isoformat()
    types = ["distance", "area", "count", "polyline"]
    for i, (leaf_id, ordinal, desc, unit) in enumerate(targets):
        m_id = str(uuid.uuid4())
        m_type = types[i % len(types)]
        page = 1 + (i % 2)
        x = 80 + i * 40
        y = 120 + (i % 4) * 50
        if m_type == "distance":
            points = [{"x": x, "y": y}, {"x": x + 200, "y": y + 30}]
            value = 12.5 + i * 1.7
        elif m_type == "area":
            points = [
                {"x": x, "y": y}, {"x": x + 180, "y": y},
                {"x": x + 180, "y": y + 90}, {"x": x, "y": y + 90},
            ]
            value = 16.2 + i * 3.4
        elif m_type == "polyline":
            points = [{"x": x, "y": y}, {"x": x + 60, "y": y + 25}, {"x": x + 140, "y": y + 5}]
            value = 8.4 + i * 1.1
        else:
            points = [{"x": x, "y": y}]
            value = float(3 + i)
        cur.execute(
            """INSERT INTO oe_takeoff_measurement
            (id, project_id, document_id, page, type, group_name, group_color,
             annotation, points, measurement_value, measurement_unit,
             linked_boq_position_id, metadata, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, '#10B981', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                m_id, project_id, doc_id, page, m_type, "BOQ Linked",
                f"{ordinal} — {desc[:60]}",
                json.dumps(points), value, unit if m_type != "count" else "ea",
                leaf_id,
                json.dumps({"source": SOURCE_TAG, "leaf_ordinal": ordinal}),
                demo_user_id, now, now,
            ),
        )
        n += 1
    conn.commit()
    return n


# ── Schedule (4D) ────────────────────────────────────────────────────────


def insert_schedule(
    conn: sqlite3.Connection, project_id: str, locale: str,
    section_rows: list[tuple[str, str, str]], leaf_rows: list[tuple[str, str, str, str]],
    demo_user_id: str,
) -> tuple[int, int, int]:
    """Create one schedule + 5-8 activities + 3-4 EAC links to BOQ sections."""
    cur = conn.cursor()
    now = dt.datetime.utcnow().isoformat()
    # Already done?
    cur.execute(
        """SELECT id FROM oe_schedule_schedule
        WHERE project_id = ? AND json_extract(metadata, '$.source') = ?
        LIMIT 1""",
        (project_id, SOURCE_TAG),
    )
    row = cur.fetchone()
    if row:
        sched_id = row[0]
        # Count existing
        cur.execute("SELECT COUNT(*) FROM oe_schedule_activity WHERE schedule_id = ?", (sched_id,))
        if cur.fetchone()[0] >= 5:
            return 0, 0, 0
    else:
        sched_id = str(uuid.uuid4())
        cur.execute(
            """INSERT INTO oe_schedule_schedule
            (id, project_id, name, schedule_type, description, start_date, end_date,
             status, data_date, created_by, metadata, created_at, updated_at)
            VALUES (?, ?, ?, 'master', ?, ?, ?, 'active', ?, ?, ?, ?, ?)""",
            (
                sched_id, project_id, "Master Schedule",
                "Project master schedule, 8 high-level activities.",
                (TODAY).isoformat(),
                (TODAY + dt.timedelta(days=365)).isoformat(),
                TODAY.isoformat(), demo_user_id,
                json.dumps({"source": SOURCE_TAG}),
                now, now,
            ),
        )

    template = SCHEDULE_TEMPLATES.get(locale, SCHEDULE_TEMPLATES["en"])
    activities_n = 0
    eac_links_n = 0
    base = TODAY
    activity_ids: list[str] = []
    for i, (wbs, name, day_off, dur) in enumerate(template):
        act_id = str(uuid.uuid4())
        start = base + dt.timedelta(days=day_off)
        end = start + dt.timedelta(days=dur)
        is_critical = 1 if i in {2, 3, 4} else 0
        cost_planned = round(50000 + i * 35000, 2)
        cost_actual = round(cost_planned * (0.9 + 0.05 * (i % 4)), 2) if start < base else 0.0
        progress = "100" if end < base else ("45" if start <= base else "0")
        status = "completed" if end < base else ("in_progress" if start <= base else "not_started")
        cur.execute(
            """INSERT INTO oe_schedule_activity
            (id, schedule_id, parent_id, name, description, wbs_code, start_date,
             end_date, duration_days, progress_pct, status, activity_type,
             dependencies, resources, boq_position_ids, color, sort_order,
             is_critical, activity_code, bim_element_ids, metadata,
             created_at, updated_at, cost_planned, cost_actual)
            VALUES (?, ?, NULL, ?, '', ?, ?, ?, ?, ?, ?, 'task', '[]', '[]', '[]',
                    '#0071e3', ?, ?, ?, NULL, ?, ?, ?, ?, ?)""",
            (
                act_id, sched_id, name, wbs, start.isoformat(), end.isoformat(),
                dur, progress, status, i, is_critical, f"ACT-{i+1:03d}",
                json.dumps({"source": SOURCE_TAG, "wbs": wbs}), now, now,
                str(cost_planned), str(cost_actual),
            ),
        )
        activities_n += 1
        activity_ids.append(act_id)

        # EAC link to a BOQ section (4D feature). Round-robin across the
        # available section ordinals.
        if section_rows and i < min(4, len(section_rows)):
            sec_ord = section_rows[i % len(section_rows)][1]
            link_id = str(uuid.uuid4())
            cur.execute(
                """INSERT INTO oe_schedule_eac_link
                (id, task_id, rule_id, predicate_json, mode, matched_element_count,
                 last_resolved_at, updated_by_user_id, created_at, updated_at)
                VALUES (?, ?, NULL, ?, 'partial_match', 0, NULL, ?, ?, ?)""",
                (
                    link_id, act_id,
                    json.dumps({
                        "boq_section_ordinal": sec_ord,
                        "source": SOURCE_TAG,
                        "wbs": wbs,
                    }),
                    demo_user_id, now, now,
                ),
            )
            eac_links_n += 1

    conn.commit()
    return 1, activities_n, eac_links_n


# ── RFIs ─────────────────────────────────────────────────────────────────


def insert_rfis(
    conn: sqlite3.Connection, project_id: str, locale: str,
    leaf_rows: list[tuple[str, str, str, str]], demo_user_id: str, model_id: str,
) -> int:
    cur = conn.cursor()
    cur.execute(
        """SELECT COUNT(*) FROM oe_rfi_rfi
        WHERE project_id = ? AND json_extract(metadata, '$.source') = ?""",
        (project_id, SOURCE_TAG),
    )
    if cur.fetchone()[0] >= 3:
        return 0
    now = dt.datetime.utcnow().isoformat()
    templates = RFI_TEMPLATES.get(locale, RFI_TEMPLATES["en"])
    n = 0
    for i, (subject, question, status) in enumerate(templates):
        # Get next RFI number
        cur.execute(
            "SELECT COUNT(*) FROM oe_rfi_rfi WHERE project_id = ?", (project_id,)
        )
        next_num = cur.fetchone()[0] + 1
        rfi_id = str(uuid.uuid4())
        target_leaf = leaf_rows[i % len(leaf_rows)] if leaf_rows else None
        cost_impact = i % 2 == 0
        sched_impact = i % 3 == 0
        responded_at = now if status in {"answered", "closed"} else None
        official = (
            "Confirmed and accepted as detailed in the response. See attached coordination drawing."
            if status in {"answered", "closed"} else None
        )
        cur.execute(
            """INSERT INTO oe_rfi_rfi
            (id, project_id, rfi_number, subject, question, raised_by, assigned_to,
             status, ball_in_court, official_response, responded_by, responded_at,
             cost_impact, cost_impact_value, schedule_impact, schedule_impact_days,
             date_required, response_due_date, linked_drawing_ids, change_order_id,
             created_by, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', NULL,
                    ?, ?, ?, ?)""",
            (
                rfi_id, project_id, f"RFI-{next_num:03d}", subject, question,
                demo_user_id, status, demo_user_id if status == "open" else None,
                official, demo_user_id if responded_at else None, responded_at,
                1 if cost_impact else 0,
                str(round(2500 + i * 1200, 2)) if cost_impact else None,
                1 if sched_impact else 0,
                3 + i if sched_impact else None,
                (TODAY + dt.timedelta(days=7)).isoformat(),
                (TODAY + dt.timedelta(days=10)).isoformat(),
                demo_user_id,
                json.dumps({
                    "source": SOURCE_TAG,
                    "linked_boq_position_id": target_leaf[0] if target_leaf else None,
                    "linked_bim_model_id": model_id,
                }),
                now, now,
            ),
        )
        n += 1
    conn.commit()
    return n


# ── Change Orders ────────────────────────────────────────────────────────


def insert_change_orders(
    conn: sqlite3.Connection, project_id: str, locale: str, currency: str,
    section_rows: list[tuple[str, str, str]], demo_user_id: str,
) -> tuple[int, int]:
    cur = conn.cursor()
    cur.execute(
        """SELECT COUNT(*) FROM oe_changeorders_order
        WHERE project_id = ? AND json_extract(metadata, '$.source') = ?""",
        (project_id, SOURCE_TAG),
    )
    if cur.fetchone()[0] >= 2:
        return 0, 0
    now = dt.datetime.utcnow().isoformat()
    templates = CO_TEMPLATES.get(locale, CO_TEMPLATES["en"])
    co_n = 0
    items_n = 0
    for i, (code, title, total, items) in enumerate(templates):
        # Append a unique suffix to keep the (project_id, code) UNIQUE
        # constraint satisfied on re-runs.
        co_code = f"{code}-EV2"
        cur.execute(
            """SELECT id FROM oe_changeorders_order WHERE project_id = ? AND code = ?""",
            (project_id, co_code),
        )
        if cur.fetchone():
            continue
        co_id = str(uuid.uuid4())
        status = "approved" if i == 0 else "submitted"
        target_section = section_rows[i % len(section_rows)] if section_rows else None
        cur.execute(
            """INSERT INTO oe_changeorders_order
            (id, project_id, code, title, description, reason_category, status,
             submitted_by, approved_by, rejected_by, submitted_at, approved_at,
             rejected_at, cost_impact, schedule_impact_days, currency,
             variation_type, cost_basis, contractor_submission_date,
             contractor_amount, engineer_amount, approved_amount, time_impact_days,
             approved_time_days, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'client_request', ?, ?, ?, NULL, ?, ?, NULL,
                    ?, ?, ?, 'change_order', 'lump_sum', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                co_id, project_id, co_code, title,
                f"Change order linked to section {target_section[1] if target_section else 'N/A'}.",
                status, demo_user_id,
                demo_user_id if status == "approved" else None,
                now, now if status == "approved" else None,
                f"{total:.2f}", 5 + i * 3, currency,
                now, f"{total:.2f}", f"{total * 0.95:.2f}",
                f"{total:.2f}" if status == "approved" else None,
                5 + i * 3, 5 + i * 3 if status == "approved" else None,
                json.dumps({
                    "source": SOURCE_TAG,
                    "linked_section_ordinal": target_section[1] if target_section else None,
                }),
                now, now,
            ),
        )
        co_n += 1
        for j, (desc, unit, qty, rate) in enumerate(items):
            item_id = str(uuid.uuid4())
            cost_delta = round(qty * rate, 2)
            cur.execute(
                """INSERT INTO oe_changeorders_item
                (id, change_order_id, description, change_type, original_quantity,
                 new_quantity, original_rate, new_rate, cost_delta, unit,
                 sort_order, metadata, created_at, updated_at)
                VALUES (?, ?, ?, 'added', '0.000000', ?, '0.000000', ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item_id, co_id, desc,
                    f"{qty:.6f}", f"{rate:.6f}", f"{cost_delta:.2f}",
                    unit, j,
                    json.dumps({"source": SOURCE_TAG}),
                    now, now,
                ),
            )
            items_n += 1
    conn.commit()
    return co_n, items_n


# ── Cost snapshots (5D) ──────────────────────────────────────────────────


def insert_cost_snapshots(
    conn: sqlite3.Connection, project_id: str, boq_id: str, demo_user_id: str,
) -> int:
    cur = conn.cursor()
    cur.execute(
        """SELECT COUNT(*) FROM oe_costmodel_snapshot
        WHERE project_id = ? AND json_extract(metadata, '$.source') = ?""",
        (project_id, SOURCE_TAG),
    )
    if cur.fetchone()[0] >= 2:
        return 0
    # Sum BOQ totals
    cur.execute(
        """SELECT COALESCE(SUM(CAST(total AS REAL)), 0) FROM oe_boq_position
        WHERE boq_id = ? AND unit != 'section'""",
        (boq_id,),
    )
    total_row = cur.fetchone()
    boq_total = float(total_row[0]) if total_row else 0.0
    if boq_total <= 0:
        boq_total = 1_000_000.0  # safe default

    now = dt.datetime.utcnow().isoformat()
    # Two snapshots: baseline (3 months ago) + current (today)
    n = 0
    snapshots = [
        ("baseline", (TODAY - dt.timedelta(days=90)).strftime("%Y-%m"),
         boq_total, boq_total * 0.05, boq_total * 0.04, boq_total * 1.02, "1.00", "1.05"),
        ("current", TODAY.strftime("%Y-%m"),
         boq_total, boq_total * 0.42, boq_total * 0.45, boq_total * 1.06, "0.96", "0.93"),
    ]
    for kind, period, planned, earned, actual, eac, spi, cpi in snapshots:
        snap_id = str(uuid.uuid4())
        cur.execute(
            """INSERT INTO oe_costmodel_snapshot
            (id, project_id, period, planned_cost, earned_value, actual_cost,
             forecast_eac, spi, cpi, notes, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                snap_id, project_id, period,
                f"{planned:.2f}", f"{earned:.2f}", f"{actual:.2f}",
                f"{eac:.2f}", spi, cpi,
                f"{kind.title()} — auto-generated by enrich_v2.",
                json.dumps({"source": SOURCE_TAG, "kind": kind}),
                now, now,
            ),
        )
        n += 1
    conn.commit()
    return n


# ── Validation reports ──────────────────────────────────────────────────


def insert_validation_reports(
    conn: sqlite3.Connection, project_id: str, boq_id: str, model_id: str,
    demo_user_id: str,
) -> int:
    cur = conn.cursor()
    cur.execute(
        """SELECT COUNT(*) FROM oe_validation_report
        WHERE project_id = ? AND json_extract(metadata, '$.source') = ?""",
        (project_id, SOURCE_TAG),
    )
    if cur.fetchone()[0] >= 2:
        return 0
    now = dt.datetime.utcnow().isoformat()
    n = 0
    for kind, target_type, target_id, rule_set, results in [
        (
            "boq_quality", "boq", boq_id, "boq_quality",
            [
                {"rule_id": "boq_quality.no_zero_price", "status": "passed",
                 "message": "All positions have non-zero unit rates", "element_ref": None,
                 "details": {}},
                {"rule_id": "boq_quality.no_duplicate_ordinal", "status": "passed",
                 "message": "All ordinals unique within BOQ", "element_ref": None,
                 "details": {}},
                {"rule_id": "boq_quality.unit_rate_within_range", "status": "warning",
                 "message": "2 positions have unit rates above the 95th percentile benchmark",
                 "element_ref": None, "details": {"position_count": 2}},
                {"rule_id": "boq_quality.classification_assigned", "status": "passed",
                 "message": "Every leaf has a classification code", "element_ref": None,
                 "details": {}},
            ],
        ),
        (
            "bim_compliance", "cad_import", model_id, "bim_compliance",
            [
                {"rule_id": "bim_compliance.elements_present", "status": "passed",
                 "message": "Model contains > 100 elements", "element_ref": None,
                 "details": {}},
                {"rule_id": "bim_compliance.required_properties", "status": "warning",
                 "message": "5% of elements missing FireRating property", "element_ref": None,
                 "details": {"missing_pct": 5}},
                {"rule_id": "bim_compliance.classification_mapped", "status": "warning",
                 "message": "Some element types not mapped to standard classification",
                 "element_ref": None, "details": {}},
                {"rule_id": "bim_compliance.no_zero_geometry", "status": "passed",
                 "message": "All elements have non-zero bounding box", "element_ref": None,
                 "details": {}},
            ],
        ),
    ]:
        passed = sum(1 for r in results if r["status"] == "passed")
        warns = sum(1 for r in results if r["status"] == "warning")
        errs = sum(1 for r in results if r["status"] == "error")
        total = len(results)
        if errs > 0:
            status = "errors"
        elif warns > 0:
            status = "warnings"
        else:
            status = "passed"
        score = passed / total if total > 0 else 0.0
        rep_id = str(uuid.uuid4())
        cur.execute(
            """INSERT INTO oe_validation_report
            (id, project_id, target_type, target_id, rule_set, status, score,
             total_rules, passed_count, warning_count, error_count, results,
             created_by, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rep_id, project_id, target_type, target_id, rule_set,
                status, f"{score:.2f}", total, passed, warns, errs,
                json.dumps(results), demo_user_id,
                json.dumps({"source": SOURCE_TAG, "kind": kind}),
                now, now,
            ),
        )
        n += 1
    conn.commit()
    return n


# ── Per-project orchestration ───────────────────────────────────────────


async def enrich_project(
    client: httpx.AsyncClient, headers: dict, key: str, spec: dict,
    failures: dict[str, list[str]],
) -> dict[str, int]:
    """Enrich one project. Each call uses its own DB connection."""
    project_id = spec["project_id"]
    locale = spec["locale"]
    currency = spec["currency"]

    print(f"[{key.upper()}] Starting enrichment...")
    conn = db_connect()
    try:
        demo_user_id = get_demo_user_id(conn)
        model_id = get_bim_model_id(conn, project_id)
        if not model_id:
            failures[key].append("No BIM model")
            print(f"[{key.upper()}] ! No BIM model — skipping")
            return {}

        # 1. DWG upload (parallel-safe; uses HTTP)
        dwg_path = CAD_SOURCE_DIR / DWG_FILES[key][0]
        drawing_id = await ensure_dwg_drawing(client, headers, project_id, dwg_path, conn)

        # 2. PDF upload
        pdf_path = CAD_SOURCE_DIR / PDF_FILES[key]
        doc_id = await ensure_pdf_document(client, headers, project_id, pdf_path, conn)

        # 3. BOQ shell + sections + leaves + bim_boq_links
        boq_id = get_or_create_boq(conn, project_id, spec["boq_name"], spec["boq_description"])
        if already_enriched(conn, project_id, boq_id):
            print(f"[{key.upper()}] BOQ already enriched (idempotent skip).")
            section_rows = get_section_ids(conn, boq_id)
            leaf_rows = get_leaf_ids(conn, boq_id)
            sections_n = sum(1 for s in section_rows if s)
            leaves_n = len(leaf_rows)
            bim_links_n = 0  # don't recount
        else:
            sections_n, leaves_n, bim_links_n = insert_boq_content(
                conn, boq_id, project_id, model_id, spec, demo_user_id
            )
            section_rows = get_section_ids(conn, boq_id)
            leaf_rows = get_leaf_ids(conn, boq_id)
            print(f"[{key.upper()}] BOQ: {sections_n} sections, {leaves_n} leaves, {bim_links_n} BIM links")

        # 4. DWG annotations linking to BOQ leaves
        ann_n = insert_dwg_annotations(conn, project_id, drawing_id, leaf_rows, demo_user_id)

        # 5. PDF measurements linking to BOQ leaves
        meas_n = insert_pdf_measurements(conn, project_id, doc_id, leaf_rows, demo_user_id)

        # 6. Schedule + 4D EAC links
        sched_n, act_n, eac_n = insert_schedule(
            conn, project_id, locale, section_rows, leaf_rows, demo_user_id
        )

        # 7. RFIs
        rfi_n = insert_rfis(conn, project_id, locale, leaf_rows, demo_user_id, model_id)

        # 8. Change orders
        co_n, co_items_n = insert_change_orders(
            conn, project_id, locale, currency, section_rows, demo_user_id
        )

        # 9. Cost snapshots
        snap_n = insert_cost_snapshots(conn, project_id, boq_id, demo_user_id)

        # 10. Validation reports
        val_n = insert_validation_reports(conn, project_id, boq_id, model_id, demo_user_id)

        result = {
            "sections": sections_n,
            "leaves": leaves_n,
            "bim_links": bim_links_n,
            "dwg_uploaded": 1 if drawing_id else 0,
            "pdf_uploaded": 1 if doc_id else 0,
            "dwg_annotations": ann_n,
            "pdf_measurements": meas_n,
            "schedule_activities": act_n,
            "eac_links": eac_n,
            "rfis": rfi_n,
            "change_orders": co_n,
            "co_items": co_items_n,
            "snapshots": snap_n,
            "validations": val_n,
        }
        print(f"[{key.upper()}] Done: {result}")
        return result
    except Exception as exc:
        traceback.print_exc()
        failures[key].append(f"Exception: {exc}")
        return {}
    finally:
        conn.close()


# ── Main ────────────────────────────────────────────────────────────────


async def main() -> None:
    started = time.monotonic()
    print(f"=== enrich_demo_v2 — {dt.datetime.now().isoformat()} ===")
    print(f"DB: {DB_PATH}")
    print(f"CAD source: {CAD_SOURCE_DIR}")

    if not DB_PATH.exists():
        raise RuntimeError(f"DB not found: {DB_PATH}")
    if not CAD_SOURCE_DIR.exists():
        raise RuntimeError(f"CAD source dir not found: {CAD_SOURCE_DIR}")

    failures: dict[str, list[str]] = {k: [] for k in PROJECT_SPECS}
    results: dict[str, dict[str, int]] = {}

    async with httpx.AsyncClient(base_url=BASE, timeout=60.0) as client:
        try:
            headers = await login(client)
            print("Auth: OK")
        except Exception as exc:
            print(f"Auth failed: {exc}")
            return

        # Run all 5 in parallel — each uses its own DB connection.
        tasks = [
            enrich_project(client, headers, key, spec, failures)
            for key, spec in PROJECT_SPECS.items()
        ]
        outputs = await asyncio.gather(*tasks, return_exceptions=True)
        for key, out in zip(PROJECT_SPECS.keys(), outputs, strict=False):
            if isinstance(out, Exception):
                failures[key].append(f"Top-level exception: {out}")
                results[key] = {}
            else:
                results[key] = out  # type: ignore[assignment]

    elapsed = time.monotonic() - started

    # ── Verification table ────────────────────────────────────────────
    print()
    print("=" * 110)
    label_map = {
        "us": "US Boylston Crossing",
        "de": "DE Wohnpark Friedrichshain",
        "es": "ES Residencial Salamanca",
        "br": "BR Vila Madalena",
        "cn": "CN Shanghai School",
    }
    header = (
        f"{'Project':<28}|{'Sec':>5}|{'Leaf':>5}|{'BIM':>5}|{'DWG':>4}|{'PDF':>4}|"
        f"{'Ann':>4}|{'Mes':>4}|{'Act':>5}|{'EAC':>4}|{'RFI':>4}|{'CO':>3}|"
        f"{'Snap':>5}|{'Val':>4}"
    )
    print(header)
    print("-" * 110)
    for key in PROJECT_SPECS:
        r = results.get(key, {}) or {}
        row = (
            f"{label_map.get(key, key):<28}|{r.get('sections', 0):>5}|"
            f"{r.get('leaves', 0):>5}|{r.get('bim_links', 0):>5}|"
            f"{r.get('dwg_uploaded', 0):>4}|{r.get('pdf_uploaded', 0):>4}|"
            f"{r.get('dwg_annotations', 0):>4}|{r.get('pdf_measurements', 0):>4}|"
            f"{r.get('schedule_activities', 0):>5}|{r.get('eac_links', 0):>4}|"
            f"{r.get('rfis', 0):>4}|{r.get('change_orders', 0):>3}|"
            f"{r.get('snapshots', 0):>5}|{r.get('validations', 0):>4}"
        )
        print(row)
    print("=" * 110)
    print()

    # Failure summary
    any_fail = False
    for k, msgs in failures.items():
        if msgs:
            any_fail = True
            print(f"  [{k.upper()}] failures:")
            for m in msgs:
                print(f"    - {m}")
    if not any_fail:
        print("No failures.")

    print(f"\nTotal wall-clock: {elapsed:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
