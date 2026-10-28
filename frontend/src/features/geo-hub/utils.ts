// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
/**
 * Lightweight formatting helpers for the Geo Hub UI.
 *
 * Pure, dependency-free — designed for use from sidebar cards, the
 * overlay HUD and the empty states. Anything that needs to traverse
 * networking, Cesium or React lives elsewhere.
 */

/** Format a byte count as KB/MB/GB with one decimal. */
import { fmtFixed } from '@/shared/lib/formatters';
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${fmtFixed(value, value >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

/**
 * Format an ISO timestamp as a short relative-time string (en-US fixed
 * — the surrounding labels are i18n-translated already, this only
 * produces digits + a unit letter).
 */
export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return '—';
  const diffSec = Math.round((Date.now() - then) / 1000);
  if (diffSec < 60) return `${diffSec}s`;
  if (diffSec < 3600) return `${Math.round(diffSec / 60)}m`;
  if (diffSec < 86_400) return `${Math.round(diffSec / 3600)}h`;
  if (diffSec < 30 * 86_400) return `${Math.round(diffSec / 86_400)}d`;
  return new Date(then).toISOString().slice(0, 10);
}

/**
 * Convert a Cesium camera altitude (metres) to a friendly label.
 * Switches to km past 1 km.
 */
export function formatAltitude(metres: number): string {
  if (!Number.isFinite(metres)) return '—';
  if (metres >= 1000) return `${fmtFixed(metres / 1000, metres >= 10_000 ? 0 : 1)} km`;
  return `${Math.round(metres)} m`;
}

/**
 * Pretty-print a coordinate value (lat or lon) with sign + 4 decimals.
 * Caller is responsible for the lat/lon suffix label so it can be i18n'd.
 */
export function formatDegrees(value: number): string {
  if (!Number.isFinite(value)) return '—';
  const sign = value >= 0 ? '+' : '−';
  return `${sign}${Math.abs(value).toFixed(4)}°`;
}
