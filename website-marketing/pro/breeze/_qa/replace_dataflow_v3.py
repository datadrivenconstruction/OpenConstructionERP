"""‌⁠‍Third pass on the homepage DATA FLOW section.

Goals from the user:
  1. Container width must match the rest of the page (centred, max 1280px)
  2. Bring back the animated SVG flow with curved traces and pulses
  3. Keep the photo / image input that v2 added
  4. Keep the per-element worked example + the slim output stats
"""

from pathlib import Path

INDEX = Path(r"c:\Users\Artem Boiko\Desktop\CodeProjects\ERP_26030500\website-marketing\pro\breeze\index.html")
START_MARK = "  <!-- SECTION 9.5 — DATA FLOW (project file → priced BOQ → tender pack) -->\n"
END_MARK = "  <!-- SECTION 10 — COMMUNITY                                            -->\n"
SEP = "  <!-- ================================================================ -->\n"

NEW_BLOCK = """‌⁠‍  <!-- SECTION 9.5 — DATA FLOW (project file → priced BOQ → tender pack) -->
  <!-- ================================================================ -->
  <style>
    .df-section { padding: 64px 0 48px; }
    .df-section .section-head { margin-bottom: 18px; }
    .df-wrap { max-width: 1280px; margin: 0 auto; padding: 0 clamp(0px, 2vw, 24px); }

    .df-card {
      margin: 28px auto 0;
      max-width: 1280px;
      padding: 28px 32px 26px;
      border-radius: 22px;
      background: var(--bg-1);
      border: 1px solid var(--line-1);
      position: relative; overflow: hidden;
    }

    /* ─── Animated SVG flow ─────────────────────────────────── */
    .df-flow { width: 100%; aspect-ratio: 12 / 5; min-height: 320px; }
    .df-flow svg { width: 100%; height: 100%; display: block; }
    .df-flow .df-eyebrow {
      font-family: 'JetBrains Mono', ui-monospace, monospace;
      font-size: 10.5px; font-weight: 600; letter-spacing: 0.08em;
      fill: var(--ink-3); text-transform: uppercase;
    }
    .df-flow .df-name {
      font-family: 'Inter Tight', sans-serif; font-size: 12.5px;
      font-weight: 600; fill: var(--ink-0); letter-spacing: -0.005em;
    }
    .df-flow .df-tag {
      font-family: 'JetBrains Mono', ui-monospace, monospace;
      font-size: 10px; fill: var(--ink-3); letter-spacing: 0.03em;
    }
    .df-flow .df-rect {
      fill: var(--bg-2, #ffffff); stroke: var(--line-2, rgba(15,23,42,0.16));
      stroke-width: 1.1;
    }
    .df-flow .df-rect-out {
      fill: color-mix(in oklab, var(--accent-3) 6%, var(--bg-2, #ffffff));
      stroke: color-mix(in oklab, var(--accent-3) 32%, var(--line-1));
      stroke-width: 1.2;
    }
    .df-flow .df-rect-pivot {
      fill: color-mix(in oklab, var(--accent) 8%, var(--bg-1));
      stroke: var(--accent); stroke-width: 1.6;
    }
    .df-flow .df-mini-st {
      fill: none; stroke: var(--accent); stroke-width: 1.3;
      stroke-linecap: round; stroke-linejoin: round;
    }
    .df-flow .df-mini-fl { fill: color-mix(in oklab, var(--accent) 18%, transparent); stroke: none; }
    .df-flow .df-mini-out-st { stroke: var(--accent-3); }
    .df-flow .df-mini-out-fl { fill: color-mix(in oklab, var(--accent-3) 18%, transparent); stroke: none; }

    .df-flow .df-trace {
      fill: none; stroke: rgba(15,23,42,0.13); stroke-width: 1.3;
    }
    .df-flow .df-pulse {
      fill: none; stroke-width: 2.6; stroke-linecap: round;
      stroke-dasharray: 8 280;
      animation: dfPulse 3.6s linear infinite;
      opacity: 0.95;
    }
    @keyframes dfPulse { 0% { stroke-dashoffset: 280; } 100% { stroke-dashoffset: -280; } }
    .df-flow .df-pulse-2 { animation-delay: 0.4s; }
    .df-flow .df-pulse-3 { animation-delay: 0.8s; }
    .df-flow .df-pulse-4 { animation-delay: 1.2s; }
    .df-flow .df-pulse-5 { animation-delay: 1.6s; }
    .df-flow .df-pulse-6 { animation-delay: 2.0s; }
    .df-flow .df-pulse-7 { animation-delay: 2.4s; }
    .df-flow .df-pulse-8 { animation-delay: 2.8s; }

    .df-legend {
      display: flex; flex-wrap: wrap; gap: 18px;
      margin-top: 14px; padding-top: 14px;
      border-top: 1px dashed var(--line-1);
      font-family: 'JetBrains Mono', ui-monospace, monospace;
      font-size: 11px; color: var(--ink-3); letter-spacing: 0.03em;
    }
    .df-legend b { color: var(--ink-1); font-weight: 600; }
    .df-legend-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; vertical-align: middle; }

    /* worked example — single horizontal strip */
    .df-walk {
      margin-top: 22px;
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
    .df-walk-strip { display: grid; gap: 10px; grid-template-columns: repeat(6, 1fr); }
    @media (max-width: 1100px) { .df-walk-strip { grid-template-columns: repeat(3, 1fr); } }
    @media (max-width: 600px)  { .df-walk-strip { grid-template-columns: repeat(2, 1fr); } }
    .df-walk-step {
      padding: 10px 12px; border-radius: 10px;
      background: var(--bg-1); border: 1px solid var(--line-1);
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

    /* stats chips */
    .df-stats { margin-top: 16px; display: flex; flex-wrap: wrap; gap: 10px; }
    .df-stat {
      flex: 1 1 160px; padding: 12px 16px;
      border-radius: 12px; background: var(--bg-1); border: 1px solid var(--line-1);
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
      font-size: 10.5px; color: var(--ink-3); letter-spacing: 0.03em; margin-top: 2px;
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

      <!-- ════ animated flow visualisation ════ -->
      <div class="df-flow">
        <svg viewBox="0 0 1200 500" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
          <defs>
            <linearGradient id="dfGradIn" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%"   stop-color="#0ea5e9" stop-opacity="0"/>
              <stop offset="50%"  stop-color="#0ea5e9" stop-opacity="0.95"/>
              <stop offset="100%" stop-color="#0284c7" stop-opacity="0"/>
            </linearGradient>
            <linearGradient id="dfGradMid" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%"   stop-color="#0284c7" stop-opacity="0"/>
              <stop offset="50%"  stop-color="#0284c7" stop-opacity="0.95"/>
              <stop offset="100%" stop-color="#2563eb" stop-opacity="0"/>
            </linearGradient>
            <linearGradient id="dfGradOut" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%"   stop-color="#2563eb" stop-opacity="0"/>
              <stop offset="50%"  stop-color="#2563eb" stop-opacity="0.95"/>
              <stop offset="100%" stop-color="#0ea5e9" stop-opacity="0"/>
            </linearGradient>
          </defs>

          <!-- ═════════ INPUT column (6 pills) ═════════ -->
          <text class="df-eyebrow" x="0" y="14">▸ INPUT · project files</text>
          <!-- 6 inputs evenly distributed top to bottom (y centres at 50, 120, 190, 260, 330, 400) -->
          <g>
            <!-- RVT — iso-cube -->
            <rect class="df-rect" x="0" y="32"  width="200" height="48" rx="10"/>
            <g transform="translate(14, 42)">
              <path class="df-mini-fl" d="M 4 14 L 14 8 L 24 14 L 14 20 Z"/>
              <path class="df-mini-st" d="M 4 14 L 14 8 L 24 14 L 14 20 Z M 4 14 L 4 22 L 14 28 L 14 20 M 24 14 L 24 22 L 14 28"/>
            </g>
            <text class="df-name" x="48" y="58">RVT · Revit</text>
            <text class="df-tag"  x="48" y="73">native model</text>

            <!-- IFC — building w/ ids -->
            <rect class="df-rect" x="0" y="100" width="200" height="48" rx="10"/>
            <g transform="translate(16, 110)">
              <path class="df-mini-fl" d="M 4 4 L 22 4 L 22 22 L 4 22 Z"/>
              <path class="df-mini-st" d="M 4 4 L 22 4 L 22 22 L 4 22 Z M 13 4 L 13 22 M 4 13 L 22 13"/>
              <circle class="df-mini-st" cx="8" cy="8" r="1.2"/><circle class="df-mini-st" cx="18" cy="18" r="1.2"/>
            </g>
            <text class="df-name" x="48" y="126">IFC 4 · 4.3</text>
            <text class="df-tag"  x="48" y="141">openBIM</text>

            <!-- DWG — 2D plan + dim -->
            <rect class="df-rect" x="0" y="168" width="200" height="48" rx="10"/>
            <g transform="translate(14, 178)">
              <path class="df-mini-st" d="M 2 24 L 28 24 M 2 24 L 2 8 L 16 8 L 16 16 L 28 16"/>
              <path class="df-mini-st" d="M 2 4 L 16 4 M 2 3 L 2 5 M 16 3 L 16 5"/>
            </g>
            <text class="df-name" x="48" y="194">DWG · DGN</text>
            <text class="df-tag"  x="48" y="209">2D + 3D drawings</text>

            <!-- PDF — page + hatched takeoff -->
            <rect class="df-rect" x="0" y="236" width="200" height="48" rx="10"/>
            <g transform="translate(16, 246)">
              <path class="df-mini-st" d="M 4 2 L 18 2 L 24 8 L 24 26 L 4 26 Z M 18 2 L 18 8 L 24 8"/>
              <path class="df-mini-st" d="M 8 14 L 20 14 L 20 22 L 8 22 Z M 8 14 L 20 22 M 8 22 L 20 14"/>
            </g>
            <text class="df-name" x="48" y="262">PDF takeoff</text>
            <text class="df-tag"  x="48" y="277">vector + scanned</text>

            <!-- PHOTO — camera viewfinder -->
            <rect class="df-rect" x="0" y="304" width="200" height="48" rx="10"/>
            <g transform="translate(14, 314)">
              <path class="df-mini-st" d="M 2 7 L 6 7 L 8 4 L 22 4 L 24 7 L 28 7 L 28 24 L 2 24 Z"/>
              <circle class="df-mini-fl" cx="15" cy="15" r="5"/>
              <circle class="df-mini-st" cx="15" cy="15" r="5"/>
            </g>
            <text class="df-name" x="48" y="330">Photo · image</text>
            <text class="df-tag"  x="48" y="345">site photo · drone shot</text>

            <!-- GAEB — tabular -->
            <rect class="df-rect" x="0" y="372" width="200" height="48" rx="10"/>
            <g transform="translate(16, 382)">
              <path class="df-mini-st" d="M 2 2 L 24 2 L 24 22 L 2 22 Z M 2 9 L 24 9 M 2 16 L 24 16 M 12 2 L 12 22"/>
            </g>
            <text class="df-name" x="48" y="398">GAEB X83 · X84</text>
            <text class="df-tag"  x="48" y="413">tender exchange</text>
          </g>

          <!-- ═════════ MIDDLE pivot (DDC + Canonical + Classify/Validate) ═════════ -->
          <text class="df-eyebrow" x="430" y="14">▸ NORMALISE · CLASSIFY · VALIDATE</text>
          <rect class="df-rect-pivot" x="430" y="32" width="320" height="388" rx="14"/>

          <!-- 3 stacked stages inside the pivot -->
          <g transform="translate(450, 60)">
            <!-- Stage 1: DDC + Canonical -->
            <circle r="11" cx="11" cy="11" fill="#0284c7"/>
            <text x="11" y="15" text-anchor="middle" font-family="JetBrains Mono, monospace" font-size="11" font-weight="700" fill="#fff">1</text>
            <text class="df-name" x="32" y="14" style="font-size:14px;">DDC cad2data → Canonical</text>
            <text class="df-tag"  x="32" y="30" style="font-size:10.5px;">elements · geometry · properties · quantities</text>
            <text class="df-tag"  x="32" y="44" style="font-size:10.5px;">single source of truth · JSON + Parquet</text>
          </g>

          <line x1="446" y1="158" x2="734" y2="158" stroke="rgba(2,132,199,0.25)" stroke-dasharray="3 3"/>

          <g transform="translate(450, 178)">
            <!-- Stage 2: Classify + Price -->
            <circle r="11" cx="11" cy="11" fill="#0284c7"/>
            <text x="11" y="15" text-anchor="middle" font-family="JetBrains Mono, monospace" font-size="11" font-weight="700" fill="#fff">2</text>
            <text class="df-name" x="32" y="14" style="font-size:14px;">Classify · price</text>
            <text class="df-tag"  x="32" y="30" style="font-size:10.5px;">DIN 276 · NRM 1/2 · MasterFormat</text>
            <text class="df-tag"  x="32" y="44" style="font-size:10.5px;">GAEB · DPGF · CWICR ~55K vector match</text>
          </g>

          <line x1="446" y1="276" x2="734" y2="276" stroke="rgba(2,132,199,0.25)" stroke-dasharray="3 3"/>

          <g transform="translate(450, 296)">
            <!-- Stage 3: Validate -->
            <circle r="11" cx="11" cy="11" fill="#0284c7"/>
            <text x="11" y="15" text-anchor="middle" font-family="JetBrains Mono, monospace" font-size="11" font-weight="700" fill="#fff">3</text>
            <text class="df-name" x="32" y="14" style="font-size:14px;">Validate</text>
            <text class="df-tag"  x="32" y="30" style="font-size:10.5px;">46 rules across 5 packs</text>
            <text class="df-tag"  x="32" y="44" style="font-size:10.5px;">structure · completeness · compliance</text>
            <text class="df-tag"  x="32" y="62" style="font-size:10.5px; fill: var(--accent);">→ traffic-light report linked to elements</text>
          </g>

          <!-- ═════════ OUTPUT column (6 pills) ═════════ -->
          <text class="df-eyebrow" x="1000" y="14">▸ OUTPUT · tender pack</text>
          <g>
            <!-- GAEB X83 -->
            <rect class="df-rect-out" x="1000" y="32"  width="200" height="48" rx="10"/>
            <g transform="translate(1014, 42)">
              <path class="df-mini-out-st df-mini-st" d="M 2 2 L 24 2 L 24 22 L 2 22 Z M 2 8 L 24 8 M 2 14 L 24 14 M 2 20 L 24 20 M 13 2 L 13 22"/>
            </g>
            <text class="df-name" x="1048" y="58">GAEB X83</text>
            <text class="df-tag"  x="1048" y="73">round-trip tender</text>

            <!-- XLSX/CSV -->
            <rect class="df-rect-out" x="1000" y="100" width="200" height="48" rx="10"/>
            <g transform="translate(1012, 110)">
              <path class="df-mini-out-st df-mini-st" d="M 2 4 L 28 4 L 28 22 L 2 22 Z M 2 11 L 28 11 M 2 17 L 28 17 M 11 4 L 11 22 M 20 4 L 20 22"/>
            </g>
            <text class="df-name" x="1048" y="126">XLSX · CSV</text>
            <text class="df-tag"  x="1048" y="141">priced positions</text>

            <!-- PDF report w/ chart -->
            <rect class="df-rect-out" x="1000" y="168" width="200" height="48" rx="10"/>
            <g transform="translate(1014, 178)">
              <path class="df-mini-out-st df-mini-st" d="M 4 2 L 18 2 L 24 8 L 24 26 L 4 26 Z M 18 2 L 18 8 L 24 8"/>
              <path class="df-mini-out-st df-mini-st" d="M 8 18 L 11 14 L 14 16 L 20 10"/>
              <circle class="df-mini-out-fl df-mini-fl" cx="8" cy="18" r="1.1"/>
              <circle class="df-mini-out-fl df-mini-fl" cx="11" cy="14" r="1.1"/>
              <circle class="df-mini-out-fl df-mini-fl" cx="14" cy="16" r="1.1"/>
              <circle class="df-mini-out-fl df-mini-fl" cx="20" cy="10" r="1.1"/>
            </g>
            <text class="df-name" x="1048" y="194">PDF report</text>
            <text class="df-tag"  x="1048" y="209">cost summary</text>

            <!-- BCF issues -->
            <rect class="df-rect-out" x="1000" y="236" width="200" height="48" rx="10"/>
            <g transform="translate(1014, 246)">
              <path class="df-mini-out-st df-mini-st" d="M 2 4 L 26 4 L 26 18 L 14 18 L 8 24 L 8 18 L 2 18 Z"/>
              <circle class="df-mini-out-fl df-mini-fl" cx="9" cy="11" r="1.2"/>
              <circle class="df-mini-out-fl df-mini-fl" cx="14" cy="11" r="1.2"/>
              <circle class="df-mini-out-fl df-mini-fl" cx="19" cy="11" r="1.2"/>
            </g>
            <text class="df-name" x="1048" y="262">BCF issues</text>
            <text class="df-tag"  x="1048" y="277">round-trip + viewpoints</text>

            <!-- REST · webhooks -->
            <rect class="df-rect-out" x="1000" y="304" width="200" height="48" rx="10"/>
            <g transform="translate(1012, 314)">
              <path class="df-mini-out-st df-mini-st" d="M 4 6 L 9 12 L 4 18 M 24 6 L 19 12 L 24 18 M 17 4 L 11 20"/>
            </g>
            <text class="df-name" x="1048" y="330">REST · webhooks</text>
            <text class="df-tag"  x="1048" y="345">to ERP / SAP / PM tools</text>

            <!-- JSON · Parquet canonical -->
            <rect class="df-rect-out" x="1000" y="372" width="200" height="48" rx="10"/>
            <g transform="translate(1014, 382)">
              <path class="df-mini-out-st df-mini-st" d="M 4 6 L 14 2 L 24 6 L 14 10 Z"/>
              <path class="df-mini-out-st df-mini-st" d="M 4 12 L 14 16 L 24 12"/>
              <path class="df-mini-out-st df-mini-st" d="M 4 18 L 14 22 L 24 18"/>
            </g>
            <text class="df-name" x="1048" y="398">JSON · Parquet</text>
            <text class="df-tag"  x="1048" y="413">canonical export</text>
          </g>

          <!-- ═════════ traces (input → pivot) ═════════ -->
          <g class="df-trace">
            <path d="M 200 56  C 300 56,  380 220, 430 156"/>
            <path d="M 200 124 C 300 124, 380 220, 430 200"/>
            <path d="M 200 192 C 300 192, 380 220, 430 226"/>
            <path d="M 200 260 C 300 260, 380 240, 430 254"/>
            <path d="M 200 328 C 300 328, 380 280, 430 290"/>
            <path d="M 200 396 C 300 396, 380 320, 430 326"/>
          </g>
          <!-- ═════════ traces (pivot → output) ═════════ -->
          <g class="df-trace">
            <path d="M 750 156 C 830 156, 920 56,  1000 56"/>
            <path d="M 750 188 C 830 188, 920 124, 1000 124"/>
            <path d="M 750 220 C 830 220, 920 192, 1000 192"/>
            <path d="M 750 260 C 830 260, 920 260, 1000 260"/>
            <path d="M 750 296 C 830 296, 920 328, 1000 328"/>
            <path d="M 750 326 C 830 326, 920 396, 1000 396"/>
          </g>

          <!-- ═════════ animated pulses ═════════ -->
          <path class="df-pulse"          d="M 200 56  C 300 56,  380 220, 430 156" stroke="url(#dfGradIn)"/>
          <path class="df-pulse df-pulse-2" d="M 200 192 C 300 192, 380 220, 430 226" stroke="url(#dfGradIn)"/>
          <path class="df-pulse df-pulse-3" d="M 200 328 C 300 328, 380 280, 430 290" stroke="url(#dfGradIn)"/>
          <path class="df-pulse df-pulse-4" d="M 200 396 C 300 396, 380 320, 430 326" stroke="url(#dfGradIn)"/>
          <path class="df-pulse df-pulse-5" d="M 750 188 C 830 188, 920 124, 1000 124" stroke="url(#dfGradOut)"/>
          <path class="df-pulse df-pulse-6" d="M 750 260 C 830 260, 920 260, 1000 260" stroke="url(#dfGradOut)"/>
          <path class="df-pulse df-pulse-7" d="M 750 296 C 830 296, 920 328, 1000 328" stroke="url(#dfGradOut)"/>
          <path class="df-pulse df-pulse-8" d="M 750 326 C 830 326, 920 396, 1000 396" stroke="url(#dfGradOut)"/>
        </svg>
      </div>

      <div class="df-legend">
        <span><span class="df-legend-dot" style="background:#0ea5e9"></span><b>read</b> in — RVT, IFC, DWG/DGN, PDF, photo, GAEB X83/X84</span>
        <span><span class="df-legend-dot" style="background:#0284c7"></span><b>canonical</b> — JSON + Parquet, single source of truth</span>
        <span><span class="df-legend-dot" style="background:#2563eb"></span><b>write</b> out — GAEB X83, XLSX/CSV, PDF, BCF, REST, JSON</span>
      </div>

      <!-- worked example — concrete wall journey -->
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

      <div class="df-stats">
        <div class="df-stat"><span class="df-stat-num"><em>~55K</em></span><span class="df-stat-label">CWICR priced positions</span></div>
        <div class="df-stat"><span class="df-stat-num"><em>5</em></span><span class="df-stat-label">rule packs · DIN/NRM/MFM/GAEB/DPGF</span></div>
        <div class="df-stat"><span class="df-stat-num"><em>6</em></span><span class="df-stat-label">file types in · 5 + REST out</span></div>
        <div class="df-stat"><span class="df-stat-num"><em>100%</em></span><span class="df-stat-label">trace · element ↔ rule ↔ price</span></div>
      </div>

    </div>
  </section>

"""

text = INDEX.read_text(encoding="utf-8")
i = text.find(START_MARK)
j = text.find(END_MARK, i)
if i == -1 or j == -1:
    raise SystemExit("markers not found")
start_idx = text.rfind(SEP, 0, i)
end_sep_idx = text.rfind(SEP, 0, j)
new_text = text[:start_idx] + NEW_BLOCK + text[end_sep_idx:]
INDEX.write_text(new_text, encoding="utf-8")
print(f"OK — replaced {end_sep_idx - start_idx} bytes with {len(NEW_BLOCK)} bytes")
