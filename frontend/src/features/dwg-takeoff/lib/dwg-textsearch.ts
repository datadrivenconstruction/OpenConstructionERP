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
 * Estimate the world-space box a single-line TEXT entity occupies.
 *
 * DXF text grows up and to the right from its insertion point; glyph width
 * is font dependent, so we use the same 0.6*height-per-character heuristic
 * `viewport.textExtents` uses. That is where the resemblance ends, and the
 * gap is now wider than it was: this box is in world units at the authored
 * height, while the renderer draws every string clamped to a readable pixel
 * band, so at extreme zoom a highlight and its glyph are visibly different
 * sizes. It is a real defect and it is not this function's to fix alone - a
 * highlight that followed the drawn size would have to be computed in screen
 * space, which is a change to the find-text overlay rather than to an
 * estimate. Rotation is deliberately ignored here, unlike in the fit: a
 * highlight has to sit where the string is, so a rotated match is framed by
 * its axis-aligned box. Returns null if the entity has no insertion point or
 * no text.
 */
export function textBoxForEntity(e: DxfEntity): WorldBox | null {
  if (e.type !== 'TEXT' || !e.start || !e.text) return null;
  const h = e.height && e.height > 0 ? e.height : 2.5;
  // Longest line drives the width so multi-line MTEXT still frames sensibly.
  const longest = e.text.split('\n').reduce((m, line) => Math.max(m, line.length), 0);
  const width = Math.max(h, h * longest * 0.6);
  const lines = e.text.split('\n').length;
  const height = h * lines * 1.3;
  return {
    minX: e.start.x,
    maxX: e.start.x + width,
    minY: e.start.y,
    maxY: e.start.y + height,
  };
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
