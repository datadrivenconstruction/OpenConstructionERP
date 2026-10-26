// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Text diff of two sheets that carry a text layer.
 *
 * Pixel diff says "something changed here"; the text layer says what: a
 * dimension that went from 3200 to 3400, a note that was reworded, a title
 * block that moved from revision B to C. Items are compared in the new
 * sheet's frame (old boxes go through the alignment), first by equal text
 * close by, then by position: what is left at the same place with other text
 * is a changed value, what is left alone was added or removed.
 */

import { applyAffine, type Affine } from './transform';

export interface TextItem {
  str: string;
  /** Box in PDF units, top-left origin. */
  x: number;
  y: number;
  w: number;
  h: number;
}

export type TextChangeKind = 'changed' | 'added' | 'removed';

export interface TextChange {
  change: TextChangeKind;
  x: number;
  y: number;
  w: number;
  h: number;
  old_text: string | null;
  new_text: string | null;
  /** Both sides hold a number and only the number differs (a revised dimension). */
  numeric: boolean;
}

export function normalizeText(s: string): string {
  return s.normalize('NFKC').replace(/\s+/g, ' ').trim();
}

const NUMBER = /[-+]?\d+(?:[.,]\d+)*/g;

/** Whether two strings differ only in their numbers ("3200 mm" vs "3400 mm"). */
export function isNumericChange(a: string, b: string): boolean {
  if (a === b) return false;
  const na = a.match(NUMBER);
  const nb = b.match(NUMBER);
  if (!na || !nb) return false;
  return a.replace(NUMBER, '#') === b.replace(NUMBER, '#');
}

function mapBox(item: TextItem, m: Affine): TextItem {
  const corners = [
    applyAffine(m, item.x, item.y),
    applyAffine(m, item.x + item.w, item.y),
    applyAffine(m, item.x, item.y + item.h),
    applyAffine(m, item.x + item.w, item.y + item.h),
  ];
  const xs = corners.map((c) => c[0]);
  const ys = corners.map((c) => c[1]);
  const x = Math.min(...xs);
  const y = Math.min(...ys);
  return { str: item.str, x, y, w: Math.max(...xs) - x, h: Math.max(...ys) - y };
}

function centre(i: TextItem): [number, number] {
  return [i.x + i.w / 2, i.y + i.h / 2];
}

function dist(a: TextItem, b: TextItem): number {
  const [ax, ay] = centre(a);
  const [bx, by] = centre(b);
  return Math.hypot(ax - bx, ay - by);
}

export interface TextDiffOptions {
  /** Equal text closer than this (PDF units) is the same item. */
  sameRadius?: number;
  /** Different text closer than this is one item whose value changed. */
  changedRadius?: number;
}

export function diffText(
  oldItems: TextItem[],
  newItems: TextItem[],
  oldToNew: Affine,
  options: TextDiffOptions = {},
): TextChange[] {
  const sameRadius = options.sameRadius ?? 6;
  const changedRadius = options.changedRadius ?? 12;
  const olds = oldItems
    .map((i) => ({ ...mapBox(i, oldToNew), str: normalizeText(i.str) }))
    .filter((i) => i.str.length > 0);
  const news = newItems.map((i) => ({ ...i, str: normalizeText(i.str) })).filter((i) => i.str.length > 0);

  const oldUsed = new Array<boolean>(olds.length).fill(false);
  const newUsed = new Array<boolean>(news.length).fill(false);
  const byText = new Map<string, number[]>();
  olds.forEach((o, i) => {
    const list = byText.get(o.str) ?? [];
    list.push(i);
    byText.set(o.str, list);
  });

  // Pass 1: the same text close by.
  news.forEach((n, ni) => {
    let best = -1;
    let bestD = sameRadius;
    for (const oi of byText.get(n.str) ?? []) {
      if (oldUsed[oi]) continue;
      const d = dist(olds[oi]!, n);
      if (d <= bestD) {
        best = oi;
        bestD = d;
      }
    }
    if (best >= 0) {
      oldUsed[best] = true;
      newUsed[ni] = true;
    }
  });

  // Pass 2: whatever is left at the same place with different text.
  const changes: TextChange[] = [];
  const pairs: Array<{ oi: number; ni: number; d: number }> = [];
  news.forEach((n, ni) => {
    if (newUsed[ni]) return;
    olds.forEach((o, oi) => {
      if (oldUsed[oi]) return;
      const d = dist(o, n);
      if (d <= changedRadius) pairs.push({ oi, ni, d });
    });
  });
  pairs.sort((a, b) => a.d - b.d);
  for (const { oi, ni } of pairs) {
    if (oldUsed[oi] || newUsed[ni]) continue;
    oldUsed[oi] = true;
    newUsed[ni] = true;
    const o = olds[oi]!;
    const n = news[ni]!;
    const x = Math.min(o.x, n.x);
    const y = Math.min(o.y, n.y);
    changes.push({
      change: 'changed',
      x,
      y,
      w: Math.max(o.x + o.w, n.x + n.w) - x,
      h: Math.max(o.y + o.h, n.y + n.h) - y,
      old_text: o.str,
      new_text: n.str,
      numeric: isNumericChange(o.str, n.str),
    });
  }
  news.forEach((n, ni) => {
    if (!newUsed[ni]) {
      changes.push({ change: 'added', x: n.x, y: n.y, w: n.w, h: n.h, old_text: null, new_text: n.str, numeric: false });
    }
  });
  olds.forEach((o, oi) => {
    if (!oldUsed[oi]) {
      changes.push({ change: 'removed', x: o.x, y: o.y, w: o.w, h: o.h, old_text: o.str, new_text: null, numeric: false });
    }
  });
  return changes;
}
