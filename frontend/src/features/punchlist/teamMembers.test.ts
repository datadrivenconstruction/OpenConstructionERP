/**
 * The Assigned To picker names people, and shows an email only to tell two of
 * them apart.
 *
 * Every account used to be listed as "Name - email", which put the whole
 * workspace's addresses in front of anyone raising a snag, and into every
 * screen share of it.
 */
import { describe, expect, it } from 'vitest';

import { withDisambiguation, type TeamMember } from './api';

const person = (over: Partial<TeamMember>): TeamMember => ({
  id: 'u',
  name: 'Name',
  email: 'name@example.com',
  avatar_url: null,
  assignable: true,
  on_roster: false,
  ...over,
});

describe('withDisambiguation', () => {
  it('shows no email for a name that is unique in the list', () => {
    const out = withDisambiguation([
      person({ id: 'a', name: 'Ana Silva', email: 'ana@example.com' }),
      person({ id: 'b', name: 'Ben Okafor', email: 'ben@example.com' }),
    ]);
    expect(out.map((m) => m.detail)).toEqual([undefined, undefined]);
  });

  it('shows the email for two people who share a name, however it is spaced or cased', () => {
    const out = withDisambiguation([
      person({ id: 'a', name: 'Ana Silva', email: 'ana.silva@example.com' }),
      person({ id: 'b', name: ' ana  silva', email: 'asilva@example.org' }),
      person({ id: 'c', name: 'Ben Okafor', email: 'ben@example.com' }),
    ]);
    expect(out.map((m) => m.detail)).toEqual(['ana.silva@example.com', 'asilva@example.org', undefined]);
  });

  it('keeps a roster row firm and role, which already tell people apart', () => {
    const out = withDisambiguation([
      person({ id: 'a', name: 'Ana Silva', on_roster: true, detail: 'Acme Drylining · Foreman' }),
      person({ id: 'b', name: 'Ana Silva', email: 'ana@example.com' }),
    ]);
    expect(out[0]!.detail).toBe('Acme Drylining · Foreman');
    expect(out[1]!.detail).toBe('ana@example.com');
  });
});
