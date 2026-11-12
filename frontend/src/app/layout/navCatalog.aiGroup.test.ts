// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// The AI screens live in one clearly named group. A sidebar that shows them
// under any other heading is a user-made group (menu editor, stored in the
// browser), never the catalogue.

import { describe, expect, it } from 'vitest';
import { navGroups } from './navCatalog';
import { DEMO_PROFILES } from '@/shared/lib/demoProfiles';

const AI_ROUTES = ['/ai-agents', '/advisor', '/chat'];

describe('AI screens in the menu catalogue', () => {
  it('sit in the Automation & AI group and nowhere else', () => {
    for (const route of AI_ROUTES) {
      const owners = navGroups.filter((g) => g.items.some((i) => i.to === route)).map((g) => g.id);
      expect(owners, route).toEqual(['grp_automation_ai']);
    }
  });

  it('name that group through a translated key with an AI label', () => {
    const group = navGroups.find((g) => g.id === 'grp_automation_ai')!;
    expect(group.labelKey).toBe('sidebar.group.automation_ai');
    expect(group.defaultLabel).toMatch(/AI/);
  });

  it('are never regrouped by a demo profile, only shown or hidden with the whole group', () => {
    const ids = new Set(navGroups.map((g) => g.id));
    for (const p of DEMO_PROFILES) {
      for (const id of p.groups ?? []) expect(ids.has(id), `${p.slug}:${id}`).toBe(true);
    }
  });
});
