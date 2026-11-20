// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Pure helpers for the scan-against-design panel. */
import type { DeviationBand, DeviationStats } from './scanDesignApi';
import type { ToleranceProfile } from '@/features/setting-out/api';

/** Heatmap colours; must match BAND_RGB in backend/app/modules/pointcloud/scan_design.py. */
export const BAND_RGB: Record<DeviationBand, [number, number, number]> = {
  far_low: [37, 99, 235],
  low: [56, 189, 248],
  within: [16, 185, 129],
  high: [245, 158, 11],
  far_high: [239, 68, 68],
  none: [148, 163, 184],
};

export const BAND_ORDER: DeviationBand[] = ['far_low', 'low', 'within', 'high', 'far_high', 'none'];

export const bandColor = (band: DeviationBand) => `rgb(${BAND_RGB[band].join(' ')})`;

/** The deviation range a band covers, for the legend: ±tol and ±2·tol are the edges. */
export function bandRange(band: DeviationBand, tolMm: number): string {
  const t = fmtMm(tolMm);
  const t2 = fmtMm(tolMm * 2);
  switch (band) {
    case 'far_low':
      return `< -${t2}`;
    case 'low':
      return `-${t2} .. -${t}`;
    case 'within':
      return `±${t}`;
    case 'high':
      return `+${t} .. +${t2}`;
    case 'far_high':
      return `> +${t2}`;
    default:
      return '';
  }
}

export function fmtMm(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return '-';
  return String(Number(v.toFixed(digits)));
}

/** Profiles that give a vertical tolerance for the item type, with that value. */
export function verticalProfiles(
  profiles: ToleranceProfile[],
  itemType = 'other',
): { key: string; name: string; source: string; vMm: number }[] {
  const out: { key: string; name: string; source: string; vMm: number }[] = [];
  for (const p of profiles) {
    const item = p.items[itemType] ?? p.items.default;
    if (item && item.v_mm != null && item.v_mm > 0) out.push({ key: p.key, name: p.name, source: p.source, vMm: item.v_mm });
  }
  return out;
}

/** Share of compared points outside tolerance, in percent. */
export function outShare(s: Pick<DeviationStats, 'within_pct' | 'points_compared'>): number | null {
  if (!s.points_compared || s.within_pct == null) return null;
  return Number((100 - s.within_pct).toFixed(2));
}

/** Warnings the person must acknowledge before a volume can be confirmed. */
export const acknowledgeable = (findings: { rule_id: string; severity: string }[]) =>
  findings.filter((f) => f.severity === 'warning').map((f) => f.rule_id);

export const hasBlockingFinding = (findings: { severity: string }[]) => findings.some((f) => f.severity === 'error');
