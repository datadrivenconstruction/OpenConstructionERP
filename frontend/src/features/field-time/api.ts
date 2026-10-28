// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for Field Time (cost-coded, signed field timesheets).
 *
 * All endpoints are mounted at /api/v1/field-time/. Hours are decimal
 * strings in and out (the platform-wide "money / quantity as string"
 * convention) so a precise value never loses digits through a JS Number.
 * The app runs with redirect_slashes disabled, so every path keeps its
 * trailing slash.
 */

import {
  API_BASE,
  apiGet,
  apiPost,
  apiPatch,
  apiDelete,
  downloadWithAuth,
  type Page,
} from '@/shared/lib/api';

const BASE = '/v1/field-time/timesheets';

/* -- Types ---------------------------------------------------------------- */

export type TimesheetStatus = 'draft' | 'submitted' | 'approved' | 'reversed';
export type LineKind = 'labour' | 'plant';

/**
 * Who employs the worker on a line. `null` means nobody said, which is the
 * state of every line on a project that records no statutory working time.
 */
export type EmployerKind = 'own' | 'subcontractor';

export interface FieldTimesheetLine {
  id: string;
  timesheet_id: string;
  resource_id: string | null;
  equipment_id: string | null;
  hours: string;
  cost_code: string;
  wbs: string | null;
  is_daywork: boolean;
  variation_id: string | null;
  daywork_sheet_id: string | null;
  note: string | null;
  /** Derived server-side: "labour" (a resource) or "plant" (equipment). */
  kind: LineKind;
  /**
   * Clock times, optional everywhere and null on every line booked by somebody
   * who does not have to record them. When both are set the server derives
   * `hours` from them less the break, so the two can never disagree.
   */
  started_at: string | null;
  ended_at: string | null;
  break_minutes: number | null;
  employer_kind: EmployerKind | null;
  employer_subcontractor_id: string | null;
  /** True when `hours` came from the clock times rather than from a keyboard. */
  hours_derived: boolean;
  created_at: string;
  updated_at: string;
}

export interface FieldTimesheet {
  id: string;
  project_id: string;
  reference: string;
  date: string;
  status: TimesheetStatus;
  submitted_by: string | null;
  submitted_at: string | null;
  approved_by: string | null;
  approved_at: string | null;
  reverses_id: string | null;
  note: string | null;
  metadata: Record<string, unknown>;
  /** The statutory regime this day is recorded under, or null for most days. */
  working_time_regime: string | null;
  /** Null unless a regime is set. Never a refusal, only a statement. */
  working_time: WorkingTimeStatus | null;
  lines: FieldTimesheetLine[];
  labour_hours: string;
  plant_hours: string;
  created_at: string;
  updated_at: string;
}

/** When one day's record was due, whether it made it, and how long it lives. */
export interface WorkingTimeStatus {
  regime: string;
  provision: string;
  deadline: string;
  days_taken: number;
  late: boolean;
  retain_until: string;
  within_retention: boolean;
}

export interface WorkingTimeRegime {
  code: string;
  label: string;
  provision: string;
  record_within_days: number;
  retention_years: number;
  summary: string;
}

/** One worker's working time on one day: the unit a labour inspection asks in. */
export interface WorkingTimeWorkerDay {
  date: string;
  resource_id: string | null;
  worker: string;
  employer_kind: string;
  employer_subcontractor_id: string | null;
  employer: string;
  started_at: string | null;
  ended_at: string | null;
  break_minutes: number;
  duration_hours: string;
  segments: number;
  /** Bookings inside the day with hours but no clock times: the audit gap. */
  segments_without_times: number;
  references: string[];
  status: string;
  recorded_at: string | null;
  days_taken: number | null;
  late: boolean;
  deadline: string | null;
  retain_until: string | null;
  within_retention: boolean;
}

export interface WorkingTimeRecord {
  project_id: string;
  date_from: string;
  date_to: string;
  regime: string | null;
  provision: string;
  generated_at: string;
  days: WorkingTimeWorkerDay[];
  workers: number;
  total_hours: string;
  late_days: number;
  days_missing_times: number;
  /** Reversed sheets and their reversals, left out of the fold and counted here. */
  excluded_corrections: number;
}

export interface FieldTimeSummary {
  total: number;
  by_status: Record<string, number>;
  labour_hours: string;
  plant_hours: string;
}

export interface CostCodeSuggestion {
  code: string;
  label: string;
  /** 0..1 model confidence - shown to the user, never auto-applied. */
  confidence: number;
}

export interface SuggestCostCodesResponse {
  suggestions: CostCodeSuggestion[];
  applied: boolean;
}

export interface FieldTimeValidationResult {
  rule_id: string;
  rule_name: string;
  severity: string;
  category: string;
  passed: boolean;
  message: string;
  element_ref: string | null;
  suggestion: string | null;
}

export interface FieldTimeValidationReport {
  status: string;
  score: number | null;
  counts: Record<string, number>;
  results: FieldTimeValidationResult[];
}

export interface CreateTimesheetPayload {
  project_id: string;
  date: string;
  note?: string | null;
  metadata?: Record<string, unknown>;
  working_time_regime?: string | null;
}

export interface UpdateTimesheetPayload {
  date?: string;
  note?: string | null;
  metadata?: Record<string, unknown>;
  working_time_regime?: string | null;
}

export interface LineCreatePayload {
  resource_id?: string | null;
  equipment_id?: string | null;
  hours: string;
  cost_code: string;
  wbs?: string | null;
  is_daywork?: boolean;
  variation_id?: string | null;
  note?: string | null;
  /** Send both or neither: with both, they decide the hours. */
  started_at?: string | null;
  ended_at?: string | null;
  break_minutes?: number | null;
  employer_kind?: EmployerKind | null;
  employer_subcontractor_id?: string | null;
}

export interface LineUpdatePayload {
  resource_id?: string | null;
  equipment_id?: string | null;
  hours?: string;
  cost_code?: string;
  wbs?: string | null;
  is_daywork?: boolean;
  variation_id?: string | null;
  note?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
  break_minutes?: number | null;
  employer_kind?: EmployerKind | null;
  employer_subcontractor_id?: string | null;
}

export interface ListTimesheetsFilters {
  status?: TimesheetStatus | '';
  date_from?: string;
  date_to?: string;
  offset?: number;
  limit?: number;
}

export interface ReverseTimesheetPayload {
  note?: string | null;
}

/* -- Offline capture ------------------------------------------------------ */

/**
 * What the server did with an offline op. A stable machine token: the UI
 * renders its own translated sentence from it and never parses `detail`,
 * which is English and meant for a log.
 */
export type OfflineOutcome = 'created' | 'replayed' | 'updated' | 'withdrawn';

/**
 * One day recorded away from the network, as a complete replacement of that
 * entry rather than a diff.
 *
 * `entry_key` names the logical entry - the foreman's record of one
 * project-day - and stays the same across every replay and every later edit of
 * that day. It is what lets the server return the original timesheet instead of
 * booking the hours twice. It is NOT the queue's per-op id: the queue mints a
 * fresh `clientOpId` for each queued op so a second edit of the same day is a
 * second op, and only this key ties them to one entry.
 */
export interface OfflineEntryPayload {
  entry_key: string;
  project_id: string;
  date: string;
  note?: string | null;
  metadata?: Record<string, unknown>;
  lines: LineCreatePayload[];
  /** Device clock at capture. Advisory: the server stamps its own arrival. */
  captured_at?: string | null;
  device?: string | null;
  /** Send the day on for approval in the same op. */
  submit?: boolean;
}

export interface OfflineWithdrawPayload {
  entry_key: string;
  project_id: string;
}

export interface OfflineEntryResult {
  entry_key: string;
  outcome: OfflineOutcome;
  timesheet: FieldTimesheet | null;
  /** True once the entry has moved past draft, so the office can see it. */
  submitted: boolean;
  detail: string | null;
}

/* -- Formatting ----------------------------------------------------------- */

/**
 * Render an hours decimal string for display / input seeding, trimming
 * trailing zeros ("8.0000" -> "8", "1.5000" -> "1.5"). Hours are bounded
 * (<= 100000, 4 dp) so a Number round-trip is always exact here.
 */
export function formatHours(raw: string | null | undefined): string {
  if (raw == null || raw === '') return '0';
  const n = Number(raw);
  return Number.isFinite(n) ? String(n) : raw;
}

/**
 * The clock time of an instant, as a `<input type="time">` value in the
 * reader's own timezone ("07:00"). Empty when there is no instant.
 */
export function timeOfDay(iso: string | null | undefined): string {
  if (!iso) return '';
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return '';
  return `${String(at.getHours()).padStart(2, '0')}:${String(at.getMinutes()).padStart(2, '0')}`;
}

/**
 * Turn a day plus a clock time into the instant it names, in the reader's own
 * timezone. A foreman types "07:00" and means seven in the morning where they
 * are standing, so the browser's own offset is what turns it into a moment; the
 * server stores moments and never a wall-clock reading with no place attached.
 *
 * `notBefore` is the shift start when this is the end of one. An end that would
 * land at or before it belongs to the next morning, which is how a night shift
 * is written down without anybody having to type tomorrow's date.
 */
export function instantFromTime(
  dayISO: string,
  time: string,
  notBefore?: string | null,
): string | null {
  if (!dayISO || !time) return null;
  const at = new Date(`${dayISO}T${time}`);
  if (Number.isNaN(at.getTime())) return null;
  if (notBefore) {
    const start = new Date(notBefore);
    if (!Number.isNaN(start.getTime()) && at.getTime() < start.getTime()) {
      at.setDate(at.getDate() + 1);
    }
  }
  return at.toISOString();
}

/* -- Timesheets ----------------------------------------------------------- */

const EMPTY_TIMESHEET_PAGE: Page<FieldTimesheet> = { items: [], total: 0, offset: 0, limit: 0 };

export async function listTimesheets(
  projectId: string,
  filters?: ListTimesheetsFilters,
): Promise<Page<FieldTimesheet>> {
  if (!projectId) return EMPTY_TIMESHEET_PAGE;
  const params = new URLSearchParams({ project_id: projectId });
  if (filters?.status) params.set('status', filters.status);
  if (filters?.date_from) params.set('date_from', filters.date_from);
  if (filters?.date_to) params.set('date_to', filters.date_to);
  if (filters?.offset !== undefined) params.set('offset', String(filters.offset));
  if (filters?.limit !== undefined) params.set('limit', String(filters.limit));
  /* Written out in full rather than through `BASE`, which every other call in
     this file uses. check_page_envelope_consumers.py binds a URL literal to
     the call it stands next to, so a path assembled from a module-level
     constant leaves the only `/v1/` literal in the file on the `BASE` line and
     this route invisible to the guard - an entry for it would report "0 call
     sites, 0 migrated" and pass without reading anything. */
  const res = await apiGet<Page<FieldTimesheet>>(
    `/v1/field-time/timesheets/?${params.toString()}`,
  );
  // The coerce this replaces was `Array.isArray(res) ? res : []`, which would
  // now discard every good answer as silently as it used to absorb a bad one.
  return Array.isArray(res?.items) ? res : EMPTY_TIMESHEET_PAGE;
}

export async function fetchTimesheet(id: string): Promise<FieldTimesheet> {
  return apiGet<FieldTimesheet>(`${BASE}/${id}/`);
}

export async function fetchTimesheetSummary(projectId: string): Promise<FieldTimeSummary | null> {
  if (!projectId) return null;
  return apiGet<FieldTimeSummary>(
    `${BASE}/summary/?project_id=${encodeURIComponent(projectId)}`,
  );
}

export async function createTimesheet(data: CreateTimesheetPayload): Promise<FieldTimesheet> {
  return apiPost<FieldTimesheet>(`${BASE}/`, data);
}

export async function updateTimesheet(
  id: string,
  data: UpdateTimesheetPayload,
): Promise<FieldTimesheet> {
  return apiPatch<FieldTimesheet>(`${BASE}/${id}/`, data);
}

export async function deleteTimesheet(id: string): Promise<void> {
  return apiDelete(`${BASE}/${id}/`);
}

/* -- Lines ---------------------------------------------------------------- */

export async function addLine(id: string, data: LineCreatePayload): Promise<FieldTimesheet> {
  return apiPost<FieldTimesheet>(`${BASE}/${id}/lines/`, data);
}

export async function updateLine(
  id: string,
  lineId: string,
  data: LineUpdatePayload,
): Promise<FieldTimesheet> {
  return apiPatch<FieldTimesheet>(`${BASE}/${id}/lines/${lineId}/`, data);
}

export async function deleteLine(id: string, lineId: string): Promise<FieldTimesheet> {
  return apiDelete<FieldTimesheet>(`${BASE}/${id}/lines/${lineId}/`);
}

/* -- Lifecycle ------------------------------------------------------------ */

export async function submitTimesheet(id: string): Promise<FieldTimesheet> {
  return apiPost<FieldTimesheet>(`${BASE}/${id}/submit/`, {});
}

export async function approveTimesheet(id: string): Promise<FieldTimesheet> {
  return apiPost<FieldTimesheet>(`${BASE}/${id}/approve/`, {});
}

export async function reverseTimesheet(
  id: string,
  data: ReverseTimesheetPayload,
): Promise<FieldTimesheet> {
  return apiPost<FieldTimesheet>(`${BASE}/${id}/reverse/`, data);
}

/* -- Offline capture ------------------------------------------------------ */

/**
 * Record a day captured with no signal. Idempotent on `entry_key`, so calling
 * it again with the same key returns what the first call produced instead of
 * writing a second timesheet.
 */
export async function recordOfflineEntry(data: OfflineEntryPayload): Promise<OfflineEntryResult> {
  return apiPost<OfflineEntryResult>(`${BASE}/offline/`, data);
}

/** Withdraw a day recorded offline. Remembered even if the day never arrived. */
export async function withdrawOfflineEntry(
  data: OfflineWithdrawPayload,
): Promise<OfflineEntryResult> {
  return apiPost<OfflineEntryResult>(`${BASE}/offline/withdraw/`, data);
}

/* -- Statutory working-time record ---------------------------------------- */

/** The regimes on offer. The vocabulary, not any project's choice. */
export async function listWorkingTimeRegimes(): Promise<WorkingTimeRegime[]> {
  const res = await apiGet<WorkingTimeRegime[]>(`${BASE}/working-time-regimes/`);
  return Array.isArray(res) ? res : [];
}

function workingTimeQuery(
  projectId: string,
  dateFrom: string,
  dateTo: string,
  regime?: string | null,
): string {
  const params = new URLSearchParams({
    project_id: projectId,
    date_from: dateFrom,
    date_to: dateTo,
  });
  if (regime) params.set('regime', regime);
  return params.toString();
}

/** Who worked here over this period, and when each of them started and stopped. */
export async function fetchWorkingTimeRecord(
  projectId: string,
  dateFrom: string,
  dateTo: string,
  regime?: string | null,
): Promise<WorkingTimeRecord | null> {
  if (!projectId || !dateFrom || !dateTo) return null;
  return apiGet<WorkingTimeRecord>(
    `${BASE}/working-time/?${workingTimeQuery(projectId, dateFrom, dateTo, regime)}`,
  );
}

/**
 * Hand the same record over as a CSV file. Goes through `downloadWithAuth` so a
 * refusal arrives as a message rather than as a .csv full of JSON.
 */
export async function downloadWorkingTimeRecord(
  projectId: string,
  dateFrom: string,
  dateTo: string,
  regime?: string | null,
): Promise<void> {
  return downloadWithAuth(
    `${API_BASE}${BASE}/working-time.csv?${workingTimeQuery(projectId, dateFrom, dateTo, regime)}`,
    `working-time-${dateFrom}-${dateTo}.csv`,
  );
}

/* -- Validation ----------------------------------------------------------- */

export async function fetchTimesheetValidation(id: string): Promise<FieldTimeValidationReport> {
  return apiGet<FieldTimeValidationReport>(`${BASE}/${id}/validation/`);
}

/* -- Cost-code assist (AI-augmented, human-confirmed) --------------------- */

export async function suggestCostCodes(
  projectId: string,
  text: string,
  limit = 5,
): Promise<SuggestCostCodesResponse> {
  return apiPost<SuggestCostCodesResponse>(
    `${BASE}/suggest-cost-codes/?project_id=${encodeURIComponent(projectId)}`,
    { text, limit },
  );
}
