// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it, vi } from 'vitest';

vi.mock('react-map-gl/maplibre', () => ({ default: () => null, Layer: () => null, Source: () => null }));
vi.mock('maplibre-gl/dist/maplibre-gl.css', () => ({}));
vi.mock('@/shared/lib/mapLibre', () => ({}));

const { chordOf, OPTIONS_BAR_CLASS } = await import('./PlanCanvas');
const { pointFeature } = await import('./PlanEditorPage');
const { planLayerSpecs } = await import('@/features/survey/SurveyPlan');

const key = (code: string, k: string, mods: Partial<Record<'ctrlKey' | 'metaKey' | 'altKey' | 'shiftKey', boolean>> = {}) => ({
  key: k,
  code,
  ctrlKey: false,
  metaKey: false,
  altKey: false,
  shiftKey: false,
  ...mods,
});

describe('canvas shortcuts', () => {
  it('read letters by physical key, so a Cyrillic or AZERTY layout still picks the tool', () => {
    expect(chordOf(key('KeyL', 'д'))).toBe('L');
    expect(chordOf(key('KeyZ', 'z', { ctrlKey: true }))).toBe('Mod+Z');
    expect(chordOf(key('KeyZ', 'Z', { metaKey: true, shiftKey: true }))).toBe('Mod+Shift+Z');
    expect(chordOf(key('KeyM', 'm', { shiftKey: true }))).toBe('Shift+M');
    expect(chordOf(key('Slash', '?', { shiftKey: true }))).toBe('?');
    expect(chordOf(key('F3', 'F3'))).toBe('F3');
    expect(chordOf(key('Escape', 'Escape'))).toBe('Escape');
  });
});

describe('editor page points', () => {
  it('control goes to its own layer and every point carries its revision', () => {
    const f = pointFeature({ id: 'u1', point_id: 'CP1', e: 389000, n: 5819000, z: 34.12, code: 'CP', kind: 'control', source_line: 3, rev: 2 });
    expect(f).toMatchObject({ id: 'point:u1', layer: 'control', entityType: 'point', entityId: 'u1', rev: 2 });
    expect(f.geometry).toEqual({ type: 'Point', coordinates: [389000, 5819000, 34.12] });
    expect(pointFeature({ id: 'u2', point_id: '7', e: 1, n: 2, z: null, code: 'EG', kind: 'topo', source_line: null, rev: 0 }).layer).toBe('points');
  });
});

describe('legacy plan feed', () => {
  const served = (local: boolean) => ({
    type: 'FeatureCollection' as const,
    properties: { epsg: local ? null : 32633, local_grid: local },
    features: [
      { type: 'Feature' as const, geometry: { type: 'Point' as const, coordinates: [13.4, 52.5] }, properties: { layer: 'points', id: 'P1', kind: 'topo', e: 389000.5, n: 5819000.25, z: 34 } },
      { type: 'Feature' as const, geometry: { type: 'LineString' as const, coordinates: [[100, 200], [110, 200]] }, properties: { layer: 'breaklines', id: 'BL' } },
      { type: 'Feature' as const, geometry: { type: 'Polygon' as const, coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] }, properties: { layer: 'heat', side: 'cut', dh: 0.4 } },
    ],
  });

  it('points always draw from grid E/N, other layers pass through on a georeferenced project', () => {
    const specs = planLayerSpecs(served(false));
    const points = specs.find((l) => l.id === 'points')!;
    expect(points.features[0]!.geometry).toEqual({ type: 'Point', coordinates: [389000.5, 5819000.25, 34] });
    expect(specs.find((l) => l.id === 'heat')!.viewFeatures?.features).toHaveLength(1);
    expect(specs.find((l) => l.id === 'breaklines')!.features).toHaveLength(0);
  });

  it('a local grid draws instead of being refused: served layers become grid features', () => {
    const specs = planLayerSpecs(served(true));
    const bl = specs.find((l) => l.id === 'breaklines')!;
    expect(bl.viewFeatures).toBeUndefined();
    expect(bl.features[0]!.geometry).toEqual({ type: 'LineString', coordinates: [[100, 200], [110, 200]] });
    expect(specs.find((l) => l.id === 'heat')!.features[0]!.properties).toMatchObject({ side: 'cut', dh: 0.4 });
  });
});

describe('options bar', () => {
  it('keeps one fixed row so starting a drawing tool does not push the plan down', () => {
    const cls = OPTIONS_BAR_CLASS.split(' ');
    expect(cls).toContain('h-12');
    expect(cls).toContain('flex-nowrap');
    expect(cls).not.toContain('flex-wrap');
  });
});
