import { describe, it, expect, beforeEach } from 'vitest';
import { useAnalysisStateStore } from '@/stores/useAnalysisStateStore';

function reset(): void {
  const s = useAnalysisStateStore.getState();
  s.clearSlicers();
  // Drop the session so saved views and chart config are forgotten.
  s.setSessionId(null);
}

describe('useAnalysisStateStore — slicers', () => {
  beforeEach(() => {
    localStorage.clear();
    reset();
  });

  it('starts with no slicers', () => {
    expect(useAnalysisStateStore.getState().slicers).toEqual([]);
  });

  it('adds a slicer for a new column', () => {
    useAnalysisStateStore.getState().addSlicer('Material', ['Concrete']);
    const s = useAnalysisStateStore.getState().slicers;
    expect(s).toHaveLength(1);
    expect(s[0]).toEqual({ column: 'Material', values: ['Concrete'] });
  });

  it('replaces the slicer values when addSlicer is called again with the same column', () => {
    const store = useAnalysisStateStore.getState();
    store.addSlicer('Material', ['Concrete']);
    store.addSlicer('Material', ['Steel', 'Wood']);
    const s = useAnalysisStateStore.getState().slicers;
    expect(s).toHaveLength(1);
    expect(s[0]?.values).toEqual(['Steel', 'Wood']);
  });

  it('does not produce a new object when addSlicer is called with identical values', () => {
    const store = useAnalysisStateStore.getState();
    store.addSlicer('Material', ['Concrete', 'Steel']);
    const before = useAnalysisStateStore.getState().slicers;
    // Order differs but values are equivalent — the debounce/diff guard
    // should short-circuit so the slicers reference is unchanged.
    store.addSlicer('Material', ['Steel', 'Concrete']);
    const after = useAnalysisStateStore.getState().slicers;
    expect(after).toBe(before);
  });

  it('composes slicers across multiple columns (AND logic)', () => {
    const store = useAnalysisStateStore.getState();
    store.addSlicer('Material', ['Concrete']);
    store.addSlicer('Level', ['L1']);
    const s = useAnalysisStateStore.getState().slicers;
    expect(s).toHaveLength(2);
    expect(s.map((x) => x.column).sort()).toEqual(['Level', 'Material']);
  });

  it('removes a specific slicer without touching the others', () => {
    const store = useAnalysisStateStore.getState();
    store.addSlicer('Material', ['Concrete']);
    store.addSlicer('Level', ['L1']);
    store.removeSlicer('Material');
    const s = useAnalysisStateStore.getState().slicers;
    expect(s).toHaveLength(1);
    expect(s[0]?.column).toBe('Level');
  });

  it('clearSlicers empties everything', () => {
    const store = useAnalysisStateStore.getState();
    store.addSlicer('Material', ['Concrete']);
    store.addSlicer('Level', ['L1']);
    store.clearSlicers();
    expect(useAnalysisStateStore.getState().slicers).toEqual([]);
  });
});

describe('useAnalysisStateStore — chart config', () => {
  beforeEach(() => {
    localStorage.clear();
    reset();
  });

  it('setChartConfig merges into the existing config', () => {
    const store = useAnalysisStateStore.getState();
    store.setChartConfig({ kind: 'line', category: 'Category', value: 'Volume' });
    const c = useAnalysisStateStore.getState().chart;
    expect(c.kind).toBe('line');
    expect(c.category).toBe('Category');
    expect(c.value).toBe('Volume');
    // Untouched defaults should remain.
    expect(c.topN).toBeNull();
    expect(c.format).toBe('number');
  });

  it('setChartConfig can update only topN without clobbering the rest', () => {
    const store = useAnalysisStateStore.getState();
    store.setChartConfig({ kind: 'bar', category: 'Category', value: 'Volume' });
    store.setChartConfig({ topN: 10 });
    const c = useAnalysisStateStore.getState().chart;
    expect(c.topN).toBe(10);
    expect(c.kind).toBe('bar');
    expect(c.value).toBe('Volume');
  });
});

describe('useAnalysisStateStore — saved views (localStorage persistence)', () => {
  beforeEach(() => {
    localStorage.clear();
    reset();
  });

  it('persists a saved view to localStorage scoped to the session id', () => {
    const store = useAnalysisStateStore.getState();
    store.setSessionId('sess-1');
    store.addSlicer('Material', ['Concrete']);
    store.setChartConfig({ kind: 'pie', category: 'Material', value: 'Volume' });
    store.saveView('My view');

    const raw = localStorage.getItem('oe_data_explorer_views_sess-1');
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw!);
    expect(parsed).toHaveLength(1);
    expect(parsed[0].name).toBe('My view');
    expect(parsed[0].slicers).toHaveLength(1);
    expect(parsed[0].chart.kind).toBe('pie');
  });

  it('hydrates saved views when setSessionId switches back', () => {
    const store = useAnalysisStateStore.getState();
    store.setSessionId('sess-1');
    store.addSlicer('Material', ['Concrete']);
    store.saveView('View A');

    // Switch to a different session and back.
    store.setSessionId('sess-2');
    expect(useAnalysisStateStore.getState().views).toEqual([]);
    store.setSessionId('sess-1');
    expect(useAnalysisStateStore.getState().views).toHaveLength(1);
    expect(useAnalysisStateStore.getState().views[0]?.name).toBe('View A');
  });

  it('loadView restores slicers and chart config', () => {
    const store = useAnalysisStateStore.getState();
    store.setSessionId('sess-1');
    store.addSlicer('Material', ['Steel']);
    store.setChartConfig({ kind: 'scatter', category: 'Category', value: 'Area' });
    const view = store.saveView('Named view');

    store.clearSlicers();
    store.setChartConfig({ kind: 'bar' });

    store.loadView(view.id);
    const state = useAnalysisStateStore.getState();
    expect(state.slicers).toHaveLength(1);
    expect(state.slicers[0]?.values).toEqual(['Steel']);
    expect(state.chart.kind).toBe('scatter');
  });

  it('deleteView removes from state and localStorage', () => {
    const store = useAnalysisStateStore.getState();
    store.setSessionId('sess-1');
    const a = store.saveView('A');
    const b = store.saveView('B');
    store.deleteView(a.id);

    const remaining = useAnalysisStateStore.getState().views;
    expect(remaining).toHaveLength(1);
    expect(remaining[0]?.id).toBe(b.id);

    const raw = localStorage.getItem('oe_data_explorer_views_sess-1');
    const parsed = JSON.parse(raw!);
    expect(parsed).toHaveLength(1);
    expect(parsed[0].id).toBe(b.id);
  });

  it('switching session clears stale slicers so filters do not leak', () => {
    const store = useAnalysisStateStore.getState();
    store.setSessionId('sess-1');
    store.addSlicer('Material', ['Concrete']);

    store.setSessionId('sess-2');
    expect(useAnalysisStateStore.getState().slicers).toEqual([]);
  });
});
