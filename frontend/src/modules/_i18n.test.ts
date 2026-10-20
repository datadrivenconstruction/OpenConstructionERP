// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The literal-vs-key rule every manifest string is read through.
//
// Run:  npx vitest run src/modules/_i18n.test.ts

import { describe, it, expect } from 'vitest';

import { isModuleI18nKey, translateManifestText } from './_i18n';

/** Stand-in for i18next's `t`: knows a few keys, falls back like the real one. */
function translator(known: Record<string, string>) {
  return (key: string, options: { defaultValue: string }) => known[key] ?? options.defaultValue;
}

describe('isModuleI18nKey', () => {
  it('accepts the key shapes the manifests actually use', () => {
    for (const key of [
      'gaeb.title',
      'collab.title',
      'nav.5d_cost_model',
      'nav.regional_exchange',
      'converter.ifc.name',
      'modules.cost_benchmark.description',
      'modules.pdf_takeoff.name',
      'schedule.title',
    ]) {
      expect(isModuleI18nKey(key), `${key} should read as a key`).toBe(true);
    }
  });

  it('leaves an English display string a literal', () => {
    // Every one of these was a manifest `name` or `description` before the
    // sweep, so this is the exact set a module outside this repository may
    // still be shipping.
    for (const literal of [
      'PDF Takeoff Viewer',
      'Real-time Collaboration',
      'GAEB XML 3.3 Import / Export',
      'DDC Converters 2.0 - IFC Converter',
      'Risk Analysis (Monte Carlo)',
      'View PDFs and take measurements directly on drawings',
      'Pipeline Builder',
      'Sustainability',
    ]) {
      expect(isModuleI18nKey(literal), `${literal} should read as a literal`).toBe(false);
    }
  });

  it('needs a dot: one bare word is a name, not a namespace', () => {
    expect(isModuleI18nKey('sustainability')).toBe(false);
    expect(isModuleI18nKey('')).toBe(false);
  });
});

describe('translateManifestText', () => {
  it('translates a key', () => {
    const t = translator({ 'collab.title': 'Echtzeit-Zusammenarbeit' });
    expect(translateManifestText(t, 'collab.title')).toBe('Echtzeit-Zusammenarbeit');
  });

  it('hands back a literal untouched, so an unmigrated module keeps its name', () => {
    const t = translator({});
    expect(translateManifestText(t, 'Real-time Collaboration')).toBe('Real-time Collaboration');
  });

  it('shows the key itself when nothing answers it', () => {
    // The alternative - substituting a prettified module id - would render a
    // plausible-looking name over a translation that is simply missing, and
    // nobody would ever go looking for it.
    const t = translator({});
    expect(translateManifestText(t, 'modules.pdf_takeoff.name')).toBe('modules.pdf_takeoff.name');
  });
});
