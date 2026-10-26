// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure three-way merge for a record edited offline​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠.
 *
 *   base    the server copy the edit started from (kept on the device)
 *   mine    the fields this device changed (a patch; absent keys were not edited)
 *   theirs  the server's current copy, taken from the 409 body
 *
 * Rules, per field the device edited:
 *   - unchanged here                -> keep theirs
 *   - changed here only             -> mine
 *   - both changed, same value      -> either (theirs)
 *   - both changed, simple field    -> mine (last writer wins, this device wrote last)
 *   - both changed, long text       -> a conflict the user resolves
 *   - checklist                     -> merged item by item, by id; only an item both
 *                                      sides changed differently is a conflict
 *
 * No I/O, no React: the dialog and the sync engine both call this.
 */

export type MergeChoice = 'mine' | 'theirs' | 'manual';

export interface ChecklistLikeItem {
  id: string;
  [key: string]: unknown;
}

export interface MergeSpec {
  /** Fields merged as long text: a real clash is shown side by side. */
  longTextFields?: readonly string[];
  /** Fields that are lists of `{id, ...}` items. */
  checklistFields?: readonly string[];
}

export interface TextConflict {
  kind: 'text';
  field: string;
  base: string;
  mine: string;
  theirs: string;
}

export interface ChecklistItemConflict {
  id: string;
  base: ChecklistLikeItem | null;
  /** null = this device removed the item. */
  mine: ChecklistLikeItem | null;
  /** null = the server removed the item. */
  theirs: ChecklistLikeItem | null;
}

export interface ChecklistConflict {
  kind: 'checklist';
  field: string;
  items: ChecklistItemConflict[];
}

export type MergeConflict = TextConflict | ChecklistConflict;

export interface ThreeWayMergeResult {
  /** Final values to send. Conflicted fields hold `mine` until resolved. */
  fields: Record<string, unknown>;
  /** Per-field resolution as the merge endpoint expects it. */
  resolutions: Record<string, MergeChoice>;
  /** Fields that need a human decision. Empty = nothing to ask. */
  conflicts: MergeConflict[];
  /** Fields settled by the rules above without asking. */
  autoResolved: string[];
}

/** What the user picked in the dialog. */
export interface ConflictDecisions {
  text?: Record<string, { choice: MergeChoice; value?: string }>;
  /** field -> item id -> side. */
  checklist?: Record<string, Record<string, 'mine' | 'theirs'>>;
}

/* ── helpers ───────────────────────────────────────────────────────────── */

function stable(v: unknown): string {
  if (v === undefined) return 'undefined';
  if (v === null || typeof v !== 'object') return JSON.stringify(v);
  if (Array.isArray(v)) return `[${v.map(stable).join(',')}]`;
  const o = v as Record<string, unknown>;
  return `{${Object.keys(o)
    .sort()
    .map((k) => `${JSON.stringify(k)}:${stable(o[k])}`)
    .join(',')}}`;
}

export function deepEqual(a: unknown, b: unknown): boolean {
  return stable(a) === stable(b);
}

/** Null and undefined and '' are the same "empty" for text. */
function textOf(v: unknown): string {
  return typeof v === 'string' ? v : v == null ? '' : String(v);
}

function asItems(v: unknown): ChecklistLikeItem[] {
  return Array.isArray(v) ? (v as ChecklistLikeItem[]).filter((x) => x && typeof x.id === 'string') : [];
}

function byId(items: ChecklistLikeItem[]): Map<string, ChecklistLikeItem> {
  const m = new Map<string, ChecklistLikeItem>();
  for (const it of items) m.set(it.id, it);
  return m;
}

/* ── checklist merge ───────────────────────────────────────────────────── */

interface ChecklistMerge {
  items: ChecklistLikeItem[];
  conflicts: ChecklistItemConflict[];
}

function mergeChecklist(base: unknown, mine: unknown, theirs: unknown): ChecklistMerge {
  const b = byId(asItems(base));
  const m = byId(asItems(mine));
  const t = byId(asItems(theirs));
  const ids: string[] = [];
  const seen = new Set<string>();
  // Server order first, then what only this device has: stable and predictable.
  for (const src of [asItems(theirs), asItems(mine), asItems(base)]) {
    for (const it of src) {
      if (!seen.has(it.id)) {
        seen.add(it.id);
        ids.push(it.id);
      }
    }
  }
  const items: ChecklistLikeItem[] = [];
  const conflicts: ChecklistItemConflict[] = [];
  for (const id of ids) {
    const bi = b.get(id) ?? null;
    const mi = m.get(id) ?? null;
    const ti = t.get(id) ?? null;
    const mineChanged = !deepEqual(mi, bi);
    const theirsChanged = !deepEqual(ti, bi);
    let pick: ChecklistLikeItem | null;
    if (deepEqual(mi, ti)) pick = ti;
    else if (!mineChanged) pick = ti;
    else if (!theirsChanged) pick = mi;
    else {
      conflicts.push({ id, base: bi, mine: mi, theirs: ti });
      pick = mi; // placeholder until decided
    }
    if (pick) items.push(pick);
  }
  return { items, conflicts };
}

/* ── main entry ────────────────────────────────────────────────────────── */

export function computeThreeWayMerge(input: {
  base: Record<string, unknown> | null | undefined;
  mine: Record<string, unknown>;
  theirs: Record<string, unknown>;
  spec?: MergeSpec;
}): ThreeWayMergeResult {
  const base = input.base ?? {};
  const longText = new Set(input.spec?.longTextFields ?? []);
  const checklists = new Set(input.spec?.checklistFields ?? []);
  const result: ThreeWayMergeResult = { fields: {}, resolutions: {}, conflicts: [], autoResolved: [] };

  for (const field of Object.keys(input.mine)) {
    const mine = input.mine[field];
    const theirs = input.theirs[field];
    const baseVal = base[field];
    const isText = longText.has(field);
    const same = isText ? textOf(mine) === textOf(theirs) : deepEqual(mine, theirs);
    const mineChanged = isText ? textOf(mine) !== textOf(baseVal) : !deepEqual(mine, baseVal);
    const theirsChanged = isText ? textOf(theirs) !== textOf(baseVal) : !deepEqual(theirs, baseVal);

    if (checklists.has(field)) {
      const merged = mergeChecklist(baseVal, mine, theirs);
      result.fields[field] = merged.items;
      if (merged.conflicts.length > 0) {
        result.conflicts.push({ kind: 'checklist', field, items: merged.conflicts });
        result.resolutions[field] = 'manual';
      } else {
        result.resolutions[field] = !theirsChanged ? 'mine' : !mineChanged ? 'theirs' : 'manual';
        result.autoResolved.push(field);
      }
      continue;
    }

    if (same || !mineChanged) {
      result.fields[field] = theirs;
      result.resolutions[field] = 'theirs';
      result.autoResolved.push(field);
    } else if (!theirsChanged || !isText) {
      // Edited only here, or a simple field both sides edited: this device is
      // the last writer.
      result.fields[field] = mine;
      result.resolutions[field] = 'mine';
      result.autoResolved.push(field);
    } else {
      result.fields[field] = mine;
      result.resolutions[field] = 'mine';
      result.conflicts.push({
        kind: 'text',
        field,
        base: textOf(baseVal),
        mine: textOf(mine),
        theirs: textOf(theirs),
      });
    }
  }
  return result;
}

/**
 * Fold the user's decisions into a merge result. Fields still undecided keep
 * `mine`. Returns a new result with `conflicts` emptied for decided fields.
 */
export function applyDecisions(merge: ThreeWayMergeResult, decisions: ConflictDecisions): ThreeWayMergeResult {
  const fields = { ...merge.fields };
  const resolutions = { ...merge.resolutions };
  const remaining: MergeConflict[] = [];

  for (const c of merge.conflicts) {
    if (c.kind === 'text') {
      const d = decisions.text?.[c.field];
      if (!d) {
        remaining.push(c);
        continue;
      }
      fields[c.field] = d.choice === 'mine' ? c.mine : d.choice === 'theirs' ? c.theirs : (d.value ?? c.mine);
      resolutions[c.field] = d.choice;
      continue;
    }
    const picks = decisions.checklist?.[c.field] ?? {};
    const undecided = c.items.filter((i) => !picks[i.id]);
    if (undecided.length > 0) {
      remaining.push({ kind: 'checklist', field: c.field, items: undecided });
    }
    const list = asItems(fields[c.field]).slice();
    let mineN = 0;
    let theirsN = 0;
    for (const item of c.items) {
      const side = picks[item.id];
      if (!side) continue;
      const chosen = side === 'mine' ? item.mine : item.theirs;
      if (side === 'mine') mineN += 1;
      else theirsN += 1;
      const idx = list.findIndex((x) => x.id === item.id);
      if (chosen === null) {
        if (idx >= 0) list.splice(idx, 1);
      } else if (idx >= 0) list[idx] = chosen;
      else list.push(chosen);
    }
    fields[c.field] = list;
    resolutions[c.field] = mineN > 0 && theirsN === 0 ? 'mine' : theirsN > 0 && mineN === 0 ? 'theirs' : 'manual';
  }
  return { ...merge, fields, resolutions, conflicts: remaining };
}
