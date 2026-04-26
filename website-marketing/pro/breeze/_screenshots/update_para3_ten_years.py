"""Add 'over the past ten years' to the closing sentence of voices.para3."""
import json
from pathlib import Path

BASE = Path('C:/Users/Artem Boiko/Desktop/CodeProjects/ERP_26030500/website-marketing/pro/breeze/locales')

REPLACEMENTS = {
    'en': (
        'Many who asked me what tools I was developing inevitably heard my ideas about creating an open-source modular ERP system.',
        'Those who have asked me over the past ten years what tools I was developing inevitably heard my ideas about creating an open-source modular ERP system.',
    ),
    'de': (
        'Viele, die mich fragten, woran ich arbeite, hörten unweigerlich meine Gedanken zu einem modularen Open-Source-ERP-System.',
        'Diejenigen, die mich in den letzten zehn Jahren fragten, woran ich arbeite, hörten unweigerlich meine Gedanken zu einem modularen Open-Source-ERP-System.',
    ),
    'ru': (
        'Многие, кто спрашивал меня, какие инструменты я разрабатываю, неизбежно слышали мои идеи о создании открытой модульной ERP-системы.',
        'Те, кто спрашивал меня последние десять лет, какие инструменты я разрабатываю, неизбежно слышали мои идеи о создании открытой модульной ERP-системы.',
    ),
}

for lang, (old, new) in REPLACEMENTS.items():
    p = BASE / f'{lang}.json'
    data = json.loads(p.read_text(encoding='utf-8'))
    para3 = data['voices']['para3']
    if old not in para3:
        print(f'!! {lang}: phrase not found, skipping')
        continue
    data['voices']['para3'] = para3.replace(old, new)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'updated {lang}.json')
