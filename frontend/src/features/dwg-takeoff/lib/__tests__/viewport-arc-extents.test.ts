import { describe, it, expect } from 'vitest';
import { computeExtents, ellipseSweep, isImplausibleSpan } from '../viewport';
import { measureEntity } from '../auto-quantify';
import type { DxfEntity } from '../../api';

describe('computeExtents with arcs', () => {
  it('frames a flat arc by its curve, not by its far-away centre', () => {
    // Radius 50 km, sweep 0.002 rad: a 100 m curve near the origin.
    const r = 50000;
    const arc: DxfEntity = {
      id: 'flat',
      type: 'ARC',
      layer: '0',
      color: 7,
      start: { x: 0, y: -r },
      radius: r,
      start_angle: Math.PI / 2 - 0.001,
      end_angle: Math.PI / 2 + 0.001,
    };
    const ext = computeExtents([arc]);
    expect(ext.maxX - ext.minX).toBeLessThan(101);
    expect(ext.maxY).toBeCloseTo(0, 3);
    expect(ext.minY).toBeGreaterThan(-1);
  });

  it('includes the axis extremes an arc sweeps through', () => {
    const arc: DxfEntity = {
      id: 'half',
      type: 'ARC',
      layer: '0',
      color: 7,
      start: { x: 0, y: 0 },
      radius: 10,
      start_angle: 0,
      end_angle: Math.PI,
    };
    const ext = computeExtents([arc]);
    expect(ext.maxY).toBeCloseTo(10);
    expect(ext.minY).toBeCloseTo(0);
    expect(ext.minX).toBeCloseTo(-10);
    expect(ext.maxX).toBeCloseTo(10);
  });
});

describe('isImplausibleSpan', () => {
  it('flags a plan that is centimetres or continents across', () => {
    // 03_electrical: extents 2.8..145 units declared as mm = 0.14 m.
    expect(isImplausibleSpan({ w: 0.142, h: 0.1 })).toBe(true);
    expect(isImplausibleSpan({ w: 250_000, h: 10 })).toBe(true);
    expect(isImplausibleSpan({ w: 42, h: 18 })).toBe(false);
  });
});

describe('elliptical arcs', () => {
  // A quarter of a 600 x 500 ellipse, as a door swing in a furniture block is stored.
  const swing: DxfEntity = {
    id: 'swing',
    type: 'ELLIPSE',
    layer: '0',
    color: 7,
    start: { x: 0, y: 0 },
    major_radius: 600,
    minor_radius: 500,
    rotation: 0,
    start_angle: 0,
    end_angle: Math.PI / 2,
  };

  it('frames the arc, not the whole ellipse', () => {
    const ext = computeExtents([swing]);
    expect(ext.minX).toBeCloseTo(0, 3);
    expect(ext.minY).toBeCloseTo(0, 3);
    expect(ext.maxX).toBeCloseTo(600, 3);
    expect(ext.maxY).toBeCloseTo(500, 3);
  });

  it('treats equal start and end as the whole ellipse', () => {
    expect(ellipseSweep({ start_angle: 0, end_angle: 0 }).sweep).toBeCloseTo(Math.PI * 2);
    expect(ellipseSweep({}).sweep).toBeCloseTo(Math.PI * 2);
    expect(ellipseSweep(swing).sweep).toBeCloseTo(Math.PI / 2);
  });

  it('encloses no area when it is only an arc', () => {
    expect(measureEntity(swing).area ?? 0).toBe(0);
    expect(measureEntity({ ...swing, end_angle: 0 }).area).toBeCloseTo(Math.PI * 600 * 500);
  });
});
