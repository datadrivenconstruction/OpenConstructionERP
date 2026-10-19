# -*- coding: utf-8 -*-
"""‌⁠‍Third-pass translator for the final remaining entries.

These are mostly technical labels where translation matters less, but we'll
handle the cases that have real prose. Pure-acronym entries (CPI, SPI, EVM,
MEP, HVAC, etc.) and brand names are intentionally left in English — these
are domain conventions used internationally regardless of locale.
Deprecated one-off: for new work use scripts/i18n.py (get/add/set/missing/rename/export/import).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MN_PATH = ROOT / "frontend" / "src" / "app" / "locales" / "mn.ts"
UNTRANS_JSON = ROOT / "scripts" / "_mn_remaining.json"


PHRASES: dict[str, str] = {
    # match_elements remaining
    "Spatial": "Орон зайн",
    "Voids": "Хоосон зай",
    "Runtime: {{runtime}} · model_loaded={{loaded}}": "Runtime: {{runtime}} · model_loaded={{loaded}}",
    "Runs locally": "Дотооддоо ажилладаг",
    "Match analytics": "Тааруулалтын аналитик",
    "{{n}} alert": "{{n}} анхааруулга",
    "{{n}} alerts": "{{n}} анхааруулга",
    "Window": "Цонх",
    "{{n}}d": "{{n}}ө",
    "Searches": "Хайлтууд",
    "{{n}} picks": "{{n}} сонголт",
    "p95 {{p}}": "p95 {{p}}",
    "Latency p95": "Хоцрогдол p95",
    "mean {{m}}": "дундаж {{m}}",
    "Zero-hit": "Тэгийн үр дүн",
    "mean rank {{r}}": "дундаж байр {{r}}",
    "BGE rerank": "BGE дахин эрэмбэлэх",
    "LLM rerank {{p}}": "LLM дахин эрэмбэлэх {{p}}",
    "Relax tier distribution": "Сулруулсан түвшний хуваарилалт",
    "Confidence band distribution": "Итгэлийн зурвасын хуваарилалт",
    "Collapse analytics": "Аналитикыг хураах",
    "Expand analytics": "Аналитикыг дэлгэх",
    "Close template library": "Загварын санг хаах",
    # boq misc
    "%": "%",  # left as-is intentionally
    "/": "/",  # left as-is intentionally
    # notification
    "RFI {{rfi_number}} — {{subject}}": "RFI {{rfi_number}} — {{subject}}",
    "{{task_title}}": "{{task_title}}",
    "Invoice {{invoice_number}} — {{amount_total}} {{currency_code}}": "Нэхэмжлэх {{invoice_number}} — {{amount_total}} {{currency_code}}",
    "Inspection scheduled": "Шалгалт хуваарьласан",
    "Submittal status changed": "Илгээлтийн төлөв өөрчлөгдсөн",
    "{{submittal_number}} ({{title}}) — {{new_status}}": "{{submittal_number}} ({{title}}) — {{new_status}}",
    "Meeting scheduled": "Уулзалт хуваарьласан",
    "Non-conformance raised": "Үл нийцлэл бүртгэгдсэн",
    "NCR {{ncr_number}} — {{title}} ({{severity}})": "NCR {{ncr_number}} — {{title}} ({{severity}})",
    "{{document_name}}": "{{document_name}}",
    # conflict
    "Conflict resolution panel": "Зөрчил шийдвэрлэх самбар",
    # bim_upload
    "Converting CAD geometry...": "CAD геометрийг хөрвүүлж байна...",
    # shortcuts
    "RFI": "RFI",
}


def main() -> None:
    with open(UNTRANS_JSON, encoding="utf-8") as f:
        untranslated = json.load(f)

    new_translations: dict[str, str] = {}
    for k, en_v in untranslated.items():
        if en_v in PHRASES:
            t = PHRASES[en_v]
            if t != en_v:
                new_translations[k] = t

    print(f"Translating {len(new_translations)} / {len(untranslated)} remaining entries")

    # newline="" on both ends, and each line keeps the ending it arrived with.
    # Path.read_text/write_text translate line endings, so on Windows a run that
    # replaces nothing still rewrites every line ending in mn.ts to CRLF.
    with open(MN_PATH, encoding="utf-8", newline="") as fh:
        mn_text = fh.read()
    out_lines: list[str] = []
    pat = re.compile(r'^(\s*)"((?:[^"\\]|\\.)+)"\s*:\s*"((?:[^"\\]|\\.)*)"(,?)\s*$')

    count_replaced = 0
    for line in mn_text.splitlines(keepends=True):
        stripped = line.rstrip("\n").rstrip("\r")
        eol = line[len(stripped):]
        m = pat.match(stripped)
        if m:
            indent, key, value, comma = m.group(1), m.group(2), m.group(3), m.group(4)
            if key in new_translations:
                new_val = new_translations[key]
                esc = new_val.replace("\\", "\\\\").replace('"', '\\"')
                new_line = f'{indent}"{key}": "{esc}"{comma}{eol}'
                out_lines.append(new_line)
                count_replaced += 1
                continue
        out_lines.append(line)

    with open(MN_PATH, "w", encoding="utf-8", newline="") as fh:
        fh.write("".join(out_lines))
    print(f"Replaced {count_replaced} entries in mn.ts")


if __name__ == "__main__":
    main()
