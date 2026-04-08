/**
 * Gantt chart utility functions for date-to-pixel conversions,
 * time header generation, dependency arrow paths, and date range calculations.
 */

export type ViewMode = 'day' | 'week' | 'month' | 'quarter' | 'year';

/** Pixels per unit for each zoom level */
export const COLUMN_WIDTH: Record<ViewMode, number> = {
  day: 30,
  week: 40,
  month: 80,
  quarter: 120,
  year: 150,
};

/** Height of each activity row in pixels */
export const ROW_HEIGHT = 40;

/** Height of the two-row time header in pixels */
export const HEADER_HEIGHT = 48;

/** Width of the left activity table panel */
export const TABLE_WIDTH = 300;

/* ── Date helpers ───────────────────────────────────────────────── */

/** Strip time portion, returning midnight UTC for a given date string. */
function toUTCDay(d: Date): number {
  return Date.UTC(d.getFullYear(), d.getMonth(), d.getDate());
}

/** Number of calendar days between two dates (rounded). */
export function daysBetween(a: Date, b: Date): number {
  return Math.round((toUTCDay(b) - toUTCDay(a)) / (1000 * 60 * 60 * 24));
}

/** Add calendar days to a Date, returning a new Date. */
export function addDays(d: Date, n: number): Date {
  const result = new Date(d);
  result.setDate(result.getDate() + n);
  return result;
}

/* ── Coordinate conversions ─────────────────────────────────────── */

/** Convert a Date to an X pixel position relative to the timeline start. */
export function dateToPx(date: Date, viewMode: ViewMode, startDate: Date): number {
  const days = daysBetween(startDate, date);
  switch (viewMode) {
    case 'day':
      return days * COLUMN_WIDTH.day;
    case 'week':
      return (days / 7) * COLUMN_WIDTH.week;
    case 'month':
      return (days / 30) * COLUMN_WIDTH.month;
    case 'quarter':
      return (days / 91) * COLUMN_WIDTH.quarter;
    case 'year':
      return (days / 365) * COLUMN_WIDTH.year;
  }
}

/** Convert an X pixel position back to a Date. */
export function pxToDate(px: number, viewMode: ViewMode, startDate: Date): Date {
  let days: number;
  switch (viewMode) {
    case 'day':
      days = Math.round(px / COLUMN_WIDTH.day);
      break;
    case 'week':
      days = Math.round((px / COLUMN_WIDTH.week) * 7);
      break;
    case 'month':
      days = Math.round((px / COLUMN_WIDTH.month) * 30);
      break;
    case 'quarter':
      days = Math.round((px / COLUMN_WIDTH.quarter) * 91);
      break;
    case 'year':
      days = Math.round((px / COLUMN_WIDTH.year) * 365);
      break;
  }
  return addDays(startDate, days);
}

/* ── Time header generation ─────────────────────────────────────── */

export interface HeaderCell {
  label: string;
  x: number;
  width: number;
}

export interface TimeHeaders {
  /** Top row: months/years or quarters */
  topRow: HeaderCell[];
  /** Bottom row: days/week numbers/month names */
  bottomRow: HeaderCell[];
}

/** Generate two-row time header labels for the given date range and zoom. */
export function generateTimeHeaders(
  startDate: Date,
  endDate: Date,
  viewMode: ViewMode,
  locale: string,
): TimeHeaders {
  const topRow: HeaderCell[] = [];
  const bottomRow: HeaderCell[] = [];

  const topFmt = new Intl.DateTimeFormat(locale, { month: 'long', year: 'numeric' });

  if (viewMode === 'day') {
    // Top row: one cell per month
    const cursor = new Date(startDate);
    cursor.setDate(1);
    while (cursor <= endDate) {
      const monthStart = new Date(cursor);
      const monthEnd = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0);
      const effectiveStart = monthStart < startDate ? startDate : monthStart;
      const effectiveEnd = monthEnd > endDate ? endDate : monthEnd;
      const x = dateToPx(effectiveStart, viewMode, startDate);
      const xEnd = dateToPx(addDays(effectiveEnd, 1), viewMode, startDate);
      topRow.push({
        label: topFmt.format(effectiveStart),
        x,
        width: xEnd - x,
      });
      cursor.setMonth(cursor.getMonth() + 1);
      cursor.setDate(1);
    }

    // Bottom row: one cell per day
    const dayFmt = new Intl.DateTimeFormat(locale, { day: 'numeric' });
    const d = new Date(startDate);
    while (d <= endDate) {
      const x = dateToPx(d, viewMode, startDate);
      bottomRow.push({
        label: dayFmt.format(d),
        x,
        width: COLUMN_WIDTH.day,
      });
      d.setDate(d.getDate() + 1);
    }
  } else if (viewMode === 'week') {
    // Top row: one cell per month
    const cursor = new Date(startDate);
    cursor.setDate(1);
    while (cursor <= endDate) {
      const monthStart = new Date(cursor);
      const monthEnd = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0);
      const effectiveStart = monthStart < startDate ? startDate : monthStart;
      const effectiveEnd = monthEnd > endDate ? endDate : monthEnd;
      const x = dateToPx(effectiveStart, viewMode, startDate);
      const xEnd = dateToPx(addDays(effectiveEnd, 1), viewMode, startDate);
      topRow.push({
        label: topFmt.format(effectiveStart),
        x,
        width: xEnd - x,
      });
      cursor.setMonth(cursor.getMonth() + 1);
      cursor.setDate(1);
    }

    // Bottom row: one cell per week, labeled "W1", "W2", etc.
    const d = new Date(startDate);
    // Advance to next Monday
    const dow = d.getDay();
    if (dow !== 1) {
      d.setDate(d.getDate() + ((8 - dow) % 7 || 7));
    }
    let weekNum = 1;
    while (d <= endDate) {
      const x = dateToPx(d, viewMode, startDate);
      bottomRow.push({
        label: `W${weekNum}`,
        x,
        width: COLUMN_WIDTH.week,
      });
      d.setDate(d.getDate() + 7);
      weekNum++;
    }
  } else if (viewMode === 'month') {
    // month view
    // Top row: one cell per year
    const yearFmt = new Intl.DateTimeFormat(locale, { year: 'numeric' });
    const cursor = new Date(startDate);
    cursor.setMonth(0);
    cursor.setDate(1);
    while (cursor <= endDate) {
      const yearStart = new Date(cursor);
      const yearEnd = new Date(cursor.getFullYear(), 11, 31);
      const effectiveStart = yearStart < startDate ? startDate : yearStart;
      const effectiveEnd = yearEnd > endDate ? endDate : yearEnd;
      const x = dateToPx(effectiveStart, viewMode, startDate);
      const xEnd = dateToPx(addDays(effectiveEnd, 1), viewMode, startDate);
      topRow.push({
        label: yearFmt.format(effectiveStart),
        x,
        width: xEnd - x,
      });
      cursor.setFullYear(cursor.getFullYear() + 1);
    }

    // Bottom row: one cell per month
    const monthShortFmt = new Intl.DateTimeFormat(locale, { month: 'short' });
    const m = new Date(startDate);
    m.setDate(1);
    while (m <= endDate) {
      const monthEnd = new Date(m.getFullYear(), m.getMonth() + 1, 0);
      const effectiveEnd = monthEnd > endDate ? endDate : monthEnd;
      const x = dateToPx(m < startDate ? startDate : m, viewMode, startDate);
      const xEnd = dateToPx(addDays(effectiveEnd, 1), viewMode, startDate);
      bottomRow.push({
        label: monthShortFmt.format(m),
        x,
        width: xEnd - x,
      });
      m.setMonth(m.getMonth() + 1);
      m.setDate(1);
    }
  } else if (viewMode === 'quarter') {
    // quarter view
    // Top row: one cell per year
    const yearFmt = new Intl.DateTimeFormat(locale, { year: 'numeric' });
    const cursor = new Date(startDate);
    cursor.setMonth(0);
    cursor.setDate(1);
    while (cursor <= endDate) {
      const yearStart = new Date(cursor);
      const yearEnd = new Date(cursor.getFullYear(), 11, 31);
      const effectiveStart = yearStart < startDate ? startDate : yearStart;
      const effectiveEnd = yearEnd > endDate ? endDate : yearEnd;
      const x = dateToPx(effectiveStart, viewMode, startDate);
      const xEnd = dateToPx(addDays(effectiveEnd, 1), viewMode, startDate);
      topRow.push({
        label: yearFmt.format(effectiveStart),
        x,
        width: xEnd - x,
      });
      cursor.setFullYear(cursor.getFullYear() + 1);
    }

    // Bottom row: one cell per quarter (Q1, Q2, Q3, Q4)
    const q = new Date(startDate);
    q.setMonth(Math.floor(q.getMonth() / 3) * 3);
    q.setDate(1);
    while (q <= endDate) {
      const quarterNum = Math.floor(q.getMonth() / 3) + 1;
      const quarterEnd = new Date(q.getFullYear(), q.getMonth() + 3, 0);
      const effectiveStart = q < startDate ? startDate : new Date(q);
      const effectiveEnd = quarterEnd > endDate ? endDate : quarterEnd;
      const x = dateToPx(effectiveStart, viewMode, startDate);
      const xEnd = dateToPx(addDays(effectiveEnd, 1), viewMode, startDate);
      bottomRow.push({
        label: `Q${quarterNum}`,
        x,
        width: xEnd - x,
      });
      q.setMonth(q.getMonth() + 3);
      q.setDate(1);
    }
  } else {
    // year view
    // Top row: one cell per decade (or just label each year in top)
    const yearFmt = new Intl.DateTimeFormat(locale, { year: 'numeric' });

    // Top row: empty / decade label (we'll just use a single span)
    const decadeCursor = new Date(startDate);
    decadeCursor.setMonth(0);
    decadeCursor.setDate(1);
    const firstYear = decadeCursor.getFullYear();
    const lastYear = endDate.getFullYear();
    // Single top row spanning entire range
    const x0 = dateToPx(startDate, viewMode, startDate);
    const xLast = dateToPx(addDays(endDate, 1), viewMode, startDate);
    topRow.push({
      label: `${firstYear} - ${lastYear}`,
      x: x0,
      width: xLast - x0,
    });

    // Bottom row: one cell per year
    const yr = new Date(startDate);
    yr.setMonth(0);
    yr.setDate(1);
    while (yr <= endDate) {
      const yearStart = new Date(yr);
      const yearEnd = new Date(yr.getFullYear(), 11, 31);
      const effectiveStart = yearStart < startDate ? startDate : yearStart;
      const effectiveEnd = yearEnd > endDate ? endDate : yearEnd;
      const x = dateToPx(effectiveStart, viewMode, startDate);
      const xEnd = dateToPx(addDays(effectiveEnd, 1), viewMode, startDate);
      bottomRow.push({
        label: yearFmt.format(effectiveStart),
        x,
        width: xEnd - x,
      });
      yr.setFullYear(yr.getFullYear() + 1);
    }
  }

  return { topRow, bottomRow };
}

/* ── Dependency arrows ──────────────────────────────────────────── */

/**
 * Calculate an SVG path `d` attribute for a Finish-to-Start dependency arrow.
 *
 * The path goes:
 *   1. Right from the end of the predecessor bar
 *   2. Down/up to the successor row
 *   3. Right into the start of the successor bar
 *
 * @param fromX - X coordinate of the predecessor bar's right edge
 * @param fromRow - row index of the predecessor
 * @param toX - X coordinate of the successor bar's left edge
 * @param toRow - row index of the successor
 * @param rowHeight - height of each row in pixels
 */
export function calculateArrowPath(
  fromX: number,
  fromRow: number,
  toX: number,
  toRow: number,
  rowHeight: number,
): string {
  const fromY = fromRow * rowHeight + rowHeight / 2;
  const toY = toRow * rowHeight + rowHeight / 2;
  const offset = 12; // horizontal elbow offset

  if (fromX + offset < toX) {
    // Simple L-shape: predecessor ends before successor starts
    const midX = fromX + offset;
    return `M ${fromX} ${fromY} L ${midX} ${fromY} L ${midX} ${toY} L ${toX} ${toY}`;
  }

  // S-shape: predecessor ends after successor starts
  const midY = fromY + (toY - fromY) / 2;
  return (
    `M ${fromX} ${fromY} ` +
    `L ${fromX + offset} ${fromY} ` +
    `L ${fromX + offset} ${midY} ` +
    `L ${toX - offset} ${midY} ` +
    `L ${toX - offset} ${toY} ` +
    `L ${toX} ${toY}`
  );
}

/* ── Date range from activities ─────────────────────────────────── */

export interface GanttActivity {
  id: string;
  name: string;
  start: string;
  end: string;
  progress: number;
  isCritical?: boolean;
  isMilestone?: boolean;
  isGroup?: boolean;
  parentId?: string | null;
  dependencies?: string[];
  baselineStart?: string;
  baselineEnd?: string;
  color?: string;
}

/**
 * Compute the overall date range from a list of activities.
 * Adds padding of 2 days before and 5 days after.
 */
export function getDateRange(activities: GanttActivity[]): { start: Date; end: Date } {
  if (activities.length === 0) {
    const now = new Date();
    return {
      start: addDays(now, -7),
      end: addDays(now, 30),
    };
  }

  let minTime = Infinity;
  let maxTime = -Infinity;

  for (const a of activities) {
    const s = new Date(a.start).getTime();
    const e = new Date(a.end).getTime();
    if (!isNaN(s) && s < minTime) minTime = s;
    if (!isNaN(e) && e > maxTime) maxTime = e;
    if (a.baselineStart) {
      const bs = new Date(a.baselineStart).getTime();
      if (!isNaN(bs) && bs < minTime) minTime = bs;
    }
    if (a.baselineEnd) {
      const be = new Date(a.baselineEnd).getTime();
      if (!isNaN(be) && be > maxTime) maxTime = be;
    }
  }

  if (!isFinite(minTime) || !isFinite(maxTime)) {
    const now = new Date();
    return { start: addDays(now, -7), end: addDays(now, 30) };
  }

  return {
    start: addDays(new Date(minTime), -2),
    end: addDays(new Date(maxTime), 5),
  };
}

/**
 * Compute the total SVG width for the timeline area given a date range and view mode.
 */
export function getTimelineWidth(startDate: Date, endDate: Date, viewMode: ViewMode): number {
  return dateToPx(endDate, viewMode, startDate);
}
