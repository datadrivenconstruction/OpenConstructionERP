import { describe, expect, it } from 'vitest';
import { navGroups } from '@/app/layout/navCatalog';
import { RU } from './testStrings';
import { manifest } from './manifest';

describe('Design menu section', () => {
  it('puts every design page in its own group, start first, in project order', () => {
    expect(new Set(manifest.navItems.map((i) => i.group))).toEqual(new Set(['grp_design']));
    expect(manifest.navItems.map((i) => i.to)).toEqual([
      '/design/overview', '/design/editor', '/design/brief', '/design/revisions', '/design/acceptance', '/design/estimate',
    ]);
  });

  it('has a top-level group in the ERP menu (patch 0008), placed before Takeoff and named by the module title', () => {
    const ids = navGroups.map((g) => g.id);
    const design = navGroups.find((g) => g.id === 'grp_design');
    expect(design).toBeDefined();
    expect(design!.items).toEqual([]); // rows come from the module only: no module, no group
    expect(design!.labelKey).toBe('design.title');
    expect(ids.indexOf('grp_design')).toBeLessThan(ids.indexOf('grp_takeoff'));
    expect(RU['design.title']).toBe('Проектирование');
  });

  it('no longer files design pages under Takeoff', () => {
    const takeoff = navGroups.find((g) => g.id === 'grp_takeoff')!;
    expect(takeoff.items.some((i) => i.to.startsWith('/design'))).toBe(false);
  });
});
