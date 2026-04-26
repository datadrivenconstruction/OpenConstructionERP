"""Rebuild DDC marquee (2→3 rows) and append GitHub-tools grid."""
from pathlib import Path
import re

INDEX = Path(__file__).resolve().parents[1] / "index.html"
src = INDEX.read_text(encoding="utf-8")

# ---------- 1. Replace 2-row marquee with 3 rows ----------
# 24 brands split into 3 rows of 8. Row 1 + Row 3 forward, Row 2 reversed.
ROWS = [
    [
        ("aecom.com", "AECOM", "AECOM", "AECOM"),
        ("dreso.com", "Drees & Sommer", "Drees & Sommer", "DREES & SOMMER"),
        ("vinci-energies.com", "VINCI Energies", "VINCI Energies", "VINCI Energies"),
        ("lindner-group.com", "Lindner Group", "Lindner", "Lindner"),
        ("arteliagroup.com", "Artelia", "Artelia", "ARTELIA"),
        ("bechtle.com", "Bechtle", "bechtle", "bechtle"),
        ("merks.eu", "Merks", "merks", "merks"),
        ("rbs-wave.de", "RBS wave", "RBS wave", "RBS wave"),
    ],
    [
        ("shapemaker.io", "Shapemaker", "Shapemaker", "Shapemaker"),
        ("scholzethost.de", "Scholze-Thost", "Scholze-Thost", "SCHOLZE THOST"),
        ("vrame.com", "VRAME", "VRAME", "VRAME"),
        ("axia-energia.com", "AXIA ENERGIA", "AXIA Energia", "AXIA ENERGIA"),
        ("afry.com", "AFRY", "AFRY", "AFRY"),
        ("hofschroeer.com", "Hofschröer", "Hofschröer", "HOFSCHRÖER"),
        ("tdf.fr", "TDF", "TDF", "TDF"),
        ("rencons.com", "Renaissance Construction", "Renaissance Construction", "RENAISSANCE CONSTRUCTION"),
    ],
    [
        ("hyundai-autoever.com", "Hyundai AutoEver", "Hyundai AutoEver", "HYUNDAI AutoEver"),
        ("sintagma.com", "Sintagma", "Sintagma", "Sintagma"),
        ("trafikverket.se", "Trafikverket", "Trafikverket", "TRAFIKVERKET"),
        ("tmmgroup.com", "TMM Group", "TMM Group", "TMM GROUP"),
        ("daralriyadh.com", "Dar Al Riyadh", "Dar Al Riyadh", "DAR AL RIYADH"),
        ("pbs-ing.de", "pbs Ingenieure", "pbs Ingenieure", "pbs INGENIEURE"),
        ("zpp.de", "ZPP German Engineering", "ZPP", "ZPP"),
        ("scon-renewables.com", "scon", "scon", "scon"),
    ],
]

def render_chip(domain: str, alt: str, name: str, fallback: str) -> str:
    alt_e = alt.replace("&", "&amp;")
    name_e = name.replace("&", "&amp;")
    fb_e = fallback.replace("&", "&amp;")
    img = (
        f'<img src="https://t3.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL'
        f'&url=http://{domain}&size=128" alt="{alt_e}" loading="lazy" decoding="async" '
        f'onerror="this.outerHTML=\'<span class=&quot;ddc-logo-text&quot;>{fb_e}</span>\'">'
    )
    return f'<span class="ddc-logo">{img}<span class="ddc-logo-name">{name_e}</span></span>'


def render_track(brands, reverse: bool) -> str:
    chips = "\n            ".join(render_chip(*b) for b in brands)
    dup = "\n            ".join(render_chip(*b) for b in brands)
    extra = " ddc-reverse" if reverse else ""
    return (
        f'        <div class="ddc-marquee">\n'
        f'          <div class="ddc-marquee-track{extra}">\n'
        f'            {chips}\n'
        f'            <!-- Duplicate set — required for the seamless loop. -->\n'
        f'            {dup}\n'
        f'          </div>\n'
        f'        </div>'
    )


new_rows = (
    '      <div class="ddc-marquee-rows">\n'
    + render_track(ROWS[0], reverse=False) + "\n"
    + render_track(ROWS[1], reverse=True) + "\n"
    + render_track(ROWS[2], reverse=False) + "\n"
    + '      </div>'
)

# Match the existing <div class="ddc-marquee-rows">…</div> (multiline, lazy).
pattern = re.compile(
    r'<div class="ddc-marquee-rows">.*?</div>\s*</div>\s*</div>',
    re.DOTALL,
)
# The pattern above is too aggressive — anchor on the first marquee-rows opening
# and the matching closing pair plus the row-2 closing. Simpler approach:
# replace from `<div class="ddc-marquee-rows">` through the last `</div>` of
# row 2 (which is the third closing div in sequence). We'll do it via a
# string find/slice anchored on a unique closing comment.
START = '      <div class="ddc-marquee-rows">'
# After row-2 closes the rows wrapper closes immediately — locate it by
# finding the final `</div>` followed by the </div> closing ddc-trusted.
i = src.index(START)
# Walk forward to find `</div>\n      </div>\n    </div>` — the rows + trusted.
end_marker = "      </div>\n    </div>\n\n    <!-- Sister products"
j = src.index(end_marker, i)
# Replace [i .. j) with new_rows + "\n    " (close trusted etc.)
src = src[:i] + new_rows + "\n    " + src[j:]


# ---------- 2. Insert GitHub-repos grid into ecosystem block ----------
# Insert before the </div> that closes ddc-ecosystem (right after socials).
GH_REPOS = [
    (
        "cad2data-Revit-IFC-DWG-DGN",
        "https://github.com/datadrivenconstruction/cad2data-Revit-IFC-DWG-DGN",
        "Command-line conversion of RVT, IFC, DWG and DGN to flat data — the engine OCERP wraps for every CAD upload.",
        ["RVT", "IFC", "DWG", "DGN"],
    ),
    (
        "OpenConstructionEstimate / CWICR",
        "https://github.com/datadrivenconstruction/OpenConstructionEstimate-DDC-CWICR",
        "55K+ work items, 27K+ resources. The multilingual cost dataset shipped with OCERP, with vector search baked in.",
        ["55K items", "21 langs"],
    ),
    (
        "DDC Skills for AI Agents",
        "https://github.com/datadrivenconstruction/DDC_Skills_for_AI_Agents_in_Construction",
        "221 ready-made AI skills covering BIM analysis, takeoff, classification and cost estimation. Drop-in for Claude Code.",
        ["221 skills", "Claude Code"],
    ),
    (
        "Project Management n8n",
        "https://github.com/datadrivenconstruction/Project-management-n8n-with-task-management-and-photo-reports",
        "n8n workflow for site project management — Telegram bot, photo reports and Google Sheets storage out of the box.",
        ["n8n", "Telegram"],
    ),
    (
        "CAD/BIM → Code Pipeline",
        "https://github.com/datadrivenconstruction/CAD-BIM-to-Code-Automation-Pipeline-DDC-Workflow-with-LLM-ChatGPT",
        "Generate project-specific Python from RVT/IFC/DWG via an LLM — automated analysis and reporting, no manual scripting.",
        ["LLM", "Python"],
    ),
    (
        "OpenConstructionERP",
        "https://github.com/datadrivenconstruction/OpenConstructionERP",
        "This product, in source. AGPL-3.0 platform with BOQ, takeoff, validation, 18+ modules and 21 languages baked in.",
        ["AGPL-3.0", "this repo"],
    ),
]

GH_ICON_SVG = (
    '<svg viewBox="0 0 98 96" fill="currentColor" width="18" height="18" aria-hidden="true">'
    '<path fill-rule="evenodd" clip-rule="evenodd" d="M48.854 0C21.839 0 0 22 0 49.217c0 21.756 13.993 40.172 33.405 46.69 2.427.49 3.316-1.059 3.316-2.362 0-1.141-.08-5.052-.08-9.127-13.59 2.934-16.42-5.867-16.42-5.867-2.184-5.704-5.42-7.17-5.42-7.17-4.448-3.015.324-3.015.324-3.015 4.934.326 7.523 5.052 7.523 5.052 4.367 7.496 11.404 5.378 14.235 4.074.404-3.178 1.699-5.378 3.074-6.6-10.839-1.141-22.243-5.378-22.243-24.283 0-5.378 1.94-9.778 5.014-13.2-.485-1.222-2.184-6.275.486-13.038 0 0 4.125-1.304 13.426 5.052a46.97 46.97 0 0 1 12.214-1.63c4.125 0 8.33.571 12.213 1.63 9.302-6.356 13.427-5.052 13.427-5.052 2.67 6.763.97 11.816.485 13.038 3.155 3.422 5.014 7.822 5.014 13.2 0 18.905-11.404 23.06-22.324 24.283 1.78 1.548 3.316 4.481 3.316 9.126 0 6.6-.08 11.897-.08 13.526 0 1.304.89 2.853 3.316 2.364 19.412-6.52 33.405-24.935 33.405-46.691C97.707 22 75.788 0 48.854 0z"/>'
    '</svg>'
)
ARROW_SVG = (
    '<svg class="ddc-gh-arrow" width="12" height="12" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M7 7h10v10"/><path d="M7 17 17 7"/></svg>'
)


def render_gh_card(name, url, desc, chips):
    chip_html = "".join(f"<span>{c}</span>" for c in chips)
    return (
        f'        <a class="ddc-gh-card" href="{url}" target="_blank" rel="noopener">\n'
        f'          <div class="ddc-gh-icon">{GH_ICON_SVG}</div>\n'
        f'          <div class="ddc-gh-body">\n'
        f'            <div class="ddc-gh-name">{name}{ARROW_SVG}</div>\n'
        f'            <p class="ddc-gh-desc">{desc}</p>\n'
        f'            <div class="ddc-gh-meta">{chip_html}</div>\n'
        f'          </div>\n'
        f'        </a>'
    )


gh_block = (
    '\n      <div class="ddc-gh-head">\n'
    '        <div class="ddc-gh-title">open-source on github · datadrivenconstruction org</div>\n'
    '        <div class="ddc-gh-sub">Six public repositories the team maintains alongside OCERP.</div>\n'
    '      </div>\n'
    '      <div class="ddc-gh-grid">\n'
    + "\n".join(render_gh_card(*r) for r in GH_REPOS)
    + "\n      </div>\n"
)

# Insert just before the closing </div> of ddc-ecosystem.
# Anchor: socials block ends with `</div>\n    </div>` (one closes socials,
# one closes ecosystem). We append before that final ecosystem close.
# Find the unique `</div>\n    </div>\n  </section>` after the socials.
ecosystem_close = "      </div>\n    </div>\n\n    <!-- ====="
# That comment opens the next section ("PRICING").  Locate it after the
# ddc-ecosystem opener and walk back by one </div> pair.
eco_open = src.index('<div class="ddc-ecosystem reveal">')
# The ecosystem div closes right before `</section>`; socials div closes one
# line above. Match the pair so we can splice the GH grid between them.
m = re.search(r'(\n      </div>)(\n    </div>\n  </section>)', src[eco_open:])
if not m:
    raise SystemExit("could not locate ecosystem close anchor")
abs_socials_close = eco_open + m.start(1)  # right before final socials </div>
abs_eco_close = eco_open + m.start(2)      # right before    </div> closing ecosystem
# We want gh_block to land between socials </div> and ecosystem </div>.
# m.start(1) is the start of "\n      </div>" (socials close).
# We insert AFTER that closing div, BEFORE ecosystem close.
insert_at = eco_open + m.end(1)  # right after socials </div>
src = src[:insert_at] + gh_block + src[insert_at:]


INDEX.write_text(src, encoding="utf-8")
print("✓ rewritten marquee → 3 rows; appended ddc-gh-grid with 6 repos")
