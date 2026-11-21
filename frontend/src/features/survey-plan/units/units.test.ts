// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
import {
  DEFAULT_CONVENTIONS,
  axisLabelFor,
  columnRole,
  csfMatters,
  formatAngle,
  formatArea,
  formatChainage,
  formatCoordPair,
  formatDirection,
  formatDistance,
  fromDisplayOrder,
  groundToGrid,
  gridToGround,
  parseAngle,
  parseChainage,
  parseCoordPair,
  parseDirection,
  parseDistance,
  resolveConventions,
  toDisplayOrder,
  type PlanConventions,
} from './index';

const conv = (over: Partial<PlanConventions> = {}): PlanConventions => ({ ...DEFAULT_CONVENTIONS, ...over });
const close = (a: number | null, b: number, eps = 1e-9) => {
  expect(a).not.toBeNull();
  expect(Math.abs((a as number) - b)).toBeLessThan(eps);
};

describe('parseAngle', () => {
  it.each([
    ['12°34\'56"', 'dms', 12 + 34 / 60 + 56 / 3600],
    ['12 34 56', 'dms', 12 + 34 / 60 + 56 / 3600],
    ['12-34-56', 'dms', 12 + 34 / 60 + 56 / 3600],
    ['12:34:56.5', 'dms', 12 + 34 / 60 + 56.5 / 3600],
    ['12°30\'', 'dms', 12.5],
    ['12.5', 'dms', 12.5],
    ['12.3456', 'deg', 12.3456],
    ['12,3456', 'deg', 12.3456],
    ['12.3456°', 'gon', 12.3456],
    ['100', 'gon', 90],
    ['12.3456g', 'dms', 12.3456 * 0.9],
    ['12.3456 gon', 'deg', 12.3456 * 0.9],
    ['400gon', 'dms', 360],
    ['-1 30', 'dms', -1.5],
    ['12 34 56', 'gon', 12 + 34 / 60 + 56 / 3600],
  ] as const)('%s in %s', (text, unit, deg) => close(parseAngle(text, unit), deg));

  it.each(['', 'abc', '12 61', '12 30 60', '1 2 3 4', '12.5 30'])('rejects %s', (text) => {
    expect(parseAngle(text, 'dms')).toBeNull();
  });
});

describe('formatAngle', () => {
  it.each([
    [12 + 34 / 60 + 56 / 3600, 'dms', 1, '12°34\'56.0"'],
    [12 + 34 / 60 + 56 / 3600, 'dms', 0, '12°34\'56"'],
    [359.99999999, 'dms', 1, '360°00\'00.0"'],
    [90, 'gon', 1, '100.00000 gon'],
    [12.5, 'deg', 1, '12.500000°'],
    [-1.5, 'dms', 0, '-1°30\'00"'],
  ] as const)('%s as %s', (deg, unit, dec, text) => expect(formatAngle(deg, unit, dec)).toBe(text));

  it('round-trips DMS to the tenth of a second', () => {
    for (const deg of [0, 0.0001, 45.123456, 179.999, 271.5]) close(parseAngle(formatAngle(deg, 'dms', 1), 'dms'), deg, 0.05 / 3600);
  });
});

describe('directions', () => {
  it.each([
    ['N45°30\'E', 45.5],
    ['N 45 30 E', 45.5],
    ['S 45 30 E', 134.5],
    ['S45-30W', 225.5],
    ['N 45 30 W', 314.5],
    ['n10e', 10],
    ['N 0 E', 0],
  ])('quadrant %s', (text, az) => close(parseDirection(text, conv()), az));

  it('reads a bare angle from the zero direction', () => {
    close(parseDirection('10', conv({ angleUnit: 'deg' })), 10);
    close(parseDirection('10', conv({ angleUnit: 'deg', azimuthZero: 'south' })), 190);
    close(parseDirection('100', conv({ angleUnit: 'gon' })), 90);
  });

  it('rejects a quadrant angle over 90', () => {
    expect(parseDirection('N 95 E', conv())).toBeNull();
  });

  it.each([
    [45.5, { directionFormat: 'quadrant' as const }, 'N 45°30\'00.0" E'],
    [225.5, { directionFormat: 'quadrant' as const, angleDecimals: 0 as const }, 'S 45°30\'00" W'],
    [10, { angleUnit: 'deg' as const, azimuthZero: 'south' as const }, '190.000000°'],
    [90, { angleUnit: 'gon' as const }, '100.00000 gon'],
  ])('formats %s', (az, over, text) => expect(formatDirection(az, conv(over))).toBe(text));
});

describe('distances and areas', () => {
  it.each([
    ['25', 'm', 25],
    ['25 m', 'ft', 25],
    ['100', 'ft', 30.48],
    ["100'", 'm', 30.48],
    ['100 US ft', 'm', 100 * (1200 / 3937)],
    ['100', 'ftUS', 100 * (1200 / 3937)],
    ['-2,5', 'm', -2.5],
  ] as const)('parses %s with %s', (text, unit, m) => close(parseDistance(text, { linearUnit: unit }), m, 1e-9));

  it('formats with precision and unit', () => {
    expect(formatDistance(25, conv())).toBe('25.000 m');
    expect(formatDistance(25, conv({ precision: 'cm' }))).toBe('25.00 m');
    expect(formatDistance(30.48, conv({ linearUnit: 'ft', precision: '0.01ft' }))).toBe('100.00 ft');
    expect(formatDistance(1200 / 3937, conv({ linearUnit: 'ftUS', precision: '0.001ft' }))).toBe('1.000 US ft');
  });

  it.each([
    ['m2', 1204.6, '1,204.60 m²'],
    ['ha', 12046, '1.2046 ha'],
    ['acre', 4046.8564224, '1.0000 ac'],
    ['ft2', 9.290304, '100.0 sq ft'],
  ] as const)('area in %s', (unit, m2, text) => expect(formatArea(m2, { areaUnit: unit })).toBe(text));

  it('grid and ground', () => {
    close(groundToGrid(100, 0.9996), 99.96);
    close(gridToGround(99.96, 0.9996), 100);
    expect(csfMatters(1.000005)).toBe(false);
    expect(csfMatters(0.99962)).toBe(true);
    expect(csfMatters(null)).toBe(false);
  });
});

describe('axes', () => {
  it.each([
    ['EN', ['E', 'N'], [1, 2]],
    ['NE', ['N', 'E'], [2, 1]],
    ['XY', ['X', 'Y'], [2, 1]],
    ['YX', ['Y', 'X'], [1, 2]],
  ] as const)('%s orders and labels', (axis, labels, order) => {
    expect(toDisplayOrder(1, 2, axis)).toEqual(order);
    expect(fromDisplayOrder(order[0], order[1], axis)).toEqual([1, 2]);
    expect(formatCoordPair(1, 2, conv({ axis })).startsWith(labels[0])).toBe(true);
  });

  it('names X north under geodetic axes', () => {
    expect(axisLabelFor('XY')).toEqual({ e: 'Y', n: 'X' });
    expect(axisLabelFor('EN')).toEqual({ e: 'E', n: 'N' });
  });

  it('reads typed pairs in display order and unit', () => {
    expect(parseCoordPair('5819004.21 389012.345', conv({ axis: 'XY' }))).toEqual([389012.345, 5819004.21]);
    expect(parseCoordPair('100 200 3', conv({ linearUnit: 'ft' }))).toEqual([30.48, 60.96, 0.9144000000000001]);
    expect(parseCoordPair('1', conv())).toBeNull();
  });

  it.each([
    ['X', 'EN', 'e'],
    ['X', 'XY', 'n'],
    ['Y', 'YX', 'e'],
    ['Y', 'EN', 'n'],
    ['Easting', 'XY', 'e'],
    ['Hochwert', 'EN', 'n'],
    ['H', 'EN', 'z'],
    ['code', 'EN', null],
  ] as const)('column %s under %s', (h, axis, role) => expect(columnRole(h, axis)).toBe(role));
});

describe('chainage', () => {
  it.each([
    [1234.5678, 'metric', '1+234.568'],
    [0, 'metric', '0+000.000'],
    [99.5, 'metric', '0+099.500'],
    [1234.6, 'km', 'km 1.235'],
    [30.48 * 12.5, 'imperial', '12+50.00'],
    [0.3048 * 1234.56, 'imperial', '12+34.56'],
  ] as const)('%s as %s', (m, fmt, text) => expect(formatChainage(m, fmt)).toBe(text));

  it.each([
    ['1+234.568', 'metric', 1234.568],
    ['km 1.235', 'metric', 1235],
    ['1.235', 'km', 1235],
    ['3+70.37', 'imperial', 370.37 * 0.3048],
    ['250', 'metric', 250],
  ] as const)('parses %s (%s)', (text, fmt, m) => close(parseChainage(text, fmt), m, 1e-9));

  it('uses the US survey foot for imperial stations when the project does', () => {
    close(parseChainage('1+00', 'imperial', { linearUnit: 'ftUS' }), 100 * (1200 / 3937));
  });
});

describe('resolveConventions', () => {
  it('layers country, project and user and drops unknown values', () => {
    const c = resolveConventions({ angleUnit: 'gon', axis: 'XY' }, { linearUnit: 'ftUS', axis: 'bogus' }, { angleDecimals: 2 });
    expect(c.angleUnit).toBe('gon');
    expect(c.axis).toBe('XY');
    expect(c.linearUnit).toBe('ftUS');
    expect(c.angleDecimals).toBe(2);
    expect(c.chainage).toBe('metric');
  });
});

describe('formatAngle DMS in a comma locale', () => {
  it('writes the seconds with a decimal comma for de-DE', () => {
    usePreferencesStore.setState({ numberLocale: 'de-DE' });
    try {
      expect(formatAngle(12 + 34 / 60 + 56.5 / 3600, 'dms', 1)).toBe(`12°34'56,5"`);
    } finally {
      usePreferencesStore.setState({ numberLocale: 'auto' });
    }
  });
});
