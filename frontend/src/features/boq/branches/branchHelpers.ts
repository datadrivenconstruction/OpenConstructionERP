// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure helpers for the estimate-branch UI: tree ordering, plan selection and
 * conflict bookkeeping. No React, no network, so every rule is unit-tested.
 */
import type { BranchCompareRow, BranchNode, PlanItem, Resolution } from './branchApi';

export interface TreeRow {
  node: BranchNode;
  depth: number;
}

/**
 * Flatten the branch tree depth-first: main first, every branch under its
 * parent, siblings oldest first. A branch whose parent is missing hangs off
 * main so it is never lost from the list.
 */
export function flattenTree(nodes: BranchNode[]): TreeRow[] {
  const main = nodes.find((n) => n.is_main);
  if (!main) return [];
  const ids = new Set(nodes.map((n) => n.boq_id));
  const children = new Map<string, BranchNode[]>();
  for (const n of nodes) {
    if (n.is_main) continue;
    const parent = n.parent_boq_id && ids.has(n.parent_boq_id) ? n.parent_boq_id : main.boq_id;
    const list = children.get(parent) ?? [];
    list.push(n);
    children.set(parent, list);
  }
  for (const list of children.values()) {
    list.sort((a, b) => (a.created_at ?? '').localeCompare(b.created_at ?? ''));
  }
  const out: TreeRow[] = [];
  const seen = new Set<string>();
  const walk = (node: BranchNode, depth: number) => {
    if (seen.has(node.boq_id)) return;
    seen.add(node.boq_id);
    out.push({ node, depth });
    for (const child of children.get(node.boq_id) ?? []) walk(child, depth + 1);
  };
  walk(main, 0);
  return out;
}

/** Sign of a decimal string: -1, 0 or 1; anything unreadable is 0. */
export function deltaSign(value: string | null | undefined): -1 | 0 | 1 {
  const n = Number(value ?? 0);
  if (!Number.isFinite(n) || n === 0) return 0;
  return n > 0 ? 1 : -1;
}

/** The plan items whose conflict still has no decision. */
export function undecidedConflicts(
  items: PlanItem[],
  selected: ReadonlySet<string>,
  resolutions: Readonly<Record<string, Resolution>>,
): PlanItem[] {
  return items.filter((i) => i.conflict && selected.has(i.key) && !resolutions[i.key]);
}

/**
 * Resolutions limited to the selected keys, so a decision taken on a line the
 * user later unticked is not sent.
 */
export function resolutionsFor(
  selected: ReadonlySet<string>,
  resolutions: Readonly<Record<string, Resolution>>,
): Record<string, Resolution> {
  const out: Record<string, Resolution> = {};
  for (const [key, value] of Object.entries(resolutions)) {
    if (selected.has(key)) out[key] = value;
  }
  return out;
}

/**
 * Selecting a line also selects its ancestors that the plan adds: a new
 * position cannot land under a section that is not carried with it.
 */
export function withRequiredParents(items: PlanItem[], keys: Iterable<string>): Set<string> {
  const byKey = new Map(items.map((i) => [i.key, i]));
  const out = new Set<string>();
  for (const key of keys) {
    out.add(key);
    let parent = byKey.get(key)?.parent_key ?? null;
    let guard = 0;
    while (parent && byKey.get(parent)?.action === 'add' && guard < 64) {
      out.add(parent);
      parent = byKey.get(parent)?.parent_key ?? null;
      guard += 1;
    }
  }
  return out;
}

/** Compare rows worth showing: everything, or only lines that differ. */
export function visibleCompareRows(rows: BranchCompareRow[], onlyChanges: boolean): BranchCompareRow[] {
  return onlyChanges ? rows.filter((r) => r.change_type !== 'unchanged') : rows;
}

/** A field value from a plan triplet as text; objects (classification) are joined as code pairs. */
export function planValueText(value: unknown): string {
  if (value === null || value === undefined || value === '') return '-';
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>).filter(([, v]) => v !== '' && v != null);
    return entries.length ? entries.map(([k, v]) => `${k}: ${String(v)}`).join(', ') : '-';
  }
  return String(value);
}
