"""Replace the inline article-search phrase in voices.para1 with a series-of-articles
phrase, in en/de/ru locale files."""
import json
from pathlib import Path

BASE = Path('C:/Users/Artem Boiko/Desktop/CodeProjects/ERP_26030500/website-marketing/pro/breeze/locales')

REPLACEMENTS = {
    'en': (
        'for those interested in this context, simply search for <em>“Lobbyist Wars and BIM Development”</em> and <em>“The History of BIM Map”</em>',
        'see the series of articles <em>“The Lobbyists’ Wars and the Development of BIM”</em> and <em>“The History of the BIM Map”</em>',
    ),
    'de': (
        'wer sich für diesen Kontext interessiert, sucht einfach nach <em>„Lobbyist Wars and BIM Development“</em> und <em>„The History of BIM Map“</em>',
        'siehe die Artikelserie <em>„The Lobbyists’ Wars and the Development of BIM“</em> und <em>„The History of the BIM Map“</em>',
    ),
    'ru': (
        'кому интересен этот контекст—достаточно поискать <em>«Lobbyist Wars and BIM Development»</em> и <em>«The History of BIM Map»</em>',
        'см. серию статей <em>«The Lobbyists’ Wars and the Development of BIM»</em> и <em>«The History of the BIM Map»</em>',
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
