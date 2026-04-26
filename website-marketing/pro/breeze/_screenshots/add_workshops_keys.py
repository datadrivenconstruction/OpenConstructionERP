"""Add workshops.{eyebrow,title,lede} keys to en/de/ru locale files."""
import json
from pathlib import Path

BASE = Path('C:/Users/Artem Boiko/Desktop/CodeProjects/ERP_26030500/website-marketing/pro/breeze/locales')

KEYS = {
    'en': {
        'eyebrow': 'DataDrivenConstruction Workshop',
        'title': 'Hands-on training, <span class="italic">in your stack.</span>',
        'lede': 'Selected public workshops only. Many major enterprise engagements remain under NDA.',
    },
    'de': {
        'eyebrow': 'DataDrivenConstruction Workshop',
        'title': 'Praxistraining, <span class="italic">in Ihrem Stack.</span>',
        'lede': 'Nur ausgewählte öffentliche Workshops. Viele größere Enterprise-Engagements bleiben unter NDA.',
    },
    'ru': {
        'eyebrow': 'DataDrivenConstruction Workshop',
        'title': 'Практическое обучение, <span class="italic">внутри вашего стека.</span>',
        'lede': 'Только избранные публичные воркшопы. Большая часть корпоративных проектов остаётся под NDA.',
    },
}

for lang, vals in KEYS.items():
    p = BASE / f'{lang}.json'
    data = json.loads(p.read_text(encoding='utf-8'))
    data['workshops'] = vals
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'updated {lang}.json')
