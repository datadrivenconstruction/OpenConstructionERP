// @ts-nocheck
import { describe, it, expect } from 'vitest';
import {
  MODULE_REGISTRY,
  getAllModuleRoutes,
  getModuleNavItems,
  getModuleSearchEntries,
  getModuleDefaults,
  getModulesByCategory,
} from './_registry';

describe('MODULE_REGISTRY', () => {
  it('should contain at least 18 modules', () => {
    expect(MODULE_REGISTRY.length).toBeGreaterThanOrEqual(18);
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

  it('should include all 6 regional exchange modules', () => {
    const ids = MODULE_REGISTRY.map((m) => m.id);
    expect(ids).toContain('uk-nrm-exchange');
    expect(ids).toContain('us-masterformat-exchange');
    expect(ids).toContain('fr-dpgf-exchange');
    expect(ids).toContain('uae-boq-exchange');
    expect(ids).toContain('au-boq-exchange');
    expect(ids).toContain('ca-boq-exchange');
  });

  it('regional modules should have category "regional"', () => {
    const regional = MODULE_REGISTRY.filter((m) => m.category === 'regional');
    expect(regional.length).toBeGreaterThanOrEqual(6);
    const ids = regional.map((m) => m.id);
    expect(ids).toContain('uk-nrm-exchange');
    expect(ids).toContain('us-masterformat-exchange');
    expect(ids).toContain('fr-dpgf-exchange');
    expect(ids).toContain('uae-boq-exchange');
    expect(ids).toContain('au-boq-exchange');
    expect(ids).toContain('ca-boq-exchange');
  });

  it('regional modules should be disabled by default', () => {
    const regional = MODULE_REGISTRY.filter((m) => m.category === 'regional');
    for (const mod of regional) {
      expect(mod.defaultEnabled).toBe(false);
    }
  });

  it('regional modules should depend on boq', () => {
    const regional = MODULE_REGISTRY.filter((m) => m.category === 'regional');
    for (const mod of regional) {
      expect(mod.depends).toContain('boq');
    }
  });

  it('regional modules should have routes, navItems, and searchEntries', () => {
    const regional = MODULE_REGISTRY.filter((m) => m.category === 'regional');
    for (const mod of regional) {
      expect(mod.routes.length).toBeGreaterThan(0);
      expect(mod.navItems.length).toBeGreaterThan(0);
      expect(mod.searchEntries!.length).toBeGreaterThan(0);
    }
  });

  it('regional modules should have translations', () => {
    const regional = MODULE_REGISTRY.filter((m) => m.category === 'regional');
    for (const mod of regional) {
      expect(mod.translations).toBeDefined();
      expect(mod.translations!['en']).toBeDefined();
    }
  });
});

describe('getAllModuleRoutes', () => {
  it('should return flat list of routes from all modules', () => {
    const routes = getAllModuleRoutes();
    expect(routes.length).toBeGreaterThanOrEqual(10);
    // Tool modules
    expect(routes.some((r) => r.path === '/sustainability')).toBe(true);
    expect(routes.some((r) => r.path === '/benchmarks')).toBe(true);
    expect(routes.some((r) => r.path === '/takeoff-viewer')).toBe(true);
    expect(routes.some((r) => r.path === '/collaboration')).toBe(true);
    // Regional modules
    expect(routes.some((r) => r.path === '/uk-nrm-exchange')).toBe(true);
    expect(routes.some((r) => r.path === '/us-masterformat-exchange')).toBe(true);
    expect(routes.some((r) => r.path === '/fr-dpgf-exchange')).toBe(true);
    expect(routes.some((r) => r.path === '/uae-boq-exchange')).toBe(true);
    expect(routes.some((r) => r.path === '/au-boq-exchange')).toBe(true);
    expect(routes.some((r) => r.path === '/ca-boq-exchange')).toBe(true);
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
    expect(items.length).toBeGreaterThanOrEqual(4);
    expect(items.some((i) => i.to === '/sustainability')).toBe(true);
    expect(items.some((i) => i.to === '/benchmarks')).toBe(true);
    expect(items.some((i) => i.to === '/takeoff-viewer')).toBe(true);
    expect(items.some((i) => i.to === '/collaboration')).toBe(true);
  });

  it('should return nav items for regional group', () => {
    const items = getModuleNavItems('regional');
    expect(items.length).toBeGreaterThanOrEqual(6);
    expect(items.some((i) => i.to === '/uk-nrm-exchange')).toBe(true);
    expect(items.some((i) => i.to === '/us-masterformat-exchange')).toBe(true);
    expect(items.some((i) => i.to === '/fr-dpgf-exchange')).toBe(true);
    expect(items.some((i) => i.to === '/uae-boq-exchange')).toBe(true);
    expect(items.some((i) => i.to === '/au-boq-exchange')).toBe(true);
    expect(items.some((i) => i.to === '/ca-boq-exchange')).toBe(true);
  });

  it('should return empty array for non-existent group', () => {
    const items = getModuleNavItems('nonexistent');
    expect(items).toEqual([]);
  });
});

describe('getModuleSearchEntries', () => {
  it('should return search entries from all modules', () => {
    const entries = getModuleSearchEntries();
    expect(entries.length).toBeGreaterThanOrEqual(8);
  });

  it('should have keywords for each entry', () => {
    const entries = getModuleSearchEntries();
    for (const entry of entries) {
      expect(entry.keywords.length).toBeGreaterThan(0);
      expect(entry.path).toBeTruthy();
      expect(entry.label).toBeTruthy();
    }
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
    expect(defaults['gaeb-exchange']).toBe(false);
    expect(defaults['uk-nrm-exchange']).toBe(false);
    expect(defaults['us-masterformat-exchange']).toBe(false);
    expect(defaults['fr-dpgf-exchange']).toBe(false);
    expect(defaults['uae-boq-exchange']).toBe(false);
    expect(defaults['au-boq-exchange']).toBe(false);
    expect(defaults['ca-boq-exchange']).toBe(false);
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

  it('should have 6 regional modules in regional category', () => {
    const grouped = getModulesByCategory();
    expect(grouped['regional']!.length).toBeGreaterThanOrEqual(6);
  });
});
