// Last Planner board tests​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Pins the look-ahead board (ready / blocked cards), the constraints log
// (overdue highlight, linked record) and the PPC charts (average, Pareto
// cumulative line).
import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';

import { LookaheadBoardView } from './LookaheadBoard';
import { ConstraintsLogTable } from './ConstraintsLog';
import { PpcTrendChart, VariancePareto } from './PpcCharts';
import { commitErrorMessage, isValidLink } from './LpsFormFields';
import { ApiError } from '@/shared/lib/api';
import type { LpsBoard, LpsConstraintRow } from './api';

const board: LpsBoard = {
  look_ahead_id: 'la1',
  master_schedule_id: 'ms1',
  project_id: 'p1',
  period_start: '2026-06-01',
  period_end: '2026-06-14',
  weeks: ['2026-06-01', '2026-06-08'],
  ready_count: 1,
  blocked_count: 1,
  tasks: [
    {
      task_ref: 't1', name: 'Pour slab', wbs_code: '1.1', start_date: '2026-06-02', end_date: '2026-06-04',
      week_start: '2026-06-01', progress_pct: '0', is_ready: true, open_constraints: 0, committed: true, constraints: [],
    },
    {
      task_ref: 't2', name: 'Erect steel', wbs_code: '1.2', start_date: '2026-06-09', end_date: '2026-06-12',
      week_start: '2026-06-08', progress_pct: '0', is_ready: false, open_constraints: 2, committed: false,
      constraints: [],
    },
  ],
};

describe('LookaheadBoardView', () => {
  it('puts each task in its week and marks it ready or blocked', () => {
    render(<LookaheadBoardView board={board} />);
    const weeks = screen.getAllByTestId('lps-board-week');
    expect(weeks).toHaveLength(2);
    const ready = within(weeks[0]!).getByTestId('lps-board-task');
    expect(ready.getAttribute('data-ready')).toBe('true');
    expect(within(ready).getByText('Committed')).toBeTruthy();
    const blocked = within(weeks[1]!).getByTestId('lps-board-task');
    expect(blocked.getAttribute('data-ready')).toBe('false');
    expect(within(blocked).getByText('Blocked')).toBeTruthy();
    expect(within(blocked).getByText('2 open constraints')).toBeTruthy();
  });
});

describe('ConstraintsLogTable', () => {
  const row = (over: Partial<LpsConstraintRow>): LpsConstraintRow => ({
    id: 'c1', task_ref: 't1', task_name: 'Pour slab', constraint_type: 'material', description: 'Rebar late',
    status: 'open', target_clear_date: '2026-06-01', linked_type: 'purchase_order', linked_id: 'po1',
    linked_label: 'PO-17', linked_status: 'issued', ...over,
  });

  it('highlights an open constraint past its due date and shows the linked record', () => {
    render(<ConstraintsLogTable rows={[row({}), row({ id: 'c2', status: 'cleared' })]} today="2026-06-10" />);
    const rows = screen.getAllByTestId('constraints-log-row');
    expect(rows[0]!.getAttribute('data-overdue')).toBe('true');
    expect(rows[1]!.getAttribute('data-overdue')).toBe('false');
    expect(within(rows[0]!).getByText(/PO-17/)).toBeTruthy();
  });
});

describe('PPC charts', () => {
  it('draws a bar per week with a ppc and states the average', () => {
    render(
      <PpcTrendChart
        average="75"
        weeks={[
          { week_plan_id: 'a', week_start_date: '2026-06-01', status: 'closed', committed: 4, completed: 3, ppc_percent: '75' },
          { week_plan_id: 'b', week_start_date: '2026-06-08', status: 'draft', committed: 0, completed: 0, ppc_percent: null },
        ]}
      />,
    );
    expect(screen.getAllByTestId('ppc-bar')).toHaveLength(1);
    expect(screen.getByTestId('ppc-average').textContent).toContain('75');
  });

  it('draws the Pareto bars and the cumulative line', () => {
    render(
      <VariancePareto
        rows={[
          { category: 'material', count: 6, percent: '60', cumulative_percent: '60' },
          { category: 'weather', count: 3, percent: '30', cumulative_percent: '90' },
          { category: 'other', count: 1, percent: '10', cumulative_percent: '100' },
        ]}
      />,
    );
    expect(screen.getAllByTestId('pareto-bar')).toHaveLength(3);
    expect(screen.getByTestId('pareto-line').getAttribute('points')!.split(' ')).toHaveLength(3);
    const last = screen.getAllByTestId('pareto-row')[2]!;
    expect(last.textContent).toContain('cumulative 100%');
  });
});

describe('form helpers', () => {
  it('sends a linked record only as a complete pair', () => {
    expect(isValidLink('', '')).toBe(true);
    expect(isValidLink('rfi', '')).toBe(false);
    expect(isValidLink('rfi', '11111111-2222-3333-4444-555555555555')).toBe(true);
  });

  it('reads the constraints_open refusal in the page words', () => {
    const err = new ApiError(409, 'Conflict', { detail: { code: 'constraints_open' } });
    const t = ((_k: string, o?: { defaultValue?: string }) => o?.defaultValue ?? '') as never;
    expect(commitErrorMessage(err, t)).toContain('clear its open constraints');
  });
});
