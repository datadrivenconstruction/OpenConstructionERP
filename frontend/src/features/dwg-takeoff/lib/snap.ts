/**
 * Snap-candidate finder for DXF entity endpoints + segment midpoints.
 *
 * During rubber-banding in any drawing tool we hover the cursor near the
 * geometry. When a snap mode is enabled and the cursor is within
 * ``tolerance`` world-units of a candidate, we return the snapped point
 * so the renderer can draw a marker and the click commits to the exact
 * vertex / midpoint of the underlying DXF entity.
 *
 * Kept pure so it can be unit-tested without a canvas.
 */

import type { DxfEntity } from '../api';

export interface Pt {
  x: number;
  y: number;
}

/** Which kinds of candidate points the finder generates. */
export interface SnapModes {
  endpoint: boolean;
  midpoint: boolean;
  /** Intersection between two entities. Optional; finder skips when false
   *  or when unimplemented. */
  intersection?: boolean;
}

/** A point the cursor can snap to, with provenance for UI labelling. */
export interface SnapCandidate {
  point: Pt;
  kind: 'endpoint' | 'midpoint' | 'intersection';
  /** Source entity id — handy for tests and optional tooltip text. */
  entityId: string;
}

/** Classify an endpoint from a polyline vertex or a line's start/end. */
function isFinitePt(p: Pt | undefined | null): p is Pt {
  return !!p && Number.isFinite(p.x) && Number.isFinite(p.y);
}

/**
 * Collect every endpoint / midpoint the cursor could snap to for the
 * given set of entities. The finder is cheap and returns the full list;
 * callers pick the closest via ``closestSnapCandidate``. Hidden entities
 * are NOT filtered here — the caller already filters by visible layer.
 */
export function collectSnapCandidates(
  entities: DxfEntity[],
  modes: SnapModes,
): SnapCandidate[] {
  const out: SnapCandidate[] = [];
  for (const e of entities) {
    // LINE: start + end endpoints; segment midpoint.
    if (e.type === 'LINE' && isFinitePt(e.start) && isFinitePt(e.end)) {
      if (modes.endpoint) {
        out.push({ point: { x: e.start.x, y: e.start.y }, kind: 'endpoint', entityId: e.id });
        out.push({ point: { x: e.end.x, y: e.end.y }, kind: 'endpoint', entityId: e.id });
      }
      if (modes.midpoint) {
        out.push({
          point: { x: (e.start.x + e.end.x) / 2, y: (e.start.y + e.end.y) / 2 },
          kind: 'midpoint',
          entityId: e.id,
        });
      }
      continue;
    }

    // LWPOLYLINE: each vertex is an endpoint; midpoint of each segment.
    if (e.type === 'LWPOLYLINE' && e.vertices && e.vertices.length >= 2) {
      const verts = e.vertices;
      if (modes.endpoint) {
        for (const v of verts) {
          if (isFinitePt(v)) {
            out.push({ point: { x: v.x, y: v.y }, kind: 'endpoint', entityId: e.id });
          }
        }
      }
      if (modes.midpoint) {
        const n = verts.length;
        const last = e.closed ? n : n - 1;
        for (let i = 0; i < last; i++) {
          const a = verts[i]!;
          const b = verts[(i + 1) % n]!;
          if (isFinitePt(a) && isFinitePt(b)) {
            out.push({
              point: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 },
              kind: 'midpoint',
              entityId: e.id,
            });
          }
        }
      }
      continue;
    }

    // CIRCLE / ARC: centre acts as endpoint-like anchor. (Cheap + useful.)
    if ((e.type === 'CIRCLE' || e.type === 'ARC') && isFinitePt(e.start)) {
      if (modes.endpoint) {
        out.push({ point: { x: e.start.x, y: e.start.y }, kind: 'endpoint', entityId: e.id });
      }
    }
  }
  return out;
}

/**
 * Return the snap candidate closest to ``cursor`` within ``tolerance``
 * world-units, or ``null`` if none qualify. When two candidates are
 * exactly equidistant, endpoint wins over midpoint (matches AutoCAD).
 */
export function closestSnapCandidate(
  candidates: SnapCandidate[],
  cursor: Pt,
  tolerance: number,
): SnapCandidate | null {
  let best: SnapCandidate | null = null;
  let bestDist = Infinity;
  const priority: Record<SnapCandidate['kind'], number> = {
    endpoint: 0,
    intersection: 1,
    midpoint: 2,
  };

  for (const c of candidates) {
    const d = Math.hypot(c.point.x - cursor.x, c.point.y - cursor.y);
    if (d > tolerance) continue;
    if (d < bestDist) {
      best = c;
      bestDist = d;
      continue;
    }
    if (d === bestDist && best && priority[c.kind] < priority[best.kind]) {
      best = c;
    }
  }
  return best;
}
