// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it, beforeEach } from 'vitest';
import type { PackageState, SolutionPackage } from '../api';
import {
  directDependents,
  isRouteHiddenByPackages,
  mergedMenu,
  mergedWidgets,
  selectionModules,
  withPackageDependencies,
} from '../logic';
import { PINNED_ROUTES_KEY, pinPackageMenu } from '../applyLayout';

function pkg(id: string, extra: Partial<SolutionPackage> = {}): SolutionPackage {
  return {
    id,
    icon: 'X',
    image: `illustration:${id}`,
    name_key: `packages.${id}.name`,
    value_key: `packages.${id}.value`,
    audience_key: `packages.${id}.audience`,
    required: [],
    optional: [],
    menu: [],
    widgets: [],
    demo_id: null,
    depends_on: [],
    ...extra,
  };
}

const PACKAGES = [
  pkg('estimate', { required: ['boq', 'validation'], menu: ['/boq', '/costs'], widgets: ['kpi'] }),
  pkg('tender', { required: ['tendering', 'boq'], menu: ['/tendering', '/boq'], widgets: ['kpi', 'inbox'], depends_on: ['estimate'] }),
  pkg('supply', { required: ['prefab'], menu: ['/prefab'] }),
];

const state = (modules: Record<string, boolean>, packaged = true): PackageState => ({
  installed: [],
  optional: [],
  modules,
  packaged,
});

describe('solution package rules', () => {
  it('selecting a package brings the packages it builds on', () => {
    expect(withPackageDependencies(PACKAGES, ['tender'])).toEqual(['estimate', 'tender']);
    expect(selectionModules(PACKAGES, ['tender'])).toEqual(['boq', 'validation', 'tendering']);
  });

  it('merges menus and widgets in package order without repeats', () => {
    expect(mergedMenu(PACKAGES, ['estimate', 'tender'])).toEqual(['/boq', '/costs', '/tendering']);
    expect(mergedWidgets(PACKAGES, ['estimate', 'tender'])).toEqual(['kpi', 'inbox']);
  });

  it('hides a route only when packages switched its module off', () => {
    expect(isRouteHiddenByPackages('oe_prefab', state({ prefab: false }))).toBe(true);
    expect(isRouteHiddenByPackages('oe_prefab', state({ prefab: true }))).toBe(false);
    expect(isRouteHiddenByPackages('oe_prefab', state({}))).toBe(false);
    expect(isRouteHiddenByPackages('oe_prefab', state({ prefab: false }, false))).toBe(false);
    expect(isRouteHiddenByPackages(undefined, state({ prefab: false }))).toBe(false);
    expect(isRouteHiddenByPackages(['oe_a', 'oe_b'], state({ a: false, b: true }))).toBe(false);
    expect(isRouteHiddenByPackages(['oe_a', 'oe_b'], state({ a: false, b: false }))).toBe(true);
  });

  it('names the enabled modules that depend on one', () => {
    const graph = [
      { key: 'clash', depends: ['bim_hub'] },
      { key: 'assets', depends: ['bim_hub'] },
      { key: 'bim_hub', depends: [] },
    ];
    expect(directDependents('bim_hub', graph, new Set(['clash', 'bim_hub']))).toEqual(['clash']);
  });
});

describe('package menu pins', () => {
  beforeEach(() => localStorage.clear());

  it('keeps existing pins and appends the package menu', () => {
    localStorage.setItem(PINNED_ROUTES_KEY, JSON.stringify(['/projects']));
    expect(pinPackageMenu(PACKAGES, ['estimate'])).toEqual(['/projects', '/boq', '/costs']);
    expect(pinPackageMenu(PACKAGES, ['estimate'])).toEqual(['/projects', '/boq', '/costs']);
  });
});
