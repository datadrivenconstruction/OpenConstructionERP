"""Replace the 'History of BIM' search hint in voices.para1 across all 3
locales with two specific article titles: 'Lobbyist Wars and BIM
Development' and 'The History of BIM Map'."""
import json
from pathlib import Path

BASE = Path('C:/Users/Artem Boiko/Desktop/CodeProjects/ERP_26030500/website-marketing/pro/breeze/locales')

REPLACEMENTS = {
    'en': (
        'simply search for <em>“History of BIM”</em>',
        'simply search for <em>“Lobbyist Wars and BIM Development”</em> and <em>“The History of BIM Map”</em>',
    ),
    'de': (
        'sucht einfach nach <em>„History of BIM“</em>',
        'sucht einfach nach <em>„Lobbyist Wars and BIM Development“</em> und <em>„The History of BIM Map“</em>',
    ),
    'ru': (
        'достаточно набрать <em>«History of BIM»</em> в поиске',
        'достаточно поискать <em>«Lobbyist Wars and BIM Development»</em> и <em>«The History of BIM Map»</em>',
    ),
}

for lang, (old, new) in REPLACEMENTS.items():
    p = BASE / f'{lang}.json'
    data = json.loads(p.read_text(encoding='utf-8'))
    para1 = data['voices']['para1']
    if old not in para1:
        print(f'!! {lang}: phrase not found, skipping')
        continue
    data['voices']['para1'] = para1.replace(old, new)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'updated {lang}.json')
