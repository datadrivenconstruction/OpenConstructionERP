// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { groupClockEvents, twoWeeksAgo } from './clockLog';
import type { ClockEvent } from './clockApi';

const ev = (p: Partial<ClockEvent>): ClockEvent => ({
  id: 'e', project_id: 'p', resource_id: 'r1', resource_name: 'Ann', kind: 'in',
  occurred_at: '2026-10-20T07:00:00', latitude: null, longitude: null, accuracy_m: null,
  geofence_id: null, geofence_name: null, inside: true, distance_m: null,
  approval_status: 'not_required', approval_reason: null, approved_by: null, approved_at: null,
  pair_event_id: null, timesheet_id: null, position_purged: false, created_at: '', ...p,
});

describe('groupClockEvents', () => {
  it('marks an unpaired in on a past day as missing clock-out', () => {
    const days = groupClockEvents([ev({ id: 'a' })], '2026-10-25');
    expect(days[0]!.workers[0]!.missingOut).toBe(true);
    expect(days[0]!.missingOut).toBe(1);
  });

  it('treats an unpaired in today as an open shift, not a miss', () => {
    const days = groupClockEvents([ev({ id: 'a', occurred_at: '2026-10-25T07:00:00' })], '2026-10-25');
    expect(days[0]!.workers[0]!.open).toBe(true);
    expect(days[0]!.workers[0]!.missingOut).toBe(false);
  });

  it('a paired shift is complete and days sort newest first', () => {
    const days = groupClockEvents(
      [
        ev({ id: 'a', pair_event_id: 'b' }),
        ev({ id: 'b', kind: 'out', occurred_at: '2026-10-20T15:00:00', pair_event_id: 'a' }),
        ev({ id: 'c', occurred_at: '2026-10-22T07:00:00', pair_event_id: 'd', approval_status: 'pending' }),
      ],
      '2026-10-25',
    );
    expect(days.map((d) => d.date)).toEqual(['2026-10-22', '2026-10-20']);
    expect(days[1]!.workers[0]!.missingOut).toBe(false);
    expect(days[0]!.pending).toBe(1);
  });

  it('twoWeeksAgo is 13 days back', () => {
    expect(twoWeeksAgo('2026-10-25')).toBe('2026-10-12');
  });
});
