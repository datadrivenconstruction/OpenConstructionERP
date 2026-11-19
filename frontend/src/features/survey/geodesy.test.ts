import { describe, expect, it } from 'vitest';
import { exportQuery, registerExportUrl, stakeExportUrl, type ScaleFactor } from './api';
import { gridGroundText, rowsToPoints } from './GeodesyPanel';

describe('export query', () => {
  it('sends CSV options only for CSV', () => {
    expect(exportQuery({ format: 'csv', preset: 'PENZD', delimiter: ';' })).toBe('format=csv&preset=PENZD&delimiter=%3B');
    expect(exportQuery({ format: 'dxf', preset: 'PENZD', delimiter: ';' })).toBe('format=dxf');
  });

  it('site grid wins over a target system', () => {
    expect(exportQuery({ format: 'landxml', local: true, target_epsg: 25833 })).toBe('format=landxml&local=true');
    expect(exportQuery({ format: 'gsi', target_epsg: 25833, locale: 'de' })).toBe('format=gsi&target_epsg=25833&locale=de');
  });

  it('builds register and stake urls', () => {
    expect(registerExportUrl('p1', { format: 'geojson', kind: 'control' })).toBe('/api/v1/survey-core/projects/p1/export?format=geojson&kind=control');
    expect(stakeExportUrl('r1', { format: 'csv', preset: 'ENZ', local: true })).toBe('/api/v1/setting-out/requests/r1/export?format=csv');
  });
});

describe('grid and ground', () => {
  it('prints the worked example', () => {
    const sf: ScaleFactor = {
      epsg: 32633,
      e: 389000,
      n: 5819000,
      height_m: 120,
      k: 0.99975171,
      elevation_factor: 0.99998117,
      csf: 0.99973288,
      distance_m: 249.933,
      grid_m: 249.866,
      ground_m: 250.0,
      diff_mm: 66.8,
      height_source: 'setting',
    };
    expect(gridGroundText(sf)).toEqual({ csf: '0.99973288', grid: '249.933', ground: '250.000', mm: '67' });
  });

  it('turns rows with an id into common points, decimal comma allowed', () => {
    const rows = [
      { point_id: ' A ', x: '1000', y: '1000', e: '389012,345', n: '5819020.111', use: true },
      { point_id: '', x: '1', y: '2', e: '3', n: '4', use: true },
    ];
    expect(rowsToPoints(rows)).toEqual([{ point_id: 'A', x: 1000, y: 1000, e: 389012.345, n: 5819020.111, use: true }]);
  });
});
