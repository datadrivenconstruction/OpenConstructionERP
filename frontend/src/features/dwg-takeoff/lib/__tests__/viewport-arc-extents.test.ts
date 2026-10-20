import { describe, it, expect } from 'vitest';
import { computeExtents } from '../viewport';
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
