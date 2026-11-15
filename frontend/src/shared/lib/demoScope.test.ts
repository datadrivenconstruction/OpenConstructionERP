// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { beforeEach, describe, expect, it } from 'vitest';
import {
  demoProjectFor,
  demoScopeFor,
  marketSwitchValue,
  scopeToProject,
  uiLanguageFor,
} from './demoScope';
import { DEMO_PROFILES } from './demoProfiles';
import { REGION_MAP } from '@/stores/useCostDatabaseStore';
import { MENU_MODE_IDS } from '@/app/layout/menuLayout';
import { useDemoSessionStore } from '@/stores/useDemoSessionStore';

// One shared demo account owns every demo project, and a few more.
const PROJECTS = [
  { id: 'riyadh', name: 'Riyadh tower', metadata: { demo_id: 'full-showcase-riyadh' } },
  { id: 'london', name: 'Halesworth House', metadata: { demo_id: 'office-london' } },
  { id: 'paris', name: 'Groupe scolaire', metadata: { demo_id: 'school-paris' } },
  { id: 'own', name: 'Visitor project', metadata: {} },
];

describe('demo project scope', () => {
  beforeEach(() => useDemoSessionStore.getState().setDemo(null));

  it('finds the project the installer marked with the demo slug', () => {
    expect(demoProjectFor(PROJECTS, 'office-london')?.id).toBe('london');
    expect(demoProjectFor(PROJECTS, 'medical-us')).toBeNull();
    expect(demoProjectFor(undefined, 'office-london')).toBeNull();
  });

  it('narrows lists to the open demo project in demo mode', () => {
    const scope = demoScopeFor({ demoMode: true, slug: 'office-london', showAll: false, projects: PROJECTS });
    expect(scope.profile?.slug).toBe('office-london');
    expect(scope.project).toEqual({ id: 'london', name: 'Halesworth House' });
    expect(scope.projectId).toBe('london');
    const estimates = [
      { id: 'b1', project_id: 'london' },
      { id: 'b2', project_id: 'riyadh' },
      { id: 'b3', project_id: 'paris' },
    ];
    expect(scopeToProject(estimates, scope.projectId, (b) => b.project_id)?.map((b) => b.id)).toEqual(['b1']);
  });

  it('shows everything when the visitor asks for all demo projects', () => {
    const scope = demoScopeFor({ demoMode: true, slug: 'office-london', showAll: true, projects: PROJECTS });
    expect(scope.project?.id).toBe('london');
    expect(scope.projectId).toBeNull();
    expect(scopeToProject(PROJECTS, scope.projectId, (p) => p.id)).toHaveLength(4);
  });

  it('never narrows outside demo mode, without a chosen demo, or before its project is known', () => {
    expect(demoScopeFor({ demoMode: false, slug: 'office-london', showAll: false, projects: PROJECTS }).projectId).toBeNull();
    expect(demoScopeFor({ demoMode: true, slug: null, showAll: false, projects: PROJECTS }).projectId).toBeNull();
    expect(demoScopeFor({ demoMode: true, slug: 'office-london', showAll: false, projects: undefined }).projectId).toBeNull();
  });

  it('opening a demo puts the lists back on its own project', () => {
    useDemoSessionStore.getState().setDemo('office-london');
    useDemoSessionStore.getState().setShowAll(true);
    expect(useDemoSessionStore.getState().showAll).toBe(true);
    expect(sessionStorage.getItem('oe_demo_show_all')).toBe('1');
    useDemoSessionStore.getState().setDemo('school-paris');
    expect(useDemoSessionStore.getState().showAll).toBe(false);
    expect(sessionStorage.getItem('oe_demo_show_all')).toBeNull();
  });

  it('gives every demo a known cost region and work mode from its profile', () => {
    DEMO_PROFILES.forEach((p) => {
      expect(REGION_MAP[p.costRegion], p.slug).toBeDefined();
      expect(MENU_MODE_IDS, p.slug).toContain(p.menuMode);
    });
    // The full platform keeps the whole menu; company demos open on a short list.
    DEMO_PROFILES.forEach((p) => expect(p.menuMode === 'all').toBe(p.groups === null));
  });
});

describe('language and market select', () => {
  const available = DEMO_PROFILES.map(({ slug, locale }) => ({ slug, locale }));

  it('shows the open demo while the interface speaks its language', () => {
    expect(marketSwitchValue('school-paris', available, 'fr')).toBe('school-paris');
    expect(marketSwitchValue('office-london', available, 'en-GB')).toBe('office-london');
  });

  it('shows no market when the card kept the visitor language', () => {
    expect(marketSwitchValue('school-paris', available, 'en')).toBe('');
    expect(marketSwitchValue('office-shanghai', available, 'en-US')).toBe('');
    expect(marketSwitchValue(null, available, 'en')).toBe('');
  });

  it('names the language the interface is in, English when none is stored', () => {
    expect(uiLanguageFor('de').code).toBe('de');
    expect(uiLanguageFor('en-US').code).toBe('en-US');
    expect(uiLanguageFor('fr-CA').code).toMatch(/^fr/);
    expect(uiLanguageFor('').code).toBe('en');
    expect(uiLanguageFor(undefined).code).toBe('en');
    expect(uiLanguageFor('xx-YY').code).toBe('en');
    expect(uiLanguageFor(undefined).name).toMatch(/^English/);
  });
});
