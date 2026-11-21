// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Cursor glyphs of the snap types, drawn as an HTML overlay at the snapped point. */

import type { SnapKind } from '../types';

const S = 14;

function Shape({ kind }: { kind: SnapKind }) {
  const c = S / 2;
  switch (kind) {
    case 'endpoint':
      return <rect x={2} y={2} width={S - 4} height={S - 4} />;
    case 'midpoint':
      return <polygon points={`${c},2 ${S - 2},${S - 2} 2,${S - 2}`} />;
    case 'intersection':
      return <path d={`M2 2 L${S - 2} ${S - 2} M${S - 2} 2 L2 ${S - 2}`} />;
    case 'perpendicular':
      return <path d={`M2 ${S - 2} L${S - 2} ${S - 2} M${c} ${S - 2} L${c} 2`} />;
    case 'nearest':
      return <path d={`M2 2 L${S - 2} 2 L2 ${S - 2} L${S - 2} ${S - 2} Z`} />;
    case 'grid':
    default:
      return <path d={`M${c} 2 L${c} ${S - 2} M2 ${c} L${S - 2} ${c}`} />;
  }
}

export const SNAP_LABEL: Record<SnapKind, [string, string]> = {
  endpoint: ['plan.snap.endpoint', 'Endpoint'],
  midpoint: ['plan.snap.midpoint', 'Midpoint'],
  intersection: ['plan.snap.intersection', 'Intersection'],
  perpendicular: ['plan.snap.perpendicular', 'Perpendicular'],
  nearest: ['plan.snap.nearest', 'Nearest'],
  grid: ['plan.snap.grid', 'Grid'],
};

/** The glyph alone, for the toolbar toggles and the legend. */
export function SnapIcon({ kind, size = S }: { kind: SnapKind; size?: number }) {
  return (
    <svg width={size} height={size} viewBox={`0 0 ${S} ${S}`} fill="none" stroke="currentColor" strokeWidth={1.6} aria-hidden>
      <Shape kind={kind} />
    </svg>
  );
}

/** Glyph plus a small tag naming the target ("Endpoint CP2"). */
export function SnapCursor({ kind, x, y, label }: { kind: SnapKind; x: number; y: number; label: string }) {
  return (
    <div
      className="pointer-events-none absolute z-10 motion-safe:transition-transform"
      style={{ left: x - S / 2, top: y - S / 2, color: 'var(--oe-map-accent)' }}
      data-testid="plan-snap-glyph"
      data-kind={kind}
    >
      <svg width={S} height={S} viewBox={`0 0 ${S} ${S}`} fill="none" stroke="currentColor" strokeWidth={2} aria-hidden>
        <Shape kind={kind} />
      </svg>
      <span
        className="absolute start-4 top-3 whitespace-nowrap rounded px-1 py-px text-2xs font-medium shadow-sm"
        style={{ background: 'var(--oe-map-halo)', color: 'var(--oe-map-ink)' }}
      >
        {label}
      </span>
    </div>
  );
}
