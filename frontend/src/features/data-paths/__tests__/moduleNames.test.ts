import { describe, expect, it } from 'vitest';
import type { TFunction } from 'i18next';
import { edgeAriaLabel, moduleLabel } from '../flowModel';

// A German reader: only the keys this bundle carries come back translated.
const DE: Record<string, string> = {
  'modules.catalog.tendering': 'Ausschreibung',
  'data_paths.edge_aria': 'Verbindung von {{source}} zu {{target}}',
};
const t = ((key: string, o?: Record<string, unknown>) => {
  let v = DE[key] ?? String(o?.defaultValue ?? key);
  for (const [k, x] of Object.entries(o ?? {})) v = v.replace(`{{${k}}}`, String(x));
  return v;
}) as unknown as TFunction;

describe('data path module names', () => {
  it('a module without a menu row reads the Settings > Modules name, not the manifest English', () => {
    expect(moduleLabel(t, 'oe_tendering', 'Tendering')).toBe('Ausschreibung');
  });

  it('falls back to the manifest name only when nothing is translated', () => {
    expect(moduleLabel(t, 'oe_no_such_module', 'Some module')).toBe('Some module');
  });

  it('names an edge in the reader language, not "Edge from oe_boq to oe_tendering"', () => {
    const label = edgeAriaLabel(t, 'oe_boq', 'oe_tendering');
    expect(label).toMatch(/^Verbindung von .+ zu Ausschreibung$/);
    expect(label).not.toContain('oe_');
  });
});
