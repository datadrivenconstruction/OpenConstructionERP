// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Column-width maths for the schedule activity grid.
 *
 * Everything here is pure and DOM-free so the arithmetic that decides how
 * wide a column ends up can be tested without a browser. The component owns
 * the events (mousedown on a grip, a ResizeObserver on the scroll wrap) and
 * the measuring; this file owns *what the numbers should be*.
 *
 * Three rules the grid has to keep, spelled once here:
 *
 * 1. A column is never squeezed under its own minimum. The minimum is set
 *    from the header label, because a header that reads "Deliver…" is worse
 *    than a table that scrolls.
 * 2. When the columns add up to less than the wrap can show, the spare width
 *    goes to ONE nominated column (the activity name) rather than being
 *    smeared across every column - a 12px-wider date column helps nobody.
 * 3. When they add up to more, every other column gives ground pro-rata to
 *    its own minimum first and the grow column gives last. Below every
 *    minimum the wrap is *meant* to scroll and no further trimming happens;
 *    pretending otherwise is how a fit loop wedges itself on.
 */

export interface ColumnSpec {
  /** Stable key - also the localStorage key and the `data-col` attribute. */
  key: string;
  /** Narrowest this column may ever be, in CSS pixels. */
  min: number;
  /** Width before the user has ever touched it. */
  def: number;
}

/** The widest auto-fit will ever make a column. A 900px name column is not a fit. */
export const MAX_COLUMN_WIDTH = 520;

/** Horizontal padding + border a cell adds around its content, in pixels. */
export const CELL_CHROME = 26;

/** Widths keyed by column key. A key the map does not carry falls back to `def`. */
export type ColumnWidths = Record<string, number>;

/** `spec.min <= w <= MAX_COLUMN_WIDTH`, rounded to a whole pixel. */
export function clampWidth(spec: ColumnSpec, w: number): number {
  if (!Number.isFinite(w)) return spec.def;
  return Math.round(Math.min(MAX_COLUMN_WIDTH, Math.max(spec.min, w)));
}

/** Every column at its stored width, or its default where nothing is stored. */
export function resolveWidths(specs: ColumnSpec[], stored: ColumnWidths | null): ColumnWidths {
  const out: ColumnWidths = {};
  for (const s of specs) {
    const v = stored?.[s.key];
    out[s.key] = typeof v === 'number' && Number.isFinite(v) ? clampWidth(s, v) : s.def;
  }
  return out;
}

export function totalWidth(specs: ColumnSpec[], widths: ColumnWidths): number {
  return specs.reduce((sum, s) => sum + (widths[s.key] ?? s.def), 0);
}

/**
 * Fit `widths` to an `available` wrap width.
 *
 * Returns a NEW map; the input is never mutated. `available <= 0` means the
 * wrap is hidden (another view tab is showing) and measuring it would be
 * nonsense, so the widths are handed back untouched.
 *
 * The `growKey` column absorbs spare width and is the last to give it up.
 * Aiming one pixel under `available` is deliberate: fractional column widths
 * round up, and a single pixel of overflow buys a real horizontal scrollbar.
 *
 * Both halves are switched off once the user has set widths of their own, and
 * that is the whole point of the flags. While the grid is at its defaults it
 * should fit the wrap - no gratuitous scrollbar, no dead space. The moment a
 * grip is dragged the numbers are the user's: re-widening the name column
 * would make dragging it narrower look broken, and re-shrinking a widened
 * column back to its minimum would make dragging it wider look broken. Their
 * widths are honoured and the wrap scrolls, which is what every spreadsheet
 * does. "Fit all columns" from the header menu is how they ask for the fit
 * back.
 *
 * The per-column minimum is applied either way: it is a floor, not a
 * preference, and a clipped header label is never the right answer.
 */
export function fitColumnWidths(
  specs: ColumnSpec[],
  widths: ColumnWidths,
  available: number,
  growKey: string,
  opts: { expand?: boolean; shrink?: boolean } = {},
): ColumnWidths {
  // The minimum is a hard floor, not just a shrink limit: a column whose
  // header turned out wider than its default has to be widened even when
  // there is no fitting to do, or the label is clipped from the first paint.
  const out: ColumnWidths = {};
  for (const s of specs) out[s.key] = Math.max(s.min, widths[s.key] ?? s.def);
  if (!(available > 0) || specs.length === 0) return out;

  const target = Math.floor(available) - 1;
  const total = totalWidth(specs, out);
  const grow: ColumnSpec = specs.find((s) => s.key === growKey) ?? (specs[0] as ColumnSpec);
  const at = (key: string, fallback: number): number => out[key] ?? fallback;

  if (total <= target) {
    // Room to spare: all of it to the grow column, capped so a wide monitor
    // does not produce a 1200px name column with a lake of dead space in it.
    if (opts.expand !== false) {
      out[grow.key] = Math.min(MAX_COLUMN_WIDTH, at(grow.key, grow.def) + (target - total));
    }
    return out;
  }

  if (opts.shrink === false) return out;

  // Over: take it off the others pro-rata to the slack each has over its own
  // minimum, then off the grow column, and stop at the floor.
  let need = total - target;
  let room = 0;
  for (const s of specs) {
    if (s.key === grow.key) continue;
    room += Math.max(0, at(s.key, s.def) - s.min);
  }
  const take = Math.min(need, room);
  if (room > 0) {
    for (const s of specs) {
      if (s.key === grow.key) continue;
      const current = at(s.key, s.def);
      const slack = Math.max(0, current - s.min);
      out[s.key] = Math.max(s.min, Math.round(current - (take * slack) / room));
    }
  }
  need -= take;
  if (need > 0) out[grow.key] = Math.max(grow.min, at(grow.key, grow.def) - need);

  // Settle the rounding residual on the grow column. Sharing a shrink out
  // pro-rata rounds every column independently, and those half-pixels add up:
  // a couple of pixels over the wrap is all it takes for the browser to paint
  // a real horizontal scrollbar under a table that visually fits.
  const settled = totalWidth(specs, out);
  if (settled !== target) {
    out[grow.key] = Math.max(grow.min, at(grow.key, grow.def) - (settled - target));
  }
  return out;
}

/**
 * The width a column needs to show its widest cell without clipping.
 *
 * `measure` turns a string into a pixel width - a canvas `measureText` in the
 * browser, a stub in a test. `extra` is per-string furniture the text does not
 * account for (a critical-path badge, a milestone diamond, a select's arrow).
 */
export function autoFitWidth(
  texts: string[],
  measure: (s: string) => number,
  opts: { min: number; extra?: number; pad?: number },
): number {
  const pad = opts.pad ?? CELL_CHROME;
  const extra = opts.extra ?? 0;
  let widest = 0;
  for (const s of texts) {
    if (!s) continue;
    const w = measure(s);
    if (Number.isFinite(w) && w > widest) widest = w;
  }
  return Math.round(Math.min(MAX_COLUMN_WIDTH, Math.max(opts.min, Math.ceil(widest) + pad + extra)));
}

/* ── Persistence ──────────────────────────────────────────────────────── */

export function widthsStorageKey(scopeId: string): string {
  return `oe.schedule.grid-cols.${scopeId}`;
}

/**
 * Read stored widths. Anything unreadable (no localStorage in this context,
 * a private window, a half-written value) reads as "nothing stored" - the
 * grid falls back to its defaults rather than throwing on render.
 */
export function loadWidths(scopeId: string): ColumnWidths | null {
  try {
    const raw = globalThis.localStorage?.getItem(widthsStorageKey(scopeId));
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
    const out: ColumnWidths = {};
    for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof v === 'number' && Number.isFinite(v)) out[k] = v;
    }
    return Object.keys(out).length ? out : null;
  } catch {
    return null;
  }
}

export function saveWidths(scopeId: string, widths: ColumnWidths): void {
  try {
    globalThis.localStorage?.setItem(widthsStorageKey(scopeId), JSON.stringify(widths));
  } catch {
    /* Storage full or blocked: the widths still work for this session. */
  }
}

export function clearWidths(scopeId: string): void {
  try {
    globalThis.localStorage?.removeItem(widthsStorageKey(scopeId));
  } catch {
    /* ignore */
  }
}

/* ── Text measurement ─────────────────────────────────────────────────── */

let measureCtx: CanvasRenderingContext2D | null | undefined;

/**
 * A text measurer for `autoFitWidth`, bound to `font` (a CSS `font` shorthand).
 *
 * Canvas is used rather than a hidden DOM node because the widest cell in a
 * six-hundred-row column would otherwise cost six hundred layouts. Where there
 * is no canvas (jsdom, a locked-down context) it degrades to a per-character
 * estimate, which is coarse but never throws and never returns 0 - a 0 would
 * silently collapse every column to its minimum.
 */
export function textMeasurer(font: string): (s: string) => number {
  if (measureCtx === undefined) {
    try {
      measureCtx = document.createElement('canvas').getContext('2d');
    } catch {
      measureCtx = null;
    }
  }
  const ctx = measureCtx;
  if (!ctx || typeof ctx.measureText !== 'function') {
    return (s: string) => s.length * 7;
  }
  ctx.font = font;
  return (s: string) => {
    try {
      return ctx.measureText(s).width;
    } catch {
      return s.length * 7;
    }
  };
}
