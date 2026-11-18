// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure editing of a document layout: block list operations, locks, language
 * fallback and an undo/redo history. The server normalises and checks every
 * template again; nothing here is trusted for publishing.
 */

import type {
  BlockType,
  I18nText,
  LayoutBlock,
  LayoutLocks,
  LayoutSpecInfo,
  LayoutTemplate,
  TableColumn,
} from './layoutApi';

/** Block types a firm can add; `section` blocks belong to the module and are never added by hand. */
export const ADDABLE_BLOCKS: BlockType[] = [
  'heading',
  'text',
  'fields',
  'table',
  'totals',
  'signatures',
  'clause',
  'notes',
  'image',
  'qr',
  'columns',
  'spacer',
  'page_break',
];

let counter = 0;

/** A block id unique within *taken*. */
export function freshId(type: string, taken: Set<string>): string {
  let id = '';
  do {
    counter += 1;
    id = `${type.replace(/[^a-z_]/g, '')}_${Date.now().toString(36).slice(-4)}${counter}`;
  } while (taken.has(id));
  return id;
}

export function allBlockIds(blocks: LayoutBlock[]): Set<string> {
  const ids = new Set<string>();
  const walk = (list: LayoutBlock[]) => {
    for (const b of list) {
      ids.add(b.id);
      if (b.type === 'columns') for (const col of (b.columns as LayoutBlock[][]) ?? []) walk(col);
    }
  };
  walk(blocks);
  return ids;
}

/** A new block with sensible content for the document. */
export function newBlock(type: BlockType, spec: LayoutSpecInfo, taken: Set<string>, locale: string): LayoutBlock {
  const id = freshId(type, taken);
  switch (type) {
    case 'heading':
      return { id, type, level: 1, text: { [locale]: '' } };
    case 'text':
    case 'notes':
      return { id, type, text: { [locale]: '' } };
    case 'fields':
      return { id, type, layout: 'pairs', fields: [] };
    case 'table': {
      const collection = spec.collections[0];
      return {
        id,
        type,
        collection: collection?.id ?? '',
        columns: (collection?.columns ?? []).map((c) => ({ id: c.id })),
      };
    }
    case 'totals':
      return { id, type, rows: [] };
    case 'signatures':
      return { id, type, signers: [] };
    case 'image':
      return { id, type, source: 'logo', width_mm: 40 };
    case 'qr':
      return { id, type, field: 'doc.number', size_mm: 22, caption: true };
    case 'clause':
      return { id, type, clause_id: '' };
    case 'columns':
      return { id, type, columns: [[], []], ratios: [1, 1] };
    case 'spacer':
      return { id, type, height_mm: 6 };
    default:
      return { id, type };
  }
}

/** Why a block may not be hidden or deleted, or null. */
export function blockLock(block: LayoutBlock, locks: LayoutLocks): string | null {
  const key = block.type === 'section' ? (block.section ?? block.id) : block.id;
  return locks.sections[key] ?? null;
}

/** Why a column may not be hidden or removed, or null. */
export function columnLock(collection: string | undefined, columnId: string, locks: LayoutLocks): string | null {
  return (collection && locks.columns[collection]?.[columnId]) || null;
}

/** Why a field may not be removed from a fields block, or null. */
export function fieldLock(path: string, locks: LayoutLocks): string | null {
  return locks.fields[path] ?? null;
}

/** Text in *locale*, else its base language, else the primary language, else English. */
export function textIn(value: I18nText | undefined, locale: string, primary = 'en'): string | undefined {
  if (!value) return undefined;
  const baseLang = locale.split('-')[0];
  for (const lang of [locale, baseLang, primary, 'en']) {
    if (lang && value[lang] !== undefined) return value[lang];
  }
  return undefined;
}

export function setText(value: I18nText | undefined, locale: string, text: string): I18nText {
  const next = { ...(value ?? {}) };
  if (text === '') delete next[locale];
  else next[locale] = text;
  return next;
}

export function moveItem<T>(list: T[], from: number, to: number): T[] {
  if (from === to || from < 0 || to < 0 || from >= list.length || to >= list.length) return list;
  const next = list.slice();
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item as T);
  return next;
}

export function updateBlock(template: LayoutTemplate, id: string, patch: Partial<LayoutBlock>): LayoutTemplate {
  const walk = (list: LayoutBlock[]): LayoutBlock[] =>
    list.map((b) => {
      if (b.id === id) return { ...b, ...patch };
      if (b.type === 'columns') return { ...b, columns: ((b.columns as LayoutBlock[][]) ?? []).map(walk) };
      return b;
    });
  return { ...template, body: walk(template.body) };
}

export function removeBlock(template: LayoutTemplate, id: string): LayoutTemplate {
  const walk = (list: LayoutBlock[]): LayoutBlock[] =>
    list
      .filter((b) => b.id !== id)
      .map((b) => (b.type === 'columns' ? { ...b, columns: ((b.columns as LayoutBlock[][]) ?? []).map(walk) } : b));
  return { ...template, body: walk(template.body) };
}

/** A copy of the block right below it, with fresh ids (children too). */
export function duplicateBlock(template: LayoutTemplate, id: string): LayoutTemplate {
  const taken = allBlockIds(template.body);
  const clone = (b: LayoutBlock): LayoutBlock => {
    const copy: LayoutBlock = JSON.parse(JSON.stringify(b));
    copy.id = freshId(b.type, taken);
    taken.add(copy.id);
    if (copy.type === 'section') copy.section = b.section ?? b.id;
    if (copy.type === 'columns') copy.columns = ((copy.columns as LayoutBlock[][]) ?? []).map((col) => col.map(clone));
    return copy;
  };
  const index = template.body.findIndex((b) => b.id === id);
  if (index < 0) return template;
  const body = template.body.slice();
  body.splice(index + 1, 0, clone(template.body[index] as LayoutBlock));
  return { ...template, body };
}

export function tableColumns(block: LayoutBlock): TableColumn[] {
  return (block.columns as TableColumn[] | undefined) ?? [];
}

/** Merge fields a text may reference, as `{{path}}`. */
export function mergeToken(path: string): string {
  return `{{${path}}}`;
}

/** Paths in `{{...}}` that the document does not know. */
export function unknownFields(text: string, known: Set<string>): string[] {
  const out: string[] = [];
  for (const match of text.matchAll(/\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}/g)) {
    const path = match[1] ?? '';
    if (!known.has(path) && !out.includes(path)) out.push(path);
  }
  return out;
}

// ── Undo / redo ──────────────────────────────────────────────────────────

export interface History<T> {
  past: T[];
  present: T;
  future: T[];
}

const HISTORY_LIMIT = 100;

export function historyOf<T>(present: T): History<T> {
  return { past: [], present, future: [] };
}

export function historyPush<T>(h: History<T>, next: T): History<T> {
  if (next === h.present) return h;
  return { past: [...h.past, h.present].slice(-HISTORY_LIMIT), present: next, future: [] };
}

export function historyUndo<T>(h: History<T>): History<T> {
  const prev = h.past[h.past.length - 1];
  if (prev === undefined) return h;
  return { past: h.past.slice(0, -1), present: prev, future: [h.present, ...h.future] };
}

export function historyRedo<T>(h: History<T>): History<T> {
  const [next, ...rest] = h.future;
  if (next === undefined) return h;
  return { past: [...h.past, h.present], present: next, future: rest };
}
