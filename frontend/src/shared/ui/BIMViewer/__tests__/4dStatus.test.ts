/**
 * Tests for the pure 4D scrubber status resolver.
 *
 * These tests exercise every branch of `resolveElementStatus`,
 * `resolveActivityStatus`, `pickActiveActivityName` and
 * `computeScheduleBounds` without any React or Three.js deps — they're
 * the contract the viewer relies on to paint the right colour for the
 * right element at the right time.
 */

import { describe, it, expect } from 'vitest';
import {
  computeScheduleBounds,
  parseDate,
  pickActiveActivityName,
  resolveActivityStatus,
  resolveElementStatus,
  type FourDActivity,
} from '../4dStatus';

/** Helper to build an activity record without writing out null
 *  boilerplate for every test. */
function act(id: string, start: string | null, end: string | null, name = id): FourDActivity {
  return { id, name, start_date: start, end_date: end };
}

/** Helper: parse a date and assert it's finite — tests blow up
 *  noisily if the input isn't a valid ISO-8601 string. */
function ms(iso: string): number {
  const n = parseDate(iso);
  if (n == null) throw new Error(`Invalid ISO date in test fixture: ${iso}`);
  return n;
}

describe('parseDate', () => {
  it('parses YYYY-MM-DD as UTC midnight', () => {
    expect(parseDate('2026-01-01')).toBe(Date.UTC(2026, 0, 1));
  });

  it('truncates full ISO timestamps to the date portion', () => {
    expect(parseDate('2026-02-15T14:30:00Z')).toBe(Date.UTC(2026, 1, 15));
  });

  it('returns null for null / undefined / empty / malformed input', () => {
    expect(parseDate(null)).toBeNull();
    expect(parseDate(undefined)).toBeNull();
    expect(parseDate('')).toBeNull();
    expect(parseDate('not-a-date')).toBeNull();
  });
});

describe('resolveActivityStatus', () => {
  const a = act('a', '2026-01-01', '2026-02-01');

  it('not_started before the start date', () => {
    expect(resolveActivityStatus(a, ms('2025-12-31'))).toBe('not_started');
  });

  it('in_progress exactly at the start date', () => {
    expect(resolveActivityStatus(a, ms('2026-01-01'))).toBe('in_progress');
  });

  it('in_progress midway through the window', () => {
    expect(resolveActivityStatus(a, ms('2026-01-15'))).toBe('in_progress');
  });

  it('in_progress exactly at the end date (inclusive)', () => {
    expect(resolveActivityStatus(a, ms('2026-02-01'))).toBe('in_progress');
  });

  it('completed strictly after the end date', () => {
    expect(resolveActivityStatus(a, ms('2026-02-02'))).toBe('completed');
  });

  it('treats an activity with no dates as in_progress (permissive fallback)', () => {
    expect(resolveActivityStatus(act('x', null, null), ms('2026-01-01'))).toBe(
      'in_progress',
    );
  });

  it('treats an open-ended start (start only) as in_progress after start', () => {
    const openEnd = act('x', '2026-01-01', null);
    expect(resolveActivityStatus(openEnd, ms('2030-01-01'))).toBe('in_progress');
    expect(resolveActivityStatus(openEnd, ms('2025-01-01'))).toBe('not_started');
  });
});

describe('resolveElementStatus', () => {
  const a = act('act-1', '2026-01-01', '2026-02-01', 'Excavation');
  const byId = new Map<string, FourDActivity>([[a.id, a]]);

  it('returns "not_started" before the activity starts', () => {
    const links = new Map([['el-1', ['act-1']]]);
    expect(resolveElementStatus('el-1', ms('2025-12-01'), links, byId)).toBe(
      'not_started',
    );
  });

  it('returns "in_progress" at exactly the start', () => {
    const links = new Map([['el-1', ['act-1']]]);
    expect(resolveElementStatus('el-1', ms('2026-01-01'), links, byId)).toBe(
      'in_progress',
    );
  });

  it('returns "in_progress" midway', () => {
    const links = new Map([['el-1', ['act-1']]]);
    expect(resolveElementStatus('el-1', ms('2026-01-15'), links, byId)).toBe(
      'in_progress',
    );
  });

  it('returns "completed" after the end date', () => {
    const links = new Map([['el-1', ['act-1']]]);
    expect(resolveElementStatus('el-1', ms('2026-03-01'), links, byId)).toBe(
      'completed',
    );
  });

  it('returns "unlinked" when the element has no activity link', () => {
    const links = new Map<string, readonly string[]>();
    expect(resolveElementStatus('el-1', ms('2026-01-15'), links, byId)).toBe(
      'unlinked',
    );
  });

  it('returns "unlinked" when the activity links list is empty for this element', () => {
    const links = new Map([['el-1', [] as readonly string[]]]);
    expect(resolveElementStatus('el-1', ms('2026-01-15'), links, byId)).toBe(
      'unlinked',
    );
  });

  it('returns "unlinked" when every linked activity id is missing from activitiesById', () => {
    const links = new Map([['el-1', ['ghost-act']]]);
    expect(resolveElementStatus('el-1', ms('2026-01-15'), links, byId)).toBe(
      'unlinked',
    );
  });

  it('with multiple activities, prefers in_progress over completed/not_started', () => {
    const a1 = act('a1', '2026-01-01', '2026-02-01', 'First');
    const a2 = act('a2', '2026-01-20', '2026-03-01', 'Second');
    const a3 = act('a3', '2026-04-01', '2026-05-01', 'Third');
    const byId2 = new Map([
      [a1.id, a1],
      [a2.id, a2],
      [a3.id, a3],
    ]);
    const links = new Map([['el-1', ['a1', 'a2', 'a3']]]);
    // 2026-02-15: a1 completed, a2 in_progress, a3 not_started → in_progress
    expect(resolveElementStatus('el-1', ms('2026-02-15'), links, byId2)).toBe(
      'in_progress',
    );
  });

  it('with multiple activities all completed, returns completed', () => {
    const a1 = act('a1', '2026-01-01', '2026-02-01');
    const a2 = act('a2', '2026-02-01', '2026-03-01');
    const byId2 = new Map([
      [a1.id, a1],
      [a2.id, a2],
    ]);
    const links = new Map([['el-1', ['a1', 'a2']]]);
    expect(resolveElementStatus('el-1', ms('2026-06-01'), links, byId2)).toBe(
      'completed',
    );
  });

  it('with all activities not-yet-started, returns not_started', () => {
    const a1 = act('a1', '2026-05-01', '2026-06-01');
    const a2 = act('a2', '2026-07-01', '2026-08-01');
    const byId2 = new Map([
      [a1.id, a1],
      [a2.id, a2],
    ]);
    const links = new Map([['el-1', ['a1', 'a2']]]);
    expect(resolveElementStatus('el-1', ms('2026-01-01'), links, byId2)).toBe(
      'not_started',
    );
  });

  it('with a mix of completed + not_started (between phases), returns completed', () => {
    const a1 = act('a1', '2026-01-01', '2026-02-01'); // completed by March
    const a2 = act('a2', '2026-06-01', '2026-07-01'); // not_started in March
    const byId2 = new Map([
      [a1.id, a1],
      [a2.id, a2],
    ]);
    const links = new Map([['el-1', ['a1', 'a2']]]);
    expect(resolveElementStatus('el-1', ms('2026-03-15'), links, byId2)).toBe(
      'completed',
    );
  });
});

describe('pickActiveActivityName', () => {
  it('returns the earliest-starting in-progress activity', () => {
    const a1 = act('a1', '2026-01-01', '2026-03-01', 'First');
    const a2 = act('a2', '2026-02-01', '2026-04-01', 'Second');
    expect(pickActiveActivityName(ms('2026-02-15'), [a1, a2])).toBe('First');
    // reverse order — still "First" because a1 started earliest
    expect(pickActiveActivityName(ms('2026-02-15'), [a2, a1])).toBe('First');
  });

  it('falls back to the next upcoming activity when none are in progress', () => {
    const a1 = act('a1', '2026-02-01', '2026-03-01', 'Soon');
    const a2 = act('a2', '2026-05-01', '2026-06-01', 'Later');
    expect(pickActiveActivityName(ms('2026-01-15'), [a1, a2])).toBe('Soon');
  });

  it('falls back to the most-recent completed activity when everything is done', () => {
    const a1 = act('a1', '2026-01-01', '2026-02-01', 'Early');
    const a2 = act('a2', '2026-02-01', '2026-03-01', 'Late');
    expect(pickActiveActivityName(ms('2026-06-01'), [a1, a2])).toBe('Late');
  });

  it('returns null when given no activities', () => {
    expect(pickActiveActivityName(ms('2026-01-01'), [])).toBeNull();
  });
});

describe('computeScheduleBounds', () => {
  it('returns the earliest start and latest end across activities', () => {
    const acts = [
      act('a', '2026-02-01', '2026-03-01'),
      act('b', '2026-01-15', '2026-04-01'),
      act('c', '2026-03-01', '2026-03-15'),
    ];
    expect(computeScheduleBounds(acts)).toEqual({
      startMs: ms('2026-01-15'),
      endMs: ms('2026-04-01'),
    });
  });

  it('returns {null, null} when no activity has valid dates', () => {
    const acts = [act('a', null, null), act('b', 'bad-date', 'also-bad')];
    expect(computeScheduleBounds(acts)).toEqual({
      startMs: null,
      endMs: null,
    });
  });

  it('handles activities with only a start or only an end', () => {
    const acts = [act('a', '2026-01-01', null), act('b', null, '2026-05-01')];
    expect(computeScheduleBounds(acts)).toEqual({
      startMs: ms('2026-01-01'),
      endMs: ms('2026-05-01'),
    });
  });

  it('returns empty bounds for an empty activity list', () => {
    expect(computeScheduleBounds([])).toEqual({ startMs: null, endMs: null });
  });
});
