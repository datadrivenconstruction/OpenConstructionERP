/**
 * Aggregation helpers for multi-entity DWG selections (RFC 11 §4.5).
 *
 * Single source of truth for Σ area / Σ perimeter / Σ length across a
 * heterogeneous set of entities. Kept pure so the unit tests can exercise
 * every branch without mocking React or the Canvas API.
 */

import type { DxfEntity } from '../api';
import { calculateArea, calculateDistance, calculatePerimeter } from './measurement';

export interface GroupAggregate {
  /** Σ area over closed polylines + circles (m²). */
  area: number;
  /** Σ perimeter over closed polylines (m). */
  perimeter: number;
  /** Σ length over LINEs + open polylines (m). */
  length: number;
  /** Number of entities that contributed to any measurement. */
  count: number;
  /** Count of entities per DXF type (for the summary panel). */
  byType: Record<string, number>;
}

const EMPTY_AGGREGATE: GroupAggregate = Object.freeze({
  area: 0,
  perimeter: 0,
  length: 0,
  count: 0,
  byType: {},
});

/**
 * Compute Σ measurements for a group of entities.
 *
 * Rules (derived directly from the existing per-entity panel logic in
 * ``DwgTakeoffPage.extractEntityMeasurement``):
 *   - Closed LWPOLYLINE → contributes its area AND its perimeter.
 *   - Open LWPOLYLINE → contributes its perimeter as length only.
 *   - LINE → contributes its length.
 *   - CIRCLE → contributes its area (π·r²).
 *   - ARC / ELLIPSE / HATCH / TEXT / INSERT / POINT → no quantitative
 *     contribution for now. Still counted in ``byType`` so the UI can
 *     show "3 walls, 1 ARC, 2 HATCH" even if it only sums the walls.
 */
export function aggregateEntities(entities: DxfEntity[]): GroupAggregate {
  if (entities.length === 0) return { ...EMPTY_AGGREGATE, byType: {} };

  let area = 0;
  let perimeter = 0;
  let length = 0;
  let count = 0;
  const byType: Record<string, number> = {};

  for (const e of entities) {
    byType[e.type] = (byType[e.type] ?? 0) + 1;

    if (e.type === 'LWPOLYLINE' && e.vertices && e.vertices.length >= 2) {
      const closed = !!e.closed;
      if (closed && e.vertices.length >= 3) {
        area += calculateArea(e.vertices);
        perimeter += calculatePerimeter(e.vertices, true);
      } else {
        length += calculatePerimeter(e.vertices, false);
      }
      count++;
    } else if (e.type === 'LINE' && e.start && e.end) {
      length += calculateDistance(e.start, e.end);
      count++;
    } else if (e.type === 'CIRCLE' && e.radius != null) {
      area += Math.PI * e.radius * e.radius;
      count++;
    }
  }

  return {
    area: Math.round(area * 1000) / 1000,
    perimeter: Math.round(perimeter * 1000) / 1000,
    length: Math.round(length * 1000) / 1000,
    count,
    byType,
  };
}
