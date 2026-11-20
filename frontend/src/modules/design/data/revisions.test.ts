import { describe, expect, it } from 'vitest';
import {
  compareRevisions,
  overlayFor,
  toggleCompare,
  hasModel,
  type CompareElement,
  type RevisionView,
} from './revisions';

const el = (key: string, hash = 'h', extra: Partial<CompareElement> = {}): CompareElement => ({
  stable_id: key, name: key, element_type: 'wall', storey: 's01', geometry_hash: hash, quantities: { area: 10 }, ...extra,
});
const rev = (n: number, model: string | null = 'm'): RevisionView => ({
  revision_id: `r${n}`, project_id: 'p', number: n, parent_revision_id: null, status: 'shared', source_kind: 'editor',
  depth_level: 'D2', message: '', bim_model_id: model, decided_by: null, decided_at: null, decision_comment: null,
  created_at: '2026-01-01T00:00:00Z',
});

describe('compareRevisions', () => {
  const base = [el('b1/s01/w1'), el('b1/s01/w2'), el('b1/s01/w3')];
  const head = [el('b1/s01/w1'), el('b1/s01/w2', 'other'), el('b1/s01/w4')];
  const cmp = compareRevisions(base, head);

  it('splits by element key', () => {
    expect(cmp.added).toEqual(['b1/s01/w4']);
    expect(cmp.removed).toEqual(['b1/s01/w3']);
    expect(cmp.changed).toEqual(['b1/s01/w2']);
    expect(cmp.unchanged).toBe(1);
  });

  it('counts a quantity change and ignores float noise', () => {
    expect(compareRevisions([el('a')], [el('a', 'h', { quantities: { area: 10.5 } })]).changed).toEqual(['a']);
    expect(compareRevisions([el('a')], [el('a', 'h', { quantities: { area: 10 + 1e-9 } })]).changed).toEqual([]);
  });

  it('identical revisions have no differences, rows without a key are skipped', () => {
    const same = compareRevisions(base, base);
    expect([same.added, same.removed, same.changed]).toEqual([[], [], []]);
    expect(compareRevisions([{ name: 'x' }], [{ name: 'y' }]).unchanged).toBe(0);
  });

  it('colours the head with added+changed and the base with removed+changed', () => {
    expect([...overlayFor(cmp, 'head')]).toEqual([['b1/s01/w2', 'modified'], ['b1/s01/w4', 'added']]);
    expect([...overlayFor(cmp, 'base')]).toEqual([['b1/s01/w2', 'modified'], ['b1/s01/w3', 'deleted']]);
  });
});

describe('toggleCompare', () => {
  it('keeps two at most, ordered by number, dropping the older pick', () => {
    let sel = toggleCompare([], rev(3));
    sel = toggleCompare(sel, rev(1));
    expect(sel.map((r) => r.number)).toEqual([1, 3]);
    sel = toggleCompare(sel, rev(2));
    expect(sel.map((r) => r.number)).toEqual([2, 3]);
  });

  it('unselects on a second click', () => {
    expect(toggleCompare([rev(1), rev(2)], rev(1)).map((r) => r.number)).toEqual([2]);
  });

  it('a revision without a model cannot be opened', () => {
    expect(hasModel(rev(1, null))).toBe(false);
    expect(hasModel(rev(1))).toBe(true);
  });
});
