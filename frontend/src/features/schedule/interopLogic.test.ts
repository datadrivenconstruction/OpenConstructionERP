import { describe, expect, it } from 'vitest';

import {
  assigneeOptions,
  canSelectRow,
  defaultSelectedRows,
  formatShift,
  isChangedActivity,
  isDeviating,
  nonDefaultSettings,
  sortedEffects,
  todayIso,
  wbsPrefixes,
} from './interopLogic';
import { DEFAULT_PROFILE_SETTINGS, progressSheetQuery } from './interopApi';
import type { RecalculatedActivity, SheetPreviewRow, SourceComparisonRow } from './interopApi';

const row = (over: Partial<SheetPreviewRow>): SheetPreviewRow => ({
  row_number: 2,
  activity_id: 'a',
  activity_code: 'A1',
  name: 'Act',
  changes: {},
  issues: [],
  stale: false,
  has_errors: false,
  applicable: false,
  ...over,
});

describe('interopLogic', () => {
  it('lists top-level WBS prefixes once, in natural order', () => {
    expect(
      wbsPrefixes([{ wbs_code: '10.2' }, { wbs_code: '2.1' }, { wbs_code: '2.3' }, { wbs_code: '' }, {}]),
    ).toEqual(['2', '10']);
  });

  it('lists responsible people once, by name', () => {
    expect(
      assigneeOptions([
        { assignee_id: 'u2', assignee_name: 'Zoe' },
        { assignee_id: 'u1', assignee_name: 'Adam' },
        { assignee_id: 'u2', assignee_name: 'Zoe' },
        { assignee_id: null },
      ]),
    ).toEqual([
      { id: 'u1', name: 'Adam' },
      { id: 'u2', name: 'Zoe' },
    ]);
  });

  it('preselects applicable rows but never stale ones', () => {
    const rows = [
      row({ row_number: 2, applicable: true }),
      row({ row_number: 3, applicable: true, stale: true }),
      row({ row_number: 4, applicable: false, has_errors: true }),
    ];
    expect([...defaultSelectedRows(rows)]).toEqual([2]);
    expect(canSelectRow(rows[1]!)).toBe(true);
    expect(canSelectRow(rows[2]!)).toBe(false);
  });

  it('names the settings that differ from the built-in ones', () => {
    expect(
      nonDefaultSettings({ ...DEFAULT_PROFILE_SETTINGS, lag_calendar: 'project' }, DEFAULT_PROFILE_SETTINGS),
    ).toEqual(['lag_calendar']);
  });

  it('detects changed activities and sorts effects', () => {
    const base = {
      current_start: '2026-05-04',
      current_end: '2026-05-08',
      new_start: '2026-05-04',
      new_end: '2026-05-08',
      was_critical: false,
      is_critical: false,
    } as RecalculatedActivity;
    expect(isChangedActivity(base)).toBe(false);
    expect(isChangedActivity({ ...base, new_end: '2026-05-11' })).toBe(true);
    expect(isChangedActivity({ ...base, is_critical: true })).toBe(true);
    expect(sortedEffects({ lag_calendar: 1, status: 4, open_ends: 0 })).toEqual([
      ['status', 4],
      ['lag_calendar', 1],
    ]);
  });

  it('formats shifts and deviations', () => {
    expect(formatShift(3)).toBe('+3');
    expect(formatShift(-2)).toBe('-2');
    expect(formatShift(0)).toBe('0');
    expect(formatShift(null)).toBe('-');
    expect(isDeviating({ start_deviation_days: 0, finish_deviation_days: 2 } as SourceComparisonRow)).toBe(true);
    expect(isDeviating({ start_deviation_days: 0, finish_deviation_days: 0 } as SourceComparisonRow)).toBe(false);
    expect(todayIso(new Date(2026, 0, 5))).toBe('2026-01-05');
  });

  it('builds the progress sheet query string', () => {
    expect(progressSheetQuery({})).toBe('');
    expect(progressSheetQuery({ wbs: '01', includeCompleted: true, locale: 'de' })).toBe(
      '?wbs=01&include_completed=true&locale=de',
    );
  });
});
