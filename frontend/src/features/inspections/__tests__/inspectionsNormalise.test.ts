// Edge cases of the inspections wire normaliser and error propagation.
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

import { fetchInspections, completeInspection, createNcrFromInspection, updateInspection } from '../api';
import { checklistWithIds, stripChecklistIds } from '../offlineChecklist';

async function normalise(row: Record<string, unknown>) {
  apiMocks.apiGet.mockResolvedValue({ items: [row] });
  const out = await fetchInspections();
  return (out as unknown as { items: Array<Record<string, unknown>> }).items?.[0] ?? (out as never)[0];
}

describe('inspections normaliser', () => {
  beforeEach(() => vi.clearAllMocks());

  it('derives passed from the response text when no explicit flag exists', async () => {
    const row = await normalise({
      id: 'i1',
      checklist_data: [
        { question: 'a', response: 'No' },
        { question: 'b', response: ' FAILED ' },
        { question: 'c', response: '0' },
        { question: 'd', response: 'yes' },
        { question: 'e', response: null },
        { question: 'f' },
      ],
    });
    const passed = (row.checklist as Array<{ passed: boolean }>).map((c) => c.passed);
    expect(passed).toEqual([false, false, false, true, true, true]);
  });

  it('an explicit passed flag wins over the response text', async () => {
    const row = await normalise({
      id: 'i1',
      checklist: [
        { question: 'a', response: 'no', passed: true },
        { question: 'b', response: 'yes', passed: false },
      ],
    });
    expect((row.checklist as Array<{ passed: boolean }>).map((c) => c.passed)).toEqual([true, false]);
  });

  it('mints positional ids, prefers description over question and defaults notes', async () => {
    const row = await normalise({
      id: 'i1',
      checklist: [{ question: 'Q', description: 'D' }, { id: 'keep', question: 'Q2', critical: true }],
    });
    const items = row.checklist as Array<Record<string, unknown>>;
    expect(items[0]).toEqual({ id: 'item-0', description: 'D', passed: true, critical: false, notes: '' });
    expect(items[1]).toMatchObject({ id: 'keep', description: 'Q2', critical: true });
  });

  it('prefers checklist over checklist_data and tolerates neither', async () => {
    const both = await normalise({ id: 'i1', checklist: [{ question: 'x' }], checklist_data: [{ question: 'y' }] });
    expect((both.checklist as Array<{ description: string }>)[0]!.description).toBe('x');
    const none = await normalise({ id: 'i2' });
    expect(none.checklist).toEqual([]);
    expect(none.notes).toBe('');
    expect(none.date).toBe('');
    expect(none.inspector).toBe('');
  });

  it('inspector falls back from resolved name to stored value to id', async () => {
    expect((await normalise({ id: 'a', inspector_name: 'Ann', inspector: 'x', inspector_id: 'u' })).inspector).toBe('Ann');
    expect((await normalise({ id: 'b', inspector: 'Typed', inspector_id: 'u' })).inspector).toBe('Typed');
    expect((await normalise({ id: 'c', inspector_id: 'u-1' })).inspector).toBe('u-1');
  });

  it('date falls back to inspection_date, and an own date wins', async () => {
    expect((await normalise({ id: 'a', inspection_date: '2026-05-01' })).date).toBe('2026-05-01');
    expect((await normalise({ id: 'b', date: '2026-06-01', inspection_date: '2026-05-01' })).date).toBe('2026-06-01');
  });
});

describe('inspections errors and checklist edge cases', () => {
  beforeEach(() => vi.clearAllMocks());

  it('propagates API failures instead of swallowing them', async () => {
    apiMocks.apiGet.mockRejectedValue(new Error('offline'));
    await expect(fetchInspections()).rejects.toThrow('offline');
    apiMocks.apiPost.mockRejectedValue(new Error('403'));
    await expect(completeInspection('i1', 'fail')).rejects.toThrow('403');
    await expect(createNcrFromInspection('i1')).rejects.toThrow('403');
    apiMocks.apiPatch.mockRejectedValue(new Error('409'));
    await expect(updateInspection('i1', {}, 3)).rejects.toThrow('409');
  });

  it('completeInspection defaults the result to pass', async () => {
    apiMocks.apiPost.mockResolvedValue({ id: 'i1' });
    await completeInspection('i1');
    expect(apiMocks.apiPost).toHaveBeenCalledWith('/v1/inspections/i1/complete/', { result: 'pass' });
  });

  it('checklistWithIds handles empty inputs', () => {
    expect(checklistWithIds([], [{ id: 'a', description: 'x' }])).toEqual([]);
    const out = checklistWithIds([{ question: 'q' } as never], [], () => 'gen');
    expect(out[0]!.id).toBe('gen');
  });

  it('stripChecklistIds leaves a patch without a checklist untouched', () => {
    const patch = { notes: 'n' };
    expect(stripChecklistIds(patch)).toBe(patch);
  });
});
