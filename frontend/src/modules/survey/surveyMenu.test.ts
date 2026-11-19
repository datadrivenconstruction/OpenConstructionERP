// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The Survey & Land menu group is empty until a survey module is switched on,
// and the sidebar drops a group with no rows (Sidebar.tsx merges the group's
// static rows with the enabled manifest rows and skips a group left with none).
import { afterEach, describe, expect, it } from 'vitest';
import { navGroups } from '@/app/layout/navCatalog';
import {
  MODULE_REGISTRY,
  getModuleDefaults,
  getModuleNavItems,
  navItemModuleId,
} from '@/modules/_registry';
import { CORE_MODULES, useModuleStore } from '@/stores/useModuleStore';

const GROUP = 'grp_survey';

function rowsInGroup(isEnabled: (key: string) => boolean): string[] {
  const group = navGroups.find((g) => g.id === GROUP)!;
  const dynamic = getModuleNavItems(group.dynamicGroupKey ?? group.id)
    .filter((mi) => isEnabled(navItemModuleId(mi)))
    .map((mi) => mi.to);
  return [...group.items.map((i) => i.to), ...dynamic];
}

// setState, not setModuleEnabled: the action also schedules a save to the server.
function turn(on: boolean): void {
  useModuleStore.setState((s) => ({ enabledModules: { ...s.enabledModules, survey_core: on } }));
}

afterEach(() => turn(false));

describe('Survey & Land menu group', () => {
  it('has no rows of its own, so it lives only on module manifests', () => {
    const group = navGroups.find((g) => g.id === GROUP)!;
    expect(group.items).toEqual([]);
    expect(group.labelKey).toBe('sidebar.group.survey');
    expect(group.defaultLabel).toBe('Survey & Land');
  });

  it('is hidden when no survey module is enabled (the shipped default)', () => {
    const defaults = getModuleDefaults();
    expect(defaults.survey_core).toBe(false);
    expect(rowsInGroup((key) => defaults[key] ?? true)).toEqual([]);
  });

  it('is hidden in the real store until the module is switched on, then shows the register', () => {
    turn(false);
    expect(useModuleStore.getState().isModuleEnabled('survey_core')).toBe(false);
    expect(rowsInGroup(useModuleStore.getState().isModuleEnabled)).toEqual([]);
    turn(true);
    expect(useModuleStore.getState().isModuleEnabled('survey_core')).toBe(true);
    expect(rowsInGroup(useModuleStore.getState().isModuleEnabled)).toEqual(['/survey', '/survey/points']);
    turn(false);
    expect(rowsInGroup(useModuleStore.getState().isModuleEnabled)).toEqual([]);
  });

  it('is filled by the survey register and the modules that depend on it, never by another module', () => {
    const publishers = MODULE_REGISTRY.filter((m) => m.navItems.some((i) => i.group === GROUP));
    expect(publishers.map((m) => m.id)).toContain('survey_core');
    for (const m of publishers) expect(m.id === 'survey_core' || (m.depends ?? []).includes('survey_core'), m.id).toBe(true);
  });

  it('is not part of the always-on core modules, so Settings > Modules can switch it off', () => {
    expect(CORE_MODULES.has('survey_core')).toBe(false);
  });

  it('keeps the register route out of the menu data of every other group', () => {
    const owners = navGroups.filter((g) => g.items.some((i) => i.to === '/survey')).map((g) => g.id);
    expect(owners).toEqual([]);
  });
});

describe('survey module manifest', () => {
  const survey = MODULE_REGISTRY.find((m) => m.id === 'survey_core')!;

  it('is off by default and names its page by translation key', () => {
    expect(survey.defaultEnabled).toBe(false);
    expect(survey.name).toBe('survey.page.register');
    expect(survey.description).toBe('survey.module_description');
  });

  it('serves the overview at /survey and the register at /survey/points', () => {
    expect(survey.routes.map((r) => r.path)).toEqual(['/survey', '/survey/points']);
    expect(survey.navItems.map((i) => [i.to, i.group])).toEqual([
      ['/survey', GROUP],
      ['/survey/points', GROUP],
    ]);
  });

  it('keeps /survey answering while the module is off, with the setup page', () => {
    expect(survey.offRoutes?.map((r) => r.path)).toEqual(['/survey']);
  });

  it('offers one collapsed setup row while the survey group is empty', () => {
    const group = navGroups.find((g) => g.id === GROUP)!;
    expect(group.emptyItem?.to).toBe('/survey');
    expect(group.emptyItem?.labelKey).toBe('survey.setup.nav');
  });
});
