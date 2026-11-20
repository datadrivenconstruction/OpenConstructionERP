// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Snapping, a pure function of the cursor, the index and the settings.
 * Priority: endpoint > intersection > midpoint > perpendicular > nearest > grid.
 * The radius is in grid metres (the canvas converts 10 px, 16 px on touch).
 */

import { SNAP_KINDS, SNAP_PRIORITY, type GridXY, type SnapKind, type SnapResult, type SnapSettings } from '../types';
import { dist, midpoint, nearestOnSegment, perpendicularFoot, segmentIntersection } from './geometry';
import type { SpatialIndex } from './spatialIndex';

export const SNAP_RADIUS_PX = 10;
export const SNAP_RADIUS_TOUCH_PX = 16;
export const GRID_STEPS = [0.1, 0.5, 1, 5, 10] as const;

export function defaultSnapSettings(): SnapSettings {
  return {
    enabled: true,
    modes: { endpoint: true, midpoint: true, intersection: true, perpendicular: true, nearest: true, grid: false },
    gridStep: 1,
  };
}

export interface SnapQuery {
  cursor: GridXY;
  /** Search radius in grid metres. */
  radius: number;
  settings: SnapSettings;
  /** The last placed vertex; perpendicular snaps from it. */
  last?: GridXY | null;
  /** Features to ignore (the one being edited). */
  exclude?: ReadonlySet<string>;
}

/** The best snap within the radius, or null. Alt-held callers pass `settings.enabled = false`. */
export function snap(index: SpatialIndex, q: SnapQuery): SnapResult | null {
  const { cursor, radius, settings } = q;
  if (!settings.enabled) return null;
  const on = settings.modes;
  const skip = (id: string) => q.exclude?.has(id) ?? false;
  const best = new Map<SnapKind, SnapResult>();
  const offer = (c: SnapResult) => {
    if (c.distance > radius) return;
    const cur = best.get(c.kind);
    if (!cur || c.distance < cur.distance) best.set(c.kind, c);
  };

  if (on.endpoint) {
    for (const v of index.queryVertices(cursor, radius)) {
      if (skip(v.featureId)) continue;
      offer({ kind: 'endpoint', point: v.p, featureId: v.featureId, targetLabel: v.label, distance: dist(cursor, v.p) });
    }
  }
  const segs = on.midpoint || on.intersection || on.perpendicular || on.nearest ? index.querySegments(cursor, radius) : [];
  const live = segs.filter((s) => !skip(s.featureId));
  for (const s of live) {
    if (on.midpoint) {
      const m = midpoint(s.a, s.b);
      offer({ kind: 'midpoint', point: m, featureId: s.featureId, targetLabel: s.label, distance: dist(cursor, m) });
    }
    if (on.nearest) {
      const { point } = nearestOnSegment(cursor, s.a, s.b);
      offer({ kind: 'nearest', point, featureId: s.featureId, targetLabel: s.label, distance: dist(cursor, point) });
    }
    if (on.perpendicular && q.last) {
      const foot = perpendicularFoot(q.last, s.a, s.b);
      if (foot && foot.t >= 0 && foot.t <= 1 && dist(foot.point, q.last) > 1e-9) {
        offer({ kind: 'perpendicular', point: foot.point, featureId: s.featureId, targetLabel: s.label, distance: dist(cursor, foot.point) });
      }
    }
  }
  if (on.intersection) {
    for (let i = 0; i < live.length; i++) {
      for (let j = i + 1; j < live.length; j++) {
        const s1 = live[i]!;
        const s2 = live[j]!;
        if (s1.featureId === s2.featureId && Math.abs(s1.index - s2.index) <= 1) continue;
        const hit = segmentIntersection(s1.a, s1.b, s2.a, s2.b);
        if (!hit) continue;
        // A shared vertex is an endpoint, not an intersection.
        if ([s1.a, s1.b].some((p) => dist(p, hit) < 1e-9) && [s2.a, s2.b].some((p) => dist(p, hit) < 1e-9)) continue;
        offer({ kind: 'intersection', point: hit, featureId: s1.featureId, targetLabel: s1.label, distance: dist(cursor, hit) });
      }
    }
  }
  if (on.grid && settings.gridStep > 0) {
    const g = settings.gridStep;
    const p: GridXY = [Math.round(cursor[0] / g) * g, Math.round(cursor[1] / g) * g];
    // The grid always answers; its radius is the cell itself.
    best.set('grid', { kind: 'grid', point: p, distance: dist(cursor, p) });
  }
  for (const kind of SNAP_PRIORITY) {
    const hit = best.get(kind);
    if (hit) return hit;
  }
  return null;
}

/** Every mode on or off at once (F3). */
export function toggleAll(settings: SnapSettings): SnapSettings {
  return { ...settings, enabled: !settings.enabled };
}

export function setMode(settings: SnapSettings, kind: SnapKind, value: boolean): SnapSettings {
  return { ...settings, modes: { ...settings.modes, [kind]: value } };
}

export { SNAP_KINDS };
