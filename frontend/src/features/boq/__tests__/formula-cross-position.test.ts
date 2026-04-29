/**
 * Phase C v2.7.0/C — cross-position live re-evaluation.
 *
 * Acceptance criterion (from the spec):
 *   "Change qty on A, verify B (=pos(A).qty * 2) updates within 200ms."
 *
 * The orchestrator is `LiveReeval` in `formula/live-reeval.ts`. It
 * batches updates within a 200ms window and emits a single refresh
 * call with the union of dependent ids.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  buildDependencyGraph,
  evaluateFormula,
  buildFormulaContext,
  LiveReeval,
  readFormula,
} from '../grid/formula';
import type { Position } from '../api';

function pos(id: string, ordinal: string, opts: Partial<Position> = {}): Position {
  return {
    id,
    boq_id: 'boq-1',
    parent_id: null,
    ordinal,
    description: '',
    unit: 'm',
    quantity: opts.quantity ?? 1,
    unit_rate: opts.unit_rate ?? 1,
    total: (opts.quantity ?? 1) * (opts.unit_rate ?? 1),
    classification: {},
    source: 'manual',
    confidence: null,
    sort_order: 0,
    validation_status: 'pending',
    metadata: opts.metadata ?? {},
  };
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('LiveReeval — debounced refresh', () => {
  it('refreshes B within 200ms when A.qty changes (B reads pos(A).qty * 2)', () => {
    const a = pos('a', '1.1', { quantity: 10 });
    const b = pos('b', '1.2', { metadata: { formula: '=pos("1.1").qty * 2' } });

    const ordToId = new Map<string, string>([
      ['1.1', 'a'],
      ['1.2', 'b'],
    ]);
    const graph = buildDependencyGraph([a, b], { resolveOrdinal: (o) => ordToId.get(o) });

    const refresh = vi.fn();
    const live = new LiveReeval({ refresh });
    live.setGraph(graph);

    live.notifyPositionChanged('a');
    expect(refresh).not.toHaveBeenCalled();

    vi.advanceTimersByTime(199);
    expect(refresh).not.toHaveBeenCalled();

    vi.advanceTimersByTime(2);
    expect(refresh).toHaveBeenCalledOnce();
    expect(refresh).toHaveBeenCalledWith(['b']);
  });

  it('coalesces multiple notifies within the window', () => {
    const a = pos('a', '1.1');
    const b = pos('b', '1.2', { metadata: { formula: '=pos("1.1").qty * 2' } });
    const c = pos('c', '1.3', { metadata: { formula: '=pos("1.2").qty + 1' } });
    const ordToId = new Map<string, string>([
      ['1.1', 'a'],
      ['1.2', 'b'],
      ['1.3', 'c'],
    ]);
    const graph = buildDependencyGraph([a, b, c], { resolveOrdinal: (o) => ordToId.get(o) });

    const refresh = vi.fn();
    const live = new LiveReeval({ refresh });
    live.setGraph(graph);

    live.notifyPositionChanged('a');
    vi.advanceTimersByTime(50);
    live.notifyPositionChanged('a');
    vi.advanceTimersByTime(50);
    live.notifyPositionChanged('a');
    expect(refresh).not.toHaveBeenCalled();

    vi.advanceTimersByTime(200);
    expect(refresh).toHaveBeenCalledOnce();
    const ids = (refresh.mock.calls[0]![0] as string[]).sort();
    expect(ids).toEqual(['b', 'c']);
  });

  it('refreshes formulas that read a $VAR when the var changes', () => {
    const a = pos('a', '1.1', { metadata: { formula: '=$GFA * 0.15' } });
    const b = pos('b', '1.2', { metadata: { formula: '=pos("1.1").qty * 2' } });
    const c = pos('c', '1.3', { metadata: { formula: '=42' } });
    const ordToId = new Map<string, string>([
      ['1.1', 'a'],
      ['1.2', 'b'],
      ['1.3', 'c'],
    ]);
    const graph = buildDependencyGraph([a, b, c], { resolveOrdinal: (o) => ordToId.get(o) });

    const refresh = vi.fn();
    const live = new LiveReeval({ refresh });
    live.setGraph(graph);

    live.notifyVariableChanged('GFA');
    vi.advanceTimersByTime(200);
    expect(refresh).toHaveBeenCalledOnce();
    const ids = (refresh.mock.calls[0]![0] as string[]).sort();
    // a reads $GFA → refresh a; b reads pos(a) → transitive includes b.
    expect(ids).toEqual(['a', 'b']);
  });

  it('flush() force-emits without waiting', () => {
    const a = pos('a', '1.1');
    const b = pos('b', '1.2', { metadata: { formula: '=pos("1.1").qty' } });
    const ordToId = new Map<string, string>([
      ['1.1', 'a'],
      ['1.2', 'b'],
    ]);
    const graph = buildDependencyGraph([a, b], { resolveOrdinal: (o) => ordToId.get(o) });

    const refresh = vi.fn();
    const live = new LiveReeval({ refresh });
    live.setGraph(graph);

    live.notifyPositionChanged('a');
    live.flush();
    expect(refresh).toHaveBeenCalledOnce();
    expect(refresh).toHaveBeenCalledWith(['b']);
  });

  it('does nothing when there are no dependents', () => {
    const a = pos('a', '1.1');
    const ordToId = new Map<string, string>([['1.1', 'a']]);
    const graph = buildDependencyGraph([a], { resolveOrdinal: (o) => ordToId.get(o) });

    const refresh = vi.fn();
    const live = new LiveReeval({ refresh });
    live.setGraph(graph);

    live.notifyPositionChanged('a');
    vi.advanceTimersByTime(300);
    expect(refresh).not.toHaveBeenCalled();
  });
});

/* ── Round-trip: B's formula re-evaluates with the new A.qty ───── */

describe('cross-position evaluation round-trip', () => {
  it('B evaluates against the latest A.qty after the refresh', () => {
    const a = pos('a', '1.1', { quantity: 10 });
    const b = pos('b', '1.2', { metadata: { formula: '=pos("1.1").qty * 2' } });

    // Initial eval (A=10, B=20)
    let ctx = buildFormulaContext({ positions: [a, b] });
    expect(readFormula(b)).toBe('=pos("1.1").qty * 2');
    expect(evaluateFormula(readFormula(b)!, ctx)).toBe(20);

    // Mutate A in place, simulating an inline edit.
    a.quantity = 17;
    ctx = buildFormulaContext({ positions: [a, b] });
    expect(evaluateFormula(readFormula(b)!, ctx)).toBe(34);
  });
});

/* ── Cycle participants compute to null (warn-and-allow) ───────── */

describe('cycle participants', () => {
  it('cycle formula evaluates with the stale-zero rule baked into the UI', () => {
    // The engine itself has no notion of "stale zero" — that's a UI
    // policy applied by checking graph.cycleIds before calling
    // evaluateFormula. Here we sanity-check that the static analyser
    // marked them.
    const a = pos('a', '1.1', { metadata: { formula: '=pos("1.2").qty' } });
    const b = pos('b', '1.2', { metadata: { formula: '=pos("1.1").qty' } });
    const ordToId = new Map<string, string>([
      ['1.1', 'a'],
      ['1.2', 'b'],
    ]);
    const graph = buildDependencyGraph([a, b], { resolveOrdinal: (o) => ordToId.get(o) });

    expect(graph.cycleIds.has('a')).toBe(true);
    expect(graph.cycleIds.has('b')).toBe(true);
    // The UI applies the "downstream of cycle reads 0" rule:
    const computed = (id: string, p: Position) =>
      graph.cycleIds.has(id) ? 0 : evaluateFormula(readFormula(p)!, buildFormulaContext({ positions: [a, b] }));
    expect(computed('a', a)).toBe(0);
    expect(computed('b', b)).toBe(0);
  });
});
