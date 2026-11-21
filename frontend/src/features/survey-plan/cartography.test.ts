import { describe, expect, it } from 'vitest';
import { defaultStyle, featureStyle, overlayStyle, readPalette } from './cartography';
import { PLAN_LAYER_IDS, type PlanStyleLayer } from './types';

// Layout properties MapLibre evaluates once per layer: an expression here makes it drop the whole layer.
const CONSTANT_ONLY = [
  'symbol-placement', 'symbol-spacing', 'symbol-avoid-edges', 'text-keep-upright', 'text-allow-overlap',
  'text-ignore-placement', 'text-optional', 'text-rotation-alignment', 'text-pitch-alignment',
  'icon-allow-overlap', 'icon-ignore-placement', 'icon-optional', 'icon-keep-upright', 'visibility',
];

const palette = readPalette(null);
const all: Array<[string, PlanStyleLayer]> = [
  ...PLAN_LAYER_IDS.flatMap((id) => defaultStyle(id, { palette, labels: 'id', opacity: 1 }).map((l) => [id, l] as [string, PlanStyleLayer])),
  ...featureStyle(palette, 1, {}).map((l) => ['feature', l] as [string, PlanStyleLayer]),
  ...overlayStyle(palette).map((l) => ['overlay', l] as [string, PlanStyleLayer]),
];

describe('plan style layers', () => {
  it.each(all.map(([layer, s]) => [`${layer}/${s.id}`, s] as const))('%s uses constants where MapLibre needs them', (_name, s) => {
    for (const prop of CONSTANT_ONLY) {
      const v = s.layout?.[prop];
      if (v !== undefined) expect(Array.isArray(v), prop).toBe(false);
    }
  });

  it('labels a rubber-band line along the line and a point at the point', () => {
    const measure = defaultStyle('measure', { palette, labels: 'id', opacity: 1 }).filter((l) => l.type === 'symbol');
    expect(measure.map((l) => l.layout?.['symbol-placement']).sort()).toEqual(['line-center', 'point']);
    expect(new Set(measure.map((l) => l.id)).size).toBe(measure.length);
  });
});
