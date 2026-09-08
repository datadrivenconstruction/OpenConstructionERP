// @ts-nocheck
import { describe, it, expect } from 'vitest';
import {
  MODULE_REGISTRY,
  getAllModuleRoutes,
  getModuleNavItems,
  getModuleDefaults,
  getModulesByCategory,
} from './_registry';
import { COUNTRY_TEMPLATES } from './regional-exchange/regionalRegistry';

describe('MODULE_REGISTRY', () => {
  it('should contain at least 16 modules (post Wave 5 Epic I collapse)', () => {
    // Wave 5 Epic I collapsed 20 country exchange modules into one
    // polymorphic `regional-exchange` module. The registry count
    // dropped from 35 → 16; we keep the assertion conservative so
    // future module additions don't break it.
    expect(MODULE_REGISTRY.length).toBeGreaterThanOrEqual(16);
  });

  it('should have unique module ids', () => {
    const ids = MODULE_REGISTRY.map((m) => m.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('should not have installable property on any module', () => {
    for (const mod of MODULE_REGISTRY) {
      expect(mod).not.toHaveProperty('installable');
    }
  });

  it('should include built-in feature modules', () => {
    const ids = MODULE_REGISTRY.map((m) => m.id);
    expect(ids).toContain('assemblies');
    expect(ids).toContain('validation');
    expect(ids).toContain('schedule');
    expect(ids).toContain('5d');
    expect(ids).toContain('tendering');
    expect(ids).toContain('reports');
  });

  it('should include tool modules', () => {
    const ids = MODULE_REGISTRY.map((m) => m.id);
    expect(ids).toContain('sustainability');
    expect(ids).toContain('cost-benchmark');
    expect(ids).toContain('pdf-takeoff');
    expect(ids).toContain('collaboration');
    expect(ids).toContain('risk-analysis');
    expect(ids).toContain('gaeb-exchange');
  });

  // Wave 5 Epic I: 20 individual country modules collapsed into ONE
  // polymorphic regional-exchange module. The old per-country routes
  // are preserved as compat shims on that single manifest.
  it('should include the collapsed regional-exchange module', () => {
    const ids = MODULE_REGISTRY.map((m) => m.id);
    expect(ids).toContain('regional-exchange');
  });

  it('regional modules should have category "regional"', () => {
    const regional = MODULE_REGISTRY.filter((m) => m.category === 'regional');
    expect(regional.length).toBeGreaterThanOrEqual(1);
    const ids = regional.map((m) => m.id);
    expect(ids).toContain('regional-exchange');
  });

  it('both exchange modules are on by default, because a file has to be able to get in', () => {
    // Was 'regional-exchange should be disabled by default'. It shipped off
    // AND with no sidebar row, and the two together meant the twenty market
    // screens behind it reached nobody at all. It now owns the exchange row
    // beside the BOQ, so being off by default would hide the way in for
    // every installation that never went looking through the module list.
    const byId = new Map(MODULE_REGISTRY.map((m) => [m.id, m]));
    for (const id of ['gaeb-exchange', 'regional-exchange']) {
      expect(byId.get(id)?.defaultEnabled, `${id} should be enabled by default`).toBe(true);
    }
  });

  it('regional modules should depend on boq', () => {
    const regional = MODULE_REGISTRY.filter((m) => m.category === 'regional');
    for (const mod of regional) {
      expect(mod.depends).toContain('boq');
    }
  });

  it('regional-exchange should expose all 20 back-compat country routes, plus the hub that reaches them', () => {
    const mod = MODULE_REGISTRY.find((m) => m.id === 'regional-exchange');
    expect(mod).toBeDefined();
    // 20 country routes and one picker. The count used to be the bare literal
    // 20, which is the number of countries rather than the number of routes;
    // stated as countries-plus-one so adding a country moves it and adding a
    // second non-country route does not go unnoticed.
    expect(mod!.routes.length).toBe(COUNTRY_TEMPLATES.length + 1);
    const paths = mod!.routes.map((r) => r.path);
    expect(paths).toContain('/regional-exchange');
    expect(paths).toContain('/uk-nrm-exchange');
    expect(paths).toContain('/us-masterformat-exchange');
    expect(paths).toContain('/fr-dpgf-exchange');
    expect(paths).toContain('/uae-boq-exchange');
    expect(paths).toContain('/au-boq-exchange');
    expect(paths).toContain('/ca-boq-exchange');
    expect(paths).toContain('/es-pbc-exchange');
    expect(paths).toContain('/de-din276-exchange');
    expect(paths).toContain('/nordic-ns3420-exchange');
  });

  it('regional-exchange should ship its own translations', () => {
    const mod = MODULE_REGISTRY.find((m) => m.id === 'regional-exchange');
    expect(mod).toBeDefined();
    expect(mod!.translations).toBeDefined();
    expect(mod!.translations!['en']).toBeDefined();
  });
});

describe('getAllModuleRoutes', () => {
  it('should return flat list of routes from all modules', () => {
    const routes = getAllModuleRoutes();
    expect(routes.length).toBeGreaterThanOrEqual(10);
    // Tool modules
    expect(routes.some((r) => r.path === '/sustainability')).toBe(true);
    expect(routes.some((r) => r.path === '/benchmarks')).toBe(true);
    expect(routes.some((r) => r.path === '/collaboration')).toBe(true);
    // `/takeoff-viewer` is deliberately NOT here any more. It mounted
    // `pdf-takeoff`'s viewer a second time with no props, next door to
    // `/takeoff`, which mounts the same component with the document library and
    // the filmstrip wired in, and nothing in the app ever linked to it. It is a
    // redirect in App.tsx now, so the bookmark survives a disabled module,
    // which a manifest route cannot do. Same retirement as `/risk-analysis`.
    expect(routes.some((r) => r.path === '/takeoff-viewer')).toBe(false);
    // The hub that picks among the twenty country routes below. Before it, the
    // twenty were reachable only by typing the URL: no nav row (#217), and the
    // BOQ link the decision assumed had never been written.
    expect(routes.some((r) => r.path === '/regional-exchange')).toBe(true);
    // Regional back-compat routes — Wave 5 Epic I kept all 20 of them
    // even though they now share one polymorphic page.
    expect(routes.some((r) => r.path === '/uk-nrm-exchange')).toBe(true);
    expect(routes.some((r) => r.path === '/us-masterformat-exchange')).toBe(true);
    expect(routes.some((r) => r.path === '/fr-dpgf-exchange')).toBe(true);
    expect(routes.some((r) => r.path === '/uae-boq-exchange')).toBe(true);
    expect(routes.some((r) => r.path === '/au-boq-exchange')).toBe(true);
    expect(routes.some((r) => r.path === '/ca-boq-exchange')).toBe(true);
    expect(routes.some((r) => r.path === '/es-pbc-exchange')).toBe(true);
    expect(routes.some((r) => r.path === '/de-din276-exchange')).toBe(true);
    expect(routes.some((r) => r.path === '/jp-sekisan-exchange')).toBe(true);
    expect(routes.some((r) => r.path === '/ru-gesn-exchange')).toBe(true);
  });

  it('should have lazy components for each route', () => {
    const routes = getAllModuleRoutes();
    for (const route of routes) {
      expect(route.component).toBeDefined();
      expect(typeof route.component).toBe('object');
    }
  });
});

describe('getModuleNavItems', () => {
  it('should return nav items for tools group', () => {
    const items = getModuleNavItems('tools');
    // Tools group holds sustainability. Other tools (benchmarks,
    // collaboration) live in their own groups now; gaeb-exchange and
    // regional-exchange opt out of sidebar nav and are reached from the BOQ
    // page instead (#217). pdf-takeoff contributes nothing here either: its
    // viewer is mounted by `/takeoff`, whose row the static catalogue owns, and
    // its own standalone route is retired. risk-analysis no longer
    // contributes a nav item: its standalone page was retired in the Monte
    // Carlo IA merge (#71) so there is one simulation home (Risk Register).
    expect(items.length).toBeGreaterThanOrEqual(1);
    expect(items.some((i) => i.to === '/sustainability')).toBe(true);
    expect(items.some((i) => i.to === '/risk-analysis')).toBe(false);
  });

  it('regional nav-items are intentionally empty (no twenty country rows in the menu)', () => {
    // Issue #217 — the 20 country pages get no individual sidebar entries;
    // the way in was to be a link from the BOQ page, the way `gaeb-exchange`
    // is. Wave 5 Epic I kept this invariant when collapsing the modules.
    //
    // The title and this comment used to state the BOQ link as fact while it
    // did not exist. It exists now: `BOQListPage` offers the module's hub page
    // from the BOQ intro card, under the same module-enabled gate the GAEB link
    // uses, and the hub links on to all twenty.
    //
    // The empty list is still the right invariant, and now for a second reason
    // as well: the sidebar's `regional` group was deleted, so an item in that
    // group would render nowhere whatever it said. See the note on `navItems`
    // in `regional-exchange/manifest.tsx`.
    const items = getModuleNavItems('regional');
    expect(items).toEqual([]);
  });

  it('should return empty array for non-existent group', () => {
    const items = getModuleNavItems('nonexistent');
    expect(items).toEqual([]);
  });
});

describe('getModuleDefaults', () => {
  it('should return defaults for all modules', () => {
    const defaults = getModuleDefaults();
    // Core modules — enabled by default
    expect(defaults['sustainability']).toBe(true);
    expect(defaults['cost-benchmark']).toBe(true);
    expect(defaults['pdf-takeoff']).toBe(true);
    expect(defaults['collaboration']).toBe(true);
    expect(defaults['assemblies']).toBe(true);
    expect(defaults['validation']).toBe(true);
    // Advanced/regional — disabled by default
    expect(defaults['risk-analysis']).toBe(false);
    // gaeb-exchange flipped to on-by-default in v2.6.30 (GAEB DA XML 3.3
    // is core for the DACH workflow — see manifest defaultEnabled=true).
    expect(defaults['gaeb-exchange']).toBe(true);
    // Wave 5 Epic I collapsed 20 country exchanges into one polymorphic
    // module and kept it disabled, like its predecessors. It is the
    // exchange hub now and carries its own sidebar row, so off by default
    // would mean the row is absent for anyone who never opened the module
    // list.
    expect(defaults['regional-exchange']).toBe(true);
  });

  it('should return an object with boolean values', () => {
    const defaults = getModuleDefaults();
    for (const value of Object.values(defaults)) {
      expect(typeof value).toBe('boolean');
    }
  });
});

describe('getModulesByCategory', () => {
  it('should group modules by category', () => {
    const grouped = getModulesByCategory();
    expect(grouped['estimation']).toBeDefined();
    expect(grouped['planning']).toBeDefined();
    expect(grouped['procurement']).toBeDefined();
    expect(grouped['tools']).toBeDefined();
    expect(grouped['regional']).toBeDefined();
  });

  it('should have assemblies in estimation category', () => {
    const grouped = getModulesByCategory();
    const ids = grouped['estimation']!.map((m) => m.id);
    expect(ids).toContain('assemblies');
  });

  it('should have sustainability in tools category', () => {
    const grouped = getModulesByCategory();
    const ids = grouped['tools']!.map((m) => m.id);
    expect(ids).toContain('sustainability');
  });

  it('should have at least one module in regional category', () => {
    const grouped = getModulesByCategory();
    expect(grouped['regional']!.length).toBeGreaterThanOrEqual(1);
    const ids = grouped['regional']!.map((m) => m.id);
    expect(ids).toContain('regional-exchange');
  });
});
