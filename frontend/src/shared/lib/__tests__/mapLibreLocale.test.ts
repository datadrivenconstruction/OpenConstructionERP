import { describe, expect, it } from 'vitest';
import type { TFunction } from 'i18next';
import { mapLibreLocale } from '../mapLibreLocale';

describe('MapLibre control titles', () => {
  it('cover the zoom and compass buttons MapLibre would otherwise title in English', () => {
    const t = ((key: string) => `de:${key}`) as unknown as TFunction;
    const locale = mapLibreLocale(t);
    expect(locale['NavigationControl.ZoomIn']).toBe('de:map.ui.zoom_in');
    expect(locale['NavigationControl.ZoomOut']).toBe('de:map.ui.zoom_out');
    expect(locale['NavigationControl.ResetBearing']).toBe('de:map.ui.reset_bearing');
  });

  it('keeps the English defaults when a bundle has no translation', () => {
    const t = ((_k: string, o: { defaultValue: string }) => o.defaultValue) as unknown as TFunction;
    expect(mapLibreLocale(t)['NavigationControl.ResetBearing']).toBe('Drag to rotate map, click to reset north');
  });
});
