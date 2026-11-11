// Pure-logic tests for the Inspections module: wire normaliser (via the API
// helpers), offline checklist id pairing, insights builder and guide keys.
import { describe, it, expect, vi, beforeEach } from 'vitest';

const apiMocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));
vi.mock('@/shared/lib/api', async (orig) => ({
  ...(await orig<typeof import('@/shared/lib/api')>()),
  ...apiMocks,
}));

import {
  fetchInspections,
  createInspection,
  completeInspection,
  createNcrFromInspection,
  updateInspection,
  deleteInspection,
} from '../api';
import { checklistWithIds, stripChecklistIds } from '../offlineChecklist';
import { buildInspectionsInsights } from '../inspectionsInsights';
import { inspectionsGuide } from '../inspectionsGuide';

const t = ((key: string, opts?: { defaultValue?: string }) => opts?.defaultValue ?? key) as never;

describe('inspections api', () => {
  beforeEach(() => vi.clearAllMocks());

  it('builds the query from set filters only', async () => {
    apiMocks.apiGet.mockResolvedValue({ items: [] });
    await fetchInspections();
    expect(apiMocks.apiGet).toHaveBeenLastCalledWith('/v1/inspections/');
    await fetchInspections({ project_id: 'p1', status: 'scheduled', result: 'fail', type: 'fire_safety' });
    const url = apiMocks.apiGet.mock.calls[1]![0] as string;
    expect(Object.fromEntries(new URLSearchParams(url.split('?')[1]))).toEqual({
      project_id: 'p1',
      status: 'scheduled',
      result: 'fail',
      type: 'fire_safety',
    });
  });

  it('normalises wire rows: inspector, date and checklist aliases', async () => {
    apiMocks.apiGet.mockResolvedValue({
      items: [
        {
          id: 'i1',
          inspector_name: 'Resolved Name',
          inspector_id: 'uuid',
          inspection_date: '2026-02-03',
          checklist_data: [
            { id: 'a', question: 'Rebar spacing?', response: 'No', critical: true, notes: null },
            { question: 'Formwork clean?', response: '' },
            { id: 'c', description: 'Cover', passed: false },
            { question: 'Ok?', response: 'yes' },
          ],
        },
        { id: 'i2', inspector_id: 'raw-typed', date: '2026-01-01' },
      ],
    });
    const page = await fetchInspections();
    const [a, b] = page.items;
    expect(a).toMatchObject({ inspector: 'Resolved Name', date: '2026-02-03', notes: '' });
    expect(a!.checklist).toEqual([
      { id: 'a', description: 'Rebar spacing?', passed: false, critical: true, notes: '' },
      { id: 'item-1', description: 'Formwork clean?', passed: true, critical: false, notes: '' },
      { id: 'c', description: 'Cover', passed: false, critical: false, notes: '' },
      { id: 'item-3', description: 'Ok?', passed: true, critical: false, notes: '' },
    ]);
    expect(b).toMatchObject({ inspector: 'raw-typed', date: '2026-01-01', checklist: [] });
  });

  it('create, complete and NCR helpers hit the right routes', async () => {
    apiMocks.apiPost.mockResolvedValue({ id: 'i1' });
    await createInspection({ project_id: 'p1', title: 'Slab' } as never);
    expect(apiMocks.apiPost).toHaveBeenLastCalledWith('/v1/inspections/', { project_id: 'p1', title: 'Slab' });
    await completeInspection('i1');
    expect(apiMocks.apiPost).toHaveBeenLastCalledWith('/v1/inspections/i1/complete/', { result: 'pass' });
    await completeInspection('i1', 'fail');
    expect(apiMocks.apiPost).toHaveBeenLastCalledWith('/v1/inspections/i1/complete/', { result: 'fail' });
    apiMocks.apiPost.mockResolvedValue({ ncr_id: 'n1', created: true });
    await expect(createNcrFromInspection('i1')).resolves.toMatchObject({ created: true });
    expect(apiMocks.apiPost).toHaveBeenLastCalledWith('/v1/inspections/i1/create-ncr/', {});
  });

  it('update sends If-Match only when a version is given', async () => {
    apiMocks.apiPatch.mockResolvedValue({ id: 'i1' });
    await updateInspection('i1', { location: 'L1' });
    expect(apiMocks.apiPatch).toHaveBeenLastCalledWith('/v1/inspections/i1', { location: 'L1' });
    await updateInspection('i1', { location: 'L1' }, 3);
    expect(apiMocks.apiPatch).toHaveBeenLastCalledWith(
      '/v1/inspections/i1',
      { location: 'L1', version: 3 },
      { headers: { 'If-Match': '3' } },
    );
  });

  it('delete uses the entry route', async () => {
    apiMocks.apiDelete.mockResolvedValue(undefined);
    await deleteInspection('i1');
    expect(apiMocks.apiDelete).toHaveBeenCalledWith('/v1/inspections/i1');
  });
});

describe('offline checklist ids', () => {
  const entry = (question: string) => ({ question }) as never;

  it('reuses the stored id for the same question and mints new ids otherwise', () => {
    let n = 0;
    const out = checklistWithIds(
      [entry('A'), entry('B'), entry('reworded')],
      [
        { id: 'id-a', description: 'A' },
        { id: 'id-b', description: 'B' },
        { id: 'id-c', description: 'C' },
      ],
      () => `new-${++n}`,
    );
    expect(out.map((o) => o.id)).toEqual(['id-a', 'id-b', 'new-1']);
  });

  it('pairs duplicate questions one-to-one', () => {
    const out = checklistWithIds(
      [entry('A'), entry('A'), entry('A')],
      [
        { id: 'x', description: 'A' },
        { id: 'y', description: 'A' },
      ],
      () => 'fresh',
    );
    expect(out.map((o) => o.id)).toEqual(['x', 'y', 'fresh']);
  });

  it('stripChecklistIds removes ids and passes other patches through', () => {
    expect(stripChecklistIds({ checklist_data: [{ id: 'x', question: 'A' }] })).toEqual({
      checklist_data: [{ question: 'A' }],
    });
    const patch = { location: 'L1' };
    expect(stripChecklistIds(patch)).toBe(patch);
  });
});

describe('buildInspectionsInsights', () => {
  const base = {
    title: 'I',
    status: 'completed',
    inspection_type: 'safety',
    result: 'pass' as string | null,
    date: '2026-04-10',
    created_at: '2026-04-01T00:00:00Z',
  };

  it('returns an empty dataset for no inspections', () => {
    const r = buildInspectionsInsights([], '', t);
    expect(r.datasets[0]!.rows).toEqual([]);
    expect(r.builtins.length).toBeGreaterThan(0);
  });

  it('derives passed / failed / open flags and a 0-100 pass rate', () => {
    const r = buildInspectionsInsights(
      [
        { ...base, title: 'p' },
        { ...base, title: 'f', result: 'fail', status: 'failed' },
        { ...base, title: 's', result: null, status: 'scheduled' },
        { ...base, title: 'w', result: 'partial', status: 'in_progress' },
      ],
      '',
      t,
    );
    const rows = Object.fromEntries(r.datasets[0]!.rows.map((x) => [x.title, x]));
    expect(rows.p).toMatchObject({ passed: 1, failed: 0, open: 0, pass_rate: 100, month: '2026-04' });
    expect(rows.f).toMatchObject({ passed: 0, failed: 1, open: 0, pass_rate: 0 });
    expect(rows.s).toMatchObject({ open: 1, result: 'Not recorded' });
    expect(rows.w).toMatchObject({ open: 1, result: 'Partial', status: 'In progress' });
  });

  it('falls back to created_at when date is empty and sorts chronologically', () => {
    const r = buildInspectionsInsights(
      [
        { ...base, title: 'b', date: '2026-06-01' },
        { ...base, title: 'a', date: '', created_at: '2026-02-01T00:00:00Z' },
      ],
      '',
      t,
    );
    expect(r.datasets[0]!.rows.map((x) => x.title)).toEqual(['a', 'b']);
    expect(r.datasets[0]!.rows[0]!.month).toBe('2026-02');
  });

  it('reads labels through inspections.* i18n keys only', () => {
    const seen: string[] = [];
    const spy = ((k: string, o?: { defaultValue?: string }) => {
      seen.push(k);
      return o?.defaultValue ?? k;
    }) as never;
    buildInspectionsInsights([base], '', spy);
    expect(seen.filter((k) => !k.startsWith('inspections.'))).toEqual([]);
    expect(seen).toEqual(
      expect.arrayContaining(['inspections.status_completed', 'inspections.type_safety', 'inspections.result_pass']),
    );
  });

  it('builtins reference only existing dataset fields', () => {
    const r = buildInspectionsInsights([], '', t);
    const keys = new Set(r.datasets[0]!.fields.map((f) => f.key));
    for (const b of r.builtins) {
      if (b.dimension) expect(keys.has(b.dimension)).toBe(true);
      if (b.measure) expect(keys.has(b.measure)).toBe(true);
    }
  });
});

describe('inspectionsGuide', () => {
  it('uses only guide.inspections.* keys with English defaults', () => {
    const entries: [string, string][] = [[inspectionsGuide.titleKey, inspectionsGuide.titleDefault]];
    if (inspectionsGuide.ctaKey) entries.push([inspectionsGuide.ctaKey, inspectionsGuide.ctaDefault ?? '']);
    for (const s of inspectionsGuide.sections) {
      entries.push([s.titleKey, s.titleDefault], [s.bodyKey, s.bodyDefault]);
    }
    for (const [k, d] of entries) {
      expect(k.startsWith('guide.inspections.')).toBe(true);
      expect(d.trim().length).toBeGreaterThan(0);
    }
    expect(new Set(entries.map(([k]) => k)).size).toBe(entries.length);
  });
});
