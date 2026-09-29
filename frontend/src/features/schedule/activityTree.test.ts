import { describe, expect, it } from 'vitest';
import { ancestorsOf, hideCollapsed, orderAsTree, parentIdsOf } from './activityTree';

const row = (id: string, parent_id: string | null = null) => ({ id, parent_id });

describe('orderAsTree', () => {
  it('puts a child created at the bottom of the flat order back under its section', () => {
    // Server order from before children were placed in their section block:
    // "Backfill" (child of s1) came back last.
    const flat = [row('s1'), row('a', 's1'), row('s2'), row('b', 's2'), row('new', 's1')];
    expect(orderAsTree(flat).map((a) => a.id)).toEqual(['s1', 'a', 'new', 's2', 'b']);
  });

  it('keeps siblings in the incoming order and nests at any depth', () => {
    const flat = [row('s1'), row('x', 's1'), row('x1', 'x'), row('y', 's1'), row('x2', 'x')];
    expect(orderAsTree(flat).map((a) => a.id)).toEqual(['s1', 'x', 'x1', 'x2', 'y']);
  });

  it('keeps a row whose parent is filtered out, and survives a parent cycle', () => {
    expect(orderAsTree([row('b', 'gone'), row('a')]).map((a) => a.id)).toEqual(['b', 'a']);
    const cyclic = [row('p', 'q'), row('q', 'p'), row('r')];
    expect(orderAsTree(cyclic).map((a) => a.id).sort()).toEqual(['p', 'q', 'r']);
  });
});

describe('collapsing', () => {
  const tree = [row('s1'), row('a', 's1'), row('a1', 'a'), row('s2'), row('b', 's2')];

  it('hides every row under a collapsed section, at any depth', () => {
    expect(hideCollapsed(tree, new Set(['s1'])).map((a) => a.id)).toEqual(['s1', 's2', 'b']);
  });

  it('still knows a collapsed section has children once they are hidden', () => {
    const visible = hideCollapsed(tree, new Set(['s1']));
    // Read from the visible rows, the collapsed section looks childless; that
    // was the lost chevron. Read from the whole schedule, it does not.
    expect(parentIdsOf(visible).has('s1')).toBe(false);
    expect(parentIdsOf(tree).has('s1')).toBe(true);
  });

  it('lists a row and all of its ancestors for auto-expanding', () => {
    expect(ancestorsOf('a1', tree)).toEqual(['a1', 'a', 's1']);
    expect(ancestorsOf('s2', tree)).toEqual(['s2']);
  });
});
