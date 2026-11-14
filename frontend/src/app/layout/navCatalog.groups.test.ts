// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The menu reads in the order a job runs, in groups an estimator and a site
// manager both recognise, and long groups are read by their section captions.
import { describe, expect, it } from 'vitest';
import {
  ASSISTANT_GROUP_ID,
  LEARN_GROUP_ID,
  NAV_GROUP_ALIASES,
  canonicalGroupId,
  navGroups,
  navSectionByRoute,
} from './navCatalog';

const ids = navGroups.map((g) => g.id);

describe('menu groups', () => {
  it('run Learn, the assistant, then the job from estimate to admin', () => {
    expect(ids).toEqual([
      LEARN_GROUP_ID,
      ASSISTANT_GROUP_ID,
      'grp_overview',
      'grp_estimating',
      'grp_cost_data',
      'grp_procurement',
      'grp_commercial',
      'grp_scheduling',
      'grp_site',
      'grp_quality',
      'grp_finance',
      'grp_documents',
      'grp_coordination',
      'grp_real_estate',
      'grp_automation_ai',
    ]);
  });

  it('put the AI chat in the assistant entry, alone', () => {
    const assistant = navGroups.find((g) => g.id === ASSISTANT_GROUP_ID)!;
    expect(assistant.items.map((i) => i.to)).toEqual(['/chat']);
  });

  it('keep every section in step with the rows of its group', () => {
    for (const group of navGroups) {
      if (!group.sections) continue;
      expect(group.sections.flatMap((s) => s.routes), group.id).toEqual(group.items.map((i) => i.to));
      expect(new Set(group.sections.map((s) => s.id)).size, group.id).toBe(group.sections.length);
      expect(group.sections.length, group.id).toBeGreaterThan(1);
    }
  });

  it('give each row of a sectioned group exactly one caption', () => {
    const estimating = navGroups.find((g) => g.id === 'grp_estimating')!;
    const byRoute = navSectionByRoute(estimating);
    expect(byRoute.get('/dwg-takeoff')?.id).toBe('takeoff');
    expect(byRoute.get('/boq')?.id).toBe('boq');
    expect(byRoute.size).toBe(estimating.items.length);
  });

  it('send every folded group id to a group that exists', () => {
    for (const [old, now] of Object.entries(NAV_GROUP_ALIASES)) {
      expect(ids, old).not.toContain(old);
      expect(ids, `${old} -> ${now}`).toContain(now);
      expect(canonicalGroupId(old)).toBe(now);
    }
    expect(canonicalGroupId('grp_quality')).toBe('grp_quality');
  });

  it('show Simple mode the rows it showed before, plus the assistant', () => {
    const simple = navGroups
      .filter((g) => !g.hideInSimple)
      .flatMap((g) => g.items.filter((i) => !i.advancedOnly).map((i) => i.to))
      .sort();
    expect(simple).toEqual(
      [
        '/videos', '/courses', '/cases', '/packs',
        '/chat',
        '/', '/projects', '/files', '/inbox', '/timeline',
        '/takeoff?tab=measurements', '/dwg-takeoff', '/bim', '/bim/rules', '/quantities',
        '/costs', '/catalog', '/cost-explorer', '/assemblies', '/cost-match', '/fx',
        '/boq', '/templates', '/regional-exchange', '/match-elements', '/project-intelligence', '/rom-estimate',
        '/methodologies',
        '/sheets',
        '/geo', '/pointcloud',
        '/contracts', '/payment-clock', '/tax-withholding', '/tax-rates', '/einvoice-clearance',
      ].sort(),
    );
  });
});
