// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import type { PlanFeature, SnapKind, SnapSettings } from '../types';
import { buildIndex, SpatialIndex } from './spatialIndex';
import { defaultSnapSettings, setMode, snap, toggleAll } from './snap';

const line = (id: string, coords: [number, number][], label?: string): PlanFeature => ({
  id,
  layer: 'sketch',
  geometry: { type: 'LineString', coordinates: coords },
  properties: label ? { label } : {},
});
const point = (id: string, e: number, n: number, label: string): PlanFeature => ({
  id,
  layer: 'points',
  geometry: { type: 'Point', coordinates: [e, n] },
  properties: { label },
});

// A horizontal line 0..10 at N=0, a vertical line E=5 from N=-5..5, and point CP2 at (20, 0).
const features = [line('h', [[0, 0], [10, 0]]), line('v', [[5, -5], [5, 5]]), point('cp2', 20, 0, 'CP2')];
const index = buildIndex(features, 2);

function only(kind: SnapKind, base: SnapSettings = defaultSnapSettings()): SnapSettings {
  let s = base;
  for (const k of Object.keys(s.modes) as SnapKind[]) s = setMode(s, k, k === kind);
  return s;
}

describe('snap types', () => {
  it('endpoint picks the vertex and names it', () => {
    const r = snap(index, { cursor: [20.3, 0.2], radius: 1, settings: only('endpoint') });
    expect(r).toMatchObject({ kind: 'endpoint', point: [20, 0], targetLabel: 'CP2', featureId: 'cp2' });
  });

  it('midpoint of a segment', () => {
    const r = snap(index, { cursor: [4.6, 0.3], radius: 1, settings: only('midpoint') });
    expect(r?.kind).toBe('midpoint');
    expect(r?.point).toEqual([5, 0]);
  });

  it('intersection of two segments', () => {
    const r = snap(index, { cursor: [5.4, 0.4], radius: 1, settings: only('intersection') });
    expect(r?.kind).toBe('intersection');
    expect(r?.point[0]).toBeCloseTo(5, 9);
    expect(r?.point[1]).toBeCloseTo(0, 9);
  });

  it('perpendicular from the last vertex', () => {
    const r = snap(index, { cursor: [7.2, 0.5], radius: 1, settings: only('perpendicular'), last: [7, 4] });
    expect(r?.kind).toBe('perpendicular');
    expect(r?.point[0]).toBeCloseTo(7, 9);
    expect(r?.point[1]).toBeCloseTo(0, 9);
  });

  it('nearest on segment', () => {
    const r = snap(index, { cursor: [8.3, 0.4], radius: 1, settings: only('nearest') });
    expect(r?.kind).toBe('nearest');
    expect(r?.point[0]).toBeCloseTo(8.3, 9);
    expect(r?.point[1]).toBeCloseTo(0, 9);
  });

  it('grid rounds to the step', () => {
    const s = { ...only('grid'), gridStep: 0.5 };
    expect(snap(index, { cursor: [101.26, 33.74], radius: 1, settings: s })?.point).toEqual([101.5, 33.5]);
  });

  it('nothing outside the radius', () => {
    expect(snap(index, { cursor: [50, 50], radius: 1, settings: defaultSnapSettings() })).toBeNull();
  });

  it('off when disabled (F3) or held Alt', () => {
    const off = toggleAll(defaultSnapSettings());
    expect(snap(index, { cursor: [20.1, 0], radius: 1, settings: off })).toBeNull();
  });
});

describe('snap priority', () => {
  const all = { ...defaultSnapSettings(), modes: { endpoint: true, midpoint: true, intersection: true, perpendicular: true, nearest: true, grid: true } };

  it('endpoint beats a closer nearest', () => {
    const r = snap(index, { cursor: [9.6, 0.05], radius: 1, settings: all });
    expect(r?.kind).toBe('endpoint');
    expect(r?.point).toEqual([10, 0]);
  });

  it('intersection beats midpoint at the same spot', () => {
    // The midpoint of h is (5, 0), which is also where v crosses it.
    const r = snap(index, { cursor: [5.2, 0.2], radius: 1, settings: all });
    expect(r?.kind).toBe('intersection');
  });

  it('midpoint beats perpendicular and nearest', () => {
    const f = [line('a', [[0, 10], [10, 10]])];
    const r = snap(buildIndex(f), { cursor: [5.3, 10.1], radius: 1, settings: all, last: [5.2, 20] });
    expect(r?.kind).toBe('midpoint');
  });

  it('perpendicular beats nearest', () => {
    const f = [line('a', [[0, 10], [10, 10]])];
    const r = snap(buildIndex(f), { cursor: [2.3, 10.1], radius: 1, settings: all, last: [2.2, 20] });
    expect(r?.kind).toBe('perpendicular');
  });

  it('nearest beats grid', () => {
    const f = [line('a', [[0.3, 0.3], [10.3, 0.3]])];
    const r = snap(buildIndex(f), { cursor: [3.3, 0.6], radius: 1, settings: all });
    expect(r?.kind).toBe('nearest');
  });

  it('grid is the last resort', () => {
    expect(snap(index, { cursor: [50.2, 50.2], radius: 1, settings: all })?.kind).toBe('grid');
  });

  it('excludes the feature being edited', () => {
    const r = snap(index, { cursor: [20.1, 0], radius: 1, settings: only('endpoint'), exclude: new Set(['cp2']) });
    expect(r).toBeNull();
  });
});

describe('spatial index', () => {
  it('stays fast and exact at 10k points', () => {
    const pts: PlanFeature[] = [];
    for (let i = 0; i < 10000; i++) pts.push(point(`p${i}`, (i % 100) * 3, Math.floor(i / 100) * 3, `P${i}`));
    const idx = buildIndex(pts, 5);
    const t0 = performance.now();
    let r = null;
    for (let k = 0; k < 1000; k++) r = snap(idx, { cursor: [150.4, 150.3], radius: 1, settings: only('endpoint') });
    expect(performance.now() - t0).toBeLessThan(500);
    expect(r?.targetLabel).toBe('P5050');
  });
});

describe('spatial index far zoomed out', () => {
  it('answers a window of millions of cells without walking them', () => {
    const idx = new SpatialIndex(5);
    idx.addVertex({ p: [100, 100], featureId: 'a', index: 0 });
    idx.addSegment({ a: [0, 0], b: [10, 0], featureId: 'b', index: 0 });
    const t0 = performance.now();
    expect(idx.queryVertices([0, 0], 5e7)).toHaveLength(1);
    expect(idx.querySegments([0, 0], 5e7)).toHaveLength(1);
    expect(idx.queryVertices([1e9, 1e9], 5e7)).toHaveLength(0);
    expect(performance.now() - t0).toBeLessThan(200);
  });
});
