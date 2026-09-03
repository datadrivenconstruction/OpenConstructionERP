// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * The pure helpers behind the department-request widgets: which five the
 * hub shows first, how a 404 is told apart from a real failure, and where
 * the chips and buttons land.
 *
 * Run: npx vitest run src/modules/comms-intelligence/WorkRequestsApi.test.ts
 */
import { describe, it, expect } from 'vitest';
import { ApiError } from '@/shared/lib/api';
import {
  departmentRequestsUrl,
  fmtHours,
  hoursProgress,
  isModuleAbsent,
  openOnly,
  projectWorkRequestsUrl,
  raiseWorkRequestUrl,
  sortByUrgency,
  workRequestUrl,
  type WorkRequestRow,
} from './WorkRequestsApi';

function row(over: Partial<WorkRequestRow> & { id: string }): WorkRequestRow {
  return {
    reference: `WR-WKS-${over.id.padStart(6, '0')}`,
    project_id: 'p1',
    project_code: '25406',
    department: 'workshop',
    request_type: 'fabrication',
    title: `Request ${over.id}`,
    status: 'open',
    stage: 'in_progress',
    due_date: null,
    is_overdue: false,
    ball_in_court: 'department',
    responsible: null,
    assignees: [],
    hours_logged: 0,
    quoted_hours: 0,
    deviation_hours: 0,
    created_at: '2026-09-01T00:00:00Z',
    ...over,
  };
}

describe('sortByUrgency', () => {
  it('puts overdue first, then earliest due, undated last, oldest among equals', () => {
    const sorted = sortByUrgency([
      row({ id: '1', due_date: null, created_at: '2026-09-02T00:00:00Z' }),
      row({ id: '2', due_date: '2026-09-20' }),
      row({ id: '3', due_date: '2026-08-20', is_overdue: true }),
      row({ id: '4', due_date: '2026-09-10' }),
      row({ id: '5', due_date: null, created_at: '2026-08-01T00:00:00Z' }),
      row({ id: '6', due_date: '2026-08-25', is_overdue: true }),
    ]);
    expect(sorted.map((r) => r.id)).toEqual(['3', '6', '4', '2', '5', '1']);
  });

  it('does not mutate its input', () => {
    const input = [row({ id: '2', due_date: '2026-09-20' }), row({ id: '1', is_overdue: true })];
    sortByUrgency(input);
    expect(input.map((r) => r.id)).toEqual(['2', '1']);
  });
});

describe('openOnly', () => {
  it('drops closed rows and keeps every other status', () => {
    const kept = openOnly([
      row({ id: '1', status: 'open' }),
      row({ id: '2', status: 'closed' }),
      row({ id: '3', status: 'on_hold' }),
    ]);
    expect(kept.map((r) => r.id)).toEqual(['1', '3']);
  });
});

describe('hoursProgress', () => {
  it('reads the share of the quote used and flags an overrun', () => {
    expect(hoursProgress(3, 6)).toEqual({ pct: 50, over: false, hasQuote: true });
    expect(hoursProgress(8, 6)).toEqual({ pct: 100, over: true, hasQuote: true });
    expect(hoursProgress(0, 6)).toEqual({ pct: 0, over: false, hasQuote: true });
  });

  it('with no quote, logged hours are an overrun and nothing logged is nothing', () => {
    expect(hoursProgress(2, 0)).toEqual({ pct: 100, over: true, hasQuote: false });
    expect(hoursProgress(0, 0)).toEqual({ pct: 0, over: false, hasQuote: false });
    expect(hoursProgress(Number.NaN, -1)).toEqual({ pct: 0, over: false, hasQuote: false });
  });
});

describe('fmtHours', () => {
  it('keeps whole hours whole and rounds the rest to one decimal', () => {
    expect(fmtHours(4)).toBe('4');
    expect(fmtHours(4.25)).toBe('4.3');
    expect(fmtHours(Number.NaN)).toBe('0');
  });
});

describe('isModuleAbsent', () => {
  it('is true only for an ApiError 404', () => {
    expect(isModuleAbsent(new ApiError(404, 'Not Found', { detail: 'Not Found' }))).toBe(true);
    expect(isModuleAbsent(new ApiError(500, 'Server Error', undefined))).toBe(false);
    expect(isModuleAbsent(new ApiError(403, 'Forbidden', undefined))).toBe(false);
    expect(isModuleAbsent(new Error('boom'))).toBe(false);
    expect(isModuleAbsent(null)).toBe(false);
  });
});

describe('urls', () => {
  it('open the request, the raise dialog on the job, and the department filter', () => {
    expect(workRequestUrl('abc')).toBe('/work-requests/abc');
    expect(raiseWorkRequestUrl('p 1')).toBe('/work-requests?raise=1&project=p%201');
    expect(projectWorkRequestsUrl('p1')).toBe('/projects/p1/work-requests');
    expect(departmentRequestsUrl('hazardous area')).toBe('/work-requests?department=hazardous%20area');
  });
});
