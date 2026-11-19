// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The menu keeps its thematic groups, in the order and under the names
// estimators and site managers learned, with Learn on top and no separate
// assistant entry.
import { describe, expect, it } from 'vitest';
import { LEARN_GROUP_ID, NAV_GROUP_ALIASES, canonicalGroupId, navGroups } from './navCatalog';

const ids = navGroups.map((g) => g.id);

describe('menu groups', () => {
  it('run Learn, then the thematic groups in their order', () => {
    expect(ids).toEqual([
      LEARN_GROUP_ID,
      'grp_overview',
      'grp_takeoff',
      'grp_cost_data',
      'grp_estimating',
      'grp_drawings',
      'grp_reality',
      'grp_survey',
      'grp_coordination',
      'grp_scheduling',
      'grp_cost_control',
      'grp_commercial',
      'grp_procurement',
      'grp_estimate_detail',
      'grp_change',
      'grp_records',
      'grp_field',
      'grp_site',
      'grp_resources',
      'grp_quality',
      'grp_handover',
      'grp_safety',
      'grp_esg',
      'grp_communication',
      'grp_documents',
      'grp_real_estate',
      'grp_finance',
      'grp_controls_bi',
      'grp_rate_buildup',
      'grp_estimating_ai',
      'grp_automation_ai',
    ]);
  });

  it('label each group with its own translated key and English fallback', () => {
    const labels = Object.fromEntries(navGroups.map((g) => [g.id, [g.labelKey, g.defaultLabel]]));
    expect(labels.grp_site).toEqual(['sidebar.group.on_site', 'On Site']);
    expect(labels.grp_commercial).toEqual(['sidebar.group.commercial', 'Commercial']);
    expect(labels.grp_automation_ai).toEqual(['sidebar.group.automation_ai', 'Automation & AI']);
    expect(new Set(navGroups.map((g) => g.labelKey)).size).toBe(navGroups.length);
  });

  it('list Learn as packs, cases, video guides, courses', () => {
    const learn = navGroups.find((g) => g.id === LEARN_GROUP_ID)!;
    expect(learn.items.map((i) => i.to)).toEqual(['/packs', '/cases', '/videos', '/courses']);
  });

  it('put every route in exactly one group', () => {
    const routes = navGroups.flatMap((g) => g.items.map((i) => i.to));
    expect(new Set(routes).size).toBe(routes.length);
  });

  it('send every alias id to a group that exists', () => {
    for (const [old, now] of Object.entries(NAV_GROUP_ALIASES)) {
      expect(ids, old).not.toContain(old);
      expect(ids, `${old} -> ${now}`).toContain(now);
      expect(canonicalGroupId(old)).toBe(now);
    }
    expect(canonicalGroupId('grp_assistant')).toBe('grp_automation_ai');
    expect(canonicalGroupId('grp_quality')).toBe('grp_quality');
  });

  it('show Simple mode the core rows only', () => {
    const simple = navGroups
      .filter((g) => !g.hideInSimple)
      .flatMap((g) => g.items.filter((i) => !i.advancedOnly).map((i) => i.to))
      .sort();
    expect(simple).toEqual(
      [
        '/videos', '/courses', '/cases', '/packs',
        '/', '/projects', '/files', '/inbox', '/timeline',
        '/takeoff?tab=measurements', '/dwg-takeoff', '/bim', '/bim/rules', '/quantities',
        '/costs', '/catalog', '/project-catalogue', '/cost-explorer', '/assemblies', '/cost-match', '/fx',
        '/boq', '/templates', '/regional-exchange', '/match-elements', '/project-intelligence', '/rom-estimate',
        '/methodologies',
        '/sheets',
        '/geo', '/pointcloud',
        '/contracts', '/framework-agreements', '/central-purchasing', '/payment-clock', '/tax-withholding', '/china-tax', '/tax-rates', '/einvoice-clearance',
      ].sort(),
    );
  });
});
