import json, re, html
d = json.load(open('C:/Users/Artem Boiko/AppData/Local/Temp/live_en.json', encoding='utf-8'))
v = d.get('voices', {})

def clean(s):
    s = re.sub(r'<[^>]+>', '', s)
    s = html.unescape(s)
    return s.strip()

orig = {
  'para1': 'Over the past ten years, I have been deeply involved in resource management for construction projects. This journey inevitably led me to study the history of the technologies that have shaped the industry\u2014from the earliest attempts at design automation to modern ERP platforms (for those interested in this context, simply search for \u201cHistory of BIM\u201d). Without understanding where we came from, it is impossible to see where we are going.',
  'para2': 'Over the years, dozens of articles have come off my desk, read by millions of professionals around the world. At the same time, I\u2019ve consulted with major construction and consulting firms, developers, and software vendors themselves on data management in projects\u2014helping them navigate processes where data is not a byproduct but the foundation for decision-making. This work gave me a rare opportunity to see the industry from both sides: through the eyes of those who create the tools and through the eyes of those who use them in real projects every day. Many of these observations and reflections are collected in my book Data-Driven Construction, which is now available in 16 languages\u2014datadrivenconstruction.io/books.',
  'para3': 'My research journey has also taken me into areas that few take seriously: reverse-engineering closed formats and systematizing descriptions of construction work using a resource model. These efforts have resulted in open-source tools\u2014DDC CAD/BIM data converters (Revit, IFC, DWG, DGN \u2192 structured data), available on GitHub, and the multilingual CWICR database of construction works and resources\u2014over 55,000 items in 11 languages, published as OpenConstructionEstimate-DDC-CWICR. All of this was a necessary step toward the idea I\u2019ve been pursuing for the past decade\u2014creating an open-source ERP for the construction industry. Many who asked me what tools I was developing inevitably heard my ideas about creating an open-source modular ERP system.',
  'para4': 'And only this year did the emergence of artificial intelligence tools make it possible to consolidate the vast body of knowledge, developments, and solutions accumulated over a decade into a single platform. Today, I am presenting it to the community\u2014in the hope that it will help companies and their clients in the construction industry transition to managing construction projects at the process level. This shift, I believe, is precisely what can finally unlock the potential for productivity and data quality in an industry that has been held back for too long by fragmented solutions and disparate approaches.',
  'pull':  'Progress is born from dialogue\u2014from the clash of perspectives and openness to new approaches. I would be grateful if you would be willing to participate in this conversation on the inevitable Uberization of the construction industry and the transparency of cost and time estimation processes for construction projects.',
}

def norm(s):
    s = s.replace('\u2014', '--').replace('\u2013', '--').replace('\u2192', '->')
    s = s.replace('\u2018', "'").replace('\u2019', "'")
    s = s.replace('\u201c', '"').replace('\u201d', '"')
    s = re.sub(r'\s+', ' ', s)
    return s.strip()

for k, expected in orig.items():
    got = clean(v.get(k, ''))
    en = norm(expected); gn = norm(got)
    if gn == en:
        print(f'{k}: OK len={len(gn)}')
    else:
        print(f'{k}: MISMATCH (got_len={len(gn)} exp_len={len(en)})')
        # find first diff
        for i in range(min(len(gn), len(en))):
            if gn[i] != en[i]:
                print(f'   GOT: ...{gn[max(0,i-40):i+50]!r}')
                print(f'   EXP: ...{en[max(0,i-40):i+50]!r}')
                break
        else:
            print(f'   tail GOT: {gn[len(en):][:120]!r}')
            print(f'   tail EXP: {en[len(gn):][:120]!r}')
