// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import { applyDecisions, computeThreeWayMerge, deepEqual } from './threeWayMerge';

const SPEC = { longTextFields: ['notes', 'description'], checklistFields: ['checklist_data'] };

describe('computeThreeWayMerge - simple fields', () => {
  it('keeps the local edit when only this device changed the field', () => {
    const r = computeThreeWayMerge({
      base: { title: 'A' },
      mine: { title: 'B' },
      theirs: { title: 'A' },
      spec: SPEC,
    });
    expect(r.fields.title).toBe('B');
    expect(r.resolutions.title).toBe('mine');
    expect(r.conflicts).toEqual([]);
  });

  it('local edit wins a simple field both sides changed (last writer)', () => {
    const r = computeThreeWayMerge({
      base: { priority: 'low' },
      mine: { priority: 'high' },
      theirs: { priority: 'medium' },
      spec: SPEC,
    });
    expect(r.fields.priority).toBe('high');
    expect(r.resolutions.priority).toBe('mine');
    expect(r.conflicts).toHaveLength(0);
    expect(r.autoResolved).toContain('priority');
  });

  it('takes the server value when this device did not really change the field', () => {
    const r = computeThreeWayMerge({
      base: { labour_count: 4 },
      mine: { labour_count: 4 },
      theirs: { labour_count: 9 },
      spec: SPEC,
    });
    expect(r.fields.labour_count).toBe(9);
    expect(r.resolutions.labour_count).toBe('theirs');
  });

  it('treats a missing base as empty', () => {
    const r = computeThreeWayMerge({ base: null, mine: { title: 'x' }, theirs: {}, spec: SPEC });
    expect(r.fields.title).toBe('x');
  });
});

describe('computeThreeWayMerge - long text', () => {
  it('auto-resolves text changed on one side only', () => {
    const r = computeThreeWayMerge({
      base: { notes: 'one' },
      mine: { notes: 'one two' },
      theirs: { notes: 'one' },
      spec: SPEC,
    });
    expect(r.fields.notes).toBe('one two');
    expect(r.conflicts).toEqual([]);
  });

  it('is a conflict when both sides changed the text differently', () => {
    const r = computeThreeWayMerge({
      base: { description: 'crack' },
      mine: { description: 'crack, 2 m' },
      theirs: { description: 'crack at gridline C' },
      spec: SPEC,
    });
    expect(r.conflicts).toEqual([
      { kind: 'text', field: 'description', base: 'crack', mine: 'crack, 2 m', theirs: 'crack at gridline C' },
    ]);
    // Undecided conflicts hold the local value.
    expect(r.fields.description).toBe('crack, 2 m');
  });

  it('is no conflict when both sides made the same edit', () => {
    const r = computeThreeWayMerge({
      base: { notes: 'a' },
      mine: { notes: 'b' },
      theirs: { notes: 'b' },
      spec: SPEC,
    });
    expect(r.conflicts).toEqual([]);
    expect(r.fields.notes).toBe('b');
  });

  it('treats null and empty string as the same empty text', () => {
    const r = computeThreeWayMerge({
      base: { notes: null },
      mine: { notes: '' },
      theirs: { notes: 'new' },
      spec: SPEC,
    });
    expect(r.conflicts).toEqual([]);
    expect(r.fields.notes).toBe('new');
  });
});

describe('computeThreeWayMerge - checklist', () => {
  const item = (id: string, over: Record<string, unknown> = {}) => ({
    id,
    question: `q-${id}`,
    passed: true,
    notes: '',
    ...over,
  });

  it('merges items changed on different sides without asking', () => {
    const r = computeThreeWayMerge({
      base: { checklist_data: [item('a'), item('b')] },
      mine: { checklist_data: [item('a', { passed: false }), item('b')] },
      theirs: { checklist_data: [item('a'), item('b', { notes: 'seen' })] },
      spec: SPEC,
    });
    expect(r.conflicts).toEqual([]);
    expect(r.fields.checklist_data).toEqual([item('a', { passed: false }), item('b', { notes: 'seen' })]);
  });

  it('adds items created on either side', () => {
    const r = computeThreeWayMerge({
      base: { checklist_data: [item('a')] },
      mine: { checklist_data: [item('a'), item('m1')] },
      theirs: { checklist_data: [item('a'), item('t1')] },
      spec: SPEC,
    });
    const ids = (r.fields.checklist_data as Array<{ id: string }>).map((i) => i.id).sort();
    expect(ids).toEqual(['a', 'm1', 't1']);
  });

  it('flags only the item both sides changed differently', () => {
    const r = computeThreeWayMerge({
      base: { checklist_data: [item('a'), item('b')] },
      mine: { checklist_data: [item('a', { passed: false }), item('b', { notes: 'mine' })] },
      theirs: { checklist_data: [item('a', { passed: true, notes: 'ok' }), item('b')] },
      spec: SPEC,
    });
    expect(r.conflicts).toHaveLength(1);
    const c = r.conflicts[0]!;
    expect(c.kind).toBe('checklist');
    if (c.kind === 'checklist') expect(c.items.map((i) => i.id)).toEqual(['a']);
    // Item b changed only here: already merged.
    const b = (r.fields.checklist_data as Array<{ id: string; notes: string }>).find((i) => i.id === 'b');
    expect(b?.notes).toBe('mine');
  });

  it('removal on one side with no edit on the other removes the item', () => {
    const r = computeThreeWayMerge({
      base: { checklist_data: [item('a'), item('b')] },
      mine: { checklist_data: [item('a')] },
      theirs: { checklist_data: [item('a'), item('b')] },
      spec: SPEC,
    });
    expect(r.conflicts).toEqual([]);
    expect((r.fields.checklist_data as unknown[]).length).toBe(1);
  });

  it('removal against an edit is a conflict with a null side', () => {
    const r = computeThreeWayMerge({
      base: { checklist_data: [item('a')] },
      mine: { checklist_data: [] },
      theirs: { checklist_data: [item('a', { notes: 'edited' })] },
      spec: SPEC,
    });
    const c = r.conflicts[0];
    expect(c?.kind === 'checklist' && c.items[0]?.mine).toBeNull();
  });
});

describe('applyDecisions', () => {
  it('applies a text pick and records the resolution', () => {
    const merge = computeThreeWayMerge({
      base: { description: 'a' },
      mine: { description: 'b' },
      theirs: { description: 'c' },
      spec: SPEC,
    });
    const theirs = applyDecisions(merge, { text: { description: { choice: 'theirs' } } });
    expect(theirs.fields.description).toBe('c');
    expect(theirs.resolutions.description).toBe('theirs');
    expect(theirs.conflicts).toEqual([]);

    const manual = applyDecisions(merge, { text: { description: { choice: 'manual', value: 'b and c' } } });
    expect(manual.fields.description).toBe('b and c');
    expect(manual.resolutions.description).toBe('manual');
  });

  it('keeps an undecided conflict pending', () => {
    const merge = computeThreeWayMerge({
      base: { description: 'a' },
      mine: { description: 'b' },
      theirs: { description: 'c' },
      spec: SPEC,
    });
    expect(applyDecisions(merge, {}).conflicts).toHaveLength(1);
  });

  it('applies per-item checklist picks', () => {
    const it1 = (over = {}) => ({ id: 'a', question: 'q', passed: true, ...over });
    const merge = computeThreeWayMerge({
      base: { checklist_data: [it1()] },
      mine: { checklist_data: [it1({ passed: false })] },
      theirs: { checklist_data: [it1({ notes: 'x' })] },
      spec: SPEC,
    });
    const out = applyDecisions(merge, { checklist: { checklist_data: { a: 'theirs' } } });
    expect(out.conflicts).toEqual([]);
    expect(out.fields.checklist_data).toEqual([it1({ notes: 'x' })]);
    expect(out.resolutions.checklist_data).toBe('theirs');
  });
});

describe('deepEqual', () => {
  it('ignores key order', () => {
    expect(deepEqual({ a: 1, b: [1, { c: 2 }] }, { b: [1, { c: 2 }], a: 1 })).toBe(true);
    expect(deepEqual({ a: 1 }, { a: 2 })).toBe(false);
  });
});
