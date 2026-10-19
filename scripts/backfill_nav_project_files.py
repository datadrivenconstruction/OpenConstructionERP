"""‌⁠‍Insert "nav.project_files" into the locales that don't have it.

The key is referenced by Sidebar.tsx and Header.tsx. Locales without it
fall through to the English label "Project Files" — surfaces in the
left sidebar and the breadcrumb.

Idempotent: if the key is already present in a locale, that file is
skipped. Backups are not made — this is a tracked file in git.
Deprecated one-off: for new work use scripts/i18n.py (get/add/set/missing/rename/export/import).
"""

from __future__ import annotations

import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

LOCALES_DIR = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "src" / "app" / "locales"

# Native-language translations sourced from each language's standard
# dictionary entries for "project files" (Wikipedia, common UI corpora).
# Where unsure, the closest natural phrase is used; review-friendly.
TRANSLATIONS = {
    "ko": "프로젝트 파일",
    "pl": "Pliki projektu",
    "sv": "Projektfiler",
    "tr": "Proje dosyaları",
    "nl": "Projectbestanden",
    "cs": "Projektové soubory",
    "fi": "Projektitiedostot",
    "ro": "Fișiere proiect",
    "hr": "Projektne datoteke",
    "id": "Berkas proyek",
    "da": "Projektfiler",
    "no": "Prosjektfiler",
    "vi": "Tệp dự án",
    "th": "ไฟล์โครงการ",
    "bg": "Файлове на проекта",
    "it": "File del progetto",
}


def insert_key(path: pathlib.Path, translation: str) -> bool:
    # Read preserving line endings: Path.read_text has no newline= and would
    # translate CRLF to LF, which turns a one-key edit into a whole-file diff.
    with open(path, encoding="utf-8", newline="") as fh:
        text = fh.read()
    eol = "\r\n" if "\r\n" in text else "\n"
    if '"nav.project_files":' in text:
        return False
    # Insert just before "nav.projects":, preserving indentation.
    pattern = r'(    "nav\.projects":)'
    new_line = f'    "nav.project_files": "{translation}",{eol}'
    if not re.search(pattern, text):
        return False
    text2 = re.sub(pattern, new_line + r"\1", text, count=1)
    path.write_text(text2, encoding="utf-8", newline="")
    return True


def main() -> int:
    changed = 0
    for code, translation in TRANSLATIONS.items():
        path = LOCALES_DIR / f"{code}.ts"
        if not path.exists():
            print(f"  skip: {code}.ts not found")
            continue
        if insert_key(path, translation):
            print(f"  + {code}: {translation}")
            changed += 1
        else:
            print(f"  = {code}: already present or no anchor")
    print(f"\n{changed} locale(s) updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
