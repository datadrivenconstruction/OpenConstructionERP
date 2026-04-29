/**
 * Position dependency graph + cycle detection for BOQ formulas.
 *
 * We treat each position with a stored formula as a node, and each
 * `pos("X")` reference as an edge from THIS position to position X.
 * Tarjan's SCC algorithm groups nodes into strongly-connected components
 * — every node in an SCC of size > 1 (or a self-loop SCC) is part of a
 * cycle.
 *
 * Cycle policy is **warn-and-allow** (locked decision):
 *   • Cycle participants render with a yellow ⚠ marker.
 *   • Their computed value falls back to `0`, and downstream readers
 *     also see `0` (cycles don't propagate).
 *   • Save is NOT blocked.
 *
 * This is a stand-alone module — it depends only on `references.ts`. The
 * UI / reactive layer uses it via `buildDependencyGraph` and queries
 * `cyclesById` / `dependentsOf` to decide what to refresh.
 */

import type { Position } from '../../api';
import { extractReferences } from './references';

export interface DependencyGraph {
  /** id → set of position ids that THIS position depends on. */
  dependsOn: Map<string, Set<string>>;
  /** id → set of position ids that depend on this position (reverse edges). */
  dependents: Map<string, Set<string>>;
  /** Set of position ids that participate in a cycle. */
  cycleIds: Set<string>;
  /** id → array of ids forming the cycle (for tooltips). */
  cyclePathById: Map<string, string[]>;
  /** Set of variable names referenced anywhere; reverse: var → ids. */
  variableUsers: Map<string, Set<string>>;
}

interface BuildOptions {
  /**
   * Resolver from a `pos("X")` ordinal to a position id. If the ordinal
   * is unknown, return `undefined` — that's not a cycle, just an unresolved
   * reference (handled at eval time).
   */
  resolveOrdinal: (ordinal: string) => string | undefined;
}

/**
 * Build the full dependency graph for a list of positions whose
 * formulas are stored on `metadata.formula`.
 */
export function buildDependencyGraph(positions: Position[], opts: BuildOptions): DependencyGraph {
  const dependsOn = new Map<string, Set<string>>();
  const dependents = new Map<string, Set<string>>();
  const variableUsers = new Map<string, Set<string>>();

  for (const p of positions) {
    if (!p.id) continue;
    const formula = readFormula(p);
    if (!formula) continue;
    const refs = extractReferences(formula);
    const deps = new Set<string>();
    for (const ord of refs.positionOrdinals) {
      const otherId = opts.resolveOrdinal(ord);
      if (otherId && otherId !== p.id) {
        deps.add(otherId);
      } else if (otherId === p.id) {
        // self-reference IS a cycle
        deps.add(otherId);
      }
    }
    dependsOn.set(p.id, deps);
    for (const dep of deps) {
      let set = dependents.get(dep);
      if (!set) {
        set = new Set();
        dependents.set(dep, set);
      }
      set.add(p.id);
    }
    for (const v of refs.variables) {
      let set = variableUsers.get(v);
      if (!set) {
        set = new Set();
        variableUsers.set(v, set);
      }
      set.add(p.id);
    }
  }

  const { cycleIds, cyclePathById } = findCycles(dependsOn);

  return { dependsOn, dependents, cycleIds, cyclePathById, variableUsers };
}

/**
 * Read the formula string from a position's metadata. Returns `null`
 * when there is no formula or it's empty.
 */
export function readFormula(p: Position): string | null {
  const md = (p.metadata ?? p.metadata_) as Record<string, unknown> | undefined;
  if (!md) return null;
  const f = md['formula'];
  if (typeof f !== 'string') return null;
  const t = f.trim();
  return t ? t : null;
}

/**
 * Tarjan's strongly-connected-components.
 *
 * Adapted from the visited-set DFS pattern at
 * `backend/app/modules/boq/service.py:1148-1240` which guards against
 * parent-id cycles. The frontend variant tracks the SCC index/lowlink
 * per node so we can both detect cycles AND report the full cycle path
 * for the user's tooltip.
 */
function findCycles(adj: Map<string, Set<string>>): {
  cycleIds: Set<string>;
  cyclePathById: Map<string, string[]>;
} {
  const cycleIds = new Set<string>();
  const cyclePathById = new Map<string, string[]>();

  const index = new Map<string, number>();
  const lowlink = new Map<string, number>();
  const onStack = new Set<string>();
  const stack: string[] = [];
  let counter = 0;

  // Build the full vertex set: keys of adj PLUS any value-side ids that
  // weren't keys (so we don't miss leaf nodes that happen to be cycle
  // targets via self-references).
  const allIds = new Set<string>();
  for (const [k, vs] of adj) {
    allIds.add(k);
    for (const v of vs) allIds.add(v);
  }

  const strongConnect = (v: string): void => {
    // Iterative DFS to avoid blowing the call stack on large BOQs.
    const work: Array<{ v: string; iter: Iterator<string>; called: boolean }> = [
      { v, iter: (adj.get(v) ?? new Set<string>()).values(), called: false },
    ];
    if (!index.has(v)) {
      index.set(v, counter);
      lowlink.set(v, counter);
      counter++;
      stack.push(v);
      onStack.add(v);
    }
    while (work.length > 0) {
      const top = work[work.length - 1]!;
      const next = top.iter.next();
      if (next.done) {
        // Pop: if v is the root of an SCC, drain the stack.
        const cur = top.v;
        if (lowlink.get(cur) === index.get(cur)) {
          const scc: string[] = [];
          while (stack.length > 0) {
            const w = stack.pop()!;
            onStack.delete(w);
            scc.push(w);
            if (w === cur) break;
          }
          // SCC of size >= 2 OR a self-loop is a cycle.
          const isSelfLoop = scc.length === 1 && (adj.get(scc[0]!) ?? new Set<string>()).has(scc[0]!);
          if (scc.length > 1 || isSelfLoop) {
            for (const id of scc) {
              cycleIds.add(id);
              cyclePathById.set(id, [...scc]);
            }
          }
        }
        work.pop();
        if (work.length > 0) {
          const parent = work[work.length - 1]!;
          parent.called = true;
          // Update parent's lowlink with cur's lowlink.
          const pl = lowlink.get(parent.v)!;
          const cl = lowlink.get(cur)!;
          if (cl < pl) lowlink.set(parent.v, cl);
        }
        continue;
      }
      const w = next.value;
      if (!index.has(w)) {
        index.set(w, counter);
        lowlink.set(w, counter);
        counter++;
        stack.push(w);
        onStack.add(w);
        work.push({ v: w, iter: (adj.get(w) ?? new Set<string>()).values(), called: false });
      } else if (onStack.has(w)) {
        // Back-edge: lower our lowlink.
        const cur = top.v;
        const pl = lowlink.get(cur)!;
        const wi = index.get(w)!;
        if (wi < pl) lowlink.set(cur, wi);
      }
    }
  };

  for (const v of allIds) {
    if (!index.has(v)) strongConnect(v);
  }

  return { cycleIds, cyclePathById };
}

/**
 * Compute the transitive set of dependents for a given position id.
 *
 * Used by the live-re-eval loop: when `posA.qty` changes, we refresh
 * every formula that reads `pos("A").*` (directly or indirectly). The
 * traversal stops at cycle-participants — they get `0` and their own
 * downstream is recomputed independently.
 */
export function transitiveDependents(graph: DependencyGraph, id: string): Set<string> {
  const out = new Set<string>();
  const stack: string[] = [id];
  while (stack.length > 0) {
    const cur = stack.pop()!;
    const direct = graph.dependents.get(cur);
    if (!direct) continue;
    for (const d of direct) {
      if (out.has(d)) continue;
      out.add(d);
      stack.push(d);
    }
  }
  return out;
}

/**
 * Helper: when a variable changes, return every position id that
 * references it.
 */
export function variableUsers(graph: DependencyGraph, varName: string): Set<string> {
  return graph.variableUsers.get(varName.toUpperCase()) ?? new Set();
}
