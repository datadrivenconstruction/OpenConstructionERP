// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Wall area from a linear takeoff measurement: length x height, openings
 * deducted (width x height x count), then wastage and the typical multiplier,
 * with the unit following (m -> m², ft -> ft²).
 *
 * The first block runs the case table the backend fold
 * (`effective_takeoff_quantity`) runs too, so the figure the ledger shows and
 * the figure the server writes into a new bill position cannot drift. The
 * rest pins the consumers: ledger subtotals and grand totals, exports, the
 * canvas label, the panel's input helpers and the create-position form.
 */
import { describe, it, expect } from 'vitest';
import cases from './fixtures/wall-quantity-cases.json';
import {
  effectiveQuantity,
  effectiveUnit,
  hasQuantityFactor,
  isWallMeasurement,
  openingsExceedGross,
  reportedMagnitude,
  reportingType,
  wallGrossArea,
  wallNetArea,
  wallOpeningsArea,
  wallOpeningsCount,
} from '@/features/takeoff/lib/takeoff-quantity';
import type { Measurement, WallOpening } from '@/features/takeoff/lib/takeoff-types';
import { groupSubtotals, ledgerToCsv, sortMeasurements, typeGrandTotals } from '@/features/takeoff/lib/takeoff-ledger';
import { computeGroupSummaries } from '@/features/takeoff/lib/takeoff-groups';
import { measurementLabel } from '@/features/takeoff/lib/takeoff-display-units';
import {
  addOpening,
  lengthToInput,
  openingsForStore,
  parseCountInput,
  parseLengthInput,
  removeOpening,
  updateOpening,
  wallBreakdown,
} from '@/features/takeoff/lib/takeoff-wall';
import {
  defaultSectionId,
  positionQuantityFor,
  positionUnitFor,
  sectionOptions,
} from '@/features/takeoff/lib/takeoff-create-position';

function mk(partial: Partial<Measurement>): Measurement {
  return {
    id: 'm1',
    type: 'distance',
    points: [],
    value: 12.5,
    unit: 'm',
    label: '',
    annotation: '',
    page: 1,
    group: 'Walls',
    ...partial,
  };
}

/** Build a frontend measurement from a stored-row case (metadata keys). */
function fromCase(c: (typeof cases.cases)[number]): Measurement {
  const meta = c.metadata as Record<string, unknown>;
  const glyph = (u: string) => (u === 'm2' ? 'm²' : u === 'm3' ? 'm³' : u);
  return mk({
    type: c.type as Measurement['type'],
    value: c.value,
    unit: glyph(c.unit),
    wallHeight: meta.wall_height as number | undefined,
    openings: meta.openings as WallOpening[] | undefined,
    slopeFactor: meta.slope_factor as number | undefined,
    wastagePct: meta.wastage_pct as number | undefined,
    multiplier: meta.multiplier as number | undefined,
  });
}

const canonical = (u: string) => u.replace('²', '2').replace('³', '3');

describe('reported quantity: shared case table with the backend fold', () => {
  for (const c of cases.cases) {
    it(c.name, () => {
      const m = fromCase(c);
      expect(effectiveQuantity(m)).toBeCloseTo(c.expected_value, 4);
      expect(canonical(effectiveUnit(m))).toBe(c.expected_unit);
    });
  }
});

describe('wall area helpers', () => {
  const wall = mk({
    wallHeight: 2.8,
    openings: [
      { width: 0.9, height: 2.1, count: 1 },
      { width: 1.2, height: 1.5, count: 3 },
    ],
  });

  it('splits gross, openings and net', () => {
    expect(isWallMeasurement(wall)).toBe(true);
    expect(wallGrossArea(wall)).toBeCloseTo(35, 6);
    expect(wallOpeningsArea(wall)).toBeCloseTo(7.29, 6);
    expect(wallOpeningsCount(wall)).toBe(4);
    expect(wallNetArea(wall)).toBeCloseTo(27.71, 6);
  });

  it('a wall reports area and is never pushed raw', () => {
    expect(reportingType(wall)).toBe('area');
    expect(effectiveUnit(wall)).toBe('m²');
    // The server push copies the raw metres; the link flow must not push.
    expect(hasQuantityFactor(wall)).toBe(true);
  });

  it('keeps legacy rows byte-identical', () => {
    const line = mk({});
    expect(isWallMeasurement(line)).toBe(false);
    expect(effectiveQuantity(line)).toBe(12.5);
    expect(effectiveUnit(line)).toBe('m');
    expect(reportingType(line)).toBe('distance');
    expect(hasQuantityFactor(line)).toBe(false);
    const area = mk({ type: 'area', value: 20, unit: 'm²' });
    expect(effectiveQuantity(area)).toBe(20);
    expect(effectiveUnit(area)).toBe('m²');
  });

  it('flags openings larger than the wall instead of hiding them', () => {
    const over = mk({ value: 2, wallHeight: 2.5, openings: [{ width: 2, height: 2, count: 2 }] });
    expect(effectiveQuantity(over)).toBe(0);
    expect(reportedMagnitude(over)).toBe(0);
    expect(openingsExceedGross(over)).toBe(true);
    expect(openingsExceedGross(wall)).toBe(false);
  });
});

describe('ledger, legend and exports carry the wall area', () => {
  const wall = mk({ id: 'w', wallHeight: 2.5, value: 10 });
  const line = mk({ id: 'l', value: 4 });
  const floor = mk({ id: 'f', type: 'area', value: 30, unit: 'm²', group: 'Floors' });

  it('subtotals key a wall by m², never into the metres', () => {
    const [walls] = groupSubtotals([wall, line]);
    expect(walls!.totals['m²']).toBeCloseTo(25, 6);
    expect(walls!.totals['m']).toBeCloseTo(4, 6);
  });

  it('grand totals sum a wall with the areas', () => {
    const totals = typeGrandTotals([wall, line, floor]);
    const area = totals.find((g) => g.type === 'area')!;
    const distance = totals.find((g) => g.type === 'distance')!;
    expect(area.total).toBeCloseTo(55, 6);
    expect(area.unit).toBe('m²');
    expect(distance.total).toBeCloseTo(4, 6);
  });

  it('the legend reads the wall group in m²', () => {
    const [summary] = computeGroupSummaries([wall], {}, '#000');
    expect(summary!.unit).toBe('m²');
    expect(summary!.total).toBeCloseTo(25, 6);
  });

  it('the CSV row states the area, in ft² for an imperial reader', () => {
    const metric = ledgerToCsv([wall]);
    expect(metric).toContain('"distance (wall)"');
    expect(metric).toContain('25.00,"m²"');
    const imperial = ledgerToCsv([wall], 'imperial');
    // 25 m² = 269.1 ft²
    expect(imperial).toMatch(/269\.1,"ft²"/);
  });

  it('sorts by the figure the column shows', () => {
    const sorted = sortMeasurements([wall, line], 'value', 'asc');
    expect(sorted.map((m) => m.id)).toEqual(['l', 'w']);
  });

  it('the canvas label shows the sum and the net figure', () => {
    const scale = { pixelsPerUnit: 100, unitLabel: 'm' };
    const plain = measurementLabel(mk({ value: 10, wallHeight: 2.5 }), scale, 'metric');
    expect(plain).toContain('×');
    expect(plain).toContain('m²');
    expect(plain).not.toContain('→');
    const net = measurementLabel(
      mk({ value: 10, wallHeight: 2.5, openings: [{ width: 1, height: 2, count: 1 }] }),
      scale,
      'metric',
    );
    expect(net).toContain('→');
  });
});

describe('wall panel input helpers', () => {
  it('parses metres, a decimal comma and decimal feet', () => {
    expect(parseLengthInput('2.8', 'metric')).toBe(2.8);
    expect(parseLengthInput(' 2,8 ', 'metric')).toBe(2.8);
    expect(parseLengthInput('9', 'imperial')).toBeCloseTo(2.7432, 6);
    expect(parseLengthInput('', 'metric')).toBeNull();
    expect(parseLengthInput('abc', 'metric')).toBeNull();
    expect(parseLengthInput('0', 'metric')).toBeNull();
    expect(parseLengthInput('-1', 'metric')).toBeNull();
  });

  it('renders a stored height back in the reader system without float noise', () => {
    expect(lengthToInput(2.8, 'metric')).toBe('2.8');
    expect(lengthToInput(parseLengthInput('9', 'imperial'), 'imperial')).toBe('9');
    expect(lengthToInput(undefined, 'metric')).toBe('');
  });

  it('parses whole opening counts', () => {
    expect(parseCountInput('3')).toBe(3);
    expect(parseCountInput('2.9')).toBe(2);
    expect(parseCountInput('0')).toBeNull();
    expect(parseCountInput('x')).toBeNull();
  });

  it('adds, edits and removes openings, and stores an empty list as nothing', () => {
    let list = addOpening(undefined, { width: 0.9, height: 2.1, count: 1 });
    list = addOpening(list, { width: 1.2, height: 1.5, count: 3 });
    expect(list).toHaveLength(2);
    list = updateOpening(list, 0, { count: 2 });
    expect(list[0]).toEqual({ width: 0.9, height: 2.1, count: 2 });
    list = removeOpening(list, 1);
    expect(list).toHaveLength(1);
    expect(openingsForStore(removeOpening(list, 0))).toBeUndefined();
  });

  it('imperial: ft x ft = ft², converted from the stored metres', () => {
    // 10 ft x 8 ft wall, stored in metres.
    const m = mk({ value: 3.048, wallHeight: parseLengthInput('8', 'imperial')! });
    const b = wallBreakdown(m, 'imperial');
    expect(b.length).toBeCloseTo(10, 3);
    expect(b.height).toBeCloseTo(8, 3);
    expect(b.gross).toBeCloseTo(80, 1);
    expect(b.areaUnit).toBe('ft²');
    expect(b.lengthUnit).toBe('ft');
  });

  it('metric breakdown carries wastage in the reported figure only', () => {
    const m = mk({ value: 10, wallHeight: 2.5, wastagePct: 10 });
    const b = wallBreakdown(m, 'metric');
    expect(b.gross).toBeCloseTo(25, 6);
    expect(b.reported).toBeCloseTo(27.5, 6);
    expect(b.areaUnit).toBe('m²');
  });
});

describe('create position form', () => {
  const positions = [
    { id: 's1', ordinal: '01', description: 'Shell', unit: '', sort_order: 1 },
    { id: 'p1', ordinal: '01.10', description: 'Concrete', unit: 'm3', parent_id: 's1', sort_order: 2 },
    { id: 's2', ordinal: '02', description: 'Drywall', unit: '', sort_order: 3 },
  ];

  it('lists sections and defaults to the last one, like the BOQ editor', () => {
    expect(sectionOptions(positions)).toEqual([
      { id: 's1', label: '01 Shell' },
      { id: 's2', label: '02 Drywall' },
    ]);
    expect(defaultSectionId(positions)).toBe('s2');
    expect(defaultSectionId([])).toBe('');
  });

  it('states a wall position in m2 (metric) or ft2 (imperial) with the reported quantity', () => {
    const wall = mk({ value: 10, wallHeight: 2.5, openings: [{ width: 1, height: 2, count: 1 }] });
    expect(positionUnitFor(wall, 'metric')).toBe('m2');
    expect(positionQuantityFor(wall, 'metric')).toBe(23);
    expect(positionUnitFor(wall, 'imperial')).toBe('ft2');
    expect(positionQuantityFor(wall, 'imperial')).toBeCloseTo(23 * 10.7639, 3);
    // A plain count stays in pcs in either system.
    const count = mk({ type: 'count', value: 4, unit: 'pcs' });
    expect(positionUnitFor(count, 'imperial')).toBe('pcs');
    expect(positionQuantityFor(count, 'imperial')).toBe(4);
  });
});
