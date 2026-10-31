// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import type { Conflict, DispatchLocation, Placement } from '../api';
import { addDays, conflictSummary, groupByLocation, mondayOf, sortLocations, toggle } from '../boardModel';

const loc = (id: string, kind: DispatchLocation['kind'], name: string): DispatchLocation => ({
  id,
  kind,
  name,
  project_id: null,
  sort_order: 0,
  is_active: true,
});

const pl = (id: string, location_id: string, start_time: string, label: string): Placement => ({
  id,
  day: '2026-11-03',
  card_kind: 'worker',
  card_ref: id,
  location_id,
  operator_ref: null,
  start_time,
  notes: '',
  source: 'manual',
  label,
  subtitle: '',
  status: '',
  members: [],
  conflict_kinds: [],
});

describe('dispatch board model', () => {
  it('shifts days across month ends and finds the Monday', () => {
    expect(addDays('2026-10-31', 1)).toBe('2026-11-01');
    expect(addDays('2026-11-01', -1)).toBe('2026-10-31');
    expect(mondayOf('2026-11-05')).toBe('2026-11-02');
    expect(mondayOf('2026-11-08')).toBe('2026-11-02');
  });

  it('puts sites first, then yard, shop and rental returned', () => {
    const out = sortLocations([loc('r', 'rental_return', 'R'), loc('y', 'yard', 'Y'), loc('b', 'project', 'B'), loc('a', 'project', 'A')]);
    expect(out.map((l) => l.id)).toEqual(['a', 'b', 'y', 'r']);
  });

  it('groups cards by column, earliest start first', () => {
    const g = groupByLocation([pl('1', 'A', '08:00', 'Zed'), pl('2', 'A', '06:30', 'Amy'), pl('3', 'B', '07:00', 'Bo')]);
    expect(g.A?.map((p) => p.id)).toEqual(['2', '1']);
    expect(g.B?.map((p) => p.id)).toEqual(['3']);
  });

  it('toggles selection without mutating', () => {
    const a = new Set(['x']);
    const b = toggle(a, 'y');
    expect([...b].sort()).toEqual(['x', 'y']);
    expect([...toggle(b, 'x')]).toEqual(['y']);
    expect([...a]).toEqual(['x']);
  });

  it('summarises conflicts with errors first', () => {
    const c = (kind: Conflict['kind'], severity: Conflict['severity']): Conflict => ({
      kind,
      severity,
      card_kind: 'worker',
      card_ref: 'w',
      message: '',
      placement_ids: [],
      details: {},
    });
    const s = conflictSummary([c('worker_absent', 'warning'), c('worker_absent', 'warning'), c('double_booked', 'error')]);
    expect(s.map((x) => [x.kind, x.count])).toEqual([
      ['double_booked', 1],
      ['worker_absent', 2],
    ]);
  });
});
