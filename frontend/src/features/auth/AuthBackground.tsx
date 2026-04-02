/**
 * Animated construction background for auth pages.
 *
 * LEFT: Large estimation table with animated cells (3D perspective).
 * RIGHT: Full dashboard grid with charts, tables, KPIs (matching 3D perspective).
 *
 * Both sides use the same visual language — thin blue lines, subtle opacity,
 * 3D tilt, and radial mask fade toward center.
 */

import { useEffect, useRef, useCallback } from 'react';

/* ── Config ──────────────────────────────────────────────────────────── */

const CELL_INTERVAL = 600;
const ACTIVATE_COUNT = 4;
const DEACTIVATE_COUNT = 3;
const SEED_PERCENT = 0.45;

const HEADERS = ['Pos.', 'Description', 'Unit', 'Qty', 'Rate', 'Total', 'CG'];
const RIGHT_COLS = new Set([3, 4, 5, 6]);

const TABLE_ROWS: { t: 's' | 'p'; v: string[] }[] = [
  { t: 's', v: ['300', 'Structure — Building Construction', '', '', '', '', ''] },
  { t: 'p', v: ['01.001', 'Reinforced concrete C30/37, slab', 'm\u00B3', '86.40', '\u20AC295.00', '\u20AC25,488', '330'] },
  { t: 'p', v: ['01.002', 'Formwork base slab, smooth', 'm\u00B2', '432.00', '\u20AC38.50', '\u20AC16,632', '330'] },
  { t: 'p', v: ['01.003', 'Reinforcement BSt 500S, mesh', 'kg', '10,368', '\u20AC2.18', '\u20AC22,602', '330'] },
  { t: 'p', v: ['01.004', 'Reinforced concrete C30/37, walls', 'm\u00B3', '156.00', '\u20AC285.00', '\u20AC44,460', '330'] },
  { t: 'p', v: ['01.005', 'Formwork walls, smooth finish', 'm\u00B2', '1,248', '\u20AC42.50', '\u20AC53,040', '330'] },
  { t: 's', v: ['', 'Subtotal CG 330', '', '', '', '\u20AC162,222', '330'] },
  { t: 's', v: ['340', 'Structure — Interior Walls', '', '', '', '', ''] },
  { t: 'p', v: ['02.001', 'Masonry KS 24cm, load-bearing', 'm\u00B2', '890.00', '\u20AC68.00', '\u20AC60,520', '340'] },
  { t: 'p', v: ['02.002', 'Masonry KS 11.5cm, partition', 'm\u00B2', '620.00', '\u20AC48.00', '\u20AC29,760', '340'] },
  { t: 's', v: ['', 'Subtotal CG 340', '', '', '', '\u20AC90,280', '340'] },
  { t: 's', v: ['400', 'Building Services — HVAC', '', '', '', '', ''] },
  { t: 'p', v: ['04.001', 'Heating pipes, copper DN15', 'm', '840.00', '\u20AC28.50', '\u20AC23,940', '420'] },
  { t: 'p', v: ['04.002', 'Cable NYM-J 3\u00D71.5', 'm', '2,800', '\u20AC4.80', '\u20AC13,440', '440'] },
];

const LEVELS = ['on', 'on-m', 'on-h'] as const;

/* ── Left: Animated Estimation Table ─────────────────────────────────── */

function AnimatedTable() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const cellsRef = useRef<HTMLDivElement[]>([]);

  const initTable = useCallback((node: HTMLDivElement | null) => {
    if (!node || containerRef.current === node) return;
    containerRef.current = node;
    cellsRef.current = [];

    HEADERS.forEach((h, i) => {
      const d = document.createElement('div');
      d.className = 'oce-cell oce-cell-header' + (RIGHT_COLS.has(i) ? ' oce-cell-right' : '');
      d.textContent = h;
      node.appendChild(d);
    });

    TABLE_ROWS.forEach((row) => {
      row.v.forEach((val, ci) => {
        const d = document.createElement('div');
        const isSection = row.t === 's';
        let cls = 'oce-cell';
        if (ci === 0) cls += ' oce-cell-pos';
        if (ci === 1) cls += ' oce-cell-desc';
        if (ci === 5) cls += ' oce-cell-total';
        if (RIGHT_COLS.has(ci)) cls += ' oce-cell-right';
        if (isSection) cls += ' oce-cell-section';
        d.className = cls;
        d.dataset.txt = val;
        node.appendChild(d);
        if (!isSection && ci > 0) cellsRef.current.push(d);
      });
    });

    node.querySelectorAll<HTMLDivElement>('.oce-cell-section').forEach((s) => {
      s.classList.add('on-m');
      s.textContent = s.dataset.txt ?? '';
    });
    node.querySelectorAll<HTMLDivElement>('.oce-cell-pos').forEach((p) => {
      p.classList.add('on');
      p.textContent = p.dataset.txt ?? '';
    });

    const cells = cellsRef.current;
    const shuffled = [...cells].sort(() => Math.random() - 0.5);
    for (let i = 0; i < Math.floor(cells.length * SEED_PERCENT); i++) {
      const c = shuffled[i]!;
      c.classList.add(LEVELS[Math.floor(Math.random() * 3)]!);
      c.textContent = c.dataset.txt ?? '';
    }
  }, []);

  useEffect(() => {
    const timer = setInterval(() => {
      const cells = cellsRef.current;
      if (cells.length === 0) return;
      for (let a = 0; a < ACTIVATE_COUNT; a++) {
        const cell = cells[Math.floor(Math.random() * cells.length)]!;
        cell.classList.remove('on', 'on-m', 'on-h');
        const idx = Array.from(cell.parentElement?.children ?? []).indexOf(cell);
        const col = idx % 7;
        const lvl = col === 5 ? 'on-h' : col >= 3 ? 'on-m' : LEVELS[Math.floor(Math.random() * 3)]!;
        cell.classList.add(lvl);
        cell.textContent = cell.dataset.txt ?? '';
      }
      for (let d = 0; d < DEACTIVATE_COUNT; d++) {
        const cell = cells[Math.floor(Math.random() * cells.length)]!;
        if (cell.classList.contains('on') || cell.classList.contains('on-m') || cell.classList.contains('on-h')) {
          cell.classList.remove('on', 'on-m', 'on-h');
          cell.textContent = '';
        }
      }
    }, CELL_INTERVAL);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="oce-bg-table-wrap" aria-hidden="true">
      <div ref={initTable} className="oce-table-grid" />
    </div>
  );
}

/* ── Right: Dashboard Grid (same visual treatment as table) ──────────── */

function DashboardGrid() {
  const c = 'var(--oce-bp-color)';

  return (
    <div className="oce-bg-dash-wrap" aria-hidden="true">
      <div className="oce-bg-dash-grid">
        {/* Row 1: Bar Chart (wide) */}
        <div className="oce-dash-cell oce-dash-wide">
          <svg viewBox="0 0 420 140" fill="none">
            <rect x="4" y="4" width="412" height="132" rx="6" fill="none" stroke={c} strokeWidth=".7" />
            <text x="16" y="22" fontSize="8" fill={c} opacity=".6" fontWeight="700" letterSpacing=".04em">COST PER TRADE (DIN 276)</text>
            {/* Bars */}
            <rect x="28"  y="100" width="30" height="28" rx="3" fill={c} opacity=".3" />
            <rect x="68"  y="72"  width="30" height="56" rx="3" fill={c} opacity=".4" />
            <rect x="108" y="44"  width="30" height="84" rx="3" fill={c} opacity=".55" />
            <rect x="148" y="80"  width="30" height="48" rx="3" fill={c} opacity=".35" />
            <rect x="188" y="36"  width="30" height="92" rx="3" fill={c} opacity=".6" />
            <rect x="228" y="60"  width="30" height="68" rx="3" fill={c} opacity=".4" />
            <rect x="268" y="88"  width="30" height="40" rx="3" fill={c} opacity=".25" />
            <rect x="308" y="52"  width="30" height="76" rx="3" fill={c} opacity=".45" />
            <rect x="348" y="68"  width="30" height="60" rx="3" fill={c} opacity=".35" />
            {/* X axis labels */}
            <text x="43"  y="137" textAnchor="middle" fontSize="7" fill={c} opacity=".4">KG300</text>
            <text x="83"  y="137" textAnchor="middle" fontSize="7" fill={c} opacity=".4">KG330</text>
            <text x="123" y="137" textAnchor="middle" fontSize="7" fill={c} opacity=".4">KG340</text>
            <text x="163" y="137" textAnchor="middle" fontSize="7" fill={c} opacity=".4">KG400</text>
            <text x="203" y="137" textAnchor="middle" fontSize="7" fill={c} opacity=".4">KG420</text>
            <text x="243" y="137" textAnchor="middle" fontSize="7" fill={c} opacity=".4">KG440</text>
            <text x="283" y="137" textAnchor="middle" fontSize="7" fill={c} opacity=".4">KG500</text>
            <text x="323" y="137" textAnchor="middle" fontSize="7" fill={c} opacity=".4">KG530</text>
            <text x="363" y="137" textAnchor="middle" fontSize="7" fill={c} opacity=".4">KG540</text>
          </svg>
        </div>

        {/* Row 2: Donut + KPI table */}
        <div className="oce-dash-cell">
          <svg viewBox="0 0 200 180" fill="none">
            <rect x="4" y="4" width="192" height="172" rx="6" fill="none" stroke={c} strokeWidth=".7" />
            <text x="100" y="22" textAnchor="middle" fontSize="8" fill={c} opacity=".6" fontWeight="700" letterSpacing=".04em">BOQ BREAKDOWN</text>
            <circle cx="100" cy="100" r="50" fill="none" stroke={c} strokeWidth="14" strokeDasharray="120 314" transform="rotate(-90 100 100)" opacity=".5" />
            <circle cx="100" cy="100" r="50" fill="none" stroke={c} strokeWidth="14" strokeDasharray="85 314" strokeDashoffset="-120" transform="rotate(-90 100 100)" opacity=".35" />
            <circle cx="100" cy="100" r="50" fill="none" stroke={c} strokeWidth="14" strokeDasharray="65 314" strokeDashoffset="-205" transform="rotate(-90 100 100)" opacity=".2" />
            <text x="100" y="98" textAnchor="middle" fontSize="18" fill={c} opacity=".5" fontWeight="700">\u20AC4.2M</text>
            <text x="100" y="112" textAnchor="middle" fontSize="7" fill={c} opacity=".35">total budget</text>
          </svg>
        </div>

        <div className="oce-dash-cell">
          <svg viewBox="0 0 200 180" fill="none">
            <rect x="4" y="4" width="192" height="172" rx="6" fill="none" stroke={c} strokeWidth=".7" />
            <text x="16" y="22" fontSize="8" fill={c} opacity=".6" fontWeight="700" letterSpacing=".04em">PROJECT KPIs</text>
            {[
              ['SPI', '1.04'], ['CPI', '0.97'], ['EAC', '\u20AC4.3M'],
              ['Variance', '-2.8%'], ['Progress', '68%'],
            ].map(([label, value], i) => (
              <g key={label}>
                <text x="16" y={46 + i * 28} fontSize="8" fill={c} opacity=".35">{label}</text>
                <text x="180" y={46 + i * 28} textAnchor="end" fontSize="12" fill={c} opacity=".55" fontWeight="600">{value}</text>
                {i < 4 && <line x1="16" y1={52 + i * 28} x2="184" y2={52 + i * 28} stroke={c} strokeWidth=".4" opacity=".15" />}
              </g>
            ))}
          </svg>
        </div>

        {/* Row 3: S-Curve (wide) */}
        <div className="oce-dash-cell oce-dash-wide">
          <svg viewBox="0 0 420 120" fill="none">
            <rect x="4" y="4" width="412" height="112" rx="6" fill="none" stroke={c} strokeWidth=".7" />
            <text x="16" y="22" fontSize="8" fill={c} opacity=".6" fontWeight="700" letterSpacing=".04em">S-CURVE — PLANNED vs ACTUAL</text>
            <defs>
              <linearGradient id="oceAreaFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={c} stopOpacity=".1" />
                <stop offset="100%" stopColor={c} stopOpacity="0" />
              </linearGradient>
            </defs>
            {/* Planned (dashed) */}
            <polyline points="24,95 60,88 100,76 140,62 180,50 220,42 260,36 300,32 340,30 380,28 400,27" fill="none" stroke={c} strokeWidth="1.2" strokeDasharray="5 4" opacity=".3" />
            {/* Actual (solid) */}
            <polyline points="24,95 60,90 100,80 140,68 180,58 220,52 260,48 300,43 340,38 380,33 400,30" fill="none" stroke={c} strokeWidth="1.8" opacity=".5" strokeLinecap="round" />
            {/* Area fill */}
            <polygon points="24,95 60,90 100,80 140,68 180,58 220,52 260,48 300,43 340,38 380,33 400,30 400,100 24,100" fill="url(#oceAreaFill)" />
            {/* Legend */}
            <line x1="300" y1="15" x2="320" y2="15" stroke={c} strokeWidth="1.2" strokeDasharray="4 3" opacity=".3" />
            <text x="324" y="18" fontSize="7" fill={c} opacity=".35">Planned</text>
            <line x1="360" y1="15" x2="380" y2="15" stroke={c} strokeWidth="1.5" opacity=".5" />
            <text x="384" y="18" fontSize="7" fill={c} opacity=".5">Actual</text>
          </svg>
        </div>

        {/* Row 4: Building elevation + Schedule mini */}
        <div className="oce-dash-cell">
          <svg viewBox="0 0 200 130" fill="none">
            <rect x="4" y="4" width="192" height="122" rx="6" fill="none" stroke={c} strokeWidth=".7" />
            <text x="16" y="20" fontSize="8" fill={c} opacity=".6" fontWeight="700" letterSpacing=".04em">ELEVATION</text>
            <line x1="20" y1="110" x2="180" y2="110" stroke={c} strokeWidth="1" opacity=".4" />
            <rect x="35" y="45" width="130" height="65" fill="none" stroke={c} strokeWidth=".7" opacity=".5" />
            <path d="M30 45 L100 20 L170 45" fill="none" stroke={c} strokeWidth=".7" opacity=".5" />
            <rect x="50" y="56" width="18" height="14" rx="1" fill="none" stroke={c} strokeWidth=".4" opacity=".4" />
            <rect x="80" y="56" width="18" height="14" rx="1" fill="none" stroke={c} strokeWidth=".4" opacity=".4" />
            <rect x="120" y="56" width="18" height="14" rx="1" fill="none" stroke={c} strokeWidth=".4" opacity=".4" />
            <rect x="85" y="82" width="22" height="28" rx="1" fill="none" stroke={c} strokeWidth=".5" opacity=".5" />
            <text x="100" y="125" textAnchor="middle" fontSize="6" fill={c} opacity=".3" fontFamily="monospace">46.00 m</text>
          </svg>
        </div>

        <div className="oce-dash-cell">
          <svg viewBox="0 0 200 130" fill="none">
            <rect x="4" y="4" width="192" height="122" rx="6" fill="none" stroke={c} strokeWidth=".7" />
            <text x="16" y="20" fontSize="8" fill={c} opacity=".6" fontWeight="700" letterSpacing=".04em">SCHEDULE</text>
            {/* Gantt bars */}
            {[
              [30, 35, 120, 'Foundation'],
              [50, 55, 100, 'Structure'],
              [80, 75, 80,  'Facade'],
              [100, 95, 60, 'MEP'],
              [120, 115, 50, 'Finishing'],
            ].map(([x, y, w, label], i) => (
              <g key={i}>
                <rect x={x as number} y={y as number} width={w as number} height="12" rx="2" fill={c} opacity={0.15 + i * 0.08} />
                <text x="16" y={(y as number) + 10} fontSize="6" fill={c} opacity=".35">{label as string}</text>
              </g>
            ))}
          </svg>
        </div>
      </div>
    </div>
  );
}

/* ── Main Background ─────────────────────────────────────────────────── */

export function AuthBackground() {
  return (
    <div className="fixed inset-0 overflow-hidden pointer-events-none oce-auth-bg" aria-hidden="true">
      <AnimatedTable />
      <DashboardGrid />
    </div>
  );
}
