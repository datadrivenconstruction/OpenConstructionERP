/**
 * Unit tests for Shift-to-lock ortho/angle math (Q1 UX #3).
 */

import { describe, it, expect } from 'vitest';
import { snapToOrthoAngle, snapAngleDegrees } from '../ortho';

describe('snapToOrthoAngle', () => {
  const anchor = { x: 10, y: 10 };

  it('snaps to 0° (due east) when cursor is roughly horizontal', () => {
    const p = snapToOrthoAngle(anchor, { x: 30, y: 11 });
    // On a pure east ray y collapses to anchor.y exactly.
    expect(p.y).toBeCloseTo(10, 6);
    // x ends up at anchor.x + raw Euclidean distance.
    const expectedDist = Math.hypot(30 - 10, 11 - 10);
    expect(p.x - anchor.x).toBeCloseTo(expectedDist, 6);
  });

  it('snaps to 90° (due north) when cursor is roughly vertical', () => {
    const p = snapToOrthoAngle(anchor, { x: 11, y: 40 });
    // On the 90° ray x collapses to anchor.x exactly.
    expect(p.x).toBeCloseTo(10, 6);
    const expectedDist = Math.hypot(11 - 10, 40 - 10);
    expect(p.y - anchor.y).toBeCloseTo(expectedDist, 6);
  });

  it('snaps to 180° (due west)', () => {
    const p = snapToOrthoAngle(anchor, { x: -30, y: 9 });
    expect(p.y).toBeCloseTo(10, 6);
    const expectedDist = Math.hypot(-30 - 10, 9 - 10);
    // On the west ray the x-offset from anchor is NEGATIVE distance.
    expect(p.x - anchor.x).toBeCloseTo(-expectedDist, 6);
  });

  it('snaps to 45° diagonal', () => {
    // Cursor at (20, 19) — roughly along +45°. Distance = ~sqrt(100+81).
    const p = snapToOrthoAngle(anchor, { x: 20, y: 19 });
    // On a 45° ray the offset from anchor in x === offset in y.
    const dx = p.x - anchor.x;
    const dy = p.y - anchor.y;
    expect(Math.abs(dx - dy)).toBeLessThan(1e-6);
    // Distance from anchor is preserved.
    const origDist = Math.hypot(20 - 10, 19 - 10);
    expect(Math.hypot(dx, dy)).toBeCloseTo(origDist, 6);
  });

  it('snaps to 135° (upper-left diagonal)', () => {
    const p = snapToOrthoAngle(anchor, { x: -10, y: 31 });
    const dx = p.x - anchor.x;
    const dy = p.y - anchor.y;
    // 135° ray: -dx == dy (both components reflect across the diagonal).
    expect(dx + dy).toBeCloseTo(0, 6);
    // But actually 135° means dx<0, dy>0 of equal magnitude
    expect(dx).toBeLessThan(0);
    expect(dy).toBeGreaterThan(0);
  });

  it('returns anchor unchanged when cursor === anchor (zero-length)', () => {
    const p = snapToOrthoAngle(anchor, { x: 10, y: 10 });
    expect(p).toEqual({ x: 10, y: 10 });
  });

  it('preserves Euclidean distance from anchor', () => {
    const cursor = { x: 50, y: 37 };
    const raw = Math.hypot(cursor.x - anchor.x, cursor.y - anchor.y);
    const snapped = snapToOrthoAngle(anchor, cursor);
    const snappedDist = Math.hypot(snapped.x - anchor.x, snapped.y - anchor.y);
    expect(snappedDist).toBeCloseTo(raw, 6);
  });
});

describe('snapAngleDegrees', () => {
  const anchor = { x: 0, y: 0 };

  it('returns 0 for east cursor', () => {
    expect(snapAngleDegrees(anchor, { x: 10, y: 0 })).toBe(0);
  });

  it('returns 90 for north cursor', () => {
    expect(snapAngleDegrees(anchor, { x: 0, y: 10 })).toBe(90);
  });

  it('returns 45 for NE cursor near the diagonal', () => {
    expect(snapAngleDegrees(anchor, { x: 10, y: 9 })).toBe(45);
  });

  it('quantizes any offset to the nearest 45° step', () => {
    // 20° should quantize down to 0° (nearer than 45°).
    const pt = { x: Math.cos((20 * Math.PI) / 180), y: Math.sin((20 * Math.PI) / 180) };
    expect(snapAngleDegrees(anchor, pt)).toBe(0);
    // 30° should snap to 45° (30 is nearer to 45 than 0 when the step is 45°? no — 30-0=30 vs 45-30=15, so 45 wins).
    const pt2 = { x: Math.cos((30 * Math.PI) / 180), y: Math.sin((30 * Math.PI) / 180) };
    expect(snapAngleDegrees(anchor, pt2)).toBe(45);
  });
});
