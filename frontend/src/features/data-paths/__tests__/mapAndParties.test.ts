import { describe, expect, it } from 'vitest';

import type { Party } from '../api';
import { partyCategory } from '../PartiesHoneycomb';

const party = (over: Partial<Party>): Party => ({
  id: 'p',
  kind: 'company',
  name: 'Kurpfalz Kaeltetechnik GmbH',
  initials: 'KK',
  zone: 'delivery',
  roles: [],
  modules: [],
  placeholder: false,
  ...over,
});

describe('honeycomb colours', () => {
  it('use the role the server ranked first', () => {
    expect(partyCategory(party({ roles: ['supplier', 'contractor'], primary_role: 'contractor' }))).toBe('contractor');
  });

  it('fall back to the strongest role, and people are always people', () => {
    expect(partyCategory(party({ roles: ['bidder', 'subcontractor'] }))).toBe('subcontractor');
    expect(partyCategory(party({ roles: ['engineer'] }))).toBe('consultant');
    expect(partyCategory(party({ kind: 'person', roles: ['site_manager'] }))).toBe('person');
  });
});
