// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import type { Feature } from 'geojson';
import { measure, snapToPoint, type Vertex } from './planMeasure';
import { surveyDefaultsFor } from './SurveySetupCard';
import { factorsBody, stagesBody, type StageRow } from './StagedPanel';
import { pointPatch } from './PointDrawer';
import { checkBody } from './ControlTab';
import { parseCodes } from './VolumeDialogs';

const on = (r: Record<string, boolean>) => Object.keys(r).filter((k) => r[k]).sort();

describe('surveyDefaultsFor', () => {
  it('a survey company gets everything but mine survey', () => {
    expect(on(surveyDefaultsFor('survey_company'))).toEqual(
      ['land-parcels', 'monitoring', 'setting-out', 'stockpiles', 'surfaces_volumes', 'survey_core'].sort(),
    );
  });
  it('a mine gets everything but land parcels', () => {
    const r = surveyDefaultsFor('mining_operator');
    expect(r.mine_survey).toBe(true);
    expect(r['land-parcels']).toBe(false);
  });
  it('a contractor gets register, volumes, stockpiles and setting-out', () => {
    expect(on(surveyDefaultsFor('general_contractor'))).toEqual(['setting-out', 'stockpiles', 'surfaces_volumes', 'survey_core']);
    expect(surveyDefaultsFor('civil_infrastructure').monitoring).toBe(true);
  });
  it('an unknown or missing profile keeps the plain defaults', () => {
    for (const key of [null, 'estimator']) {
      const r = surveyDefaultsFor(key);
      expect(r.mine_survey).toBe(false);
      expect(r.survey_core).toBe(true);
    }
  });
});

describe('plan measure', () => {
  const grid: Vertex[] = [
    { lon: 0, lat: 0, e: 1000, n: 2000 },
    { lon: 0, lat: 0, e: 1030, n: 2000 },
    { lon: 0, lat: 0, e: 1030, n: 2030 },
  ];
  it('uses the project grid when every vertex is snapped', () => {
    expect(measure(grid.slice(0, 2), false)).toEqual({ distance_m: 30, area_m2: null, exact: true });
    const tri = measure(grid, true);
    expect(tri.area_m2).toBe(450);
    expect(tri.distance_m).toBeCloseTo(60 + Math.hypot(30, 30), 6);
  });
  it('falls back to a ground estimate from WGS 84', () => {
    // 0.001 deg of latitude is about 111.2 m.
    const r = measure([{ lon: 13, lat: 52 }, { lon: 13, lat: 52.001 }], false);
    expect(r.exact).toBe(false);
    expect(r.distance_m).toBeCloseTo(111.2, 0);
  });
  it('snaps only within the radius', () => {
    const pts: Feature[] = [
      { type: 'Feature', geometry: { type: 'Point', coordinates: [13, 52] }, properties: { layer: 'points', id: 'CP1', e: 1, n: 2 } },
    ];
    expect(snapToPoint({ lon: 13.00001, lat: 52 }, pts, 3).label).toBe('CP1');
    expect(snapToPoint({ lon: 13.001, lat: 52 }, pts, 3).label).toBeUndefined();
  });
});

describe('staged request', () => {
  const row = (p: Partial<StageRow>): StageRow => ({ label: '', kind: 'surface', surface_id: '', depth: '', date: '', material: '', ...p });
  it('needs a surface first and complete rows', () => {
    expect(stagesBody([row({ kind: 'strip', depth: '0.3' }), row({ surface_id: 'a' })])).toBeNull();
    expect(stagesBody([row({ surface_id: 'a' }), row({ kind: 'strip', depth: '' })])).toBeNull();
    expect(stagesBody([row({ surface_id: 'a', label: 'Ground' }), row({ kind: 'strip', depth: '0,3', material: ' topsoil ' })])).toEqual([
      { label: 'Ground', surface_id: 'a', surveyed_on: '', material: '' },
      { label: '#2', strip_depth_m: 0.3, surveyed_on: '', material: 'topsoil' },
    ]);
  });
  it('leaves blank factors out instead of sending zero', () => {
    expect(factorsBody({ topsoil: { loose: '1.25', compacted: '' }, clay: { loose: '', compacted: '' } })).toEqual({ topsoil: { loose: 1.25 } });
  });
});

describe('point and control forms', () => {
  const base = { point_id: '101', code: 'TOE', kind: 'topo' as const, e: '1.000', n: '2.000', z: '3.000', description: '' };
  it('sends only what changed, and an emptied height clears Z', () => {
    expect(pointPatch(base, base)).toEqual({});
    expect(pointPatch(base, { ...base, code: 'CREST ', z: '' })).toEqual({ code: 'CREST', clear_z: true });
  });
  it('typed coordinates win over a picked point', () => {
    expect(checkBody('', 'm', '', '', '')).toBeNull();
    expect(checkBody('c', 'm', '', '', '')).toEqual({ control_point_id: 'c', measured_point_id: 'm' });
    expect(checkBody('c', 'm', '1,5', '2', '')).toEqual({ control_point_id: 'c', e: 1.5, n: 2, z: null });
  });
  it('splits breakline codes', () => {
    expect(parseCodes('TOE, CREST;kerb TOE')).toEqual(['TOE', 'CREST', 'kerb']);
  });
});
