// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Inline validation: the latest validation-engine findings of what is on
 * screen, shown in place. A finding's element_ref names a record; any row or
 * field that carries the same id as data-position-id, data-row-id, row-id
 * (AG Grid) or data-check-ref gets data-oe-check="error|warning" and the
 * message as its tooltip, so pages need no code of their own. The Checks
 * panel (shared/ui/ChecksPanel.tsx) lists the same findings with a counter.
 *
 * Pages that validate something other than a bill publish their findings with
 * `publishChecks(source, findings)`; the panel merges every source.
 */
import { create } from 'zustand';

export type CheckSeverity = 'error' | 'warning' | 'info';

export interface CheckFinding {
  rule_id: string;
  rule_name: string;
  severity: CheckSeverity;
  message: string;
  element_ref: string | null;
  suggestion: string | null;
}

interface ChecksState {
  sources: Record<string, CheckFinding[]>;
  publish: (source: string, findings: CheckFinding[]) => void;
  clear: (source: string) => void;
}

export const useChecksStore = create<ChecksState>((set) => ({
  sources: {},
  publish: (source, findings) => set((s) => ({ sources: { ...s.sources, [source]: findings } })),
  clear: (source) =>
    set((s) => {
      const next = { ...s.sources };
      delete next[source];
      return { sources: next };
    }),
}));

export function publishChecks(source: string, findings: CheckFinding[]): void {
  useChecksStore.getState().publish(source, findings);
}

const RANK: Record<CheckSeverity, number> = { error: 0, warning: 1, info: 2 };

/** Failing findings only, worst first, one entry per rule and element. */
export function openFindings(rows: (CheckFinding & { passed?: boolean })[]): CheckFinding[] {
  const seen = new Set<string>();
  return rows
    .filter((r) => r.passed !== true && r.severity !== 'info')
    .filter((r) => {
      const key = `${r.rule_id}|${r.element_ref ?? ''}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .sort((a, b) => RANK[a.severity] - RANK[b.severity]);
}

export function countBySeverity(findings: CheckFinding[]): { error: number; warning: number } {
  let error = 0;
  let warning = 0;
  for (const f of findings) {
    if (f.severity === 'error') error++;
    else if (f.severity === 'warning') warning++;
  }
  return { error, warning };
}

function cssId(ref: string): string {
  return typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(ref) : ref.replace(/["\\]/g, '\\$&');
}

/** Elements on screen that show the record a finding is about. */
export function elementsFor(ref: string, root: ParentNode = document): HTMLElement[] {
  const id = cssId(ref);
  return Array.from(
    root.querySelectorAll<HTMLElement>(
      `[data-position-id="${id}"], [data-row-id="${id}"], .ag-row[row-id="${id}"], [data-check-ref="${id}"]`,
    ),
  );
}

/** Put the findings on the rows and fields they name; clears stale marks. */
export function markFindings(findings: CheckFinding[], root: ParentNode = document): number {
  const byRef = new Map<string, CheckFinding[]>();
  for (const f of findings) {
    if (!f.element_ref) continue;
    const list = byRef.get(f.element_ref) ?? [];
    list.push(f);
    byRef.set(f.element_ref, list);
  }
  const marked = new Set<HTMLElement>();
  for (const [ref, list] of byRef) {
    const worst = list.some((f) => f.severity === 'error') ? 'error' : 'warning';
    const title = list.map((f) => f.message).join('\n');
    for (const el of elementsFor(ref, root)) {
      if (el.dataset.oeCheck !== worst) el.dataset.oeCheck = worst;
      if (el.dataset.oeCheckMsg !== title) {
        el.dataset.oeCheckMsg = title;
        el.title = title;
      }
      marked.add(el);
    }
  }
  root.querySelectorAll<HTMLElement>('[data-oe-check]').forEach((el) => {
    if (marked.has(el)) return;
    delete el.dataset.oeCheck;
    if (el.dataset.oeCheckMsg && el.title === el.dataset.oeCheckMsg) el.removeAttribute('title');
    delete el.dataset.oeCheckMsg;
  });
  return marked.size;
}
