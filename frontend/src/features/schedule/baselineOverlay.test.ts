import { describe, expect, it } from 'vitest';

import type { ScheduleBaseline } from './api';
import { approvalOf, baselineDatesById, baselinesOfSchedule, effectiveBaseline } from './baselineOverlay';

const bl = (over: Partial<ScheduleBaseline>): ScheduleBaseline => ({
  id: 'x',
  schedule_id: 's1',
  project_id: 'p1',
  name: 'B0',
  baseline_date: '2026-01-05',
  snapshot_data: {},
  is_active: false,
  created_by: null,
  created_at: '2026-01-01T00:00:00',
  updated_at: '2026-01-01T00:00:00',
  ...over,
});

describe('effectiveBaseline', () => {
  it('picks the latest approved active baseline', () => {
    const rows = [
      bl({ id: 'b0', name: 'B0', is_active: true, metadata_: { approval: { approved_at: '2026-01-10T09:00:00' } } }),
      bl({ id: 'b1', name: 'B1', is_active: true, metadata_: { approval: { approved_at: '2026-02-10T09:00:00' } } }),
      bl({ id: 'b2', name: 'B2', created_at: '2026-03-01T00:00:00' }),
    ];
    expect(effectiveBaseline(rows)?.name).toBe('B1');
  });

  it('falls back to the newest active row without stamps, and to null', () => {
    const rows = [
      bl({ id: 'old', is_active: true, created_at: '2026-01-01T00:00:00' }),
      bl({ id: 'new', is_active: true, created_at: '2026-02-01T00:00:00' }),
    ];
    expect(effectiveBaseline(rows)?.id).toBe('new');
    expect(effectiveBaseline([bl({})])).toBeNull();
  });

  it('reads the approval stamp only when it carries a time', () => {
    expect(approvalOf(bl({ metadata_: { approval: { approved_by: 'u' } } }))).toBeNull();
    expect(approvalOf(bl({ metadata_: { approval: { approved_at: 't' } } }))).toEqual({ approved_at: 't' });
  });
});

describe('baselinesOfSchedule', () => {
  it('keeps this schedule only, oldest first', () => {
    const rows = [
      bl({ id: 'b1', created_at: '2026-02-01' }),
      bl({ id: 'other', schedule_id: 's2' }),
      bl({ id: 'b0', created_at: '2026-01-01' }),
    ];
    expect(baselinesOfSchedule(rows, 's1').map((b) => b.id)).toEqual(['b0', 'b1']);
  });
});

describe('baselineDatesById', () => {
  it('matches by id, then by WBS code, and skips undated rows', () => {
    const snapshot = {
      activities: [
        { id: 'a1', start_date: '2026-01-05', end_date: '2026-01-23' },
        { id: 'imported-7', wbs_code: '1.2', start_date: '2026-01-26T00:00:00', end_date: '2026-03-06' },
        { id: 'a3' },
      ],
    };
    const map = baselineDatesById(snapshot, [
      { id: 'a1', wbs_code: '1.1' },
      { id: 'a2', wbs_code: '1.2' },
      { id: 'a3', wbs_code: '2' },
    ]);
    expect(map.get('a1')).toEqual({ start: '2026-01-05', end: '2026-01-23' });
    expect(map.get('a2')).toEqual({ start: '2026-01-26', end: '2026-03-06' });
    expect(map.has('a3')).toBe(false);
  });

  it('returns nothing for an empty or missing snapshot', () => {
    expect(baselineDatesById(null, [{ id: 'a' }]).size).toBe(0);
    expect(baselineDatesById({}, [{ id: 'a' }]).size).toBe(0);
  });
});
