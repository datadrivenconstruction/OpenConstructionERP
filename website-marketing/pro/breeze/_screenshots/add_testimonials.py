"""Add two real testimonials about DataDrivenConstruction (Chris Andrew at
AECOM and Prof. Dr.-Ing. Michael Buehler at GemeinWerk Ventures) into the
DDC section of the breeze index.html.

The avatars are pulled verbatim from the archived buildcalculator.io
testimonials block as base64 data URIs so the photos render without any
extra network requests or asset deploy.
"""
from pathlib import Path
import re

INDEX = Path(__file__).resolve().parents[1] / "index.html"
ARCHIVE = Path(r"C:\Users\Artem Boiko\Desktop\CodeProjects\NewVPS_buildcost\testimonials_archive.html")

src = INDEX.read_text(encoding="utf-8")
arc = ARCHIVE.read_text(encoding="utf-8")

# Pull each avatar's base64 data URI from the archive. The two <img> tags
# inside .tst-avatar carry alt="Chris Andrew" and alt="Michael Bühler".
def grab_avatar(alt_substr: str) -> str:
    m = re.search(
        r'<img src="(data:image/jpeg;base64,[^"]+)"\s+alt="' + alt_substr,
        arc,
    )
    if not m:
        raise SystemExit(f"could not find avatar for {alt_substr}")
    return m.group(1)


chris = grab_avatar("Chris Andrew")
michael = grab_avatar("Michael")

# ---------- 1. CSS ----------
# Insert after the .ddc-marquee CSS rules and before .ddc-logo.
css = """
    /* Testimonials block — two glass cards matching the ecosystem card
       language: hairline border, soft glass surface, accent on hover. The
       big quote glyph is a decorative pseudo-element on each card. */
    .ddc-testimonials {
      max-width: 1440px;
      margin: 0 auto clamp(40px, 4vw, 56px);
      padding: 0 clamp(16px, 3vw, 40px);
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }
    @media (max-width: 720px) {
      .ddc-testimonials { grid-template-columns: 1fr; }
    }
    .ddc-tst {
      position: relative;
      padding: 26px 28px 22px;
      border-radius: 14px;
      background: color-mix(in oklab, #ffffff 62%, transparent);
      backdrop-filter: blur(8px);
      -webkit-backdrop-filter: blur(8px);
      border: 1px solid var(--line-1);
      box-shadow: 0 4px 12px -8px rgba(15,23,42,0.10);
      transition: border-color 0.25s ease, transform 0.25s ease, box-shadow 0.25s ease, background 0.25s ease;
      overflow: hidden;
    }
    .ddc-tst:hover {
      border-color: color-mix(in oklab, var(--accent) 28%, var(--line-1));
      background: #ffffff;
      transform: translateY(-2px);
      box-shadow: 0 14px 28px -16px color-mix(in oklab, var(--accent) 30%, rgba(15,23,42,0.18));
    }
    .ddc-tst::before {
      content: '\\201C';
      position: absolute;
      top: 6px;
      right: 22px;
      font-family: Georgia, serif;
      font-size: 64px;
      font-weight: 800;
      color: var(--accent);
      opacity: 0.10;
      line-height: 1;
      pointer-events: none;
    }
    .ddc-tst-quote {
      font-family: 'Inter Tight', 'Inter', sans-serif;
      font-size: 13.5px;
      line-height: 1.65;
      color: var(--ink-1);
      font-style: italic;
      margin: 0 0 18px;
      position: relative;
      z-index: 1;
    }
    .ddc-tst-author {
      display: flex;
      align-items: center;
      gap: 12px;
      padding-top: 14px;
      border-top: 1px solid var(--line-1);
    }
    .ddc-tst-avatar {
      width: 42px;
      height: 42px;
      border-radius: 50%;
      flex-shrink: 0;
      overflow: hidden;
      background: linear-gradient(135deg, var(--accent), var(--accent-3));
      box-shadow: 0 2px 8px -2px color-mix(in oklab, var(--accent) 35%, rgba(15,23,42,0.18));
    }
    .ddc-tst-avatar img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
    .ddc-tst-meta { min-width: 0; }
    .ddc-tst-name {
      font-family: 'Inter Tight', sans-serif;
      font-size: 13px;
      font-weight: 700;
      color: var(--ink-0);
      letter-spacing: -0.005em;
      line-height: 1.2;
    }
    .ddc-tst-role {
      font-size: 11.5px;
      color: var(--ink-3);
      margin-top: 2px;
      line-height: 1.3;
    }
    [data-theme="dark"] .ddc-tst {
      background: color-mix(in oklab, #ffffff 5%, transparent);
      border-color: rgba(255,255,255,0.08);
    }
"""

CSS_ANCHOR = "    /* Brand chip — compact pill with favicon"
src = src.replace(CSS_ANCHOR, css + CSS_ANCHOR, 1)

# ---------- 2. HTML ----------
# Insert between </div> closing ddc-trusted and the next "Sister products" comment.
html_block = (
    '\n    <!-- Two unprompted testimonials about DataDrivenConstruction\'s\n'
    '         tooling and mission. Quotes preserved verbatim from the\n'
    '         original buildcalculator.io page. -->\n'
    '    <div class="ddc-testimonials reveal">\n'
    '      <article class="ddc-tst">\n'
    '        <p class="ddc-tst-quote">'
    'BuildCalculator (DataDrivenConstruction) converters crack open closed '
    'formats and give you structured data you can actually use &mdash; in '
    'Power BI, in Excel, or even in an LLM prompt. It&rsquo;s not flashy, '
    'but it&rsquo;s insanely useful.'
    '</p>\n'
    '        <div class="ddc-tst-author">\n'
    f'          <div class="ddc-tst-avatar"><img src="{chris}" alt="Chris Andrew" loading="lazy" decoding="async"></div>\n'
    '          <div class="ddc-tst-meta">\n'
    '            <div class="ddc-tst-name">Chris Andrew</div>\n'
    '            <div class="ddc-tst-role">AECOM &middot; Digital Transformation Technical Lead &amp; Associate Director</div>\n'
    '          </div>\n'
    '        </div>\n'
    '      </article>\n'
    '      <article class="ddc-tst">\n'
    '        <p class="ddc-tst-quote">'
    'Be part of the movement with DataDrivenConstruction! Let&rsquo;s make '
    'true freedom in data formats a reality and catalyze a new era of '
    'productivity and innovation in construction.'
    '</p>\n'
    '        <div class="ddc-tst-author">\n'
    f'          <div class="ddc-tst-avatar"><img src="{michael}" alt="Michael B&uuml;hler" loading="lazy" decoding="async"></div>\n'
    '          <div class="ddc-tst-meta">\n'
    '            <div class="ddc-tst-name">Prof. Dr.-Ing. Michael B&uuml;hler</div>\n'
    '            <div class="ddc-tst-role">Co-Owner, GemeinWerk Ventures</div>\n'
    '          </div>\n'
    '        </div>\n'
    '      </article>\n'
    '    </div>\n'
)

HTML_ANCHOR = "    <!-- Sister products — featured on datadrivenconstruction.io"
if HTML_ANCHOR not in src:
    raise SystemExit("html anchor not found")
src = src.replace(HTML_ANCHOR, html_block + "\n" + HTML_ANCHOR, 1)

INDEX.write_text(src, encoding="utf-8")
print("inserted testimonials + css")
