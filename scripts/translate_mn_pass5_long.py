# -*- coding: utf-8 -*-
"""‌⁠‍Pass 5: Replace heavily-mixed long descriptive sentences with proper
full Mongolian translations. These are mostly the marketing/landing
paragraphs in the 'about' section and long descriptive labels.

Deprecated one-off: for new work use scripts/i18n.py (get/add/set/missing/rename/export/import).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EN_PATH = ROOT / "frontend" / "src" / "app" / "locales" / "en.ts"
MN_PATH = ROOT / "frontend" / "src" / "app" / "locales" / "mn.ts"


# Full proper translations for the long descriptive sentences.
# Keyed by the original English text (case-sensitive).
FULL_TRANSLATIONS: dict[str, str] = {
    "OpenConstructionERP is a modern platform for construction cost management. It covers the full estimation workflow — from creating a bill of quantities to tendering and bid comparison. Designed for professionals worldwide, it supports international standards and works in 20 languages.":
        "OpenConstructionERP нь барилгын өртгийн удирдлагын орчин үеийн платформ юм. Энэ нь ажил материалын жагсаалт үүсгэхээс эхлээд тендер зарлах, саналыг харьцуулах хүртэлх тооцооллын бүх ажлын урсгалыг хамардаг. Олон улсын мэргэжилтнүүдэд зориулсан энэхүү систем нь олон улсын стандартыг дэмждэг бөгөөд 20 хэлээр ажилладаг.",

    "Unlike traditional commercial solutions, OpenConstructionERP runs entirely on your computer. Your project data never leaves your machine — you have full ownership and control. The source code is open and auditable, so you always know exactly what the software does.":
        "Уламжлалт арилжааны шийдлүүдээс ялгаатай нь OpenConstructionERP нь таны компьютер дээр бүхэлдээ ажилладаг. Таны төслийн өгөгдөл таны машинаас гадагш гарахгүй — та бүрэн эзэмшил, хяналттай. Эх код нь нээлттэй бөгөөд аудит хийх боломжтой тул програм юу хийдгийг та яг таг үргэлж мэдэж байдаг.",

    "Construction cost data is one of the most valuable assets a company owns. With proprietary software, your data is often locked inside formats you cannot control. If the vendor raises prices, changes terms, or discontinues the product — you may lose access to years of work.":
        "Барилгын өртгийн өгөгдөл нь компанийн эзэмшдэг хамгийн үнэ цэнэтэй хөрөнгийн нэг юм. Эзэмшлийн програм хангамжийн хувьд таны өгөгдөл нь таны хяналтгүй форматуудад түгжигдсэн байдаг. Хэрэв нийлүүлэгч үнээ нэмэх, нөхцлөө өөрчлөх, эсвэл бүтээгдэхүүнээ зогсоосон тохиолдолд та олон жилийн ажлынхаа хандалтыг алдаж болзошгүй.",

    "OpenConstructionERP takes a different approach. Your data is stored in open formats (SQLite, JSON, CSV) on your own hardware. You can export everything at any time. The source code is publicly auditable under AGPL-3.0, so there are no hidden data transfers, no telemetry, and no surprises.":
        "OpenConstructionERP өөр аргыг сонгосон. Таны өгөгдөл нь өөрийн тань техник хангамж дээр нээлттэй формат (SQLite, JSON, CSV)-аар хадгалагдана. Та бүх зүйлийг дурын үед экспортлох боломжтой. Эх код нь AGPL-3.0 лицензийн дор нийтэд аудит хийгдэх боломжтой тул нуугдсан өгөгдөл дамжуулалт, телеметр, гэнэтийн зүйл байхгүй.",

    "The platform is modular — install only what you need. Community modules extend functionality without bloating the core. And because it runs locally, it works offline and performs fast even with large projects.":
        "Платформ нь модуль бүтэцтэй — танд хэрэгтэйг л суулгана. Хамт олны модулиуд цөмийг хэт ачаалахгүйгээр функциональ байдлыг өргөтгөдөг. Дотооддоо ажилладаг тул интернетгүйгээр ч ажиллах ба том төслүүдийн үед хүртэл хурдан ажилладаг.",

    "OpenConstructionERP is designed for anyone involved in construction cost management — whether you work on residential projects or large-scale infrastructure, in-house or as a consultant.":
        "OpenConstructionERP нь барилгын өртгийн удирдлагад оролцдог хэн бүхэнд зориулагдсан — та орон сууцны төсөл дээр ажилладаг ч, том хэмжээний дэд бүтцийн төсөл дээр ажилладаг ч, дотоодын мэргэжилтэн ч, зөвлөх ч байсан хамаагүй.",

    "Create detailed BOQ with hierarchical sections, positions, assemblies, markups (overhead, profit, VAT), and automatic totals. Supports DIN 276, NRM 1/2, MasterFormat, and custom classification systems.":
        "Шатлалт хэсэг, байрлал, угсралт, тэмдэглэгээ (нэмэгдэл, ашиг, VAT), автомат нийт дүн бүхий дэлгэрэнгүй BOQ үүсгэнэ. DIN 276, NRM 1/2, MasterFormat болон захиалгат ангиллын системийг дэмждэг.",

    "7,000+ resources — materials, equipment, labor, operators, and utilities. Build reusable assemblies (composite rates) from catalog items and apply them directly to BOQ positions.":
        "7,000+ нөөц — материал, тоног төхөөрөмж, хөдөлмөр, оператор, инженерийн шугам. Каталогийн зүйлсээс дахин ашиглах боломжтой угсралт (нийлмэл тариф) бүтээгээд BOQ-н байрлалд шууд хэрэглэнэ.",

    "Track budgets over time with Earned Value Management (SPI, CPI), S-curve visualization, cash flow projections, cost snapshots, and what-if scenario modeling for informed decision-making.":
        "Earned Value Management (SPI, CPI), S-curve дүрслэл, мөнгөн урсгалын урьдчилсан тооцоо, өртгийн хувилбар, мэдээлэлд суурилсан шийдвэр гаргалтад зориулсан what-if хувилбарын загварчлал ашиглан төсвийг цаг хугацааны явцад хянана.",

    "55,000+ cost items across 30 regional databases worldwide. Add your own rates, import from Excel, or build a custom database from scratch.":
        "Дэлхий даяар 30 бүсийн өгөгдлийн санд 55,000+ өртгийн зүйл. Өөрийн тарифыг нэмэх, Excel-ээс импортлох, эсвэл захиалгат өгөгдлийн санг шинээр бүтээх боломжтой.",

    "Full support for GAEB XML (X83), Excel, and CSV import/export. Generate professional PDF reports. Seamlessly integrate with your existing tools and workflows.":
        "GAEB XML (X83), Excel, CSV импорт/экспортыг бүрэн дэмждэг. Мэргэжлийн PDF тайлан үүсгэнэ. Одоо байгаа таны хэрэгсэл болон ажлын урсгалд саадгүй нийлэн ажиллана.",

    "Create project schedules with CPM critical path calculation, interactive Gantt charts, Monte Carlo risk analysis, resource assignment, and auto-generation of activities from your BOQ.":
        "CPM чухал замын тооцоолол, интерактив Gantt диаграм, Monte Carlo эрсдэлийн шинжилгээ, нөөцийн хуваарилалт, BOQ-оос үйл ажиллагааг автоматаар үүсгэх замаар төслийн хуваарийг үүсгэнэ.",

    "Create tender packages with scope and positions, distribute to subcontractors, collect and compare bids side-by-side in a price mirror, and make award decisions based on data.":
        "Хүрээ ба байрлалтай тендерийн багц үүсгэн, туслан гүйцэтгэгчдэд тарааж, үнийн толинд саналуудыг зэрэгцүүлэн харьцуулж цуглуулан, өгөгдөлд тулгуурлан гэрээ байгуулах шийдвэр гаргана.",

    "Built-in quality engine automatically checks for missing quantities, zero prices, duplicate positions, classification compliance, and rate anomalies — with a traffic-light dashboard.":
        "Дотоод чанарын систем нь дутуу тоо хэмжээ, тэг үнэ, давхардсан байрлал, ангиллын дагалт, тарифын гажиглыг автоматаар шалгах ба гэрлэн дохиотой самбараар үзүүлдэг.",

    "OpenConstructionERP includes optional AI-powered tools — quick estimation from text descriptions, smart cost suggestions, and BOQ chat assistant. These features require an API key from a provider of your choice (Anthropic, OpenAI, Google). AI is always opt-in: it only activates when you configure it, and you decide what data to send. Without an API key, all other features work fully offline.":
        "OpenConstructionERP нь нэмэлт AI-д суурилсан хэрэгслүүдтэй — текст тайлбараас хурдан тооцоо, ухаалаг өртгийн санал, BOQ чат туслах. Эдгээр боломжуудад таны сонгосон үйлчилгээ үзүүлэгчийн (Anthropic, OpenAI, Google) API түлхүүр шаардлагатай. AI нь үргэлж сонголтоор идэвхждэг: зөвхөн та тохируулах үед идэвхэжих ба ямар өгөгдөл илгээхийг та шийднэ. API түлхүүргүйгээр бусад бүх боломж бүрэн оффлайн ажиллана.",

    "CAD/BIM files (.rvt, .ifc, .dwg, .dgn) require the DDC converter to be installed. Elements will be extracted and used to generate a cost estimate. Download converters from GitHub and place them in ~/.openestimator/converters/.":
        "CAD/BIM файлууд (.rvt, .ifc, .dwg, .dgn) нь DDC хөрвүүлэгч суулгасан байхыг шаардана. Элементүүдийг гаргаж авч өртгийн тооцоо үүсгэхэд ашиглана. Хөрвүүлэгчдийг GitHub-аас татаж ~/.openestimator/converters/ зам дотор байршуулна уу.",

    "Add your API key for Anthropic Claude, OpenAI, or Google Gemini to generate estimates from text, photos, PDFs, and CAD files.":
        "Текст, зураг, PDF, CAD файлуудаас тооцоо үүсгэхийн тулд Anthropic Claude, OpenAI, эсвэл Google Gemini-ийн API түлхүүрээ нэмнэ үү.",

    "Ask questions about costs, materials, and pricing — from your database and AI knowledge":
        "Өртөг, материал, үнийн талаар асуулт асуу — таны өгөгдлийн сан болон AI мэдлэгээс",

    "Auto-detects tab-separated, semicolon, or comma-delimited data. AI will parse and structure your data into estimate items.":
        "Tab, цэг таслал, эсвэл таслалаар тусгаарласан өгөгдлийг автоматаар таньдаг. AI таны өгөгдлийг задлан тооцооны зүйлс болгон бүтэцлэнэ.",

    "Works best with columns: Description, Unit, Quantity, Rate/Price.":
        "Дараах баганатай үед хамгийн сайн ажилладаг: Тайлбар, Нэгж, Тоо хэмжээ, Тариф/Үнэ.",

    "Upload BOQ documents, specifications, or drawings in PDF format.":
        "BOQ баримт бичиг, тодорхойлолт, эсвэл зургийг PDF форматаар байршуулна уу.",

    "Please try again or check your AI settings.":
        "Дахин оролдох эсвэл AI тохиргоогоо шалгана уу.",

    "Based on AACE International Recommended Practice 18R-97. Classification is auto-detected from BOQ completeness metrics.":
        "AACE International-ын зөвлөмжтэй практик 18R-97-д үндэслэсэн. Ангилал нь BOQ-ийн бүрэн байдлын үзүүлэлтээс автоматаар тодорхойлогдоно.",

    "Ask me to generate BOQ positions. For example: \\\"Add MEP items for a 5-story office building\\\"":
        "BOQ байрлал үүсгэхийг надаас гуй. Жишээ нь: \\\"5 давхар оффис барилгад MEP зүйлс нэмэх\\\"",

    "Assemblies are reusable cost recipes that combine multiple resources (materials, labor, equipment) into a single composite rate. For example, a \\\"Reinforced Concrete Wall\\\" assembly includes concrete, rebar, formwork, and labor. Apply assemblies to BOQ positions to auto-populate component costs.":
        "Угсралтууд гэдэг нь олон нөөцийг (материал, хөдөлмөр, тоног төхөөрөмж) нэг нийлмэл тариф болгон нэгтгэдэг дахин ашиглах боломжтой өртгийн жор юм. Жишээ нь, \\\"Армопэлсэн бетон хана\\\" угсралтад бетон, арматур, хашмал, хөдөлмөр багтана. Бүрэлдэхүүний өртгийг автоматаар оруулахын тулд угсралтыг BOQ байрлалд хэрэглэнэ.",
}


def main() -> None:
    # newline="" on both ends, and each line keeps the ending it arrived with.
    # Path.read_text/write_text translate line endings, so on Windows a run that
    # replaces nothing still rewrites every line ending in mn.ts to CRLF.
    with open(EN_PATH, encoding="utf-8", newline="") as fh:
        en_text = fh.read()
    with open(MN_PATH, encoding="utf-8", newline="") as fh:
        mn_text = fh.read()

    en_full = re.compile(r'"((?:[^"\\]|\\.)+)"\s*:\s*"((?:[^"\\]|\\.)*)"')
    en_pairs = {m.group(1): m.group(2) for m in en_full.finditer(en_text)}

    # Build a map of en-value -> proper translation
    pat = re.compile(r'^(\s*)"((?:[^"\\]|\\.)+)"\s*:\s*"((?:[^"\\]|\\.)*)"(,?)\s*$')

    # Identify keys whose EN matches our FULL_TRANSLATIONS
    keys_to_replace: dict[str, str] = {}
    for k, en_v in en_pairs.items():
        # decoded en_v
        dec = en_v.replace('\\"', '"').replace("\\\\", "\\")
        if dec in FULL_TRANSLATIONS:
            keys_to_replace[k] = FULL_TRANSLATIONS[dec]

    print(f"Will replace {len(keys_to_replace)} long entries")

    out_lines: list[str] = []
    count = 0
    for line in mn_text.splitlines(keepends=True):
        stripped = line.rstrip("\n").rstrip("\r")
        eol = line[len(stripped):]
        m = pat.match(stripped)
        if m:
            indent, key, value, comma = m.group(1), m.group(2), m.group(3), m.group(4)
            if key in keys_to_replace:
                new_val = keys_to_replace[key]
                esc = new_val.replace("\\", "\\\\").replace('"', '\\"')
                # Note: new_val may already contain literal \\\" sequences that we need
                # Actually we provide raw strings, so escape normally:
                # But some entries had escaped quotes in the EN source - we mirror them
                new_line = f'{indent}"{key}": "{esc}"{comma}{eol}'
                out_lines.append(new_line)
                count += 1
                continue
        out_lines.append(line)

    with open(MN_PATH, "w", encoding="utf-8", newline="") as fh:
        fh.write("".join(out_lines))
    print(f"Replaced {count} long entries")


if __name__ == "__main__":
    main()
