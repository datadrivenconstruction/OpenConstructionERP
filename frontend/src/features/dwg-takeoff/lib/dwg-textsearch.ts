// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure helpers for "find text on drawing" in the DWG takeoff viewer.
 *
 * Unlike the PDF takeoff (which has to reconstruct text runs from a pdf.js
 * text layer), a DWG/DXF already carries TEXT / MTEXT entities with their
 * string content and an insertion point in world (drawing) units, so the
 * search is a straightforward scan over those entities. The backend maps
 * MTEXT -> TEXT for the renderer, so both arrive as `type: 'TEXT'` with a
 * populated `text` field.
 *
 * This module is intentionally free of React / canvas so it can be unit
 * tested with hand-built entity fixtures. The viewer consumes the returned
 * boxes (world units) to highlight matches and to frame the zoom-to-match.
 */

import type { DxfEntity } from '../api';
import { textWorldBox } from './viewport';

/** Axis-aligned box in world (drawing) units. */
export interface WorldBox {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

/** A single text hit. `index` is the running ordinal in reading order. */
export interface DwgTextMatch {
  entityId: string;
  /** The full text of the matched entity. */
  text: string;
  /** Short, single-line context around the first occurrence. */
  snippet: string;
  /** The entity's text box in world units (for highlight + zoom). */
  box: WorldBox;
  /** Box centre, in world units (zoom-to-match target). */
  center: { x: number; y: number };
  index: number;
}

/** Max characters of context shown around a hit in the result list. */
const SNIPPET_RADIUS = 28;

/**
 * Estimate the world-space box a TEXT entity occupies, for the find overlay.
 *
 * Shares `viewport.textWorldBox` with the renderer's layout, so justified
 * text and MTEXT attachment frame where the glyphs are drawn, and a rotated
 * label is framed by the axis-aligned box of its rotated rectangle. Glyph
 * width stays the 0.6*height-per-character estimate. Returns null if the
 * entity has no insertion point or no text.
 */
export function textBoxForEntity(e: DxfEntity): WorldBox | null {
  if (e.type !== 'TEXT') return null;
  return textWorldBox(e);
}

/**
 * A short, single-line context snippet around the first occurrence of the
 * query within `runText`, with ellipses where it was clipped.
 */
export function buildSnippet(runText: string, matchStart: number, matchLen: number): string {
  const flat = runText.replace(/\s+/g, ' ');
  // Re-locate the match in the whitespace-collapsed string for a tidy snippet.
  const start = Math.max(0, matchStart - SNIPPET_RADIUS);
  const end = Math.min(runText.length, matchStart + matchLen + SNIPPET_RADIUS);
  let s = runText.slice(start, end).replace(/\s+/g, ' ').trim();
  if (start > 0) s = `…${s}`;
  if (end < runText.length) s = `${s}…`;
  return s || flat.trim();
}

/**
 * Find every TEXT entity whose content contains `query` (case-insensitive),
 * one match per entity. Matches are returned in reading order: top-to-bottom
 * (DXF y grows up, so larger y first), then left-to-right, so Next / Previous
 * navigation walks the drawing the way a person reads it. `index` is assigned
 * after sorting so it is stable and 0-based.
 *
 * An empty / whitespace-only query yields no matches.
 */
export function findTextMatches(entities: DxfEntity[], query: string): DwgTextMatch[] {
  const q = query.trim().toLowerCase();
  if (q.length === 0) return [];

  const hits: Omit<DwgTextMatch, 'index'>[] = [];
  for (const e of entities) {
    if (e.type !== 'TEXT' || !e.text || !e.start) continue;
    const pos = e.text.toLowerCase().indexOf(q);
    if (pos === -1) continue;
    const box = textBoxForEntity(e);
    if (!box) continue;
    hits.push({
      entityId: e.id,
      text: e.text,
      snippet: buildSnippet(e.text, pos, q.length),
      box,
      center: { x: (box.minX + box.maxX) / 2, y: (box.minY + box.maxY) / 2 },
    });
  }

  // Reading order: larger world-y (visually higher) first, then smaller x.
  hits.sort((a, b) => {
    const dy = b.center.y - a.center.y;
    if (Math.abs(dy) > 1e-6) return dy;
    return a.center.x - b.center.x;
  });

  return hits.map((h, i) => ({ ...h, index: i }));
}
