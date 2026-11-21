// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Scale bar and north arrow (grid north, with true north when they differ). */

import { useTranslation } from 'react-i18next';
import { niceBar } from '../engine/viewTransform';
import { formatDistance } from '../units/linear';
import type { PlanConventions } from '../units/conventions';

export function ScaleBar({ mpp, conventions }: { mpp: number; conventions: PlanConventions }) {
  const { metres, px } = niceBar(mpp);
  if (!Number.isFinite(px) || px <= 0) return null;
  const text = formatDistance(metres, { ...conventions, precision: metres >= 1 ? 'mm' : conventions.precision }, true).replace(/\.0+(?=\s)/, '');
  return (
    <div className="pointer-events-none select-none" data-testid="plan-scale-bar" aria-hidden>
      <div className="mb-0.5 text-2xs font-medium" style={{ color: 'var(--oe-map-ink)', textShadow: '0 0 3px var(--oe-map-halo)' }}>
        {text}
      </div>
      <div className="flex h-1.5" style={{ width: px, border: '1px solid var(--oe-map-ink)', background: 'var(--oe-map-halo)' }}>
        <div className="h-full w-1/2" style={{ background: 'var(--oe-map-ink)' }} />
      </div>
    </div>
  );
}

/**
 * The arrow points at grid north on screen. `bearing` is the map rotation and
 * `gridNorth` the geographic azimuth of grid north; true north shows as a thin tick.
 */
export function NorthArrow({ bearing, gridNorth, onReset }: { bearing: number; gridNorth: number; onReset: () => void }) {
  const { t } = useTranslation();
  const grid = gridNorth - bearing;
  const trueN = -bearing;
  const showTrue = Math.abs(gridNorth) > 0.05;
  return (
    <button
      type="button"
      onClick={onReset}
      className="flex h-11 w-11 items-center justify-center rounded-full border border-border-light bg-surface-elevated/90 shadow-sm backdrop-blur hover:bg-surface-secondary"
      title={t('plan.north_reset', { defaultValue: 'Grid north up' })}
      aria-label={t('plan.north_reset', { defaultValue: 'Grid north up' })}
      data-testid="plan-north"
    >
      <svg width="30" height="30" viewBox="-15 -15 30 30" aria-hidden>
        {showTrue && <line x1="0" y1="2" x2="0" y2="-13" stroke="var(--oe-map-ink-2)" strokeWidth="1" transform={`rotate(${trueN})`} />}
        <g transform={`rotate(${grid})`}>
          <path d="M0 -12 L5 4 L0 1 L-5 4 Z" fill="var(--oe-map-ink)" />
          <text y="13" textAnchor="middle" fontSize="7" fontWeight="600" fill="var(--oe-map-ink)">
            N
          </text>
        </g>
      </svg>
    </button>
  );
}
