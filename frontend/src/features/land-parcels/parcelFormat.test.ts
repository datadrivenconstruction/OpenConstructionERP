// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import type { PlanCollection } from './api';
import { STATUS_FILL, STATUS_VARIANT, formatOf, importBodyFor, planCentre, ruleIds } from './parcelFormat';

function plan(local: boolean, rings: number[][][]): PlanCollection {
  return {
    type: 'FeatureCollection',
    local,
    epsg: local ? null : 4326,
    features: rings.map((ring, i) => ({
      type: 'Feature',
      id: `f${i}`,
      properties: { kind: 'parcel', id: `p${i}` },
      geometry: { type: 'Polygon', coordinates: [ring] },
    })),
  };
}

describe('parcelFormat', () => {
  it('maps every status to a dot variant and a fill', () => {
    expect(Object.keys(STATUS_VARIANT).sort()).toEqual(Object.keys(STATUS_FILL).sort());
    expect(STATUS_VARIANT.acquired).toBe('success');
    expect(STATUS_VARIANT.expropriation).toBe('error');
  });

  it('detects the import format from the file name', () => {
    expect(formatOf('Parcels.ZIP')).toBe('shapefile');
    expect(formatOf('parcels.geojson')).toBe('geojson');
    expect(formatOf('parcels.json')).toBe('geojson');
    expect(formatOf('parcels.dxf')).toBeNull();
  });

  it('sends GeoJSON as text and a zip as base64', async () => {
    const gj = await importBodyFor(new File(['{"type":"FeatureCollection"}'], 'a.geojson'), 'parcels');
    expect(gj).toMatchObject({ format: 'geojson', target: 'parcels', text: '{"type":"FeatureCollection"}' });
    const zip = await importBodyFor(new File([new Uint8Array([80, 75, 3, 4])], 'a.zip'), 'work_zone');
    expect(zip).toMatchObject({ format: 'shapefile', target: 'work_zone', content_base64: 'UEsDBA==' });
    await expect(importBodyFor(new File(['x'], 'a.txt'), 'parcels')).rejects.toThrow('unsupported');
  });

  it('centres the plan on the bounding box, not on a local grid', () => {
    const rings = [[[10, 50], [12, 50], [12, 52], [10, 50]]];
    expect(planCentre(plan(false, rings))).toEqual({ lon: 11, lat: 51 });
    expect(planCentre(plan(true, rings))).toBeNull();
    expect(planCentre(plan(false, []))).toBeNull();
    expect(planCentre(undefined)).toBeNull();
  });

  it('deduplicates and sorts rule ids', () => {
    expect(ruleIds([{ rule_id: 'PAR-003' }, { rule_id: 'PAR-001' }, { rule_id: 'PAR-003' }])).toEqual(['PAR-001', 'PAR-003']);
  });
});
