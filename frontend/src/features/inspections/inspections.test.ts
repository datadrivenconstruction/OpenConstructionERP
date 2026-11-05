import { describe, expect, it } from 'vitest';
import { checklistWithIds, stripChecklistIds } from './offlineChecklist';
import { buildInspectionsInsights } from './inspectionsInsights';

const t = ((k: string, o?: { defaultValue?: string }) => o?.defaultValue ?? k) as never;

describe('checklistWithIds', () => {
  const existing = [
    { id: 'i1', description: 'Rebar cover' },
    { id: 'i2', description: 'Formwork' },
  ];
  it('keeps the stored id for the same question, so the merge sees a change', () => {
    const out = checklistWithIds([{ question: 'Formwork', passed: true }], existing, () => 'n');
    expect(out).toEqual([{ question: 'Formwork', passed: true, id: 'i2' }]);
  });
  it('gives a reworded question a new id and pairs a duplicate question once', () => {
    const out = checklistWithIds(
      [{ question: 'Cover to rebar' }, { question: 'Formwork' }, { question: 'Formwork' }],
      existing,
      () => 'new',
    );
    expect(out.map((e) => e.id)).toEqual(['new', 'i2', 'new']);
  });
});

describe('stripChecklistIds', () => {
  it('drops ids from the checklist rows and leaves other fields', () => {
    const out = stripChecklistIds({ title: 'X', checklist_data: [{ id: 'i1', question: 'Q' }] });
    expect(out).toEqual({ title: 'X', checklist_data: [{ question: 'Q' }] });
  });
  it('returns a patch without a checklist untouched', () => {
    const p = { title: 'X' };
    expect(stripChecklistIds(p)).toBe(p);
  });
});

describe('buildInspectionsInsights', () => {
  const mk = (title: string, status: string, result: string | null, date: string) => ({
    title, status, inspection_type: 'safety', result, date, created_at: date,
  });
  it('derives pass rate and open flags, ordered by date', () => {
    const rows = buildInspectionsInsights(
      [mk('B', 'completed', 'fail', '2026-02-01'), mk('A', 'scheduled', null, '2026-01-01'), mk('C', 'completed', 'pass', '2026-03-01')],
      '',
      t,
    ).datasets[0]!.rows;
    expect(rows.map((r) => r.title)).toEqual(['A', 'B', 'C']);
    expect(rows[0]).toMatchObject({ open: 1, result: 'Not recorded', pass_rate: 0 });
    expect(rows[1]).toMatchObject({ failed: 1, open: 0 });
    expect(rows[2]).toMatchObject({ passed: 1, pass_rate: 100 });
  });
});
