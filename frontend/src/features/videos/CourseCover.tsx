// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The illustrated cover of a course, checklist or guide: a subject glyph in a
// brand-coloured hexagon, its neighbours of the comb around it, on a paper
// ground (ink in the dark theme). Drawn inline from tokens, so it follows the
// theme and costs no request. The title stays text on the card, never here.

import { useId } from 'react';
import type { AcademyItem } from './academyTypes';
import { COVER_ACCENT, coverSeed, coverSubject, secondSubject, type CoverAccent, type CoverSubject } from './courseCovers';

interface Stroke {
  d: string;
  w?: number;
}

/** Line glyphs on a 48 grid, drawn with the current colour. */
const GLYPH: Record<CoverSubject, Stroke[]> = {
  takeoff: [
    { d: 'M11 7h18l8 8v26H11z' },
    { d: 'M29 7v8h8' },
    { d: 'M16 19h10' },
    { d: 'M16 32h16M16 29v6M32 29v6' },
  ],
  bim: [{ d: 'M24 7l15 8.5v17L24 41 9 32.5v-17z' }, { d: 'M9 15.5L24 24l15-8.5M24 24v17' }],
  estimate: [{ d: 'M9 9h30v30H9z' }, { d: 'M9 17h30M9 25h30M9 32h30M19 17v22' }],
  exchange: [
    { d: 'M8 8h15v19H8zM25 21h15v19H25z' },
    { d: 'M29 9h4a5 5 0 0 1 5 5v3M35 15l3 3 3-3' },
    { d: 'M19 39h-4a5 5 0 0 1-5-5v-3M13 33l-3-3-3 3' },
  ],
  tender: [{ d: 'M7 13h34v23H7z' }, { d: 'M7 13l17 13 17-13' }, { d: 'M7 36l12-11M41 36L29 25' }],
  schedule: [
    { d: 'M8 8v32h32' },
    { d: 'M13 15h12M19 22h14M16 29h9M26 35h10', w: 4 },
  ],
  cost: [{ d: 'M8 8v32h32' }, { d: 'M13 32l8-9 6 5 11-13' }, { d: 'M32 15h6v6' }],
  finance: [
    { d: 'M10 7h20v33l-4-3-3 3-3-3-3 3-3-3-4 3z' },
    { d: 'M15 15h10M15 21h10M15 27h6' },
    { d: 'M34 25m-7 0a7 7 0 1 0 14 0a7 7 0 1 0-14 0M34 22v6' },
  ],
  contract: [
    { d: 'M11 7h18l8 8v26H11z' },
    { d: 'M29 7v8h8' },
    { d: 'M16 18h12M16 24h16' },
    { d: 'M16 34c3-4 5 2 8-1s4-2 6 0' },
  ],
  quality: [{ d: 'M15 10h-4v31h26V10h-4' }, { d: 'M18 7h12v6H18z' }, { d: 'M17 27l5 5 9-10' }],
  safety: [{ d: 'M10 32a14 14 0 0 1 28 0' }, { d: 'M6 32h36v5H6z' }, { d: 'M20.5 19V13h7v6' }],
  site: [
    { d: 'M13 7h23v34H13z' },
    { d: 'M9 13h7M9 21h7M9 29h7' },
    { d: 'M20 15h10M20 21h10M20 27h6' },
  ],
  carbon: [
    { d: 'M38 9C21 9 10 17 10 30c0 4 2 9 2 9' },
    { d: 'M38 9c0 18-8 29-22 29' },
    { d: 'M12 39c6-10 13-16 21-20' },
  ],
  checklist: [
    { d: 'M9 12l3 3 5-6M9 24l3 3 5-6M9 36l3 3 5-6' },
    { d: 'M23 12h16M23 24h16M23 36h16' },
  ],
  guide: [
    { d: 'M24 13c-4-4-10-5-16-4v28c6-1 12 0 16 4' },
    { d: 'M24 13c4-4 10-5 16-4v28c-6-1-12 0-16 4' },
    { d: 'M24 13v28' },
  ],
};

const ACCENT_VAR: Record<CoverAccent, string> = {
  erp: 'var(--oe-brand-erp)',
  academy: 'var(--oe-brand-academy)',
  design: 'var(--oe-brand-design)',
};

export function coverAccentColor(subject: CoverSubject): string {
  return ACCENT_VAR[COVER_ACCENT[subject]];
}

/** The subject glyph alone, for small faces such as a honeycomb cell. */
export function CourseGlyph({ subject, size = 24, className }: { subject: CoverSubject; size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      stroke="currentColor"
      strokeWidth={2.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden
      focusable="false"
    >
      {GLYPH[subject].map((s, i) => (
        <path key={i} d={s.d} strokeWidth={s.w} />
      ))}
    </svg>
  );
}

const SQRT3 = Math.sqrt(3);

/** Flat-top hexagon (points left and right, like HEX_CELL_CLIP) as a path. */
function hexPath(cx: number, cy: number, r: number): string {
  const h = (SQRT3 / 2) * r;
  const f = (n: number) => Math.round(n * 10) / 10;
  return `M${f(cx - r)} ${f(cy)}L${f(cx - r / 2)} ${f(cy - h)}H${f(cx + r / 2)}L${f(cx + r)} ${f(cy)}L${f(cx + r / 2)} ${f(cy + h)}H${f(cx - r / 2)}Z`;
}

// One tile of a flat-top honeycomb of side 12: the middle cell and two stubs.
const TILE_R = 12;
const TILE_W = 3 * TILE_R;
const TILE_H = SQRT3 * TILE_R;
const TILE_PATH = (() => {
  const r = TILE_R;
  const h = TILE_H / 2;
  return `M0 ${h}H${r / 2}L${r} 0H${2 * r}L${2.5 * r} ${h}H${3 * r}M${r / 2} ${h}L${r} ${2 * h}H${2 * r}L${2.5 * r} ${h}`;
})();

// Neighbour directions of a flat-top cell, as unit offsets.
const NEIGHBOURS: [number, number][] = [
  [1.5, -SQRT3 / 2],
  [1.5, SQRT3 / 2],
  [0, SQRT3],
  [-1.5, SQRT3 / 2],
  [-1.5, -SQRT3 / 2],
  [0, -SQRT3],
];

/**
 * A 16:9 cover for one item. `className` sizes it (it fills its box by
 * default). Decorative: the card carries the title and the meaning.
 */
export function CourseCover({ item, className }: { item: Pick<AcademyItem, 'id' | 'topics' | 'routes' | 'kind'>; className?: string }) {
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, '');
  const subject = coverSubject(item);
  const accent = coverAccentColor(subject);
  const seed = coverSeed(item.id);
  const second = secondSubject(item, subject);
  const R = 44;
  const step = 47;
  const cx = 224 + ((seed % 5) - 2) * 6;
  const cy = 90 + (((seed >>> 4) % 3) - 1) * 6;
  // The second topic sits in a solid cell to the left, where it is never cut off.
  const solid = second ? 3 + ((seed >>> 2) % 2) : seed % 6;
  const tint = (solid + 2 + ((seed >>> 3) % 3)) % 6;
  const glyph = 54;
  const small = 30;

  return (
    <svg
      viewBox="0 0 320 180"
      preserveAspectRatio="xMidYMid slice"
      className={className ?? 'h-full w-full'}
      aria-hidden
      focusable="false"
      data-testid="course-cover"
      data-subject={subject}
    >
      <defs>
        <pattern id={`p${uid}`} width={TILE_W} height={TILE_H} patternUnits="userSpaceOnUse" x={(seed % 7) * 2} y={(seed % 5) * 2}>
          <path d={TILE_PATH} fill="none" stroke={accent} strokeWidth={1} />
        </pattern>
        <linearGradient id={`f${uid}`} x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stopColor="white" stopOpacity="0" />
          <stop offset="0.75" stopColor="white" stopOpacity="1" />
        </linearGradient>
        <mask id={`m${uid}`}>
          <rect width="320" height="180" fill={`url(#f${uid})`} />
        </mask>
        <radialGradient id={`g${uid}`} cx={cx / 320} cy={cy / 180} r="0.55">
          <stop offset="0" stopColor={accent} stopOpacity="0.22" />
          <stop offset="1" stopColor={accent} stopOpacity="0" />
        </radialGradient>
        <linearGradient id={`s${uid}`} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="white" stopOpacity="0.22" />
          <stop offset="0.55" stopColor="white" stopOpacity="0" />
        </linearGradient>
      </defs>
      <rect width="320" height="180" fill="var(--oe-cover-ground)" />
      <rect width="320" height="180" fill={`url(#g${uid})`} />
      <rect width="320" height="180" fill={`url(#p${uid})`} opacity="0.2" mask={`url(#m${uid})`} />
      {NEIGHBOURS.map(([dx, dy], i) => (
        <path
          key={i}
          d={hexPath(cx + dx * step, cy + dy * step, R)}
          fill={i === solid && second ? coverAccentColor(second) : accent}
          fillOpacity={i === solid ? (second ? 0.9 : 0.5) : i === tint ? 0.16 : 0}
          stroke={accent}
          strokeOpacity={i === solid && second ? 0 : 0.4}
          strokeWidth={1.25}
        />
      ))}
      {second && (
        <g
          transform={`translate(${cx + NEIGHBOURS[solid]![0] * step - small / 2} ${cy + NEIGHBOURS[solid]![1] * step - small / 2}) scale(${small / 48})`}
          color="white"
        >
          <g fill="none" stroke="currentColor" strokeWidth={3.25} strokeLinecap="round" strokeLinejoin="round">
            {GLYPH[second].map((s, i) => (
              <path key={i} d={s.d} strokeWidth={s.w ? s.w + 0.5 : undefined} />
            ))}
          </g>
        </g>
      )}
      <path d={hexPath(cx, cy, R)} fill={accent} />
      <path d={hexPath(cx, cy, R)} fill={`url(#s${uid})`} />
      <g transform={`translate(${cx - glyph / 2} ${cy - glyph / 2}) scale(${glyph / 48})`} color="white">
        <g fill="none" stroke="currentColor" strokeWidth={2.75} strokeLinecap="round" strokeLinejoin="round">
          {GLYPH[subject].map((s, i) => (
            <path key={i} d={s.d} strokeWidth={s.w} />
          ))}
        </g>
      </g>
    </svg>
  );
}
