// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Aggregation helpers for multi-entity DWG selections (RFC 11 §4.5).
 *
 * Single source of truth for Σ area / Σ perimeter / Σ length across a
 * heterogeneous set of entities. Kept pure so the unit tests can exercise
 * every branch without mocking React or the Canvas API.
 */

import type { DxfEntity } from '../api';
import { measureEntity } from './auto-quantify';

export interface GroupAggregate {
  /** Σ area over closed polylines, circles, ellipses and hatches (m²). */
  area: number;
  /** Σ perimeter over closed polylines (m). */
  perimeter: number;
  /** Σ length over LINEs, open polylines and arcs (m). */
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
 * Per-entity rules are {@link measureEntity}, shared with the per-layer
 * auto-quantify so a selection, the Summary totals and the exports count
 * the same geometry: closed polylines give area and perimeter, open
 * polylines, lines and arcs give length, circles, ellipses and hatches give
 * area. TEXT / INSERT / POINT are only counted in ``byType``.
 *
 * ``scale`` is the effective scale (drawing-scale ratio × unit-factor, e.g.
 * ``0.001`` for a millimetre drawing) that converts raw DXF units to real
 * metres. Linear sums are multiplied by ``scale`` and areal sums by
 * ``scale²`` so the totals match the per-measurement labels the canvas
 * renders. Defaults to ``1`` (raw units) so callers and tests that don't
 * care about real-world units are unaffected.
 */
export function aggregateEntities(entities: DxfEntity[], scale = 1): GroupAggregate {
  if (entities.length === 0) return { ...EMPTY_AGGREGATE, byType: {} };

  let area = 0;
  let perimeter = 0;
  let length = 0;
  let count = 0;
  const byType: Record<string, number> = {};

  for (const e of entities) {
    byType[e.type] = (byType[e.type] ?? 0) + 1;
    const m = measureEntity(e);
    if (!m.measured) continue;
    area += m.area;
    perimeter += m.perimeter;
    length += m.length;
    count++;
  }

  const areaScale = scale * scale;
  return {
    area: Math.round(area * areaScale * 1000) / 1000,
    perimeter: Math.round(perimeter * scale * 1000) / 1000,
    length: Math.round(length * scale * 1000) / 1000,
    count,
    byType,
  };
}
