import { describe, expect, it } from 'vitest';

import type { Party } from '../api';
import { partyCategory } from '../PartiesHoneycomb';
import { edgeWidth } from '../PlatformMapCanvas';

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

describe('platform map edges', () => {
  it('grow thicker with the live count and stay bounded', () => {
    expect(edgeWidth(0, 'supporting')).toBeLessThan(edgeWidth(5, 'supporting'));
    expect(edgeWidth(5, 'supporting')).toBeLessThan(edgeWidth(350, 'supporting'));
    expect(edgeWidth(1_000_000, 'critical')).toBeLessThanOrEqual(1.75 + 4.5);
    expect(edgeWidth(null, 'high')).toBe(1.4);
  });
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
