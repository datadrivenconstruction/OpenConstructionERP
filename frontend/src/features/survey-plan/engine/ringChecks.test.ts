// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import type { PlanFeature } from '../types';
import { boundaryGap, intersectionArea, padFindings, parcelFindings, ringAreaM2, ringValid, selfIntersections, zoneFindings } from './ringChecks';

type Ring = Array<[number, number]>;
const sq = (x: number, y: number, w: number, h = w): Ring => [[x, y], [x + w, y], [x + w, y + h], [x, y + h], [x, y]];
const poly = (id: string, layer: string, ring: Ring, props: Record<string, unknown> = {}): PlanFeature => ({
  id,
  layer,
  geometry: { type: 'Polygon', coordinates: [ring] },
  properties: { ref: id, ...props },
});
const settings = { gapToleranceM: 0.1, areaTolerance: () => 1, idPattern: '' };

describe('ring geometry, mirrored from the server checks', () => {
  it('measures a 10 m square as 100 m² whichever way it winds', () => {
    expect(ringAreaM2(sq(0, 0, 10))).toBeCloseTo(100, 9);
    expect(ringAreaM2([...sq(0, 0, 10)].reverse())).toBeCloseTo(100, 9);
  });

  it('finds the one crossing of a bow tie and calls it invalid (PAR-002)', () => {
    const bow: Ring = [[0, 0], [10, 10], [10, 0], [0, 10], [0, 0]];
    expect(selfIntersections(bow)).toHaveLength(1);
    expect(ringValid(bow)).toBe(false);
    expect(ringValid(sq(0, 0, 10))).toBe(true);
  });

  it('gives 20 m² shared by two 10 m squares 8 m apart (PAR-004)', () => {
    expect(intersectionArea(sq(0, 0, 10), sq(8, 0, 10))).toBeCloseTo(20, 6);
  });

  it('gives a 5 cm gap between squares that do not touch (PAR-005)', () => {
    expect(boundaryGap(sq(0, 0, 10), sq(10.05, 0, 10))).toBeCloseTo(0.05, 9);
    expect(intersectionArea(sq(0, 0, 10), sq(10, 0, 10))).toBeLessThan(0.01);
  });
});

describe('parcelFindings', () => {
  it('reports a bow tie, an overlap and a sliver gap, and nothing for neighbours that share an edge', () => {
    const f = [
      poly('A', 'parcels', sq(0, 0, 10)),
      poly('B', 'parcels', sq(10, 0, 10)),
      poly('C', 'parcels', sq(18, 0, 10)),
      poly('D', 'parcels', sq(0, 10.05, 9)),
      poly('E', 'parcels', [[50, 0], [60, 10], [60, 0], [50, 10], [50, 0]]),
    ];
    const rules = parcelFindings(f, settings).map((x) => `${x.ruleId}:${x.params?.a ?? x.params?.id}:${x.params?.b ?? ''}`).sort();
    expect(rules).toEqual(['PAR-002:E:', 'PAR-004:B:C', 'PAR-005:A:D']);
  });

  it('warns when the area from coordinates misses the registered area by more than the tolerance (PAR-001)', () => {
    const out = parcelFindings([poly('A', 'parcels', sq(0, 0, 10), { legal_area: '102' })], settings);
    expect(out).toHaveLength(1);
    expect(out[0]!.ruleId).toBe('PAR-001');
    expect(out[0]!.params).toMatchObject({ a: '100.00', l: '102.00', t: '1.00' });
    expect(parcelFindings([poly('A', 'parcels', sq(0, 0, 10), { legal_area: '100.5' })], settings)).toEqual([]);
  });

  it('checks the id against the pack pattern only when the pack gives one (PAR-006)', () => {
    const f = [poly('12/3', 'parcels', sq(0, 0, 10)), poly('X-1', 'parcels', sq(20, 0, 10))];
    expect(parcelFindings(f, settings)).toEqual([]);
    const out = parcelFindings(f, { ...settings, idPattern: String.raw`\d+/\d+` });
    expect(out.map((x) => x.params?.id)).toEqual(['X-1']);
  });
});

describe('zone and pad findings', () => {
  it('flags the part of a work zone on land that is not acquired (PAR-003)', () => {
    const f = [
      poly('A', 'parcels', sq(0, 0, 10), { status: 'acquired' }),
      poly('B', 'parcels', sq(10, 0, 10), { status: 'needed' }),
      poly('Z', 'zones', sq(5, 0, 10, 4)),
    ];
    const out = zoneFindings(f);
    expect(out).toHaveLength(1);
    expect(out[0]!.params).toMatchObject({ id: 'B', area: '20.00' });
  });

  it('needs a closed simple outline and a design level on a pad (SRV-083)', () => {
    expect(padFindings([poly('p', 'pads', sq(0, 0, 10), { name: 'P1', level: 12.5 })])).toEqual([]);
    const keys = padFindings([
      poly('q', 'pads', [[0, 0], [1, 1], [0, 0]], { name: 'Q' }),
      poly('r', 'pads', [[0, 0], [10, 10], [10, 0], [0, 10], [0, 0]], { name: 'R' }),
    ]).map((x) => x.messageKey);
    expect(keys).toEqual(['plan.tin.check.pad_ring_open', 'plan.tin.check.pad_self_intersects', 'plan.tin.check.pad_no_level']);
  });
});
