// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Issue-tracking layer for markups (pure helpers, no React / no fetch).
 *
 * A markup starts life as a bare drawing annotation. This module upgrades it
 * into a lightweight tracked site issue by attaching a *priority* and a *due
 * date*, surfacing an *overdue* state, and computing the geometry centroid a
 * markup would pin to when promoted to a full punch-list item.
 *
 * None of this needs a backend schema change: the values ride in the markup's
 * existing ``metadata`` JSONB column. The PATCH endpoint shallow-merges the
 * ``metadata`` it receives onto the stored value, so writing ``{ priority }``
 * leaves ``due_date`` / ``punch_item_id`` untouched, and vice versa.
 */

import type { Markup } from './api';

/* ── Priority ─────────────────────────────────────────────────────────── */

/**
 * Priority vocabulary. Deliberately identical to the punch-list's
 * ``PunchPriority`` so "Convert to issue" maps 1:1 with no translation table.
 */
export type MarkupPriority = 'low' | 'medium' | 'high' | 'critical';

/** Ordered low -> critical for filter dropdowns and sorting. */
export const MARKUP_PRIORITIES: readonly MarkupPriority[] = [
  'low',
  'medium',
  'high',
  'critical',
] as const;

/** English fallbacks for the priority labels (wrapped in i18n at call sites). */
export const PRIORITY_LABELS: Record<MarkupPriority, string> = {
  low: 'Low',
  medium: 'Medium',
  high: 'High',
  critical: 'Critical',
};

/**
 * Tailwind classes for the priority chip, light + dark. Kept here (not JSX)
 * so both the list chips and any future surface share one palette.
 */
export const PRIORITY_CHIP_CLASSES: Record<MarkupPriority, string> = {
  critical:
    'bg-red-100 text-red-700 border-red-300 dark:bg-red-900/30 dark:text-red-300 dark:border-red-700',
  high: 'bg-orange-100 text-orange-700 border-orange-300 dark:bg-orange-900/30 dark:text-orange-300 dark:border-orange-700',
  medium:
    'bg-amber-100 text-amber-700 border-amber-300 dark:bg-amber-900/30 dark:text-amber-300 dark:border-amber-700',
  low: 'bg-slate-100 text-slate-600 border-slate-300 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-600',
};

export function isMarkupPriority(v: unknown): v is MarkupPriority {
  return v === 'low' || v === 'medium' || v === 'high' || v === 'critical';
}

/** Read the priority stored in a markup's metadata, or ``null`` when unset. */
export function getMarkupPriority(
  m: Pick<Markup, 'metadata'> | null | undefined,
): MarkupPriority | null {
  const v = m?.metadata?.['priority'];
  return isMarkupPriority(v) ? v : null;
}

/* ── Due date ─────────────────────────────────────────────────────────── */

/**
 * Read the due date (``YYYY-MM-DD``) stored in metadata, or ``null``. Any
 * time component is trimmed so callers always get a bare calendar date, which
 * is what ``<input type="date">`` and the overdue check both expect.
 */
export function getMarkupDueDate(
  m: Pick<Markup, 'metadata'> | null | undefined,
): string | null {
  const v = m?.metadata?.['due_date'];
  if (typeof v !== 'string' || !v.trim()) return null;
  const dateOnly = v.trim().slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(dateOnly) ? dateOnly : null;
}

/**
 * A markup is overdue when it carries a due date in the past *and* is still
 * open. Resolved / archived markups are done, so they are never overdue even
 * if the date has passed. The comparison is against end-of-day local time so a
 * markup due "today" only flips overdue once today is over.
 */
export function isMarkupOverdue(
  m: Pick<Markup, 'metadata' | 'status'> | null | undefined,
): boolean {
  if (!m) return false;
  if (m.status === 'resolved' || m.status === 'archived') return false;
  const due = getMarkupDueDate(m);
  if (!due) return false;
  const dueMs = Date.parse(`${due}T23:59:59`);
  return Number.isFinite(dueMs) && dueMs < Date.now();
}

/* ── Punch-list link ──────────────────────────────────────────────────── */

/**
 * The id of the punch-list item this markup was promoted into, if any.
 * Presence of this key is what flips the row's action from "Convert to issue"
 * to "Open issue" and blocks a duplicate conversion.
 */
export function getMarkupPunchId(
  m: Pick<Markup, 'metadata'> | null | undefined,
): string | null {
  const v = m?.metadata?.['punch_item_id'];
  return typeof v === 'string' && v.trim() ? v.trim() : null;
}

/* ── Geometry centroid (0..1) ─────────────────────────────────────────── */

const clamp01 = (n: number): number => Math.min(1, Math.max(0, n));

function toFiniteNumber(v: unknown): number | null {
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

/**
 * Compute the normalised (0..1) centroid a markup would pin to on its sheet.
 *
 * Markup vertices are stored in PDF user units (bottom-left origin) and carry
 * no page size, whereas a punch pin is placed as a fraction of the sheet
 * (top-left origin). We therefore normalise *only* when we can do it honestly:
 *
 *   1. If the geometry carries an explicit page size, divide by it (and flip
 *      Y for PDF-space points so the pin lands the right way up).
 *   2. Otherwise, if the centroid is already inside the unit square, the
 *      points were stored pre-normalised (some DWG / pin sources) - use them.
 *   3. Otherwise return ``null``: we cannot know where on the sheet this is,
 *      so the promoted issue is created *unplaced* rather than pinned to a
 *      wrong spot (a wrong pin actively misinforms; an unplaced one does not).
 *
 * The pin board treats a ``null`` location as an unplaced item the user can
 * drag onto the sheet, so returning ``null`` degrades gracefully.
 */
export function computeGeometryCentroid01(
  geometry: Record<string, unknown> | null | undefined,
): { x: number; y: number } | null {
  if (!geometry || typeof geometry !== 'object') return null;
  const g = geometry as Record<string, unknown>;

  const pts: Array<{ x: number; y: number }> = [];
  const pushXY = (x: unknown, y: unknown): void => {
    const nx = toFiniteNumber(x);
    const ny = toFiniteNumber(y);
    if (nx !== null && ny !== null) pts.push({ x: nx, y: ny });
  };

  const rawPoints = g['points'];
  if (Array.isArray(rawPoints)) {
    for (const p of rawPoints) {
      if (Array.isArray(p) && p.length >= 2) {
        pushXY(p[0], p[1]);
      } else if (p && typeof p === 'object') {
        pushXY((p as Record<string, unknown>)['x'], (p as Record<string, unknown>)['y']);
      }
    }
  }
  // Scalar fallbacks for pin-like single-point shapes.
  if (pts.length === 0) {
    if ('x' in g && 'y' in g) pushXY(g['x'], g['y']);
    else if ('cx' in g && 'cy' in g) pushXY(g['cx'], g['cy']);
  }
  if (pts.length === 0) return null;

  let sx = 0;
  let sy = 0;
  for (const p of pts) {
    sx += p.x;
    sy += p.y;
  }
  const cx = sx / pts.length;
  const cy = sy / pts.length;

  const positive = (v: unknown): number => {
    const n = toFiniteNumber(v);
    return n !== null && n > 0 ? n : 0;
  };
  const pw = positive(g['page_width'] ?? g['pageWidth'] ?? g['width'] ?? g['w']);
  const ph = positive(g['page_height'] ?? g['pageHeight'] ?? g['height'] ?? g['h']);

  if (pw > 0 && ph > 0) {
    const nx = cx / pw;
    // PDF user space is bottom-left origin; the sheet overlay is top-left.
    const ny = g['coord_space'] === 'pdf' ? 1 - cy / ph : cy / ph;
    return { x: clamp01(nx), y: clamp01(ny) };
  }

  if (cx >= 0 && cx <= 1 && cy >= 0 && cy <= 1) {
    return { x: cx, y: cy };
  }

  return null;
}
