// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Team metrics + presence API - kept out of api.ts so the board's own
// client never has to change for the dashboard.
import { API_BASE, apiGet, getAuthToken } from '@/shared/lib/api';

const BASE = '/v1/team-standup';

export interface JobSeconds {
  project_id: string;
  code: string;
  name: string;
  seconds: number;
}

/** Today's sign-in summary for one person (UTC ISO instants). */
export interface PersonToday {
  first_seen: string | null;
  last_seen: string | null;
  /** A presence ping landed in the last three minutes. */
  online: boolean;
}

export interface PersonMetrics {
  user_id: string;
  name: string;
  tasks_completed: number;
  tasks_open: number;
  tasks_overdue: number;
  avg_days_to_close: number | null;
  standups_posted: number;
  blockers_raised: number;
  seconds_by_module: Record<string, number>;
  seconds_by_job: JobSeconds[];
  /** Absent from a backend started before the attendance update. */
  today?: PersonToday;
}

/** One person on one day: when they arrived, left, and how long they were active. */
export interface AttendanceRow {
  user_id: string;
  name: string;
  /** Local ISO day (YYYY-MM-DD) as the module labels days. */
  day: string;
  first_seen: string | null;
  last_seen: string | null;
  /** Explicit sign-ins (UTC ISO). */
  logins: string[];
  /** Explicit sign-outs (UTC ISO). */
  logouts: string[];
  /** Tab closes / navigations away (UTC ISO). */
  ends: string[];
  active_seconds: number;
  /** Today and pinged within the last three minutes. */
  still_on: boolean;
}

export interface PersonSeconds {
  user_id: string;
  name: string;
  seconds: number;
}

export interface JobMetrics {
  project_id: string;
  code: string;
  name: string;
  open_tasks: number;
  completed: number;
  overdue: number;
  seconds_total: number;
  people: PersonSeconds[];
}

export interface ModuleSeconds {
  module_key: string;
  seconds: number;
}

export interface TeamMetrics {
  window_days: number;
  people: PersonMetrics[];
  jobs: JobMetrics[];
  modules: ModuleSeconds[];
  /** Absent from a backend started before the attendance update. */
  attendance?: AttendanceRow[];
}

export type MetricsWindow = 7 | 30 | 90;

export const fetchTeamMetrics = (days: MetricsWindow) =>
  apiGet<TeamMetrics>(`${BASE}/metrics?days=${days}`);

export interface PresencePingBody {
  path: string;
  project_id?: string | null;
  seconds: number;
}

/**
 * Presence ping. Deliberately NOT through apiPost: the shared client
 * queues failed mutations for offline replay and toasts "Saved offline",
 * and a beacon must never do either. Raw fetch, keepalive, swallow all.
 */
export async function sendPresencePing(body: PresencePingBody): Promise<void> {
  const token = getAuthToken();
  if (!token) return;
  try {
    await fetch(`${API_BASE}${BASE}/presence/ping`, {
      method: 'POST',
      keepalive: true,
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(body),
    });
  } catch {
    /* a lost ping is a lost minute, nothing more */
  }
}

export type SessionEventKind = 'login' | 'logout' | 'end';

/**
 * Session event: `login` after a successful sign-in, `logout` on an explicit
 * sign-out, `end` when the tab goes away. Same contract as the ping: raw
 * fetch, keepalive, never a toast, never queued for replay.
 *
 * `navigator.sendBeacon` is deliberately NOT used: it cannot carry the
 * `Authorization` header and this API authenticates only by bearer. A
 * keepalive fetch is what browsers honour for unload-time requests.
 *
 * `token` lets a caller that is about to clear the session (logout) hand
 * over the token it still holds.
 */
export async function sendSessionEvent(
  event: SessionEventKind,
  opts: { token?: string | null; at?: Date } = {},
): Promise<void> {
  const token = opts.token ?? getAuthToken();
  if (!token) return;
  try {
    await fetch(`${API_BASE}${BASE}/presence/session`, {
      method: 'POST',
      keepalive: true,
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ event, at: (opts.at ?? new Date()).toISOString() }),
    });
  } catch {
    /* a lost event is a gap in the attendance table, nothing more */
  }
}
