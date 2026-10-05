// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// listScheduleMilestoneCandidates decides which schedule activities the
// payment plan picker offers. The link route refuses anything that is not a
// milestone by type, so the picker has to use the same test: a zero-duration
// task is not a milestone, and every milestone type the schedule knows is.

import { describe, it, expect, vi, beforeEach } from 'vitest';

const apiGet = vi.hoisted(() => vi.fn());
vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, apiGet };
});

import { listScheduleMilestoneCandidates } from './api';

beforeEach(() => {
  apiGet.mockReset();
});

describe('listScheduleMilestoneCandidates', () => {
  it('calls an activity a milestone by its type, not by its duration', async () => {
    apiGet.mockImplementation(async (path: string) => {
      if (path.startsWith('/v1/schedule/schedules/?')) {
        return { items: [{ id: 's-1', name: 'Main programme' }], total: 1 };
      }
      return {
        items: [
          { id: 'm', name: 'Handover', activity_type: 'milestone', duration_days: 0 },
          { id: 'sm', name: 'Start on site', activity_type: 'start_milestone' },
          { id: 'fm', name: 'Roof finished', activity_type: 'finish_milestone' },
          { id: 'zero', name: 'Inspection', activity_type: 'task', duration_days: 0 },
          { id: 'none', name: 'Untyped', activity_type: null },
          { id: 'sum', name: 'Shell', activity_type: 'summary' },
        ],
        total: 6,
      };
    });
    const rows = await listScheduleMilestoneCandidates('pr 1');
    expect(apiGet.mock.calls.some(([path]) => path === '/v1/schedule/schedules/?project_id=pr%201&limit=100')).toBe(
      true,
    );
    expect(Object.fromEntries(rows.map((r) => [r.id, r.is_milestone]))).toEqual({
      m: true,
      sm: true,
      fm: true,
      zero: false,
      none: false,
      sum: false,
    });
    expect(rows[0]).toMatchObject({ schedule_id: 's-1', schedule_name: 'Main programme' });
  });
});
