// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pixel regions plus text changes into the change list that is stored.
 *
 * A changed value (3200 -> 3400) is one row of kind `text`; the pixel region
 * it causes is dropped when the text box covers most of it, so the reviewer
 * reads the value instead of a red and blue smudge. Added or removed text
 * that falls inside a pixel region is folded into that region's row.
 * Coordinates leave here in PDF units of the new sheet.
 */

import { coveredShare, type DiffRegion } from './cluster';
import type { TextChange } from './textDiff';

export type ChangeKind = 'added' | 'removed' | 'modified' | 'text';

export interface DraftChange {
  kind: ChangeKind;
  x: number;
  y: number;
  w: number;
  h: number;
  score: number | null;
  old_text: string | null;
  new_text: string | null;
  details: Record<string, unknown>;
}

/** Share of a pixel region a changed-text box must cover to stand for it. */
const TEXT_COVERS = 0.6;
/** PDF units of padding around a text box when matching it to pixel regions. */
const TEXT_PAD = 2;

function join(a: string | null, b: string | null): string | null {
  if (!a) return b;
  if (!b) return a;
  return `${a} ${b}`;
}

export function buildChanges(
  regions: DiffRegion[],
  texts: TextChange[],
  pxPerUnit: number,
  maxChanges = 500,
): DraftChange[] {
  const out: DraftChange[] = [];
  const changed = texts.filter((t) => t.change === 'changed');
  const loose = texts.filter((t) => t.change !== 'changed');
  const padded = (t: TextChange) => ({ x: t.x - TEXT_PAD, y: t.y - TEXT_PAD, w: t.w + 2 * TEXT_PAD, h: t.h + 2 * TEXT_PAD });

  for (const t of changed) {
    out.push({
      kind: 'text',
      x: t.x,
      y: t.y,
      w: t.w,
      h: t.h,
      score: null,
      old_text: t.old_text,
      new_text: t.new_text,
      details: { numeric: t.numeric },
    });
  }
  const usedLoose = new Set<number>();
  for (const r of regions) {
    const box = { x: r.x / pxPerUnit, y: r.y / pxPerUnit, w: r.w / pxPerUnit, h: r.h / pxPerUnit };
    if (changed.some((t) => coveredShare(box, padded(t)) >= TEXT_COVERS)) continue;
    let oldText: string | null = null;
    let newText: string | null = null;
    loose.forEach((t, i) => {
      if (usedLoose.has(i) || coveredShare(padded(t), box) < 0.5) return;
      usedLoose.add(i);
      if (t.change === 'added') newText = join(newText, t.new_text);
      else oldText = join(oldText, t.old_text);
    });
    out.push({
      kind: r.kind,
      ...box,
      score: r.added + r.removed,
      old_text: oldText,
      new_text: newText,
      details: { added_px: r.added, removed_px: r.removed },
    });
  }
  return out.slice(0, maxChanges);
}
