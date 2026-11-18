/** Kurztext / Langtext helpers for the BOQ grid.
 *
 *  The Langtext of a position or section lives in `metadata.gaeb_long_text`
 *  (line breaks preserved). The GAEB importer fills it; the text editor writes
 *  it through the `long_text` field of a position PATCH. */

import type { BoqDescDensity } from '@/stores/useBoqDescDensityStore';

/** Long text of a position, or null when absent/blank or equal to the short text. */
export function getGaebLongText(meta: unknown): string | null {
  if (!meta || typeof meta !== 'object') return null;
  const raw = (meta as { gaeb_long_text?: unknown }).gaeb_long_text;
  if (typeof raw !== 'string') return null;
  const text = raw.replace(/\r\n?/g, '\n').trim();
  return text.length > 0 ? text : null;
}

/** GAEB cuts the Kurztext to 70 characters on export. */
export const GAEB_SHORT_TEXT_MAX = 70;

/** Line height (px) of the Kurztext and Langtext lines in the grid. */
export const TEXT_LINE_PX = 18;
/** Lines the "first lines" mode shows of a Langtext before it is cut. */
export const PREVIEW_LINES = 2;
/** Upper bound of Langtext lines a row grows to; the editor shows the rest. */
export const MAX_ROW_LINES = 60;

type Measure = (s: string) => number;

let canvasCtx: CanvasRenderingContext2D | null | undefined;
const widthCache = new Map<string, number>();

/** Width of `s` at the grid's 12px text, measured once per string. */
function measureText(s: string): number {
  const hit = widthCache.get(s);
  if (hit !== undefined) return hit;
  if (canvasCtx === undefined) {
    try {
      canvasCtx = typeof document !== 'undefined' ? document.createElement('canvas').getContext('2d') : null;
      if (canvasCtx) {
        const family = typeof getComputedStyle === 'function'
          ? getComputedStyle(document.body).fontFamily || 'sans-serif'
          : 'sans-serif';
        canvasCtx.font = `12px ${family}`;
      }
    } catch {
      canvasCtx = null;
    }
  }
  const w = canvasCtx ? canvasCtx.measureText(s).width : s.length * 6.4;
  if (widthCache.size > 20000) widthCache.clear();
  widthCache.set(s, w);
  return w;
}

/** Number of visual lines `text` wraps to in `widthPx` (greedy word wrap,
 *  hard line breaks honoured). Words longer than a line break mid-word. */
export function wrappedLineCount(text: string, widthPx: number, measure: Measure = measureText): number {
  if (!text) return 0;
  const width = Math.max(40, widthPx);
  const space = measure(' ');
  let lines = 0;
  for (const paragraph of text.split('\n')) {
    let used = 0;
    let count = 1;
    for (const word of paragraph.split(/\s+/)) {
      if (!word) continue;
      const w = measure(word);
      if (used === 0) {
        if (w > width) {
          count += Math.ceil(w / width) - 1;
          used = w % width;
        } else {
          used = w;
        }
      } else if (used + space + w <= width) {
        used += space + w;
      } else {
        count += 1;
        used = Math.min(w, width);
        if (w > width) count += Math.ceil(w / width) - 1;
      }
    }
    lines += count;
  }
  return lines;
}

/** How many lines of Kurztext and Langtext a row shows for a mode. */
export function visibleTextLines(opts: {
  shortText: string;
  longText: string | null;
  mode: BoqDescDensity;
  expanded: boolean;
  widthPx: number;
  measure?: Measure;
}): { shortLines: number; longLines: number; longTotal: number } {
  const { shortText, longText, mode, expanded, widthPx, measure } = opts;
  const full = expanded || mode === 'tall';
  const longTotal = longText ? wrappedLineCount(longText, widthPx, measure) : 0;
  let longLines = 0;
  if (longText) {
    if (full) longLines = Math.min(longTotal, MAX_ROW_LINES);
    else if (mode === 'comfortable') longLines = Math.min(longTotal, PREVIEW_LINES);
  }
  let shortLines = 1;
  if (mode !== 'compact' || expanded) {
    const wrapped = Math.max(1, wrappedLineCount(shortText, widthPx, measure));
    shortLines = full ? Math.min(wrapped, 12) : Math.min(wrapped, PREVIEW_LINES);
  }
  return { shortLines, longLines, longTotal };
}

/** Pixel height of a position row whose description shows these lines. */
export function positionRowHeight(base: number, lines: { shortLines: number; longLines: number }): number {
  if (lines.shortLines <= 1 && lines.longLines === 0) return base;
  const text = 10 + lines.shortLines * TEXT_LINE_PX + (lines.longLines > 0 ? 4 + lines.longLines * TEXT_LINE_PX : 0);
  return Math.max(base, text);
}

/** Header height of a section row; its Langtext adds lines below it. */
export const SECTION_HEADER_PX = 38;

/** Pixel height of a section row showing `longLines` lines of its Langtext. */
export function sectionRowHeight(longLines: number): number {
  return longLines > 0 ? SECTION_HEADER_PX + 8 + longLines * TEXT_LINE_PX : SECTION_HEADER_PX;
}
