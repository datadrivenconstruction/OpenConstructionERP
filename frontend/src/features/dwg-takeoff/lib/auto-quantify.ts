// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Per-layer auto-quantification for DWG takeoff.
 *
 * DWG's edge over PDF is that the drawing is exact vector geometry, not
 * pixels: every wall, slab and pipe already carries its true length and
 * area. This helper rolls those up per layer so an estimator gets a full
 * quantity takeoff with zero manual tracing - the headline "auto-quantify"
 * feature.
 *
 * It is deliberately broader than {@link aggregateEntities}: it also measures
 * ARC (arc length), ELLIPSE (area) and HATCH (filled area) entities, and it
 * picks a single headline measure per layer (area > length > count) so the
 * UI can show one clean quantity per layer with the right unit.
 *
 * Pure (no React / Canvas) so the unit tests can exercise every branch and
 * both the Summary panel and any export can reuse it.
 */

import type { DxfEntity } from '../api';
import { calculateArea, calculateDistance, calculatePerimeter } from './measurement';
import { ellipseSweep } from './viewport';

export type QuantifyMeasure = 'area' | 'length' | 'count';

export interface LayerQuantity {
  layer: string;
  /** Σ area (m²) from closed polylines, circles, ellipses and hatches. */
  area: number;
  /** Σ length (m) from lines, open polylines and arcs. */
  length: number;
  /** Σ perimeter (m) of closed polylines. Not part of ``length``. */
  perimeter: number;
  /** Number of entities on the layer (every type is counted). */
  count: number;
  /** The measure auto-selected as the headline quantity for this layer. */
  primary: QuantifyMeasure;
  /** Headline quantity = the value of ``primary``. */
  quantity: number;
  /** Unit label matching ``primary``: ``m²`` / ``m`` / ``nr``. */
  unit: string;
  /** Measures that have a meaningful (non-zero) value, in display order.
   *  ``count`` is always present; ``area`` / ``length`` only when > 0. Drives
   *  the per-layer measure toggle so the user can override the headline. */
  available: QuantifyMeasure[];
}

const TAU = Math.PI * 2;
const EPS = 1e-9;

/** Sweep angle of an arc in radians, normalised to (0, 2π]. */
function arcSweep(start = 0, end = 0): number {
  let s = end - start;
  while (s <= 0) s += TAU;
  while (s > TAU + EPS) s -= TAU;
  return s;
}

/** Major / minor radii of an ellipse, from either the explicit radii or the
 *  ezdxf ``major_axis`` vector + ``ratio`` representation. */
function ellipseRadii(e: DxfEntity): { a: number; b: number } | null {
  if (e.major_radius != null && e.minor_radius != null) {
    return { a: e.major_radius, b: e.minor_radius };
  }
  if (e.major_axis && e.ratio != null) {
    const a = Math.hypot(e.major_axis.x, e.major_axis.y);
    return { a, b: a * e.ratio };
  }
  return null;
}

/** Unit label for a measure. ``nr`` (number) is the construction-standard
 *  count unit, matching the Count tool's markers. */
export function unitForMeasure(measure: QuantifyMeasure): string {
  return measure === 'area' ? 'm²' : measure === 'length' ? 'm' : 'nr';
}

/** Headline measure: area wins (slabs, walls-as-faces), then length (runs of
 *  pipe / linear elements), else a plain count (symbols, blocks, text). */
function pickPrimary(area: number, length: number): QuantifyMeasure {
  if (area > EPS) return 'area';
  if (length > EPS) return 'length';
  return 'count';
}

/** Raw-unit measures of one entity. ``measured`` is false for entities that
 *  carry no quantity (TEXT, INSERT, POINT ...). */
export interface EntityMeasure {
  area: number;
  length: number;
  perimeter: number;
  measured: boolean;
}

/**
 * The one per-entity measuring rule. The per-layer auto-quantify, the
 * selection aggregate and therefore every Summary total and export go
 * through it, so no two of them can count a different set of entities.
 */
export function measureEntity(e: DxfEntity): EntityMeasure {
  const m: EntityMeasure = { area: 0, length: 0, perimeter: 0, measured: false };
  switch (e.type) {
    case 'LWPOLYLINE':
      if (e.vertices && e.vertices.length >= 2) {
        if (e.closed && e.vertices.length >= 3) {
          m.area = calculateArea(e.vertices);
          m.perimeter = calculatePerimeter(e.vertices, true);
        } else {
          m.length = calculatePerimeter(e.vertices, false);
        }
        m.measured = true;
      }
      break;
    case 'HATCH':
      // A hatch is a filled region - areal even when ``closed`` is unset.
      if (e.vertices && e.vertices.length >= 3) {
        m.area = calculateArea(e.vertices);
        m.measured = true;
      }
      break;
    case 'LINE':
      if (e.start && e.end) {
        m.length = calculateDistance(e.start, e.end);
        m.measured = true;
      }
      break;
    case 'CIRCLE':
      if (e.radius != null) {
        m.area = Math.PI * e.radius * e.radius;
        m.measured = true;
      }
      break;
    case 'ARC':
      if (e.radius != null) {
        m.length = e.radius * arcSweep(e.start_angle, e.end_angle);
        m.measured = true;
      }
      break;
    case 'ELLIPSE': {
      const r = ellipseRadii(e);
      // An elliptical arc (a door swing) is an open curve and encloses nothing.
      if (r && ellipseSweep(e).sweep >= Math.PI * 2) {
        m.area = Math.PI * r.a * r.b;
        m.measured = true;
      }
      break;
    }
    // INSERT / TEXT / POINT contribute to ``count`` only.
    default:
      break;
  }
  return m;
}

/**
 * Roll every entity up by layer into area / length / count, then pick the
 * headline measure per layer.
 *
 * ``scale`` converts raw DXF units to metres: linear sums are multiplied by
 * ``scale`` and areal sums by ``scale²`` so the numbers match the per-entity
 * labels the canvas renders. Defaults to ``1`` (raw units).
 */
export function quantifyByLayer(entities: DxfEntity[], scale = 1): LayerQuantity[] {
  const buckets = new Map<string, { area: number; length: number; perimeter: number; count: number }>();
  for (const e of entities) {
    const layer = e.layer || '0';
    let b = buckets.get(layer);
    if (!b) {
      b = { area: 0, length: 0, perimeter: 0, count: 0 };
      buckets.set(layer, b);
    }
    b.count++;
    const m = measureEntity(e);
    b.area += m.area;
    b.length += m.length;
    b.perimeter += m.perimeter;
  }

  const areaScale = scale * scale;
  const round = (n: number) => Math.round(n * 1000) / 1000;
  const measureRank: Record<QuantifyMeasure, number> = { area: 0, length: 1, count: 2 };

  return Array.from(buckets.entries())
    .map(([layer, v]) => {
      const area = round(v.area * areaScale);
      const length = round(v.length * scale);
      const perimeter = round(v.perimeter * scale);
      const count = v.count;
      const primary = pickPrimary(area, length);
      const available: QuantifyMeasure[] = [];
      if (area > EPS) available.push('area');
      if (length > EPS) available.push('length');
      available.push('count');
      const quantity = primary === 'area' ? area : primary === 'length' ? length : count;
      return {
        layer,
        area,
        length,
        perimeter,
        count,
        primary,
        quantity,
        unit: unitForMeasure(primary),
        available,
      };
    })
    .sort((a, b) => {
      // Areal layers first (the usual headline trades), then by quantity desc
      // so the biggest contributor in each band lands on top.
      if (a.primary !== b.primary) return measureRank[a.primary] - measureRank[b.primary];
      return b.quantity - a.quantity;
    });
}

/** Quantity for a layer under an explicit measure (used when the user
 *  overrides the auto-selected headline measure in the UI). */
export function quantityFor(row: LayerQuantity, measure: QuantifyMeasure): number {
  return measure === 'area' ? row.area : measure === 'length' ? row.length : row.count;
}
