// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { dhToken, heatFeatures } from './surfaceLayers';
import { areaComparison } from './parcelLayers';
import { parseOutline } from './ZonePadEditor';
import type { SurveyGrid } from './api';

describe('heatFeatures', () => {
  it('merges same-class cells of a row into one rectangle and skips the near-zero band', () => {
    const h = { origin_e: 100, origin_n: 200, cell: 2, nx: 4, ny: 2, dh: [1, 1, 0, -3, null, 0.06, 0.07, 0.01] };
    const f = heatFeatures(h);
    expect(f.map((x) => x.properties.token)).toEqual(['cut-2', 'fill-3', 'cut-1']);
    expect(f[0]!.geometry.coordinates).toEqual([[[100, 200], [104, 200], [104, 202], [100, 202]]]);
    expect(f[2]!.geometry.coordinates).toEqual([[[102, 202], [106, 202], [106, 204], [102, 204]]]);
    expect(dhToken(-0.05)).toBe('neutral');
    expect(dhToken(2)).toBe('cut-3');
  });
});

describe('areaComparison', () => {
  it('compares the area from the edited corners with the register and the tolerance', () => {
    const corner = (label: string, e: number, n: number) => ({ label, e, n, mark: 'pin' });
    const grid: SurveyGrid = {
      epsg: null,
      id_pattern: '',
      gap_tolerance_m: '0.1',
      zones: [],
      parcels: [{ id: 'p1', ref: '1/1', name: '', status: 'needed', legal_area: '400', computed_area: null, tolerance_m2: '2',
        points: [corner('1', 0, 0), corner('2', 20, 0), corner('3', 20, 20), corner('4', 0, 20)] }],
    };
    expect(areaComparison(grid, {})[0]).toMatchObject({ computed: 400, diff: 0, within: true });
    const moved = { p1: [corner('1', 0, 0), corner('2', 20.2, 0), corner('3', 20.2, 20), corner('4', 0, 20)] };
    const row = areaComparison(grid, moved)[0]!;
    expect(row.diff).toBeCloseTo(4, 9);
    expect(row.within).toBe(false);
  });
});

describe('parseOutline', () => {
  it('reads corners in the display axis order and unit and reports bad lines by number', () => {
    const out = parseOutline('200 100\nnot a point\n\n210,5 100', { axis: 'NE', linearUnit: 'm' });
    expect(out.ring[0]).toEqual([100, 200]);
    expect(out.bad).toEqual([2]);
    const ft = parseOutline('10 20', { axis: 'EN', linearUnit: 'ft' });
    expect(ft.ring[0]![0]).toBeCloseTo(3.048, 9);
  });
});
