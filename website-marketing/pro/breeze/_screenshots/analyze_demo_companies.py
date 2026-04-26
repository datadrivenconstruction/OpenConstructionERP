"""Pull a curated, ranked list of companies that signed up for the demo —
   filtering out junk, test entries, and disposable emails — so we can
   pick the most recognizable brands for the trust-strip logo wall."""
import json
import re
from collections import defaultdict
from pathlib import Path

SRC = Path('C:/Users/Artem Boiko/Desktop/demo-registrations.jsonl')

# Load with the same tolerant parser as the Excel exporter.
rows = []
with SRC.open(encoding='utf-8') as f:
    decoder = json.JSONDecoder()
    for line in f:
        line = line.strip()
        if not line:
            continue
        idx = 0
        while idx < len(line):
            try:
                obj, end = decoder.raw_decode(line, idx)
            except json.JSONDecodeError:
                break
            rows.append(obj)
            idx = end
            while idx < len(line) and line[idx] in ' \t,':
                idx += 1

# ─── Filter junk ────────────────────────────────────────────────────────
JUNK_NAME = re.compile(r'^(test|qwerty|asdf|zxcv|тест|123|abc|aaaa|----)\b', re.I)
JUNK_COMPANY = re.compile(
    r'^(test|тест|asdf|qwerty|abc|123|none|n/?a|--|sole|self|private|home|individual)\s*$',
    re.I)
DISPOSABLE = {
    'mailinator.com', 'tempmail.com', 'guerrillamail.com', 'yopmail.com',
    '10minutemail.com', 'trashmail.com', 'sharklasers.com', 'fakeinbox.com',
    'example.com', 'example.org', 'test.com',
}
FREE_MAIL = {
    'gmail.com', 'googlemail.com', 'yahoo.com', 'yahoo.co.uk', 'hotmail.com',
    'outlook.com', 'live.com', 'icloud.com', 'me.com', 'aol.com', 'mail.com',
    'mail.ru', 'yandex.ru', 'yandex.com', 'protonmail.com', 'proton.me',
    'gmx.de', 'gmx.com', 'web.de', 'qq.com', '163.com', '126.com',
}

clean = []
for r in rows:
    company = (r.get('company') or '').strip()
    email = (r.get('email') or '').strip().lower()
    fname = (r.get('firstName') or '').strip()
    lname = (r.get('lastName') or '').strip()

    if not company or len(company) < 2:
        continue
    if JUNK_COMPANY.match(company):
        continue
    if JUNK_NAME.match(fname) or JUNK_NAME.match(lname):
        continue
    if '@' not in email:
        continue
    domain = email.rsplit('@', 1)[1]
    if domain in DISPOSABLE:
        continue
    clean.append({
        'company': company,
        'email': email,
        'domain': domain,
        'name': f'{fname} {lname}'.strip(),
        'role': r.get('role') or '',
        'size': r.get('companySize') or '',
        'lang': r.get('language') or '',
        'time': r.get('server_time') or '',
        'is_corp_domain': domain not in FREE_MAIL,
    })

# ─── Group by normalised company name ──────────────────────────────────
def norm(c):
    s = c.lower().strip()
    s = re.sub(r'[\s\-\.,/]+', ' ', s)
    s = re.sub(r'\b(gmbh|ag|ltd|llc|inc|sa|s\.?a\.?|s\.?l\.?|spa|s\.?r\.?l\.?|kg|bv|nv|pllc|llp|gmbh & co kg|& co)\b', '', s)
    return s.strip()

groups = defaultdict(list)
for r in clean:
    groups[norm(r['company'])].append(r)

# ─── Score and sort ────────────────────────────────────────────────────
scored = []
for key, members in groups.items():
    primary = members[0]['company']
    n_signups = len(members)
    has_corp = any(m['is_corp_domain'] for m in members)
    sample_domain = next((m['domain'] for m in members if m['is_corp_domain']), members[0]['domain'])
    sample_role = members[0]['role']
    size = members[0]['size']
    # heuristic: corp-domain emails outweigh personal-mail signups
    score = n_signups * (3 if has_corp else 1)
    scored.append({
        'company': primary,
        'norm': key,
        'count': n_signups,
        'has_corp': has_corp,
        'domain': sample_domain,
        'role': sample_role,
        'size': size,
        'score': score,
        'names': [m['name'] for m in members],
    })

scored.sort(key=lambda r: (-r['score'], r['company']))

# ─── Print buckets ──────────────────────────────────────────────────────
print('=' * 78)
print(f'TOTAL CLEAN SIGNUPS: {len(clean)}')
print(f'UNIQUE COMPANIES (deduped): {len(scored)}')
print('=' * 78)

print('\n--- A. CORPORATE-DOMAIN SIGNUPS (highest signal — they used a work email) ---\n')
corp = [r for r in scored if r['has_corp']]
print(f'{len(corp)} unique companies\n')
for r in corp:
    star = '*' if r['count'] > 1 else ' '
    print(f"  {star} {r['company']:<40s}  @{r['domain']:<28s}  role={r['role']:<10s}  size={r['size']}")

print('\n--- B. NOTABLE NAMES WORTH INVESTIGATING (personal-mail but recognisable) ---\n')
notable_keywords = (
    'group', 'engineering', 'construction', 'bau', 'baugruppe', 'consulting',
    'university', 'institut', 'invest', 'develop', 'studio', 'arch', 'plan',
    'architects', 'partners', 'ingenieur', 'projekt', 'industrie', 'building',
    'estate', 'real', 'civil', 'corp', 'kapital',
)
personal = [r for r in scored if not r['has_corp']]
notable = [r for r in personal if any(kw in r['company'].lower() for kw in notable_keywords)]
print(f'{len(notable)} potentially-notable names\n')
for r in notable:
    print(f"    {r['company']:<50s}  @{r['domain']:<22s}  size={r['size']}")
