// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Read-only hooks feeding the Project-team tile and the availability popup.
 *
 * One hook per upstream source, each of them *graceful*: a module that is
 * switched off, 404s or errors resolves to ``null`` rather than throwing, so
 * the tile keeps rendering the part it can answer and the popup shows an
 * honest one-liner for the section it cannot. Nothing here writes.
 *
 * Sources:
 *
 *   GET /api/v1/team-standup/full-board?day=<iso>
 *       entries[]  today's standup posts: status + activity ids per person
 *       week       {start, entries[]} — used for "did they post that day"
 *       tasks[]    assignee_id, due, stage_id, waiting_on, project_id
 *       stages[]   is_done, so an open task can be told from a closed one
 *   GET /api/v1/team-standup/presence/today?project_id=<id>
 *       [{user_id, name, online, first_seen, last_seen}] — the green dot and
 *       the popup's "Online now" badge. VIEWER-level: everyone on the team
 *       may see who is about, which is the whole point of the tile.
 *   GET /api/v1/team-standup/metrics?days=7
 *       attendance[]   per user/day first_seen, last_seen, active_seconds,
 *                      still_on — the popup's attendance section.
 *       MANAGER-only (it also carries everyone's task throughput, average
 *       days to close and blocker counts), so this one 403s for an ordinary
 *       team member and its section says so in words. Nothing else on either
 *       surface may depend on it.
 *   GET /api/v1/work-requests/departments
 *       key, name, member_ids, lead_user_id — which departments a member is in
 *   GET /api/v1/work-requests/planner?department=&from=&to=
 *       rows[] {assignees[], alloc{isoDay: number}}, capacity{} — the week strip
 *   GET /api/v1/work-requests/requests?assignee_id=<id>
 *       their open requests (the endpoint already drops closed/cancelled)
 *
 * Caching: the board/metrics/departments queries are shared by the tile and
 * the popup under stable keys, so opening a member's popup costs at most the
 * two queries that are actually per-member. Everything the popup alone needs
 * takes ``enabled`` so it stays unfetched until a popup opens — the tile must
 * never wait on popup data.
 */

import { useMemo } from 'react';
import { useQuery, useQueries } from '@tanstack/react-query';
import { apiGet } from '@/shared/lib/api';

/* ── Wire types (only the fields we read) ─────────────────────────────── */

export interface StandupEntry {
  id: string;
  user_id: string;
  author_name: string;
  day: string;
  /** office | site | wfh | travel | leave */
  status: string;
  activities: string[];
}

export interface StandupActivity {
  id: string;
  name: string;
  color: string;
}

export interface StandupStage {
  id: string;
  name: string;
  is_done: boolean;
}

export interface StandupTask {
  id: string;
  title: string;
  project_id: string;
  stage_id: string;
  assignee_id: string;
  assignee_name: string;
  due: string;
  priority: string;
  /** Non-empty means the task is waiting on somebody. */
  waiting_on: string;
  completed_at?: string | null;
}

export interface StandupJob {
  id: string;
  code: string;
  name: string;
  label: string;
}

export interface StandupBoard {
  day: string;
  today: string;
  entries: StandupEntry[];
  week: { start: string; entries: StandupEntry[] };
  stages: StandupStage[];
  activities: StandupActivity[];
  tasks: StandupTask[];
  jobs: StandupJob[];
}

export interface AttendanceRow {
  user_id: string;
  name: string;
  day: string;
  first_seen: string | null;
  last_seen: string | null;
  active_seconds: number;
  still_on: boolean;
}

export interface StandupMetrics {
  window_days: number;
  people: {
    user_id: string;
    name: string;
    tasks_open: number;
    tasks_overdue: number;
    today: { first_seen: string | null; last_seen: string | null; online: boolean };
  }[];
  attendance: AttendanceRow[];
}

/**
 * One row of ``GET /team-standup/presence/today`` — five fields, today only.
 *
 * Presence lives on its own viewer-level endpoint because ``/metrics`` is
 * manager-only: it carries every colleague's task throughput, average days to
 * close, blockers and multi-day attendance. Who is online right now is
 * ordinary team awareness and stays visible to the whole team, so the tile
 * and the popup read presence from HERE and never from the rollup.
 */
export interface PresencePerson {
  user_id: string;
  name: string;
  online: boolean;
  first_seen: string | null;
  last_seen: string | null;
}

/**
 * What the manager-only rollup query resolves to.
 *
 * ``forbidden`` is the difference between "this deployment has no standup
 * module" and "you are not a manager" — the popup has to say which, because
 * "not available on this install" is a lie to an ordinary team member whose
 * colleague can see the very same section.
 */
export interface MetricsResult {
  metrics: StandupMetrics | null;
  forbidden: boolean;
}

export interface WorkRequestDepartment {
  key: string;
  name: string;
  colour?: string;
  active?: boolean;
  lead_user_id?: string | null;
  member_ids?: string[];
}

export interface PlannerRow {
  request_id: string;
  reference: string;
  title: string;
  due_date: string | null;
  assignees: { id: string; name: string }[];
  /** ISO day → headcount allocated that day. Missing day = 0. */
  alloc: Record<string, number>;
}

export interface PlannerPayload {
  department: string;
  days: string[];
  members: { id: string; name: string }[];
  rows: PlannerRow[];
  capacity: Record<string, { available: number; allocated: number; override: boolean }>;
}

export interface WorkRequestRow {
  id: string;
  reference: string;
  title: string;
  department: string;
  department_name?: string;
  status: string;
  due_date: string | null;
  is_overdue?: boolean;
  hours_logged?: number;
  quoted_hours?: number | null;
}

/* ── Date helpers ─────────────────────────────────────────────────────── */

/** Local-calendar ISO day (``toISOString`` would shift a Sydney evening back a day). */
export function isoDay(d: Date): string {
  const y = d.getFullYear();
  const m = `${d.getMonth() + 1}`.padStart(2, '0');
  const day = `${d.getDate()}`.padStart(2, '0');
  return `${y}-${m}-${day}`;
}

/** Monday → Sunday of the week containing ``ref``, as ISO days. */
export function weekDays(ref: Date = new Date()): string[] {
  const monday = new Date(ref.getFullYear(), ref.getMonth(), ref.getDate());
  // getDay(): 0=Sun … 6=Sat. Sunday belongs to the week that *started* on the
  // previous Monday, so it steps back 6 days rather than forward.
  const offset = (monday.getDay() + 6) % 7;
  monday.setDate(monday.getDate() - offset);
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(monday);
    d.setDate(monday.getDate() + i);
    return isoDay(d);
  });
}

/* ── Graceful fetch ───────────────────────────────────────────────────── */

/**
 * ``apiGet`` that resolves to ``null`` on any failure.
 *
 * The team tile sits on a project hub next to a dozen other widgets; a
 * standup module that is not installed on this deployment must degrade to a
 * sentence, not take the page down. The caller can tell "no data" from "still
 * loading" via the query's own ``isLoading``.
 */
async function gracefulGet<T>(path: string): Promise<T | null> {
  try {
    return await apiGet<T>(path);
  } catch {
    return null;
  }
}

/** HTTP status off an ``ApiError`` (or anything else carrying one), else null. */
function httpStatus(err: unknown): number | null {
  const status = (err as { status?: unknown } | null)?.status;
  return typeof status === 'number' ? status : null;
}

const SHARED = { retry: false, staleTime: 60_000 } as const;

/* ── Hooks ────────────────────────────────────────────────────────────── */

/** Today's standup board: who posted what, and every task on the board. */
export function useStandupBoard(day: string, enabled = true) {
  return useQuery<StandupBoard | null>({
    queryKey: ['team-availability', 'standup-board', day],
    queryFn: () =>
      gracefulGet<StandupBoard>(
        `/v1/team-standup/full-board?day=${encodeURIComponent(day)}`,
      ),
    enabled,
    ...SHARED,
  });
}

/**
 * Today's presence for the people on a project — viewer-level.
 *
 * Deliberately NOT ``/metrics``. The tile's green dot and the popup's "Online
 * now" badge are the only things those surfaces ever wanted out of the
 * rollup, and the rollup is manager-only, so reading them from it blanked the
 * tile for every ordinary team member. This endpoint returns today's
 * presence and nothing else, so it can stay on ``team_standup.read``.
 */
export function usePresenceToday(projectId?: string, enabled = true) {
  return useQuery<PresencePerson[] | null>({
    queryKey: ['team-availability', 'presence-today', projectId ?? ''],
    queryFn: () =>
      gracefulGet<{ items?: PresencePerson[] }>(
        `/v1/team-standup/presence/today${
          projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''
        }`,
      ).then((page) => (page === null ? null : (page.items ?? []))),
    enabled,
    // Presence goes stale fast — a 60s window would leave a green dot up long
    // after someone signed off.
    staleTime: 30_000,
    refetchInterval: enabled ? 60_000 : false,
    retry: false,
  });
}

/**
 * The manager-only rollup: per-person performance and multi-day attendance.
 *
 * Resolves to a {@link MetricsResult} rather than throwing, so a caller can
 * tell a 403 (you are not a manager) from a missing module and word its
 * fallback line honestly. Nothing that every team member is entitled to see
 * may be read from here — use {@link usePresenceToday} for presence and the
 * standup board / work-request planner for tasks and allocation, all of which
 * stay viewer-level.
 */
export function useStandupMetrics(days = 7, enabled = true) {
  return useQuery<MetricsResult>({
    queryKey: ['team-availability', 'standup-metrics', days],
    queryFn: async () => {
      try {
        return {
          metrics: await apiGet<StandupMetrics>(`/v1/team-standup/metrics?days=${days}`),
          forbidden: false,
        };
      } catch (err) {
        return { metrics: null, forbidden: httpStatus(err) === 403 };
      }
    },
    enabled,
    staleTime: 60_000,
    retry: false,
  });
}

/** The work-request departments, for the member → department mapping. */
export function useWorkRequestDepartments(enabled = true) {
  return useQuery<WorkRequestDepartment[] | null>({
    queryKey: ['team-availability', 'wr-departments'],
    queryFn: () =>
      gracefulGet<{ items?: WorkRequestDepartment[] }>('/v1/work-requests/departments').then(
        (page) => (page === null ? null : (page.items ?? [])),
      ),
    enabled,
    retry: false,
    // Departments change about once a quarter.
    staleTime: 10 * 60_000,
  });
}

/**
 * Planner rows for several departments over one window.
 *
 * ``useQueries`` rather than a loop of ``useQuery`` so the department list can
 * grow or shrink between renders without breaking the rules of hooks.
 */
export function usePlannerForDepartments(
  deptKeys: readonly string[],
  from: string,
  to: string,
  enabled = true,
) {
  const results = useQueries({
    queries: deptKeys.map((key) => ({
      queryKey: ['team-availability', 'wr-planner', key, from, to],
      queryFn: () =>
        gracefulGet<PlannerPayload>(
          `/v1/work-requests/planner?department=${encodeURIComponent(key)}&from=${from}&to=${to}`,
        ),
      enabled: enabled && !!key && !!from && !!to,
      retry: false,
      staleTime: 60_000,
    })),
  });

  return useMemo(
    () => ({
      payloads: results
        .map((r) => r.data)
        .filter((p): p is PlannerPayload => !!p),
      isLoading: results.some((r) => r.isLoading),
      /** True when every department query came back empty / failed. */
      allFailed: results.length > 0 && results.every((r) => !r.isLoading && !r.data),
    }),
    [results],
  );
}

/** One member's open work requests. Popup-only, hence the ``enabled`` gate. */
export function useMemberRequests(userId: string | null, enabled = true) {
  return useQuery<WorkRequestRow[] | null>({
    queryKey: ['team-availability', 'wr-requests', userId],
    queryFn: () =>
      gracefulGet<WorkRequestRow[]>(
        `/v1/work-requests/requests?assignee_id=${encodeURIComponent(userId ?? '')}&limit=50`,
      ),
    enabled: enabled && !!userId,
    ...SHARED,
  });
}

/* ── Derivations ──────────────────────────────────────────────────────── */

/** Human label + tone for a standup status code. */
export const STANDUP_STATUS_LABELS: Readonly<Record<string, string>> = {
  site: 'On site',
  office: 'In the office',
  wfh: 'Working from home',
  travel: 'Travelling',
  leave: 'On leave',
};

export function standupStatusLabel(status: string | undefined): string {
  if (!status) return '';
  return STANDUP_STATUS_LABELS[status] ?? status;
}

/** Ids of the stages that mean "done", so an open task can be counted. */
export function doneStageIds(board: StandupBoard | null | undefined): Set<string> {
  return new Set((board?.stages ?? []).filter((s) => s.is_done).map((s) => String(s.id)));
}

/** A person's open standup tasks (not in a done stage, not completed). */
export function openTasksFor(
  board: StandupBoard | null | undefined,
  userId: string,
): StandupTask[] {
  if (!board) return [];
  const done = doneStageIds(board);
  return board.tasks.filter(
    (task) =>
      task.assignee_id === userId &&
      !task.completed_at &&
      !done.has(String(task.stage_id)),
  );
}

/**
 * Per-day allocation for one person across every planner payload we hold.
 *
 * A planner row is a *request*, and its ``alloc`` is the headcount booked on
 * that request for that day — not a per-person split. So a person's figure for
 * a day is the sum of ``alloc[day]`` over the rows they are assigned to. That
 * over-counts a two-person row, which is why the popup labels it
 * "people booked on their jobs" rather than claiming it is their own hours.
 */
export function allocByDayFor(
  payloads: readonly PlannerPayload[],
  userId: string,
  days: readonly string[],
): Record<string, number> {
  const out: Record<string, number> = Object.fromEntries(days.map((d) => [d, 0]));
  for (const payload of payloads) {
    for (const row of payload.rows ?? []) {
      if (!row.assignees?.some((a) => a.id === userId)) continue;
      for (const day of days) {
        const v = row.alloc?.[day];
        if (typeof v === 'number' && v > 0) out[day] = (out[day] ?? 0) + v;
      }
    }
  }
  return out;
}

/** How many days this week the person has any allocation at all. */
export function allocatedDayCount(alloc: Record<string, number>): number {
  return Object.values(alloc).filter((v) => v > 0).length;
}

/** Department keys + names a user belongs to (member or lead). */
export function departmentsFor(
  departments: readonly WorkRequestDepartment[] | null | undefined,
  userId: string,
): WorkRequestDepartment[] {
  if (!departments) return [];
  return departments.filter(
    (d) =>
      d.lead_user_id === userId || (d.member_ids ?? []).includes(userId),
  );
}

/** Seconds → "6h 20m" / "45m" / "—". */
export function formatActiveSeconds(seconds: number | null | undefined): string {
  if (!seconds || seconds <= 0) return '—';
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  if (h === 0) return `${m}m`;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

/** ISO datetime → local "14:32", or an em-dash when absent. */
export function formatClock(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return `${`${d.getHours()}`.padStart(2, '0')}:${`${d.getMinutes()}`.padStart(2, '0')}`;
}
