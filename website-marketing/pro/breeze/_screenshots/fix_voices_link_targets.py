"""Replace anchor-jump targets (#voices-ref-*) with the real external URLs
across voices.para2 and voices.para3 in all 3 locale files."""
import json, re
from pathlib import Path

BASE = Path('C:/Users/Artem Boiko/Desktop/CodeProjects/ERP_26030500/website-marketing/pro/breeze/locales')

# Map every fragment-link to a real URL that opens in a new tab.
LINK_MAP = {
    '#voices-ref-book':     'https://datadrivenconstruction.io/books/',
    '#voices-ref-cad2data': 'https://github.com/datadrivenconstruction/cad2data-Revit-IFC-DWG-DGN',
    '#voices-ref-cwicr':    'https://github.com/datadrivenconstruction/OpenConstructionEstimate-DDC-CWICR',
}

# Match <a href="#voices-ref-..."> with possibly other attrs preceding/following.
ANCHOR_RE = re.compile(r'<a\s+([^>]*?)href="(#voices-ref-[a-z0-9]+)"([^>]*)>', re.IGNORECASE)


def rewrite(html_str):
    def repl(m):
        before, frag, after = m.group(1), m.group(2), m.group(3)
        url = LINK_MAP.get(frag)
        if not url:
            return m.group(0)
        # Drop any pre-existing target/rel from before/after, then inject fresh ones.
        cleaned = (before + after).strip()
        cleaned = re.sub(r'\s*target="[^"]*"', '', cleaned)
        cleaned = re.sub(r'\s*rel="[^"]*"', '', cleaned)
        cleaned = cleaned.strip()
        attrs = (cleaned + ' ').strip()
        prefix = (attrs + ' ') if attrs else ''
        return f'<a {prefix}href="{url}" target="_blank" rel="noopener">'
    return ANCHOR_RE.sub(repl, html_str)


KEYS = ['para1', 'para2', 'para3', 'para4', 'pull']

for lang in ['en', 'de', 'ru']:
    p = BASE / f'{lang}.json'
    data = json.loads(p.read_text(encoding='utf-8'))
    voices = data['voices']
    changed = 0
    for k in KEYS:
        if k not in voices:
            continue
        before = voices[k]
        after = rewrite(before)
        if after != before:
            voices[k] = after
            changed += 1
    if changed:
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'updated {p.name}: rewrote anchor links in {changed} keys')
    else:
        print(f'{p.name}: no anchor links found')
