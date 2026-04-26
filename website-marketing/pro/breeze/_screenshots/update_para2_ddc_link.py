"""Wrap *Data-Driven Construction* (book title) with a link to the DDC homepage
in voices.para2 across all 3 locales, and add ref_ddc_* sidebar strings."""
import json, re
from pathlib import Path

BASE = Path('C:/Users/Artem Boiko/Desktop/CodeProjects/ERP_26030500/website-marketing/pro/breeze/locales')

# Replace the bare <em>Data-Driven Construction</em> with an anchor.
LINK_OPEN = '<a href="https://datadrivenconstruction.io/" target="_blank" rel="noopener" style="color: var(--accent-3); text-decoration: underline; text-underline-offset: 2px; font-style: italic;">'
LINK_CLOSE = '</a>'

# Each locale has the italic phrase translated. We wrap whatever sits inside
# <em>...</em> immediately before the "datadrivenconstruction.io/books" anchor.
EM_PATTERN = re.compile(r'<em>([^<]+)</em>')

REF_DDC = {
    'en': {
        'ref_ddc_name': 'DataDrivenConstruction',
        'ref_ddc_meta': 'The Lab Homepage',
    },
    'de': {
        'ref_ddc_name': 'DataDrivenConstruction',
        'ref_ddc_meta': 'Die Lab-Homepage',
    },
    'ru': {
        'ref_ddc_name': 'DataDrivenConstruction',
        'ref_ddc_meta': 'Сайт лаборатории',
    },
}

for lang in ['en', 'de', 'ru']:
    p = BASE / f'{lang}.json'
    data = json.loads(p.read_text(encoding='utf-8'))
    para2 = data['voices']['para2']

    # Wrap the FIRST <em>...</em> occurrence (the book title) in the homepage link.
    m = EM_PATTERN.search(para2)
    if not m:
        print(f'!! {lang}: <em> not found in para2')
    else:
        inner = m.group(1)
        replacement = f'{LINK_OPEN}{inner}{LINK_CLOSE}'
        para2 = para2[:m.start()] + replacement + para2[m.end():]
        data['voices']['para2'] = para2
        print(f'updated {lang}.json para2 (wrapped: {inner!r})')

    # Update group_count for flagship section to 04 (we added the DDC card).
    data['voices'].update(REF_DDC[lang])
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
