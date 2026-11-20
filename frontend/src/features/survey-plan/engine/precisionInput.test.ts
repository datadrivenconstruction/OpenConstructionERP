// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import type { GridXY, PrecisionContext, PrecisionResult } from '../types';
import { DEFAULT_CONVENTIONS, type PlanConventions } from '../units/conventions';
import { emptyFields, fieldOrder, nextMode, parsePrecision } from './precisionInput';

const register: Record<string, GridXY> = { T1: [1000, 2000], T2: [1000, 2100] };
const ctx = (over: Partial<PlanConventions> = {}, extra: Partial<PrecisionContext> = {}): PrecisionContext => ({
  conventions: { ...DEFAULT_CONVENTIONS, ...over },
  last: [1000, 2000],
  lookup: (id) => register[id] ?? null,
  csf: null,
  ...extra,
});
const at = (r: PrecisionResult): GridXY => {
  if (!r.ok) throw new Error(`${r.field}: ${r.defaultError}`);
  return r.point;
};
const near = (p: GridXY, e: number, n: number) => {
  expect(p[0]).toBeCloseTo(e, 6);
  expect(p[1]).toBeCloseTo(n, 6);
};

describe('bearing + distance', () => {
  it.each([
    ['dms', '45 00 00', 'N 45 E'],
    ['deg', '45', 'N45E'],
    ['gon', '50', 'N 50 E'],
  ] as const)('%s', (unit, azimuth, quadrant) => {
    const s = Math.SQRT1_2 * 25;
    near(at(parsePrecision({ mode: 'brg_dist', bearing: azimuth, distance: '25' }, ctx({ angleUnit: unit }))), 1000 + s, 2000 + s);
    near(at(parsePrecision({ mode: 'brg_dist', bearing: quadrant, distance: '25' }, ctx({ angleUnit: unit }))), 1000 + s, 2000 + s);
  });

  it('reads azimuths from south when the project counts from south', () => {
    near(at(parsePrecision({ mode: 'brg_dist', bearing: '180', distance: '10' }, ctx({ angleUnit: 'deg', azimuthZero: 'south' }))), 1000, 2010);
  });

  it('converts a typed ground distance to grid by the CSF', () => {
    const p = at(parsePrecision({ mode: 'brg_dist', bearing: '90', distance: '100' }, ctx({ angleUnit: 'deg', distanceInput: 'ground' }, { csf: 0.9996 })));
    near(p, 1099.96, 2000);
  });

  it('takes feet when the project is in US survey feet', () => {
    near(at(parsePrecision({ mode: 'brg_dist', bearing: '0', distance: '100' }, ctx({ angleUnit: 'deg', linearUnit: 'ftUS' }))), 1000, 2000 + 100 * (1200 / 3937));
  });

  it('names the wrong field', () => {
    expect(parsePrecision({ mode: 'brg_dist', bearing: 'x', distance: '1' }, ctx())).toMatchObject({ ok: false, field: 'bearing' });
    expect(parsePrecision({ mode: 'brg_dist', bearing: '10', distance: '-1' }, ctx())).toMatchObject({ ok: false, field: 'distance' });
    expect(parsePrecision({ mode: 'brg_dist', bearing: '10', distance: '1' }, ctx({}, { last: null }))).toMatchObject({ ok: false, errorKey: 'plan.input.needs_start' });
  });
});

describe('dE/dN', () => {
  it('offsets in display order', () => {
    near(at(parsePrecision({ mode: 'delta', first: '3', second: '-4' }, ctx())), 1003, 1996);
    // Geodetic axes: first is dX (north).
    near(at(parsePrecision({ mode: 'delta', first: '3', second: '-4' }, ctx({ axis: 'XY' }))), 996, 2003);
  });
});

describe('E/N absolute', () => {
  it('with and without Z, in the axis order', () => {
    expect(parsePrecision({ mode: 'abs', first: '389012.345', second: '5819004.21', z: '' }, ctx())).toEqual({ ok: true, point: [389012.345, 5819004.21] });
    expect(parsePrecision({ mode: 'abs', first: '5819004.21', second: '389012.345', z: '35.2' }, ctx({ axis: 'XY' }))).toEqual({
      ok: true,
      point: [389012.345, 5819004.21],
      z: 35.2,
    });
    expect(parsePrecision({ mode: 'abs', first: '1', second: 'n', z: '' }, ctx())).toMatchObject({ ok: false, field: 'second' });
  });
});

describe('polar from a station', () => {
  it.each([
    ['dms', '90 00 00'],
    ['deg', '90'],
    ['gon', '100'],
  ] as const)('angle turned from the backsight in %s', (unit, angle) => {
    // Station T1, backsight T2 due north; 90 deg clockwise is due east.
    near(at(parsePrecision({ mode: 'polar', station: 'T1', backsight: 'T2', angle, distance: '50' }, ctx({ angleUnit: unit }))), 1050, 2000);
  });

  it('unknown point ids name their field', () => {
    expect(parsePrecision({ mode: 'polar', station: 'X9', backsight: 'T2', angle: '1', distance: '1' }, ctx())).toMatchObject({ ok: false, field: 'station' });
    expect(parsePrecision({ mode: 'polar', station: 'T1', backsight: 'X9', angle: '1', distance: '1' }, ctx())).toMatchObject({ ok: false, field: 'backsight' });
  });
});

describe('modes', () => {
  it('cycle and list fields in Tab order', () => {
    expect(nextMode('brg_dist')).toBe('delta');
    expect(nextMode('polar')).toBe('brg_dist');
    expect(fieldOrder('polar')).toEqual(['station', 'backsight', 'angle', 'distance']);
    expect(emptyFields('abs')).toEqual({ mode: 'abs', first: '', second: '', z: '' });
  });
});
