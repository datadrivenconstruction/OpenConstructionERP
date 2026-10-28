// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** 
 * SelectionSetsStore — localStorage-backed named selection sets per BIM model.
 *
 * Part of v3.13.0 W6.6 "BIM Viewer Pro UX". A "selection set" is a named,
 * persistent bag of element ids the user can recall later — useful for
 * recurring inspections ("Level 3 columns", "MEP risers", "façade panels")
 * without re-running filters every time. The store is intentionally keyed
 * by *model* id so picking a different model in the viewer never spills
 * stale ids from a previous one.
 *
 * Persistence shape on disk (single localStorage entry):
 *   key   : oe_bim_selection_sets_v1
 *   value : { [modelId: string]: SelectionSet[] }
 *
 * Caps:
 *   - 50 sets per model (create throws past the cap so the UI can show a
 *     dedicated error rather than silently dropping the request).
 *   - 10000 element ids per set (truncated with a warning on create —
 *     element selections from massive isolations should not crash the
 *     localStorage write but the trim avoids quota explosions later).
 *
 * Cross-tab sync mirrors ``useBrandingStore``: a ``storage`` event listener
 * notifies subscribers when another tab writes to the same key. Same-tab
 * edits always flow through this module so they bypass the listener.
 */

import { uuid } from '@/shared/lib/browser';

const STORAGE_KEY = 'oe_bim_selection_sets_v1';
const MAX_SETS_PER_MODEL = 50;
const MAX_ELEMENT_IDS_PER_SET = 10000;
const NAME_MAX = 60;
const NOTE_MAX = 200;

export interface SelectionSet {
  /** UUID v4 from the secure-context-safe uuid() helper. */
  id: string;
  /** Human-readable label. Trimmed; 1 ≤ length ≤ 60. */
  name: string;
  /** BIM model id this set lives under. Sets never cross models. */
  modelId: string;
  /** Ordered, deduplicated element ids in this set. */
  elementIds: string[];
  /** ISO 8601 creation timestamp. */
  createdAt: string;
  /** ISO 8601 last-mutation timestamp. */
  updatedAt: string;
  /** Optional hex tag colour (#rrggbb). Free-form 6-colour swatch in the UI. */
  color?: string;
  /** Optional free-text note. 0 ≤ length ≤ 200. */
  note?: string;
  /** Optional folder label for grouping sets in the panel (B4). Empty / blank
   *  means ungrouped. Trimmed; max 60 chars (same cap as the name). */
  folder?: string;
}

type PersistedShape = Record<string, SelectionSet[]>;

function randomId(): string {
  return uuid();
}

function nowIso(): string {
  return new Date().toISOString();
}

function dedupe(ids: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const id of ids) {
    if (typeof id !== 'string' || id.length === 0) continue;
    if (seen.has(id)) continue;
    seen.add(id);
    out.push(id);
  }
  return out;
}

function clampElementIds(ids: string[]): string[] {
  const cleaned = dedupe(ids);
  if (cleaned.length <= MAX_ELEMENT_IDS_PER_SET) return cleaned;
  // eslint-disable-next-line no-console
  console.warn(
    `[SelectionSetsStore] selection set truncated from ${cleaned.length} to ${MAX_ELEMENT_IDS_PER_SET} elements (cap MAX_ELEMENT_IDS_PER_SET).`,
  );
  return cleaned.slice(0, MAX_ELEMENT_IDS_PER_SET);
}

function readAll(): PersistedShape {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    const out: PersistedShape = {};
    for (const [modelId, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (!Array.isArray(value)) continue;
      const sets: SelectionSet[] = [];
      for (const raw of value) {
        if (!raw || typeof raw !== 'object') continue;
        const candidate = raw as Partial<SelectionSet>;
        if (
          typeof candidate.id !== 'string' ||
          typeof candidate.name !== 'string' ||
          typeof candidate.modelId !== 'string' ||
          !Array.isArray(candidate.elementIds)
        ) {
          continue;
        }
        sets.push({
          id: candidate.id,
          name: candidate.name,
          modelId: candidate.modelId,
          elementIds: candidate.elementIds.filter((x): x is string => typeof x === 'string'),
          createdAt: typeof candidate.createdAt === 'string' ? candidate.createdAt : nowIso(),
          updatedAt: typeof candidate.updatedAt === 'string' ? candidate.updatedAt : nowIso(),
          color: typeof candidate.color === 'string' ? candidate.color : undefined,
          note: typeof candidate.note === 'string' ? candidate.note : undefined,
          folder:
            typeof candidate.folder === 'string' && candidate.folder.trim()
              ? candidate.folder.trim()
              : undefined,
        });
      }
      out[modelId] = sets;
    }
    return out;
  } catch {
    return {};
  }
}

function writeAll(data: PersistedShape): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
  } catch {
    // Quota or serialisation error — best-effort. The in-memory copy still
    // works for the current session.
  }
}

function validateName(rawName: string): string {
  const trimmed = (rawName ?? '').trim();
  if (trimmed.length === 0) {
    throw new Error('Selection set name cannot be empty.');
  }
  if (trimmed.length > NAME_MAX) {
    throw new Error(`Selection set name cannot exceed ${NAME_MAX} characters.`);
  }
  return trimmed;
}

function validateNote(rawNote: string | undefined): string | undefined {
  if (rawNote === undefined || rawNote === null) return undefined;
  if (typeof rawNote !== 'string') return undefined;
  if (rawNote.length > NOTE_MAX) {
    throw new Error(`Selection set note cannot exceed ${NOTE_MAX} characters.`);
  }
  return rawNote;
}

/** Trim a folder label; blank becomes ``undefined`` (ungrouped). Throws when
 *  the label exceeds the name cap so the UI can surface a clear error. */
function validateFolder(rawFolder: string | undefined): string | undefined {
  if (typeof rawFolder !== 'string') return undefined;
  const trimmed = rawFolder.trim();
  if (trimmed.length === 0) return undefined;
  if (trimmed.length > NAME_MAX) {
    throw new Error(`Selection set folder cannot exceed ${NAME_MAX} characters.`);
  }
  return trimmed;
}

export class SelectionSetsStore {
  private subscribers = new Set<() => void>();
  private listenerInstalled = false;

  constructor() {
    if (typeof window !== 'undefined' && !this.listenerInstalled) {
      window.addEventListener('storage', this.onStorage);
      this.listenerInstalled = true;
    }
  }

  /** Cross-tab sync handler — only react to OUR key. */
  private onStorage = (e: StorageEvent): void => {
    if (e.key !== STORAGE_KEY) return;
    this.notify();
  };

  /** Sets for the supplied model. Returns a defensive copy. */
  list(modelId: string): SelectionSet[] {
    const all = readAll();
    const sets = all[modelId] ?? [];
    return sets.map((s) => ({ ...s, elementIds: [...s.elementIds] }));
  }

  /**
   * Persist a new set under ``modelId`` from the supplied element ids. The
   * elementIds list is deduplicated and (if needed) truncated to the
   * per-set cap. Throws if the per-model cap (50) is already reached.
   */
  create(
    modelId: string,
    name: string,
    elementIds: string[],
    extras?: { color?: string; note?: string; folder?: string },
  ): SelectionSet {
    if (modelId === '__proto__' || modelId === 'constructor' || modelId === 'prototype') {
      throw new Error('Invalid model id.');
    }
    const trimmedName = validateName(name);
    const note = validateNote(extras?.note);
    const folder = validateFolder(extras?.folder);
    const all = readAll();
    const sets = all[modelId] ?? [];
    if (sets.length >= MAX_SETS_PER_MODEL) {
      throw new Error(
        `Cannot create more than ${MAX_SETS_PER_MODEL} selection sets per model. Delete an existing set first.`,
      );
    }
    const now = nowIso();
    const set: SelectionSet = {
      id: randomId(),
      name: trimmedName,
      modelId,
      elementIds: clampElementIds(elementIds ?? []),
      createdAt: now,
      updatedAt: now,
      color: extras?.color,
      note,
      folder,
    };
    all[modelId] = [...sets, set];
    writeAll(all);
    this.notify();
    return { ...set, elementIds: [...set.elementIds] };
  }

  /**
   * Patch a stored set. Validates name / note. Bumps ``updatedAt``. Throws
   * if the id is not found in ANY model's bucket — IDs are globally unique
   * so we can scan all buckets without needing the modelId from the caller.
   */
  update(
    id: string,
    patch: Partial<
      Pick<SelectionSet, 'name' | 'color' | 'note' | 'folder' | 'elementIds'>
    >,
  ): SelectionSet {
    const all = readAll();
    for (const [modelId, sets] of Object.entries(all)) {
      const idx = sets.findIndex((s) => s.id === id);
      if (idx < 0) continue;
      const current = sets[idx]!;
      const nextName =
        patch.name !== undefined ? validateName(patch.name) : current.name;
      const nextNote = 'note' in patch ? validateNote(patch.note) : current.note;
      const nextColor = 'color' in patch ? patch.color : current.color;
      const nextFolder =
        'folder' in patch ? validateFolder(patch.folder) : current.folder;
      const nextIds =
        patch.elementIds !== undefined
          ? clampElementIds(patch.elementIds)
          : current.elementIds;
      const updated: SelectionSet = {
        ...current,
        name: nextName,
        note: nextNote,
        color: nextColor,
        folder: nextFolder,
        elementIds: nextIds,
        updatedAt: nowIso(),
      };
      const nextSets = sets.slice();
      nextSets[idx] = updated;
      all[modelId] = nextSets;
      writeAll(all);
      this.notify();
      return { ...updated, elementIds: [...updated.elementIds] };
    }
    throw new Error(`Selection set ${id} not found.`);
  }

  /** Remove a set. Silent no-op if the id is absent (matches the spec
   *  signature — ``delete`` returns ``void``). */
  delete(id: string): void {
    const all = readAll();
    let changed = false;
    for (const [modelId, sets] of Object.entries(all)) {
      const next = sets.filter((s) => s.id !== id);
      if (next.length !== sets.length) {
        all[modelId] = next;
        changed = true;
      }
    }
    if (changed) {
      writeAll(all);
      this.notify();
    }
  }

  /** Subscribe to mutations. Returns an unsubscribe function. */
  subscribe(cb: () => void): () => void {
    this.subscribers.add(cb);
    return () => {
      this.subscribers.delete(cb);
    };
  }

  private notify(): void {
    for (const cb of this.subscribers) {
      try {
        cb();
      } catch {
        // Swallow subscriber errors — they should not break the store.
      }
    }
  }
}

/** Singleton instance — colocated so multiple panels share the same
 *  subscription set and cross-tab listener. */
export const selectionSetsStore = new SelectionSetsStore();

/** Test-only knobs (kept in sync with SavedViewsStore's pattern). */
export const __test__ = {
  STORAGE_KEY,
  MAX_SETS_PER_MODEL,
  MAX_ELEMENT_IDS_PER_SET,
  NAME_MAX,
  NOTE_MAX,
};
