"""‌⁠‍Replace the bulky DATA FLOW block on index.html with a tighter,
more visually-rich version that includes a Photo / image input and
proper mini-illustrations for every input/output node.
"""

from pathlib import Path

INDEX = Path(r"c:\Users\Artem Boiko\Desktop\CodeProjects\ERP_26030500\website-marketing\pro\breeze\index.html")
START_MARK = "  <!-- SECTION 9.5 — DATA FLOW (project file → priced BOQ → tender pack) -->\n"
END_MARK = "  <!-- SECTION 10 — COMMUNITY                                            -->\n"

NEW_BLOCK = """‌⁠‍  <!-- SECTION 9.5 — DATA FLOW (project file → priced BOQ → tender pack) -->
  <!-- ================================================================ -->
  <style>
    .df-section { padding: 64px 0 48px; }
    .df-section .section-head { margin-bottom: 18px; }
    .df-section .section-title { font-size: clamp(28px, 3.2vw, 38px) !important; }
    .df-card {
      margin: 22px 0 0;
      padding: 26px 28px 24px;
      border-radius: 18px;
      background: var(--bg-1);
      border: 1px solid var(--line-1);
    }

    /* compact 3-column flow board */
    .df-board {
      display: grid; gap: 12px;
      grid-template-columns: minmax(180px, 1fr) minmax(220px, 1.2fr) minmax(180px, 1fr);
      align-items: stretch;
    }
    @media (max-width: 880px) { .df-board { grid-template-columns: 1fr; } }

    .df-col-eyebrow {
      font-family: 'JetBrains Mono', ui-monospace, monospace;
      font-size: 10.5px; font-weight: 600; letter-spacing: 0.08em;
      text-transform: uppercase; color: var(--ink-3);
      margin: 0 0 8px;
    }

    /* node — input/output pill with a mini-illustration left */
    .df-node {
      display: grid; grid-template-columns: 38px 1fr; gap: 10px;
      align-items: center;
      padding: 9px 11px;
      border-radius: 10px;
      background: var(--bg-2, #ffffff);
      border: 1px solid var(--line-1);
      margin-bottom: 6px;
    }
    .df-node-out { border-color: color-mix(in oklab, var(--accent-3) 22%, var(--line-1)); }
    .df-node-icon {
      width: 38px; height: 30px;
      border-radius: 7px;
      background: color-mix(in oklab, var(--accent) 8%, var(--bg-1));
      display: flex; align-items: center; justify-content: center;
    }
    .df-node-out .df-node-icon { background: color-mix(in oklab, var(--accent-3) 8%, var(--bg-1)); }
    .df-node-icon svg { width: 26px; height: 22px; display: block; }
    .df-node-icon svg .df-st { fill: none; stroke: var(--accent); stroke-width: 1.4; stroke-linecap: round; stroke-linejoin: round; }
    .df-node-icon svg .df-fl { fill: color-mix(in oklab, var(--accent) 18%, transparent); stroke: none; }
    .df-node-out .df-node-icon svg .df-st { stroke: var(--accent-3); }
    .df-node-out .df-node-icon svg .df-fl { fill: color-mix(in oklab, var(--accent-3) 18%, transparent); }
    .df-node-text {
      display: flex; flex-direction: column; line-height: 1.15;
    }
    .df-node-name {
      font-family: 'Inter Tight', sans-serif; font-size: 13px;
      font-weight: 600; color: var(--ink-0); letter-spacing: -0.005em;
    }
    .df-node-tag {
      font-family: 'JetBrains Mono', ui-monospace, monospace;
      font-size: 10px; color: var(--ink-3); letter-spacing: 0.02em;
      margin-top: 2px;
    }

    /* central pivot — DDC + Canonical + Classify/Price/Validate stacked */
    .df-pivot {
      padding: 14px 16px;
      border-radius: 12px;
      background: color-mix(in oklab, var(--accent) 7%, var(--bg-1));
      border: 1.4px solid var(--accent);
      display: flex; flex-direction: column; gap: 10px;
      position: relative;
    }
    .df-pivot-row {
      display: grid; grid-template-columns: 28px 1fr; gap: 10px; align-items: start;
      padding: 8px 0;
      border-bottom: 1px dashed color-mix(in oklab, var(--accent) 22%, var(--line-1));
    }
    .df-pivot-row:last-child { border-bottom: 0; }
    .df-pivot-num {
      width: 22px; height: 22px; border-radius: 50%;
      background: var(--accent); color: #fff;
      font-family: 'JetBrains Mono', ui-monospace, monospace;
      font-size: 10.5px; font-weight: 700;
      display: inline-flex; align-items: center; justify-content: center;
      margin-top: 2px;
    }
    .df-pivot-name {
      font-family: 'Inter Tight', sans-serif; font-size: 13px; font-weight: 700;
      color: var(--ink-0); letter-spacing: -0.005em; margin: 0 0 2px;
    }
    .df-pivot-tag {
      font-family: 'JetBrains Mono', ui-monospace, monospace;
      font-size: 10.5px; color: var(--ink-2); letter-spacing: 0.02em;
      line-height: 1.4;
    }
    .df-pivot-tag b { color: var(--ink-0); font-weight: 600; }

    /* worked example — compact horizontal strip */
    .df-walk {
      margin-top: 18px;
      padding: 18px 22px;
      border-radius: 14px;
      background: color-mix(in oklab, var(--accent-2) 5%, var(--bg-1));
      border: 1px solid color-mix(in oklab, var(--accent) 18%, var(--line-1));
    }
    .df-walk-eyebrow {
      font-family: 'JetBrains Mono', ui-monospace, monospace;
      font-size: 10.5px; font-weight: 600; letter-spacing: 0.1em;
      text-transform: uppercase; color: var(--accent); margin: 0 0 8px;
    }
    .df-walk h4 {
      font-family: 'Inter Tight', sans-serif; font-size: 16px; font-weight: 600;
      color: var(--ink-0); margin: 0 0 14px; letter-spacing: -0.01em;
    }
    .df-walk h4 em {
      font-family: 'Fraunces', serif; font-style: italic; font-weight: 500;
      background: linear-gradient(110deg, var(--accent-2), var(--accent), var(--accent-3));
      -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
    }
    .df-walk-strip {
      display: grid; gap: 10px;
      grid-template-columns: repeat(6, 1fr);
    }
    @media (max-width: 1100px) { .df-walk-strip { grid-template-columns: repeat(3, 1fr); } }
    @media (max-width: 600px)  { .df-walk-strip { grid-template-columns: repeat(2, 1fr); } }
    .df-walk-step {
      padding: 10px 12px;
      border-radius: 10px;
      background: var(--bg-1);
      border: 1px solid var(--line-1);
      position: relative;
    }
    .df-walk-step-head {
      font-family: 'JetBrains Mono', ui-monospace, monospace;
      font-size: 9.5px; font-weight: 600; letter-spacing: 0.08em;
      text-transform: uppercase; color: var(--accent); margin: 0 0 4px;
    }
    .df-walk-step-name {
      font-family: 'Inter Tight', sans-serif; font-size: 12px; font-weight: 600;
      color: var(--ink-0); letter-spacing: -0.005em; margin: 0 0 4px; line-height: 1.25;
    }
    .df-walk-step-val {
      font-family: 'JetBrains Mono', ui-monospace, monospace;
      font-size: 10.5px; color: var(--ink-2); line-height: 1.4;
    }
    .df-walk-step-val b { color: var(--ink-0); font-weight: 600; }

    /* output stats — slim chip strip */
    .df-stats {
      margin-top: 16px;
      display: flex; flex-wrap: wrap; gap: 10px;
    }
    .df-stat {
      flex: 1 1 160px;
      padding: 12px 16px;
      border-radius: 12px;
      background: var(--bg-1);
      border: 1px solid var(--line-1);
      display: flex; flex-direction: column; gap: 2px;
    }
    .df-stat-num {
      font-family: 'Inter Tight', sans-serif; font-size: 22px; font-weight: 700;
      letter-spacing: -0.02em; color: var(--ink-0); line-height: 1;
    }
    .df-stat-num em {
      font-family: 'Fraunces', serif; font-style: italic; font-weight: 400;
      background: linear-gradient(110deg, var(--accent-2), var(--accent), var(--accent-3));
      -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
    }
    .df-stat-label {
      font-family: 'JetBrains Mono', ui-monospace, monospace;
      font-size: 10.5px; color: var(--ink-3); letter-spacing: 0.03em;
      margin-top: 2px;
    }
  </style>

  <section class="section df-section reveal" id="dataflow" aria-label="Data flow — concept to priced BOQ">
    <div class="section-head reveal">
      <div class="section-eyebrow">
        <span class="bar"></span>
        <span>Data flow · concept → priced BOQ → tender pack</span>
      </div>
      <h2 class="section-title">
        How a project file <em>becomes</em> a fully priced tender pack.
      </h2>
      <p class="section-lede">
        One pipeline, three stages, six file types in. <b>Photos and PDFs</b> on one side,
        a tender‑ready BOQ on the other — every element classified, measured, priced and traceable.
      </p>
    </div>

    <div class="df-card reveal-up">

      <!-- 3-column compact flow board -->
      <div class="df-board">

        <!-- LEFT: inputs -->
        <div>
          <p class="df-col-eyebrow">▸ Input · project files</p>

          <!-- RVT — isometric building -->
          <div class="df-node">
            <div class="df-node-icon"><svg viewBox="0 0 26 22">
              <path class="df-fl" d="M 4 12 L 13 7 L 22 12 L 13 17 Z"/>
              <path class="df-st" d="M 4 12 L 13 7 L 22 12 L 13 17 Z M 4 12 L 4 17 L 13 22 L 13 17 M 22 12 L 22 17 L 13 22"/>
            </svg></div>
            <div class="df-node-text"><span class="df-node-name">RVT · Revit</span><span class="df-node-tag">native model</span></div>
          </div>

          <!-- IFC — building with element labels -->
          <div class="df-node">
            <div class="df-node-icon"><svg viewBox="0 0 26 22">
              <path class="df-fl" d="M 6 6 L 20 6 L 20 18 L 6 18 Z"/>
              <path class="df-st" d="M 6 6 L 20 6 L 20 18 L 6 18 Z M 13 6 L 13 18 M 6 12 L 20 12"/>
              <circle class="df-st" cx="9" cy="9" r="1.2"/><circle class="df-st" cx="17" cy="15" r="1.2"/>
            </svg></div>
            <div class="df-node-text"><span class="df-node-name">IFC 4 · 4.3</span><span class="df-node-tag">openBIM</span></div>
          </div>

          <!-- DWG/DGN — 2D plan with dim arrow -->
          <div class="df-node">
            <div class="df-node-icon"><svg viewBox="0 0 26 22">
              <path class="df-st" d="M 4 17 L 22 17 M 4 17 L 4 7 L 14 7 L 14 12 L 22 12"/>
              <path class="df-st" d="M 4 5 L 14 5 M 4 4 L 4 6 M 14 4 L 14 6"/>
            </svg></div>
            <div class="df-node-text"><span class="df-node-name">DWG · DGN</span><span class="df-node-tag">2D + 3D drawings</span></div>
          </div>

          <!-- PDF — page with hatched takeoff zone -->
          <div class="df-node">
            <div class="df-node-icon"><svg viewBox="0 0 26 22">
              <path class="df-st" d="M 6 3 L 17 3 L 21 7 L 21 19 L 6 19 Z M 17 3 L 17 7 L 21 7"/>
              <path class="df-st" d="M 9 11 L 18 11 L 18 16 L 9 16 Z M 9 11 L 18 16 M 9 16 L 18 11"/>
            </svg></div>
            <div class="df-node-text"><span class="df-node-name">PDF takeoff</span><span class="df-node-tag">vector + scanned</span></div>
          </div>

          <!-- PHOTO — camera viewfinder around a building -->
          <div class="df-node">
            <div class="df-node-icon"><svg viewBox="0 0 26 22">
              <path class="df-st" d="M 4 7 L 7 7 L 9 5 L 17 5 L 19 7 L 22 7 L 22 18 L 4 18 Z"/>
              <circle class="df-fl" cx="13" cy="12" r="3.5"/>
              <circle class="df-st" cx="13" cy="12" r="3.5"/>
            </svg></div>
            <div class="df-node-text"><span class="df-node-name">Photo · image</span><span class="df-node-tag">site photo · drone shot</span></div>
          </div>

          <!-- GAEB — tender table -->
          <div class="df-node">
            <div class="df-node-icon"><svg viewBox="0 0 26 22">
              <path class="df-st" d="M 4 4 L 22 4 L 22 18 L 4 18 Z M 4 9 L 22 9 M 4 14 L 22 14 M 11 4 L 11 18"/>
            </svg></div>
            <div class="df-node-text"><span class="df-node-name">GAEB X83 · X84</span><span class="df-node-tag">tender exchange</span></div>
          </div>
        </div>

        <!-- MIDDLE: pivot — 3 stacked stages -->
        <div>
          <p class="df-col-eyebrow">▸ Process · DDC pipeline</p>
          <div class="df-pivot">
            <div class="df-pivot-row">
              <span class="df-pivot-num">1</span>
              <div>
                <p class="df-pivot-name">Normalise</p>
                <p class="df-pivot-tag">DDC <b>cad2data</b> reads every file type into a single <b>canonical model</b> (JSON + Parquet) — one source of truth for elements, geometry, properties, quantities.</p>
              </div>
            </div>
            <div class="df-pivot-row">
              <span class="df-pivot-num">2</span>
              <div>
                <p class="df-pivot-name">Classify · price</p>
                <p class="df-pivot-tag">Auto-mapping into <b>DIN 276 · NRM 1/2 · MasterFormat · GAEB · DPGF</b>, then vector-matched against the <b>CWICR ~55K</b> priced catalogue with confidence scores.</p>
              </div>
            </div>
            <div class="df-pivot-row">
              <span class="df-pivot-num">3</span>
              <div>
                <p class="df-pivot-name">Validate</p>
                <p class="df-pivot-tag"><b>46 rules</b> across 5 packs — structure, completeness, consistency, compliance — surface as a traffic-light report linked back to every element.</p>
              </div>
            </div>
          </div>
        </div>

        <!-- RIGHT: outputs -->
        <div>
          <p class="df-col-eyebrow">▸ Output · tender pack</p>

          <div class="df-node df-node-out">
            <div class="df-node-icon"><svg viewBox="0 0 26 22">
              <path class="df-st" d="M 4 4 L 22 4 L 22 18 L 4 18 Z M 4 9 L 22 9 M 4 14 L 22 14"/>
              <path class="df-st" d="M 8 11 L 14 11 M 8 16 L 14 16"/>
            </svg></div>
            <div class="df-node-text"><span class="df-node-name">GAEB X83</span><span class="df-node-tag">round-trip tender</span></div>
          </div>

          <div class="df-node df-node-out">
            <div class="df-node-icon"><svg viewBox="0 0 26 22">
              <path class="df-st" d="M 3 4 L 23 4 L 23 18 L 3 18 Z M 3 9 L 23 9 M 3 13 L 23 13 M 9 4 L 9 18 M 17 4 L 17 18"/>
            </svg></div>
            <div class="df-node-text"><span class="df-node-name">XLSX · CSV</span><span class="df-node-tag">priced positions</span></div>
          </div>

          <div class="df-node df-node-out">
            <div class="df-node-icon"><svg viewBox="0 0 26 22">
              <path class="df-st" d="M 6 3 L 17 3 L 21 7 L 21 19 L 6 19 Z M 17 3 L 17 7 L 21 7"/>
              <path class="df-st" d="M 9 14 L 11 11 L 13 13 L 17 9"/>
              <circle class="df-fl" cx="9" cy="14" r="0.9"/><circle class="df-fl" cx="11" cy="11" r="0.9"/><circle class="df-fl" cx="13" cy="13" r="0.9"/><circle class="df-fl" cx="17" cy="9" r="0.9"/>
            </svg></div>
            <div class="df-node-text"><span class="df-node-name">PDF report</span><span class="df-node-tag">cost summary</span></div>
          </div>

          <div class="df-node df-node-out">
            <div class="df-node-icon"><svg viewBox="0 0 26 22">
              <path class="df-st" d="M 4 5 L 22 5 L 22 16 L 14 16 L 9 20 L 9 16 L 4 16 Z"/>
              <circle class="df-fl" cx="10" cy="11" r="1.1"/><circle class="df-fl" cx="13" cy="11" r="1.1"/><circle class="df-fl" cx="16" cy="11" r="1.1"/>
            </svg></div>
            <div class="df-node-text"><span class="df-node-name">BCF issues</span><span class="df-node-tag">round-trip + viewpoints</span></div>
          </div>

          <div class="df-node df-node-out">
            <div class="df-node-icon"><svg viewBox="0 0 26 22">
              <path class="df-st" d="M 5 7 L 8 11 L 5 15 M 21 7 L 18 11 L 21 15 M 14 6 L 11 16"/>
            </svg></div>
            <div class="df-node-text"><span class="df-node-name">REST · webhooks</span><span class="df-node-tag">to ERP / SAP / PM tools</span></div>
          </div>

          <div class="df-node df-node-out">
            <div class="df-node-icon"><svg viewBox="0 0 26 22">
              <path class="df-st" d="M 5 7 L 13 4 L 21 7 L 13 10 Z"/>
              <path class="df-st" d="M 5 11 L 13 14 L 21 11"/>
              <path class="df-st" d="M 5 15 L 13 18 L 21 15"/>
            </svg></div>
            <div class="df-node-text"><span class="df-node-name">JSON · Parquet</span><span class="df-node-tag">canonical export</span></div>
          </div>
        </div>
      </div>

      <!-- worked example — concrete wall journey, single horizontal strip -->
      <div class="df-walk">
        <p class="df-walk-eyebrow">▸ Worked example · one wall, end-to-end</p>
        <h4>What we extract from a single CAD element <em>before</em> it lands as a BOQ row.</h4>
        <div class="df-walk-strip">
          <div class="df-walk-step">
            <p class="df-walk-step-head">▸ Element</p>
            <p class="df-walk-step-name">Wall_Lvl01_E034</p>
            <p class="df-walk-step-val">stable across model revisions</p>
          </div>
          <div class="df-walk-step">
            <p class="df-walk-step-head">▸ Class</p>
            <p class="df-walk-step-name">DIN 276 · KG 330</p>
            <p class="df-walk-step-val">Außenwände · external wall</p>
          </div>
          <div class="df-walk-step">
            <p class="df-walk-step-head">▸ Geometry</p>
            <p class="df-walk-step-name">12.5 × 3.0 × 0.24 m</p>
            <p class="df-walk-step-val"><b>9.0 m³</b> · 37.5 m²</p>
          </div>
          <div class="df-walk-step">
            <p class="df-walk-step-head">▸ Properties</p>
            <p class="df-walk-step-name">Concrete C30/37</p>
            <p class="df-walk-step-val">F90 fire rating</p>
          </div>
          <div class="df-walk-step">
            <p class="df-walk-step-head">▸ Cost</p>
            <p class="df-walk-step-name">CWICR · DACH</p>
            <p class="df-walk-step-val"><b>€ 245 / m³</b> matched</p>
          </div>
          <div class="df-walk-step">
            <p class="df-walk-step-head">▸ BOQ line</p>
            <p class="df-walk-step-name">9.0 m³ × € 245</p>
            <p class="df-walk-step-val"><b>€ 2,205</b> on the tender</p>
          </div>
        </div>
      </div>

      <!-- output stats chips -->
      <div class="df-stats">
        <div class="df-stat">
          <span class="df-stat-num"><em>~55K</em></span>
          <span class="df-stat-label">CWICR priced positions</span>
        </div>
        <div class="df-stat">
          <span class="df-stat-num"><em>5</em></span>
          <span class="df-stat-label">rule packs · DIN/NRM/MFM/GAEB/DPGF</span>
        </div>
        <div class="df-stat">
          <span class="df-stat-num"><em>6</em></span>
          <span class="df-stat-label">file types in · 5 + REST out</span>
        </div>
        <div class="df-stat">
          <span class="df-stat-num"><em>100%</em></span>
          <span class="df-stat-label">trace · element ↔ rule ↔ price</span>
        </div>
      </div>

    </div>
  </section>

"""

text = INDEX.read_text(encoding="utf-8")
i = text.find(START_MARK)
j = text.find(END_MARK, i)
if i == -1 or j == -1:
    raise SystemExit("markers not found")

# Replace from one line above START_MARK (the ===== separator above it)
# up to one line above END_MARK (the ===== separator above SECTION 10).
# We want to keep one of the leading '======' separators on each side.
# Simplest: find the '<!-- ===' line directly above each marker and
# replace from that.
sep = "  <!-- ================================================================ -->\n"
# back up one separator line above START_MARK
start_idx = text.rfind(sep, 0, i)
# the END_MARK is preceded by a separator line and an empty line
# find the separator above END_MARK
end_sep_idx = text.rfind(sep, 0, j)
# we want to delete from start_idx up to end_sep_idx (exclusive)
# so that the separator above SECTION 10 is preserved.
new_text = text[:start_idx] + NEW_BLOCK + text[end_sep_idx:]
INDEX.write_text(new_text, encoding="utf-8")
print(f"OK — replaced {end_sep_idx - start_idx} bytes with {len(NEW_BLOCK)} bytes")
