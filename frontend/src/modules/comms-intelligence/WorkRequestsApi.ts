// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * Read-side client for the Work requests module (`/api/v1/work-requests`),
 * as the project hub and dashboard widgets see it.
 *
 * Deliberately NOT an import from `@/modules/work-requests`: that module
 * ships on its own and may be absent from a deployment (or the backend may
 * predate it), so the widgets carry the two reads they need here and treat
 * a 404 as "module not available" rather than an error.
 */
import { ApiError, apiGet } from '@/shared/lib/api';
import { fmtFixed } from '@/shared/lib/formatters';

export type BallInCourt = 'requester' | 'department';

export interface WorkRequestPerson {
  id: string;
  name: string;
}

export interface WorkRequestRow {
  id: string;
  /** e.g. WR-WKS-000012 */
  reference: string;
  project_id: string;
  project_code: string;
  department: string;
  request_type: string;
  title: string;
  status: string;
  stage: string;
  due_date: string | null;
  is_overdue: boolean;
  ball_in_court: BallInCourt;
  responsible: WorkRequestPerson | null;
  assignees: WorkRequestPerson[];
  hours_logged: number;
  /** Null until somebody quotes the work - not 0. */
  quoted_hours: number | null;
  /** Null while there is no quote to deviate from. */
  deviation_hours: number | null;
  created_at: string;
}

export interface WorkRequestStage {
  key: string;
  name: string;
  colour: string;
  closes: boolean;
}

export interface WorkRequestDepartment {
  key: string;
  name: string;
  colour: string;
  stages: WorkRequestStage[];
}

export interface DepartmentSummaryRow {
  key: string;
  name: string;
  colour: string;
  open: number;
  overdue: number;
  with_requester: number;
  due_this_week: number;
  hours_quoted: number;
  hours_logged: number;
  /** Finished, waiting on the requester to close it. */
  awaiting_close?: number;
}

export interface WorkRequestSummary {
  departments: DepartmentSummaryRow[];
}

const BASE = '/v1/work-requests';

/** Per-department counts: one job's when `projectId` is given, else the portfolio. */
export function fetchWorkRequestSummary(projectId?: string): Promise<WorkRequestSummary> {
  const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
  return apiGet<WorkRequestSummary>(`${BASE}/summary${qs}`);
}

/** A job's open requests (the module lists open ones unless asked for closed). */
export function fetchOpenWorkRequests(projectId: string): Promise<WorkRequestRow[]> {
  return apiGet<WorkRequestRow[]>(`${BASE}/requests?project_id=${encodeURIComponent(projectId)}`);
}

/** The module is not mounted on this server (or the backend predates it). */
export function isModuleAbsent(err: unknown): boolean {
  return err instanceof ApiError && err.status === 404;
}

// ── Where things open ────────────────────────────────────────────────────

export function workRequestUrl(id: string): string {
  return `/work-requests/${encodeURIComponent(id)}`;
}

/** The module owns its raise dialog; the widgets only open it on the job. */
export function raiseWorkRequestUrl(projectId: string): string {
  return `/work-requests?raise=1&project=${encodeURIComponent(projectId)}`;
}

export function projectWorkRequestsUrl(projectId: string): string {
  return `/projects/${encodeURIComponent(projectId)}/work-requests`;
}

export function departmentRequestsUrl(departmentKey: string): string {
  return `/work-requests?department=${encodeURIComponent(departmentKey)}`;
}

// ── Pure helpers (tested) ────────────────────────────────────────────────

/** Anything the module still counts as live. A defensive filter: the
 *  list endpoint already defaults to open, but a closed row that slipped
 *  through must not be shown as "urgent". */
export function openOnly(rows: readonly WorkRequestRow[]): WorkRequestRow[] {
  return rows.filter((r) => r.status !== 'closed');
}

/**
 * Most urgent first: overdue before not, then the earliest due date,
 * undated requests last, and the oldest raised first among equals - so
 * the five the hub shows are the five somebody should look at today.
 */
export function sortByUrgency(rows: readonly WorkRequestRow[]): WorkRequestRow[] {
  return [...rows].sort((a, b) => {
    if (a.is_overdue !== b.is_overdue) return a.is_overdue ? -1 : 1;
    const ad = a.due_date ?? '';
    const bd = b.due_date ?? '';
    if (ad !== bd) {
      if (!ad) return 1;
      if (!bd) return -1;
      return ad < bd ? -1 : 1;
    }
    const ac = a.created_at ?? '';
    const bc = b.created_at ?? '';
    return ac < bc ? -1 : ac > bc ? 1 : 0;
  });
}

/** Share of the quote used, capped at 100 for the bar; `over` says
 *  whether the hours have run past the quote. No quote = no bar. */
export function hoursProgress(
  logged: number | null | undefined,
  quoted: number | null | undefined,
): { pct: number; over: boolean; hasQuote: boolean } {
  const l = typeof logged === 'number' && Number.isFinite(logged) ? Math.max(0, logged) : 0;
  const q = typeof quoted === 'number' && Number.isFinite(quoted) ? Math.max(0, quoted) : 0;
  if (q <= 0) return { pct: l > 0 ? 100 : 0, over: l > 0, hasQuote: false };
  return { pct: Math.min(100, Math.round((l / q) * 100)), over: l > q, hasQuote: true };
}

/**
 * A department's colour arrives as a TOKEN, not as CSS - and three of the
 * ones the backend allows (`slate`, `amber`, `rose`) are not CSS colour
 * keywords, so painting them straight into `background-color` produced no
 * colour at all: the Hazardous Area dot on both widgets measured
 * `rgba(0, 0, 0, 0)` on the live seed. The tokens that ARE keywords
 * resolved to the raw web colours (`blue` is #0000ff), which are nothing
 * like the module's own inks.
 *
 * The map is duplicated from `@/modules/work-requests/lib` on purpose:
 * this file exists precisely so the widgets do not import a module that
 * may not be installed. Keep the two in step - `red` is the Hazardous
 * Area seed's new colour and must stay the same hex on both sides, or one
 * department reads as two colours on one screen.
 */
const COLOUR_TOKENS: Record<string, string> = {
  slate: '#55616e',
  grey: '#55616e',
  gray: '#55616e',
  blue: '#1361c9',
  indigo: '#2f42a8',
  violet: '#6136ad',
  purple: '#6136ad',
  cyan: '#06657f',
  teal: '#0a6f66',
  green: '#14713d',
  lime: '#4f6a10',
  amber: '#8a5406',
  yellow: '#8a5406',
  orange: '#a4470c',
  rose: '#a52f5b',
  pink: '#a52f5b',
  red: '#a92c23',
};

/** A department colour as real CSS; unknown text (a hex) passes through. */
export function departmentColour(colour: string | null | undefined): string {
  if (!colour) return 'var(--oe-border-light)';
  return COLOUR_TOKENS[colour.trim().toLowerCase()] ?? colour;
}

/** "4" / "4.5" - hours read with at most one decimal. Null quotes read "0". */
export function fmtHours(h: number | null | undefined): string {
  const n = typeof h === 'number' && Number.isFinite(h) ? h : 0;
  return Number.isInteger(n) ? String(n) : fmtFixed(n, 1);
}
