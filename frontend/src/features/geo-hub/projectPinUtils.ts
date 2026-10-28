// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
/**
 * Pure helpers used by ``CesiumViewer`` to render the global Geo Hub
 * project pin layer with:
 *
 *   * Per-project-type pin icons (residential / commercial / civil /
 *     default).
 *   * Per-status pin colours (active / planning / completed).
 *   * Distance-based clustering — bucket pins that fall within a
 *     pixel-equivalent distance into one cluster entity so a 100-pin
 *     globe doesn't render as illegible noise.
 *
 * Kept Cesium-agnostic so the unit tests don't need a Cesium runtime.
 */

import type { AnchoredProject } from './types';

export type ProjectIconFamily =
  | 'residential'
  | 'commercial'
  | 'civil'
  | 'default';

/**
 * Map a backend ``project_type`` string to the matching icon family.
 *
 * Falls through to ``"default"`` for unknown / empty values so the
 * viewer always has something to render.
 */
export function iconFamilyForProjectType(
  projectType: string | null | undefined,
): ProjectIconFamily {
  if (!projectType) return 'default';
  const t = projectType.toLowerCase();
  if (
    t.includes('residential') ||
    t.includes('housing') ||
    t.includes('home') ||
    t.includes('apartment')
  ) {
    return 'residential';
  }
  if (
    t.includes('commercial') ||
    t.includes('retail') ||
    t.includes('office') ||
    t.includes('hotel') ||
    t.includes('industrial')
  ) {
    return 'commercial';
  }
  if (
    t.includes('civil') ||
    t.includes('road') ||
    t.includes('rail') ||
    t.includes('bridge') ||
    t.includes('infrastructure') ||
    t.includes('utility')
  ) {
    return 'civil';
  }
  return 'default';
}

/**
 * CSS colour for a project status. Used by the Cesium ``Color`` lookup
 * in the viewer and by the cluster badge in DOM overlays.
 */
export function colorForProjectStatus(
  status: string | null | undefined,
): string {
  if (!status) return '#22c55e'; // green-500, "active" default
  const s = status.toLowerCase();
  if (s.includes('planning') || s === 'planned' || s === 'draft') {
    return '#f59e0b'; // amber-500
  }
  if (
    s.includes('completed') ||
    s === 'completed' ||
    s === 'handed_over' ||
    s === 'closed' ||
    s === 'archived'
  ) {
    return '#3b82f6'; // blue-500
  }
  if (s === 'on_hold' || s === 'paused' || s === 'cancelled') {
    return '#9ca3af'; // gray-400
  }
  return '#22c55e'; // active / unknown → green
}

/**
 * Tooltip label for the Cesium label element on a project pin.
 * Composes name + type + status into one short string.
 */
export function pinTooltipLabel(p: AnchoredProject): string {
  const parts: string[] = [p.project_name || 'Project'];
  if (p.project_type) parts.push(p.project_type);
  if (p.status) parts.push(p.status);
  return parts.join(' · ');
}

export interface PinCluster {
  /** Mean lat across the cluster — used as the cluster pin position. */
  lat: number;
  lon: number;
  /** The projects that fall inside this cluster. */
  projects: AnchoredProject[];
}

/**
 * Group ``projects`` into clusters by Haversine distance.
 *
 * Cheap O(n²) — fine for the n ≤ ~2000 cap we accept on
 * ``/api/v1/geo-hub/projects``. The threshold is computed in degrees
 * (a coarse approximation of pixel distance) so the caller can pass a
 * camera-altitude-derived value: closer camera → smaller threshold →
 * less aggressive clustering.
 *
 * Returns a stable order — clusters are sorted by descending size so
 * the legend / Cesium primitive list draws bigger clusters first.
 *
 * Single-pin clusters are still returned (with length 1) so the caller
 * can render them as ordinary individual pins via the same code path.
 */
export function clusterProjects(
  projects: AnchoredProject[],
  thresholdDeg: number,
): PinCluster[] {
  if (projects.length === 0) return [];
  // Pre-parse coords once so the inner loop stays cheap.
  type ParsedRow = { p: AnchoredProject; lat: number; lon: number };
  const rows: ParsedRow[] = [];
  for (const p of projects) {
    const lat = Number(p.lat);
    const lon = Number(p.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;
    rows.push({ p, lat, lon });
  }
  const used = new Set<number>();
  const clusters: PinCluster[] = [];
  const th2 = thresholdDeg * thresholdDeg;
  for (let i = 0; i < rows.length; i++) {
    if (used.has(i)) continue;
    const seed = rows[i];
    if (!seed) continue;
    used.add(i);
    const grouped: ParsedRow[] = [seed];
    for (let j = i + 1; j < rows.length; j++) {
      if (used.has(j)) continue;
      const other = rows[j];
      if (!other) continue;
      const dy = other.lat - seed.lat;
      const dx = other.lon - seed.lon;
      // Squared distance comparison avoids the sqrt; thresholdDeg is
      // an absolute degree threshold (we don't bother with the cos
      // correction for longitude — for the cluster threshold this is
      // a coarse hint that the user can fine-tune by zooming in).
      if (dx * dx + dy * dy <= th2) {
        used.add(j);
        grouped.push(other);
      }
    }
    // Pick the centroid lat/lon for the cluster pin.
    const sumLat = grouped.reduce((a, r) => a + r.lat, 0);
    const sumLon = grouped.reduce((a, r) => a + r.lon, 0);
    clusters.push({
      lat: sumLat / grouped.length,
      lon: sumLon / grouped.length,
      projects: grouped.map((r) => r.p),
    });
  }
  clusters.sort((a, b) => b.projects.length - a.projects.length);
  return clusters;
}

/**
 * Translate a camera altitude (metres above the ellipsoid) into a
 * cluster threshold in degrees. Closer camera → tighter threshold
 * (less aggressive clustering); far-away camera → loose threshold so
 * the globe stays uncluttered.
 *
 * The numbers are derived empirically from a screen-pixel-equivalent
 * of ~30 px between cluster centroids at WGS-84 resolution.
 */
export function clusterThresholdForAltitude(altitudeM: number): number {
  if (!Number.isFinite(altitudeM)) return 0.5;
  // < 5 km eye → effectively no clustering (each pin distinguishable).
  if (altitudeM < 5_000) return 0;
  if (altitudeM < 25_000) return 0.05;
  if (altitudeM < 100_000) return 0.2;
  if (altitudeM < 500_000) return 0.6;
  if (altitudeM < 2_000_000) return 1.5;
  if (altitudeM < 8_000_000) return 4;
  return 8;
}
