// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
/**
 * Overlay HUD floating above the Cesium canvas.
 *
 * Renders four glass-card pods:
 *
 * * **North arrow** — fixed-bearing rose at the top-right.
 * * **Camera altitude** — current eye height in m/km.
 * * **Cursor coordinates** — lat / lon under the pointer (or "—" when
 *   the cursor is off-globe).
 * * **Scale bar** — orders-of-magnitude bar tied to altitude.
 *
 * The HUD is purely presentational. The viewer wires
 * ``onCameraChange`` / ``onMouseCoord`` callbacks to push state up; if
 * Cesium isn't loaded we still render the chrome (with em-dashes) so
 * the layout is stable.
 */

import { useTranslation } from 'react-i18next';
import { Compass } from 'lucide-react';

import { formatAltitude, formatDegrees } from './utils';
import { fmtFixed } from '@/shared/lib/formatters';

interface GeoOverlayHudProps {
  /** Cursor latitude in degrees (null when pointer is off-globe). */
  cursorLat: number | null;
  /** Cursor longitude in degrees. */
  cursorLon: number | null;
  /** Current camera altitude over the ellipsoid, in metres. */
  altitudeM: number | null;
  /**
   * Camera heading in degrees clockwise from north (0..360). When null
   * the north arrow renders fixed at the top (decorative-only fallback).
   */
  headingDeg?: number | null;
  /** True when the underlying Cesium viewer is up and the HUD is live. */
  active: boolean;
}

/**
 * Pick a friendly bar width for the current altitude. Returns a label
 * (e.g. "5 km", "100 m") plus the bar pixel width — kept in a single
 * helper so the rendering stays declarative.
 */
function scaleBarFor(alt: number | null): { label: string; widthPx: number } {
  if (alt === null || !Number.isFinite(alt)) {
    return { label: '—', widthPx: 80 };
  }
  // Heuristic: bar represents roughly altitude / 8 in ground units.
  const groundMetres = alt / 8;
  const steps = [
    10, 25, 50, 100, 250, 500, 1_000, 2_500, 5_000, 10_000, 25_000,
    50_000, 100_000, 250_000, 500_000, 1_000_000, 2_500_000,
  ];
  const fallback = steps[steps.length - 1] ?? 1000;
  const pick = steps.find((s) => s >= groundMetres) ?? fallback;
  const label =
    pick >= 1000
      ? `${fmtFixed(pick / 1000, 0)} km`
      : `${fmtFixed(pick, 0)} m`;
  // Width is capped 60-130 px so the bar never dominates the HUD.
  const widthPx = Math.min(130, Math.max(60, 60 + Math.log10(pick) * 12));
  return { label, widthPx };
}

const GLASS_CARD = [
  'pointer-events-auto inline-flex items-center gap-2',
  'rounded-md border border-white/10 bg-slate-900/65 px-2.5 py-1.5',
  'text-2xs font-medium text-slate-100 shadow-md backdrop-blur-md',
  'ring-1 ring-white/5',
].join(' ');

export function GeoOverlayHud({
  cursorLat,
  cursorLon,
  altitudeM,
  headingDeg,
  active,
}: GeoOverlayHudProps) {
  const { t } = useTranslation();
  const scale = scaleBarFor(altitudeM);
  // Cesium reports heading clockwise from north — we want the compass
  // needle to rotate counter-clockwise so that the rose stays oriented
  // to true north regardless of camera bearing.
  const headingRotation =
    active && headingDeg !== null && headingDeg !== undefined && Number.isFinite(headingDeg)
      ? -headingDeg
      : 0;

  return (
    <>
      {/* Top-right: north arrow + altitude */}
      <div className="pointer-events-none absolute top-3 right-3 z-10 flex flex-col items-end gap-1.5">
        <div className={GLASS_CARD} aria-label={t('geo_hub.hud.north', { defaultValue: 'North' })}>
          <Compass
            size={12}
            strokeWidth={2}
            className="text-emerald-300 transition-transform duration-150 ease-out"
            style={{ transform: `rotate(${headingRotation}deg)` }}
          />
          <span className="uppercase tracking-wider">
            {t('geo_hub.hud.north_short', { defaultValue: 'N' })}
          </span>
        </div>
        <div className={GLASS_CARD}>
          <span className="text-slate-400 uppercase tracking-wider">
            {t('geo_hub.hud.altitude', { defaultValue: 'ALT' })}
          </span>
          <span className="font-mono tabular-nums text-white">
            {active ? formatAltitude(altitudeM ?? NaN) : '—'}
          </span>
        </div>
      </div>

      {/* Bottom-left: coordinates + scale bar */}
      <div
        className="pointer-events-none absolute bottom-3 left-3 z-10 flex flex-col items-start gap-1.5"
        data-testid="geo-tour-hud"
      >
        <div className={GLASS_CARD}>
          <span className="text-slate-400 uppercase tracking-wider">
            {t('geo_hub.hud.lat', { defaultValue: 'LAT' })}
          </span>
          <span className="font-mono tabular-nums text-white min-w-[70px]">
            {active && cursorLat !== null ? formatDegrees(cursorLat) : '—'}
          </span>
          <span className="ml-1 text-slate-400 uppercase tracking-wider">
            {t('geo_hub.hud.lon', { defaultValue: 'LON' })}
          </span>
          <span className="font-mono tabular-nums text-white min-w-[70px]">
            {active && cursorLon !== null ? formatDegrees(cursorLon) : '—'}
          </span>
        </div>
        <div className={GLASS_CARD}>
          <span className="text-slate-400 uppercase tracking-wider">
            {t('geo_hub.hud.scale', { defaultValue: 'SCALE' })}
          </span>
          <div className="flex items-center gap-1.5">
            <div
              className="h-1.5 rounded-sm border border-white/40"
              style={{
                width: `${scale.widthPx}px`,
                background:
                  'repeating-linear-gradient(90deg, rgba(255,255,255,0.9) 0 8px, rgba(255,255,255,0.15) 8px 16px)',
              }}
              aria-hidden
            />
            <span className="font-mono tabular-nums text-white">{scale.label}</span>
          </div>
        </div>
      </div>
    </>
  );
}

export default GeoOverlayHud;
