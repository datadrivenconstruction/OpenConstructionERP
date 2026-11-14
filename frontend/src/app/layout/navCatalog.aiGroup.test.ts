// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// The AI chat is the assistant entry at the top; the agents live in one
// clearly named group. A sidebar that shows them under any other heading is a
// user-made group (menu editor, stored in the browser), never the catalogue.

import { describe, expect, it } from 'vitest';
import { canonicalGroupId, navGroups } from './navCatalog';
import { DEMO_PROFILES } from '@/shared/lib/demoProfiles';

const OWNER: Record<string, string> = {
  '/chat': 'grp_assistant',
  '/ai-agents': 'grp_automation_ai',
  '/advisor': 'grp_estimating',
};

describe('AI screens in the menu catalogue', () => {
  it('each sit in one group', () => {
    for (const [route, owner] of Object.entries(OWNER)) {
      const owners = navGroups.filter((g) => g.items.some((i) => i.to === route)).map((g) => g.id);
      expect(owners, route).toEqual([owner]);
    }
  });

  it('name the agents group through a translated key with an AI label', () => {
    const group = navGroups.find((g) => g.id === 'grp_automation_ai')!;
    expect(group.labelKey).toBe('sidebar.group.automation_admin');
    expect(group.defaultLabel).toMatch(/AI/);
  });

  it('are never regrouped by a demo profile, only shown or hidden with the whole group', () => {
    const ids = new Set(navGroups.map((g) => g.id));
    for (const p of DEMO_PROFILES) {
      for (const id of p.groups ?? []) expect(ids.has(canonicalGroupId(id)), `${p.slug}:${id}`).toBe(true);
    }
  });
});
