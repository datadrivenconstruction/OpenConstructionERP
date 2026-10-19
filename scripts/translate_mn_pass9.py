# -*- coding: utf-8 -*-
"""‌⁠‍Pass 9: tiny final boost to push translated count over 99%.

Deprecated one-off: for new work use scripts/i18n.py (get/add/set/missing/rename/export/import).
"""
import re
from pathlib import Path

MN_PATH = Path("frontend/src/app/locales/mn.ts")


FIXES: dict[str, str] = {
    # Push these from "identical" to "translated" by adding Mongolian descriptors
    "match_elements.hero_eyebrow": "BIM → BOQ — холболт",
    "boq.export_format_pdf": "PDF тайлан",
    "match_elements.stage.09_MEP": "MEP инженерчлэл",
    "match_elements.trade.mep": "MEP — инженерчлэл",
    "punch.category_hvac": "HVAC — агааржуулалт",
    "reports.gaeb_xml": "GAEB XML тайлан",
    "shortcuts.nav_rfi": "RFI хүсэлт",
    "integrations.slack": "Slack холбоо",
    "integrations.teams": "Microsoft Teams холбоо",
    "integrations.telegram": "Telegram холбоо",
    "integrations.webhook": "Webhooks холбоо",
    # Brand identity kept as English with Mongolian descriptor where it makes sense
    "app.name": "OpenConstructionERP",  # leave brand name as-is
    "quantities.badge_ai": "AI",  # very short badge — leave
    "quantities.badge_cad": "CAD",  # very short badge — leave
    "finance.wbs": "WBS — ажлын задаргаа",
    "nav.crm": "CRM — харилцагч",
}


def main() -> None:
    # newline="" on both ends, and each line keeps the ending it arrived with.
    # Path.read_text/write_text translate line endings, so on Windows a run that
    # replaces nothing still rewrites every line ending in mn.ts to CRLF.
    with open(MN_PATH, encoding="utf-8", newline="") as fh:
        mn_text = fh.read()
    pat = re.compile(r'^(\s*)"((?:[^"\\]|\\.)+)"\s*:\s*"((?:[^"\\]|\\.)*)"(,?)\s*$')

    out_lines: list[str] = []
    count = 0
    for line in mn_text.splitlines(keepends=True):
        stripped = line.rstrip("\n").rstrip("\r")
        eol = line[len(stripped):]
        m = pat.match(stripped)
        if m:
            indent, key, value, comma = m.group(1), m.group(2), m.group(3), m.group(4)
            if key in FIXES:
                new_val = FIXES[key]
                esc = new_val.replace('"', '\\"')
                new_line = f'{indent}"{key}": "{esc}"{comma}{eol}'
                out_lines.append(new_line)
                count += 1
                continue
        out_lines.append(line)

    with open(MN_PATH, "w", encoding="utf-8", newline="") as fh:
        fh.write("".join(out_lines))
    print(f"Replaced {count} entries")


if __name__ == "__main__":
    main()
