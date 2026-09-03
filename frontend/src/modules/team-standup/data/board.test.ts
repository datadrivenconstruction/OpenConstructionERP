// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * Tests for the board helpers, each pinned to the failure it prevents.
 *
 * `list` exists because a real deploy broke the page: the browser held the
 * new chunk while rendering an old-shaped board payload, `job_ids` was
 * undefined, `.length` threw, and the error boundary swallowed the whole
 * screen. The day helpers exist because UTC arithmetic opens an AEST
 * team's board on the wrong date.
 */

import { describe, expect, it } from 'vitest';
import { jobLabel, list, localDay, shiftDay, weekStart } from './board';

describe('list', () => {
  it('passes a real array through untouched', () => {
    const xs = [1, 2, 3];
    expect(list(xs)).toBe(xs);
  });

  it('turns a missing field into an empty array rather than throwing', () => {
    // The exact shape an old backend sends: the key simply is not there.
    const stale = { user_id: 'u1' } as { user_id: string; job_ids?: string[] };
    expect(list(stale.job_ids)).toEqual([]);
    expect(() => list(stale.job_ids).length).not.toThrow();
    expect(list(null)).toEqual([]);
  });

  it('refuses a non-array masquerading as one', () => {
    expect(list('nope' as unknown as string[])).toEqual([]);
    expect(list({ 0: 'a', length: 1 } as unknown as string[])).toEqual([]);
  });
});

describe('localDay', () => {
  it('names the LOCAL calendar day, not the UTC one', () => {
    // 09:00 on 1 Sep in Sydney is still 23:00 on 31 Aug UTC. A board keyed
    // off toISOString() would open on the 31st for the whole morning.
    const nineAmLocal = new Date(2026, 8, 1, 9, 0, 0);
    expect(localDay(nineAmLocal)).toBe('2026-09-01');

    // And late evening must not roll forward either.
    const elevenPmLocal = new Date(2026, 8, 1, 23, 30, 0);
    expect(localDay(elevenPmLocal)).toBe('2026-09-01');
  });

  it('zero-pads so days sort as strings', () => {
    expect(localDay(new Date(2026, 0, 5))).toBe('2026-01-05');
  });
});

describe('shiftDay', () => {
  it('steps forward and back across month and year ends', () => {
    expect(shiftDay('2026-09-01', -1)).toBe('2026-08-31');
    expect(shiftDay('2026-08-31', 1)).toBe('2026-09-01');
    expect(shiftDay('2026-01-01', -1)).toBe('2025-12-31');
    expect(shiftDay('2026-09-01', -6)).toBe('2026-08-26');
  });

  it('handles a leap day', () => {
    expect(shiftDay('2028-02-28', 1)).toBe('2028-02-29');
    expect(shiftDay('2028-02-29', 1)).toBe('2028-03-01');
  });
});

describe('weekStart', () => {
  it('returns the Monday of that week', () => {
    // 2026-09-01 is a Tuesday.
    expect(weekStart('2026-09-01')).toBe('2026-08-31');
    // A Monday is its own week start...
    expect(weekStart('2026-08-31')).toBe('2026-08-31');
    // ...and Sunday belongs to the week that started six days earlier,
    // not to the one about to begin.
    expect(weekStart('2026-09-06')).toBe('2026-08-31');
  });
});

describe('jobLabel', () => {
  it('leads with the job number when there is one', () => {
    expect(jobLabel({ id: 'x', name: 'Northbank - Plant C', code: '25406' })).toBe(
      '25406 · Northbank - Plant C',
    );
  });

  it('falls back to the bare name for an auto-coded job', () => {
    expect(jobLabel({ id: 'x', name: 'New Job', code: '' })).toBe('New Job');
  });
});

// ── Delivery-board filter predicates ─────────────────────────────────────
// Imported separately so the block above stays a verbatim record of the
// deploy incident it documents.
import { UNASSIGNED, assigneeMatches, dueMatches, isWorkshopRequest } from './board';

describe('dueMatches', () => {
  // Wednesday 2 Sep 2026; the week ends Friday 4 Sep.
  const win = { today: '2026-09-02', endWeek: '2026-09-04' };

  it('never calls a closed task overdue', () => {
    expect(dueMatches('2026-08-30', false, 'overdue', win)).toBe(true);
    expect(dueMatches('2026-08-30', true, 'overdue', win)).toBe(false);
    expect(dueMatches('2026-09-02', false, 'overdue', win)).toBe(false);
  });

  it('this week runs today to Friday, next week is the seven days after', () => {
    expect(dueMatches('2026-09-02', false, 'week', win)).toBe(true);
    expect(dueMatches('2026-09-04', false, 'week', win)).toBe(true);
    expect(dueMatches('2026-09-05', false, 'week', win)).toBe(false);
    expect(dueMatches('2026-09-01', false, 'week', win)).toBe(false);
    expect(dueMatches('2026-09-05', false, 'nextweek', win)).toBe(true);
    expect(dueMatches('2026-09-11', false, 'nextweek', win)).toBe(true);
    expect(dueMatches('2026-09-12', false, 'nextweek', win)).toBe(false);
  });

  it('no date matches only undated tasks, and a range respects its ends', () => {
    expect(dueMatches('', false, 'none', win)).toBe(true);
    expect(dueMatches(null, false, 'none', win)).toBe(true);
    expect(dueMatches('2026-09-02', false, 'none', win)).toBe(false);
    const r = { ...win, from: '2026-09-10', to: '2026-09-20' };
    expect(dueMatches('2026-09-10', false, 'range', r)).toBe(true);
    expect(dueMatches('2026-09-20', false, 'range', r)).toBe(true);
    expect(dueMatches('2026-09-21', false, 'range', r)).toBe(false);
    expect(dueMatches('', false, 'range', r)).toBe(false);
    expect(dueMatches('2026-01-01', false, 'range', { ...win, from: '', to: '2026-09-20' })).toBe(true);
  });
});

describe('assigneeMatches', () => {
  const known = (id: string) => id === 'u1' || id === 'u2';

  it('an empty selection is everyone', () => {
    expect(assigneeMatches('u1', known, [])).toBe(true);
    expect(assigneeMatches('', known, [])).toBe(true);
  });

  it('a departed or missing assignee counts as unassigned', () => {
    expect(assigneeMatches('gone', known, [UNASSIGNED])).toBe(true);
    expect(assigneeMatches('', known, [UNASSIGNED])).toBe(true);
    expect(assigneeMatches('u1', known, [UNASSIGNED])).toBe(false);
    expect(assigneeMatches('u1', known, ['u2', 'u1'])).toBe(true);
    expect(assigneeMatches('u2', known, ['u1'])).toBe(false);
  });
});

describe('isWorkshopRequest', () => {
  it('trusts the module when it answered, the reference when it did not', () => {
    expect(isWorkshopRequest('WR-DRF-000001', 'workshop')).toBe(true);
    expect(isWorkshopRequest('WR-WKS-000001', 'drafting')).toBe(false);
    expect(isWorkshopRequest('WR-WKS-000001', undefined)).toBe(true);
    expect(isWorkshopRequest('WR-DRF-000001', undefined)).toBe(false);
    expect(isWorkshopRequest('', undefined)).toBe(false);
  });
});
