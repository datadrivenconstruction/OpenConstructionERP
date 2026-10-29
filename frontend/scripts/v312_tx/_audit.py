"""Audit: for each target locale, count how many v3.12 keys still equal English."""
import json
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from _parse_helper import parse_ts

LOCALES_DIR = r'C:/Users/dev/Desktop/CodeProjects/ERP_26030500/frontend/src/app/locales'
TARGETS = ['ar', 'bg', 'cs', 'da', 'fi', 'hi', 'hr', 'id', 'ja', 'ko', 'mn', 'no', 'ro', 'sv', 'th', 'tr', 'vi']

en, _, _ = parse_ts(f'{LOCALES_DIR}/en.ts')

# load reference key list (use ru.json — same 485 keys)
with open(r'C:/Users/dev/Desktop/CodeProjects/ERP_26030500/frontend/scripts/v312_tx/ru.json',
          'r', encoding='utf-8') as f:
    ru = json.load(f)

v312_keys = [k for k in ru if k in en]  # 483 keys present in en
print(f'v3.12 keys to audit: {len(v312_keys)}\n')

for lang in TARGETS:
    loc, _, _ = parse_ts(f'{LOCALES_DIR}/{lang}.ts')
    missing_in_locale = [k for k in v312_keys if k not in loc]
    placeholders = [k for k in v312_keys if k in loc and loc[k] == en[k]]
    translated = [k for k in v312_keys if k in loc and loc[k] != en[k]]
    print(f'{lang}: total_in_locale_keys={len(loc)} placeholder={len(placeholders)} translated={len(translated)} missing={len(missing_in_locale)}')
