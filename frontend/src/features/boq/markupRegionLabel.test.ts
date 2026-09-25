// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import { markupRegionLabel, type MarkupRegion } from './markupRegionLabel';
import hr from '@/app/locales/hr';
import de from '@/app/locales/de';
import fr from '@/app/locales/fr';

/** A `t` that reads one locale's flat table and interpolates like i18next. */
function tFrom(table: Record<string, string>) {
  return (key: string, opts?: Record<string, unknown>) => table[key] ?? String(opts?.defaultValue ?? key);
}

const croatia: MarkupRegion = { code: 'HR', flag: '', standard: 'Troškovnik' };
const dach: MarkupRegion = { code: 'DACH', flag: '', countries: ['DE', 'AT', 'CH'], standard: 'VOB/HOAI' };
const uk: MarkupRegion = { code: 'UK', flag: '', countries: ['GB'], standard: 'NRM/RICS' };
const gulf: MarkupRegion = {
  code: 'GULF',
  flag: '',
  labelKey: 'boq.markup_region.gulf',
  labelDefault: 'Gulf states',
  standard: 'FIDIC',
};
const generic: MarkupRegion = {
  code: 'DEFAULT',
  flag: '',
  labelKey: 'boq.markup_region.generic',
  labelDefault: 'Generic international',
  standard: '',
};

describe('markupRegionLabel', () => {
  it('names the templates in Croatian', () => {
    const t = tFrom(hr.translation);
    expect(markupRegionLabel(croatia, 'hr', t)).toBe('Hrvatska');
    expect(markupRegionLabel(dach, 'hr', t)).toBe('Njemačka, Austrija i Švicarska');
    expect(markupRegionLabel(gulf, 'hr', t)).toBe('Zaljevske države');
    expect(markupRegionLabel(generic, 'hr', t)).toBe('Opće međunarodno');
  });

  it('names the templates in German', () => {
    const t = tFrom(de.translation);
    expect(markupRegionLabel(croatia, 'de', t)).toBe('Kroatien');
    expect(markupRegionLabel(dach, 'de', t)).toBe('Deutschland, Österreich und Schweiz');
    expect(markupRegionLabel(uk, 'de', t)).toBe('Vereinigtes Königreich');
    expect(markupRegionLabel(gulf, 'de', t)).toBe('Golfstaaten');
  });

  it('names the templates in French', () => {
    const t = tFrom(fr.translation);
    expect(markupRegionLabel(croatia, 'fr', t)).toBe('Croatie');
    expect(markupRegionLabel(uk, 'fr', t)).toBe('Royaume-Uni');
    expect(markupRegionLabel(gulf, 'fr', t)).toBe('États du Golfe');
    expect(markupRegionLabel(generic, 'fr', t)).toBe('International générique');
  });
});
