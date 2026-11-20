// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * A uniform grid hash over vertices and segments, so snapping and picking at
 * 10k points stay well under a frame. Built once per feature set; queries are
 * by a square window around the cursor.
 */

import type { GridXY, PlanFeature } from '../types';
import { featureSegments, featureVertices } from './geometry';

export interface IndexedVertex {
  p: GridXY;
  featureId: string;
  /** Vertex number within the feature (rings counted across rings). */
  index: number;
  label?: string;
}

export interface IndexedSegment {
  a: GridXY;
  b: GridXY;
  featureId: string;
  index: number;
  label?: string;
}

export class SpatialIndex {
  readonly cell: number;
  private vertices = new Map<string, IndexedVertex[]>();
  private segments = new Map<string, IndexedSegment[]>();
  readonly size: { vertices: number; segments: number } = { vertices: 0, segments: 0 };

  constructor(cell: number) {
    this.cell = cell > 0 ? cell : 1;
  }

  private key(i: number, j: number): string {
    return `${i}:${j}`;
  }

  private cellOf(p: GridXY): [number, number] {
    return [Math.floor(p[0] / this.cell), Math.floor(p[1] / this.cell)];
  }

  addVertex(v: IndexedVertex): void {
    const [i, j] = this.cellOf(v.p);
    const k = this.key(i, j);
    const list = this.vertices.get(k);
    if (list) list.push(v);
    else this.vertices.set(k, [v]);
    this.size.vertices++;
  }

  addSegment(s: IndexedSegment): void {
    const [i0, j0] = this.cellOf([Math.min(s.a[0], s.b[0]), Math.min(s.a[1], s.b[1])]);
    const [i1, j1] = this.cellOf([Math.max(s.a[0], s.b[0]), Math.max(s.a[1], s.b[1])]);
    // Very long segments would fill thousands of cells; cap and fall back to a scan bucket.
    if ((i1 - i0 + 1) * (j1 - j0 + 1) > 4096) {
      const list = this.segments.get('*');
      if (list) list.push(s);
      else this.segments.set('*', [s]);
    } else {
      for (let i = i0; i <= i1; i++) {
        for (let j = j0; j <= j1; j++) {
          const k = this.key(i, j);
          const list = this.segments.get(k);
          if (list) list.push(s);
          else this.segments.set(k, [s]);
        }
      }
    }
    this.size.segments++;
  }

  addFeature(f: PlanFeature): void {
    const label = typeof f.properties.label === 'string' ? f.properties.label : undefined;
    featureVertices(f).forEach((p, index) => this.addVertex({ p, featureId: f.id, index, label }));
    featureSegments(f).forEach(([a, b], index) => this.addSegment({ a, b, featureId: f.id, index, label }));
  }

  /** Vertices whose cell meets the window [p - r, p + r]. */
  queryVertices(p: GridXY, r: number): IndexedVertex[] {
    const out: IndexedVertex[] = [];
    const [i0, j0] = this.cellOf([p[0] - r, p[1] - r]);
    const [i1, j1] = this.cellOf([p[0] + r, p[1] + r]);
    for (let i = i0; i <= i1; i++) for (let j = j0; j <= j1; j++) out.push(...(this.vertices.get(this.key(i, j)) ?? []));
    return out;
  }

  /** Segments whose cells meet the window, each once. */
  querySegments(p: GridXY, r: number): IndexedSegment[] {
    const seen = new Set<IndexedSegment>();
    const [i0, j0] = this.cellOf([p[0] - r, p[1] - r]);
    const [i1, j1] = this.cellOf([p[0] + r, p[1] + r]);
    for (let i = i0; i <= i1; i++) for (let j = j0; j <= j1; j++) for (const s of this.segments.get(this.key(i, j)) ?? []) seen.add(s);
    for (const s of this.segments.get('*') ?? []) seen.add(s);
    return [...seen];
  }
}

/** Index of the snappable features, with a cell size suited to the extent. */
export function buildIndex(features: Iterable<PlanFeature>, cell = 5): SpatialIndex {
  const idx = new SpatialIndex(cell);
  for (const f of features) idx.addFeature(f);
  return idx;
}
