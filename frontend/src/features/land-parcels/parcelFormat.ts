// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Pure helpers of the parcel screen: status colours, file reading, plan centre. */

import type { ImportBody, ImportTarget, ParcelStatus, PlanCollection } from './api';

/** StatusDot variant per acquisition status; the label always travels with it. */
export const STATUS_VARIANT: Record<ParcelStatus, 'success' | 'warning' | 'error' | 'info' | 'neutral'> = {
  needed: 'neutral',
  negotiating: 'warning',
  acquired: 'success',
  expropriation: 'error',
};

/** Fill colour on the plan, the same hues as the StatusDot variants. */
export const STATUS_FILL: Record<ParcelStatus, string> = {
  needed: '#94a3b8',
  negotiating: '#f59e0b',
  acquired: '#16a34a',
  expropriation: '#dc2626',
};

export function formatOf(filename: string): ImportBody['format'] | null {
  const lower = filename.toLowerCase();
  if (lower.endsWith('.zip')) return 'shapefile';
  if (lower.endsWith('.geojson') || lower.endsWith('.json')) return 'geojson';
  return null;
}

function toBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

/** The import body for a dropped file: GeoJSON as text, a Shapefile zip as base64. */
export async function importBodyFor(file: File, target: ImportTarget): Promise<ImportBody> {
  const format = formatOf(file.name);
  if (!format) throw new Error('unsupported');
  if (format === 'shapefile') {
    return { format, target, filename: file.name, content_base64: toBase64(await file.arrayBuffer()) };
  }
  return { format, target, filename: file.name, text: await file.text() };
}

/** Centre of everything on the plan, for the first camera move; null when empty. */
export function planCentre(plan: PlanCollection | undefined): { lat: number; lon: number } | null {
  const pts = (plan?.features ?? []).flatMap((f) => f.geometry.coordinates[0] ?? []);
  if (pts.length === 0 || plan?.local) return null;
  const lons = pts.map((p) => p[0]!);
  const lats = pts.map((p) => p[1]!);
  return { lon: (Math.min(...lons) + Math.max(...lons)) / 2, lat: (Math.min(...lats) + Math.max(...lats)) / 2 };
}

/** Rule ids of the parcel's findings, deduplicated, in rule order. */
export function ruleIds(findings: { rule_id: string }[]): string[] {
  return [...new Set(findings.map((f) => f.rule_id))].sort();
}
