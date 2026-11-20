// Design module (ERP side of the design editor link).
/** Revision list helpers and the element-level comparison of two revisions, keyed by `element_key`. */

export interface RevisionView {
  revision_id: string;
  project_id: string;
  number: number;
  parent_revision_id: string | null;
  status: 'shared' | 'published' | 'rejected' | 'archived';
  source_kind: string;
  /** null for a wrapped import whose level of detail nobody stated (R16). */
  depth_level: string | null;
  message: string;
  bim_model_id: string | null;
  decided_by: string | null;
  decided_at: string | null;
  decision_comment: string | null;
  created_at: string;
  manifest?: { schema?: string };
}

/** A converter model wrapped as a revision (R16): no package, the BIM hub's own geometry. */
export const isImported = (r: Pick<RevisionView, 'manifest'>): boolean => r.manifest?.schema === 'ddc-import/1';

/** Editor GLBs are Y-up; converter geometry keeps the BIM hub's Z-up default. */
export const upAxis = (r: Pick<RevisionView, 'manifest'>): 'y' | 'z' => (isImported(r) ? 'z' : 'y');

/** The fields of an ERP element row the comparison looks at. `stable_id` carries the element key. */
export interface CompareElement {
  stable_id?: string;
  name?: string;
  element_type?: string;
  storey?: string;
  geometry_hash?: string | null;
  quantities?: Record<string, number>;
}

export interface Comparison {
  added: string[];
  removed: string[];
  changed: string[];
  unchanged: number;
}

export type Overlay = Map<string, 'added' | 'deleted' | 'modified'>;
export type Tone = 'warning' | 'success' | 'error' | 'neutral';

const sameQuantities = (a: Record<string, number> = {}, b: Record<string, number> = {}): boolean => {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  for (const k of keys) {
    if (Math.abs((a[k] ?? 0) - (b[k] ?? 0)) > 1e-6) return false;
  }
  return true;
};

/** An element changed when its shape (geometry hash), identity fields or measured quantities differ. */
export function elementChanged(a: CompareElement, b: CompareElement): boolean {
  if ((a.geometry_hash ?? null) !== (b.geometry_hash ?? null)) return true;
  if ((a.name ?? '') !== (b.name ?? '') || (a.element_type ?? '') !== (b.element_type ?? '')) return true;
  if ((a.storey ?? '') !== (b.storey ?? '')) return true;
  return !sameQuantities(a.quantities, b.quantities);
}

/** Compare `base` (earlier) with `head` (later) by element key. Rows without a key are ignored. */
export function compareRevisions(base: CompareElement[], head: CompareElement[]): Comparison {
  const before = new Map(base.filter((e) => e.stable_id).map((e) => [e.stable_id as string, e]));
  const after = new Map(head.filter((e) => e.stable_id).map((e) => [e.stable_id as string, e]));
  const out: Comparison = { added: [], removed: [], changed: [], unchanged: 0 };
  for (const [key, el] of after) {
    const old = before.get(key);
    if (!old) out.added.push(key);
    else if (elementChanged(old, el)) out.changed.push(key);
    else out.unchanged += 1;
  }
  for (const key of before.keys()) if (!after.has(key)) out.removed.push(key);
  for (const list of [out.added, out.removed, out.changed]) list.sort();
  return out;
}

/** Viewer overlay for one side: the head shows added and changed, the base shows removed and changed. */
export function overlayFor(cmp: Comparison, side: 'base' | 'head'): Overlay {
  const map: Overlay = new Map();
  for (const k of cmp.changed) map.set(k, 'modified');
  for (const k of side === 'head' ? cmp.added : cmp.removed) map.set(k, side === 'head' ? 'added' : 'deleted');
  return map;
}

/** Compare selection: at most two revisions, kept in order of revision number (base first). */
export function toggleCompare(selected: RevisionView[], rev: RevisionView): RevisionView[] {
  if (selected.some((r) => r.revision_id === rev.revision_id)) {
    return selected.filter((r) => r.revision_id !== rev.revision_id);
  }
  const last = selected[selected.length - 1];
  const next: RevisionView[] = selected.length >= 2 && last ? [last, rev] : [...selected, rev];
  return [...next].sort((a, b) => a.number - b.number);
}

/** Revisions that can be opened in the viewer: they own a registered model. */
export const hasModel = (r: RevisionView): boolean => r.bim_model_id !== null;

const TONES: Record<RevisionView['status'], Tone> = {
  shared: 'warning',
  published: 'success',
  rejected: 'error',
  archived: 'neutral',
};

/** Badge tone for a revision status. */
export const statusTone = (status: RevisionView['status']): Tone => TONES[status];
