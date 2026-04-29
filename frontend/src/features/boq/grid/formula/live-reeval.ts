/**
 * Debounced live re-evaluation orchestrator.
 *
 * When a position's qty/rate or a $VAR changes, every formula that
 * depends on it must be re-evaluated and the corresponding AG Grid
 * cells refreshed. To avoid thrashing on bulk paste / multi-cell edit
 * we debounce the refresh by 200ms.
 */

import type { DependencyGraph } from './dependency-graph';
import { transitiveDependents, variableUsers } from './dependency-graph';

export interface LiveReevalOptions {
  /** Debounce window in milliseconds (default 200). */
  debounceMs?: number;
  /** Callback to refresh AG Grid rows by id. */
  refresh: (positionIds: string[]) => void;
}

export class LiveReeval {
  private graph: DependencyGraph | null = null;
  private pending = new Set<string>();
  private timer: ReturnType<typeof setTimeout> | null = null;
  private readonly debounceMs: number;
  private readonly refresh: (ids: string[]) => void;

  constructor(opts: LiveReevalOptions) {
    this.debounceMs = opts.debounceMs ?? 200;
    this.refresh = opts.refresh;
  }

  setGraph(graph: DependencyGraph): void {
    this.graph = graph;
  }

  /** A position's qty / rate / formula changed. */
  notifyPositionChanged(positionId: string): void {
    if (!this.graph) return;
    const tx = transitiveDependents(this.graph, positionId);
    for (const id of tx) this.pending.add(id);
    this.schedule();
  }

  /** A named variable changed. */
  notifyVariableChanged(name: string): void {
    if (!this.graph) return;
    const direct = variableUsers(this.graph, name);
    for (const id of direct) {
      this.pending.add(id);
      const tx = transitiveDependents(this.graph, id);
      for (const t of tx) this.pending.add(t);
    }
    this.schedule();
  }

  /** Force-flush the pending set immediately (testing / unmount). */
  flush(): void {
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    if (this.pending.size === 0) return;
    const ids = [...this.pending];
    this.pending.clear();
    this.refresh(ids);
  }

  private schedule(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      this.timer = null;
      if (this.pending.size === 0) return;
      const ids = [...this.pending];
      this.pending.clear();
      this.refresh(ids);
    }, this.debounceMs);
  }
}
