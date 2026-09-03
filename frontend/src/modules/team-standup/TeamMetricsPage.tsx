// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Team metrics - who is doing what, which jobs take the team's time, and
// where people are in the ERP. Listed under Team Standup; reads the
// standup's tasks/entries and the presence beacon's rows. CSS bars only.
//
// MANAGERS AND ADMINS ONLY. The payload is management information about
// people (per-person throughput, standups, blockers, hours by job and by
// module, and an attendance table of sign-ins and last-seen times), so
// the backend gates GET /metrics on `team_standup.metrics` at MANAGER.
// The check below is the matching client affordance - it decides what to
// OFFER, never what is permitted; a 403 is handled the same way in case
// the stored role is stale.

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { MouseEvent as ReactMouseEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { navGroups } from '@/app/layout/navCatalog';
import { MODULE_REGISTRY } from '@/modules/_registry';
import { ApiError } from '@/shared/lib/api';
import { fmtDate, fmtPercent, getIntlLocale, fmtFixed, fmtList } from '@/shared/lib/formatters';
import { ROLE_RANK, normalizeRole } from '@/shared/lib/roles';
import { useAuthStore } from '@/stores/useAuthStore';

import type { AttendanceRow, JobMetrics, MetricsWindow, PersonMetrics, TeamMetrics } from './metricsApi';
import { fetchTeamMetrics } from './metricsApi';
import './team-metrics.css';

const WINDOWS: MetricsWindow[] = [7, 30, 90];
const WINDOW_KEY = 'oe_team_metrics_window';
/** The attendance table shows this many days until "show all" is pressed. */
const ATTENDANCE_DAYS_FOLDED = 7;
/**
 * Modules drawn as their own segment in a person's time bar. The ERP has
 * two dozen first-path segments and a person touches most of them in a
 * month; twenty-four slivers and a twenty-four-entry legend is a colour
 * chart, not a reading. The rest are summed into one honest "Elsewhere"
 * segment and the tooltip still lists every module by name.
 */
const BAR_MODULES = 6;

/** The one absent-value mark on this page (matches `shared/lib/formatters`). */
const EM_DASH = '—';

const PALETTE = ['violet', 'blue', 'teal', 'amber', 'rose', 'indigo', 'green', 'orange', 'cyan', 'lime', 'red', 'slate'];

/** A stable palette key for a string (same name -> same colour everywhere). */
function tintFor(key: string): string {
  let h = 0;
  for (let i = 0; i < key.length; i += 1) h = (h * 31 + key.charCodeAt(i)) >>> 0;
  return PALETTE[h % PALETTE.length] ?? 'slate';
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  const first = parts[0]?.[0] ?? '';
  const last = parts.length > 1 ? parts[parts.length - 1]?.[0] ?? '' : '';
  return (first + last).toUpperCase() || first.toUpperCase();
}

/* ── Numbers that read as numbers ─────────────────────────────────────── */

/** Seconds -> "6:45 h". ONE duration format on this page, always with its unit. */
function fmtHours(seconds: number): string {
  const mins = Math.round(Math.max(0, seconds) / 60);
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return `${h}:${String(m).padStart(2, '0')} h`;
}

/**
 * A span of time, honest at both ends: nothing recorded reads as an
 * em-dash rather than "0:00 h" (which looks like a measurement), and
 * anything under a minute says so rather than rounding itself away.
 */
function fmtSpan(seconds: number | null | undefined): string {
  const s = Math.max(0, Math.round(seconds ?? 0));
  if (s <= 0) return EM_DASH;
  if (s < 60) return '< 1 min';
  return fmtHours(s);
}

/** "1 job" / "2 jobs" - a count is never a bare number on this page. */
function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`;
}

/* ── Dates and times ──────────────────────────────────────────────────── */

/** Local ISO calendar day (YYYY-MM-DD) for a Date - never a UTC shift. */
function isoDay(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/**
 * A calendar day in the format the rest of the ERP uses.
 *
 * `fmtDate` honours the user's Settings -> Regional date-format preference
 * and pins a date-only string to UTC so the calendar day never slips. This
 * page used to roll its own `toLocaleDateString`, which printed "Tue 2 Sep"
 * beside the app's "02 Sep 2026" on the same screen and ignored the
 * preference entirely - the same defect the request drawer had.
 */
function fmtDay(day: string | null | undefined): string {
  if (!day) return EM_DASH;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return day;
  return fmtDate(day);
}

/**
 * A UTC ISO instant as a wall clock, e.g. "08:02".
 *
 * There is no shared time-of-day formatter to borrow, so this is the one
 * `toLocale*` call left on the page - and it is pinned to the app's Intl
 * locale (`getIntlLocale`) rather than the browser's, so it matches every
 * other formatted value here instead of following the OS.
 */
function fmtClock(iso: string | null | undefined): string {
  if (!iso) return EM_DASH;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return EM_DASH;
  return d.toLocaleTimeString(getIntlLocale(), { hour: '2-digit', minute: '2-digit' });
}

/** "just now" / "2m ago" / "1h 05m ago" for a UTC ISO instant. */
function fmtAgo(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return 'never';
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return 'never';
  const secs = Math.max(0, Math.round((now - t) / 1000));
  if (secs < 45) return 'just now';
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return `${h}h ${String(m).padStart(2, '0')}m ago`;
}

/* ── Module keys -> the names people see in the sidebar ───────────────── */

/** Words the ERP writes in capitals; a slug made of them is never sentence-cased. */
const ACRONYMS: Record<string, string> = {
  rfi: 'RFI', boq: 'BOQ', bim: 'BIM', cde: 'CDE', crm: 'CRM', qms: 'QMS',
  ncr: 'NCR', dwg: 'DWG', ifc: 'IFC', rvt: 'RVT', evm: 'EVM', hse: 'HSE',
  pdf: 'PDF', ai: 'AI', gaeb: 'GAEB', bcf: 'BCF',
};

/** Last-resort reading of a slug: `dwg-takeoff` -> `DWG takeoff`. */
function sentenceCaseSlug(slug: string): string {
  const words = slug.split(/[-_]+/).filter(Boolean);
  if (words.length === 0) return slug;
  const [head, ...rest] = words;
  const first = ACRONYMS[head!.toLowerCase()] ?? head![0]!.toUpperCase() + head!.slice(1);
  return [first, ...rest.map((w) => ACRONYMS[w.toLowerCase()] ?? w)].join(' ');
}

interface SlugLabel {
  /** i18n key, so the label follows the reader's language. */
  key: string;
  /** English fallback, used when nothing answers the key. */
  en: string;
}

/**
 * `module_key` -> the label that module wears in the sidebar.
 *
 * A presence row stores the first path segment (`comms-intelligence`,
 * `work-requests`, `dwg-takeoff`), which is a route slug, not a name. The
 * app already knows every one of those names: the static sidebar
 * catalogue and the module manifests. Reading them from there rather than
 * hand-keeping a list here is what stops this page from calling a module
 * something the sidebar does not.
 */
const NAV_LABEL_BY_SLUG: Record<string, SlugLabel> = (() => {
  const out: Record<string, SlugLabel> = {};
  const put = (to: string, key: string, en?: string) => {
    const slug = (to.replace(/^\/+/, '').split(/[/?#]/)[0] ?? '').toLowerCase();
    if (!slug || out[slug]) return;
    out[slug] = { key, en: en?.trim() || sentenceCaseSlug(slug) };
  };
  for (const group of navGroups) {
    for (const item of group.items) put(item.to, item.labelKey, item.defaultLabel);
  }
  for (const mod of MODULE_REGISTRY) {
    for (const item of mod.navItems) put(item.to, item.labelKey, mod.translations?.['en']?.[item.labelKey]);
  }
  // The ERP root is stored as `dashboard` by the beacon, and the sidebar's
  // dashboard row is `/`, whose slug is empty - so name it explicitly.
  out['dashboard'] ??= { key: 'nav.dashboard', en: 'Dashboard' };
  return out;
})();

/* ── Copy for the clipboard ───────────────────────────────────────────── */

/** The most recent sign-out or tab close on a row (UTC ISO), if any. */
function lastDeparture(row: AttendanceRow): { at: string; kind: 'logout' | 'end' } | null {
  const logout = row.logouts.length ? row.logouts[row.logouts.length - 1] : null;
  const end = row.ends.length ? row.ends[row.ends.length - 1] : null;
  if (logout && (!end || logout >= end)) return { at: logout, kind: 'logout' };
  if (end) return { at: end, kind: 'end' };
  return null;
}

/** Plain-text line for "Copy times". */
function attendanceLine(row: AttendanceRow): string {
  const gone = lastDeparture(row);
  const parts = [
    row.name,
    fmtDay(row.day),
    `first seen ${fmtClock(row.first_seen)}`,
    `last seen ${fmtClock(row.last_seen)}`,
    `active ${fmtSpan(row.active_seconds)}`,
    `sign-ins ${row.logins.length ? fmtList(row.logins.map((t) => fmtClock(t))) : 'none recorded'}`,
    row.still_on
      ? 'still on'
      : gone
        ? `${gone.kind === 'logout' ? 'signed out' : 'tab closed'} ${fmtClock(gone.at)}`
        : 'no sign-out recorded',
  ];
  return parts.join(' · ');
}

async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    /* clipboard blocked - nothing else sensible to do without a prompt */
  }
}

function readWindow(): MetricsWindow {
  try {
    const raw = Number(localStorage.getItem(WINDOW_KEY));
    return (WINDOWS as number[]).includes(raw) ? (raw as MetricsWindow) : 30;
  } catch {
    return 30;
  }
}

/** Manager or above may read the team rollup; everyone else gets the panel. */
function mayReadMetrics(role: string | null | undefined): boolean {
  const rank = ROLE_RANK[normalizeRole(role) as keyof typeof ROLE_RANK];
  return typeof rank === 'number' && rank >= ROLE_RANK.manager;
}

type MenuTarget =
  | { kind: 'person'; person: PersonMetrics }
  | { kind: 'job'; job: JobMetrics }
  | { kind: 'attendance'; row: AttendanceRow };
type Menu = MenuTarget & { x: number; y: number };

export default function TeamMetricsPage() {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const userRole = useAuthStore((s) => s.userRole);
  const allowed = mayReadMetrics(userRole);

  const [days, setDays] = useState<MetricsWindow>(readWindow);
  const [data, setData] = useState<TeamMetrics | null>(null);
  const [status, setStatus] = useState<'loading' | 'ready' | 'unavailable' | 'forbidden' | 'error'>('loading');
  const [errorText, setErrorText] = useState('');
  const [retry, setRetry] = useState(0);
  const [menu, setMenu] = useState<Menu | null>(null);
  const [allDays, setAllDays] = useState(false);
  const [copied, setCopied] = useState(false);

  /** A module key as a person reads it, in their language. */
  const moduleLabel = useCallback(
    (key: string): string => {
      const slug = (key || '').toLowerCase();
      const hit = NAV_LABEL_BY_SLUG[slug];
      if (hit) return t(hit.key, { defaultValue: hit.en });
      // `other` is what the server stores for a path it will not keep raw.
      if (slug === 'other') return 'Elsewhere in the ERP';
      return sentenceCaseSlug(slug);
    },
    [t],
  );

  useEffect(() => {
    if (!allowed) return;
    let alive = true;
    setStatus('loading');
    fetchTeamMetrics(days)
      .then((d) => {
        if (!alive) return;
        if (d && Array.isArray(d.people)) {
          setData(d);
          setStatus('ready');
        } else {
          setStatus('unavailable');
        }
      })
      .catch((e: unknown) => {
        if (!alive) return;
        if (e instanceof ApiError && (e.status === 403 || e.status === 401)) {
          // The stored role said manager but the server disagrees (a
          // demotion the client has not synced yet). Same calm panel, not
          // an error: the reader has not done anything wrong.
          setStatus('forbidden');
          return;
        }
        if (e instanceof ApiError && (e.status === 404 || e.status === 405)) {
          // The metrics endpoint is not on this server yet (needs a restart
          // after the module update). Not a crash - an honest empty state.
          setStatus('unavailable');
          return;
        }
        setErrorText(e instanceof Error ? e.message : 'The metrics did not load.');
        setStatus('error');
      });
    return () => {
      alive = false;
    };
  }, [allowed, days, retry]);

  const pickWindow = (w: MetricsWindow) => {
    setDays(w);
    try {
      localStorage.setItem(WINDOW_KEY, String(w));
    } catch {
      /* ignore */
    }
  };

  // Close the context menu on any click, Escape, scroll or resize.
  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(null);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
    };
    window.addEventListener('mousedown', close);
    window.addEventListener('scroll', close, true);
    window.addEventListener('resize', close);
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('mousedown', close);
      window.removeEventListener('scroll', close, true);
      window.removeEventListener('resize', close);
      window.removeEventListener('keydown', onKey);
    };
  }, [menu]);

  const openMenu = useCallback((e: ReactMouseEvent, m: MenuTarget) => {
    e.preventDefault();
    const x = Math.min(e.clientX, window.innerWidth - 240);
    const y = Math.min(e.clientY, window.innerHeight - 120);
    setMenu({ ...m, x, y });
  }, []);

  const moduleOrder = useMemo(() => (data ? data.modules.map((m) => m.module_key) : []), [data]);
  const moduleTotal = useMemo(() => (data ? data.modules.reduce((a, m) => a + m.seconds, 0) : 0), [data]);
  /** The modules that get their own bar segment; everything else is "Elsewhere". */
  const barModules = useMemo(() => moduleOrder.slice(0, BAR_MODULES), [moduleOrder]);
  const hasOtherModules = moduleOrder.length > barModules.length;
  const jobMax = useMemo(() => (data ? Math.max(0, ...data.jobs.map((j) => j.seconds_total)) : 0), [data]);
  const hasPresence = moduleTotal > 0;
  const hasAnyTaskWork = !!data && data.people.some((p) => p.tasks_open + p.tasks_completed + p.standups_posted > 0);

  // Attendance: the server sends the whole window newest-first; fold to the
  // newest ATTENDANCE_DAYS_FOLDED days until "show all" is pressed.
  const attendanceAll = useMemo<AttendanceRow[]>(() => (Array.isArray(data?.attendance) ? data.attendance : []), [data]);
  const attendanceDays = useMemo(() => Array.from(new Set(attendanceAll.map((r) => r.day))), [attendanceAll]);
  const attendance = useMemo(() => {
    if (allDays || attendanceDays.length <= ATTENDANCE_DAYS_FOLDED) return attendanceAll;
    const keep = new Set(attendanceDays.slice(0, ATTENDANCE_DAYS_FOLDED));
    return attendanceAll.filter((r) => keep.has(r.day));
  }, [attendanceAll, attendanceDays, allDays]);
  const attendanceSupported = !!data && Array.isArray(data.attendance);
  const onlineCount = data ? data.people.filter((p) => p.today?.online).length : 0;

  useEffect(() => {
    if (!copied) return;
    const t2 = window.setTimeout(() => setCopied(false), 1600);
    return () => window.clearTimeout(t2);
  }, [copied]);

  const today = new Date();
  const from = new Date(today.getTime() - (days - 1) * 86_400_000);
  const dateLabel = `${fmtDay(isoDay(from))} – ${fmtDay(isoDay(today))}`;

  /** The page chrome, shared by the gate panel and the dashboard itself. */
  const chrome = (
    <div className="tm-chrome">
      <div>
        <h1>Team metrics</h1>
        <p className="tm-sub">How the team is performing, where the time goes, and where everyone is in the ERP.</p>
      </div>
      <div className="tm-chrome-actions">
        <button type="button" className="tm-ghost" onClick={() => navigate('/team-standup')}>
          Back to Team Standup
        </button>
        {allowed && (
          <button type="button" className="tm-ghost" onClick={() => setRetry((k) => k + 1)}>
            Refresh
          </button>
        )}
      </div>
    </div>
  );

  // ── Managers and admins only ───────────────────────────────────────────
  // Reached by typing the URL, or by a bookmark kept after a demotion. Say
  // so plainly and point at the page they can use, rather than showing an
  // error, an empty dashboard, or nothing at all.
  if (!allowed || status === 'forbidden') {
    return (
      <div className="tm-root">
        <div className="tm-wrap">
          {chrome}
          <div className="tm-app">
            <div className="tm-empty tm-gate">
              <b>This page is for managers</b>
              <span>
                Team metrics reports on people - what each person closed, how long it took, and when they were
                signed in - so it is limited to manager and admin accounts. Nothing has gone wrong, and your own
                presence is still counted towards the team&apos;s figures.
              </span>
              <span>Your own board, tasks and standups are on Team Standup.</span>
              <div className="tm-gate-actions">
                <button type="button" className="tm-btn-quiet" onClick={() => navigate('/team-standup')}>
                  Open Team Standup
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="tm-root">
      <div className="tm-wrap">
        {chrome}

        <div className="tm-app">
          <div className="tm-head">
            <div>
              <h2>Last {days} days</h2>
              <p className="tm-date">{dateLabel}</p>
            </div>
            <div className="tm-controls">
              <span className="tm-hint">Window</span>
              <div className="tm-seg" role="group" aria-label="Window">
                {WINDOWS.map((w) => (
                  <button key={w} type="button" aria-pressed={w === days} onClick={() => pickWindow(w)}>
                    {w}d
                  </button>
                ))}
              </div>
            </div>
          </div>

          {status === 'loading' && !data && <p className="tm-hint">Loading the metrics...</p>}

          {status === 'error' && (
            <div className="tm-error">
              {errorText}{' '}
              <button type="button" className="tm-btn-quiet" onClick={() => setRetry((k) => k + 1)}>
                Try again
              </button>
            </div>
          )}

          {status === 'unavailable' && (
            <div className="tm-empty">
              <b>Metrics are not available on this server yet.</b>
              <span>
                The Team Standup module has the metrics endpoint, but the running backend was started before it
                existed. Restart the backend and reload this page. Presence (time by module and by job) starts
                counting from the first sign-in after that restart - there is no history before it.
              </span>
            </div>
          )}

          {data && (
            <>
              {!hasPresence && (
                <div className="tm-empty">
                  <b>No presence recorded yet in this window.</b>
                  <span>
                    Time-in-ERP starts counting from now: every signed-in tab reports where it is once a minute
                    (idle tabs stop after five minutes). Task and standup figures below come from the delivery
                    board and are complete for the window.
                  </span>
                </div>
              )}

              {/* People */}
              <section className="tm-tile" style={{ ['--tint' as string]: 'var(--c-violet)', ['--tint-wash' as string]: 'var(--w-violet)' }}>
                <div className="tm-tile-head">
                  <h3>People</h3>
                  <span className="tm-meta">Tasks, standups and time by module. Right-click a person for their tasks.</span>
                  <span className="tm-spacer" />
                  {onlineCount > 0 && (
                    <span className="tm-pip tm-pip-online" title="Signed in and active in the last three minutes">
                      {onlineCount} online
                    </span>
                  )}
                  <span className="tm-pip">{plural(data.people.length, 'person', 'people')}</span>
                </div>
                <div className="tm-tile-body">
                  {data.people.length === 0 || !hasAnyTaskWork ? (
                    <p className="tm-hint">Nobody has posted a standup or been assigned a delivery-board task in this window.</p>
                  ) : null}
                  {data.people.length > 0 && (
                    <div className="tm-tablewrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Person</th>
                            <th className="tm-num">Done</th>
                            <th className="tm-num">Open</th>
                            <th className="tm-num">Overdue</th>
                            <th className="tm-num">Avg days to close</th>
                            <th className="tm-num">Standups</th>
                            <th className="tm-num">Blockers</th>
                            <th>Time by module</th>
                            <th>Top jobs by time</th>
                          </tr>
                        </thead>
                        <tbody>
                          {data.people.map((p) => {
                            const total = Object.values(p.seconds_by_module).reduce((a, b) => a + b, 0);
                            const named = barModules.reduce((a, k) => a + (p.seconds_by_module[k] ?? 0), 0);
                            const elsewhere = Math.max(0, total - named);
                            const tint = tintFor(p.user_id);
                            const breakdown = moduleOrder
                              .filter((k) => (p.seconds_by_module[k] ?? 0) > 0)
                              .map((k) => `${moduleLabel(k)} ${fmtSpan(p.seconds_by_module[k] ?? 0)}`)
                              .join(' · ');
                            return (
                              <tr
                                key={p.user_id}
                                className="tm-hot"
                                onContextMenu={(e) => openMenu(e, { kind: 'person', person: p })}
                              >
                                <td className="tm-who">
                                  <span className="tm-person">
                                    <span className="tm-av" style={{ ['--tint' as string]: `var(--c-${tint})` }} aria-hidden>
                                      {initials(p.name)}
                                    </span>
                                    <span className="tm-name">{p.name}</span>
                                    {p.today?.online && (
                                      <span
                                        className="tm-online"
                                        role="img"
                                        aria-label="Online now"
                                        title={`Online now · last seen ${fmtAgo(p.today.last_seen)}`}
                                      />
                                    )}
                                  </span>
                                </td>
                                <Num v={p.tasks_completed} />
                                <Num v={p.tasks_open} />
                                <Num v={p.tasks_overdue} crit />
                                <td className={`tm-num${p.avg_days_to_close === null ? ' tm-zero' : ''}`}>
                                  {p.avg_days_to_close === null ? EM_DASH : fmtFixed(p.avg_days_to_close, 1)}
                                </td>
                                <Num v={p.standups_posted} />
                                <Num v={p.blockers_raised} />
                                <td>
                                  {total > 0 ? (
                                    <div className="tm-barcell">
                                      <div className="tm-bar" title={breakdown}>
                                        {barModules.map((k) => {
                                          const s = p.seconds_by_module[k] ?? 0;
                                          if (!s) return null;
                                          return (
                                            <span
                                              key={k}
                                              style={{ width: `${(s / total) * 100}%`, ['--seg' as string]: `var(--c-${tintFor(k)})` }}
                                            />
                                          );
                                        })}
                                        {elsewhere > 0 && (
                                          <span style={{ width: `${(elsewhere / total) * 100}%`, ['--seg' as string]: 'var(--c-slate)' }} />
                                        )}
                                      </div>
                                      <span className="tm-dur">{fmtSpan(total)}</span>
                                    </div>
                                  ) : (
                                    <span className="tm-hint">No presence yet</span>
                                  )}
                                </td>
                                <td>
                                  {p.seconds_by_job.length ? (
                                    <div className="tm-chips">
                                      {p.seconds_by_job.slice(0, 3).map((j) => (
                                        <span key={j.project_id} className="tm-chip" title={j.name || 'Job with no name'}>
                                          <span className="tm-code" style={{ ['--tint' as string]: `var(--c-${tintFor(j.project_id)})`, ['--tint-wash' as string]: `var(--w-${tintFor(j.project_id)})` }}>
                                            {j.code || 'No job number'}
                                          </span>
                                          <b>{fmtSpan(j.seconds)}</b>
                                        </span>
                                      ))}
                                    </div>
                                  ) : (
                                    <span className="tm-hint" title="No time recorded against a job in this window">
                                      {EM_DASH}
                                    </span>
                                  )}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                  {hasPresence && (
                    <div className="tm-legend">
                      {barModules.map((k) => (
                        <span key={k}>
                          <i style={{ ['--seg' as string]: `var(--c-${tintFor(k)})` }} />
                          {moduleLabel(k)}
                        </span>
                      ))}
                      {hasOtherModules && (
                        <span title={moduleOrder.slice(BAR_MODULES).map(moduleLabel).join(' · ')}>
                          <i style={{ ['--seg' as string]: 'var(--c-slate)' }} />
                          Elsewhere ({moduleOrder.length - BAR_MODULES} more)
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </section>

              {/* Attendance */}
              <section className="tm-tile" style={{ ['--tint' as string]: 'var(--c-green)', ['--tint-wash' as string]: 'var(--w-green)' }}>
                <div className="tm-tile-head">
                  <h3>Attendance</h3>
                  <span className="tm-meta">When each person signed in, was last seen and finished. Right-click a row to copy the times.</span>
                  <span className="tm-spacer" />
                  {attendanceDays.length > ATTENDANCE_DAYS_FOLDED && (
                    <button type="button" className="tm-btn-quiet tm-btn-xs" onClick={() => setAllDays((v) => !v)}>
                      {allDays ? `Newest ${ATTENDANCE_DAYS_FOLDED} days` : `Show all ${plural(attendanceDays.length, 'day')}`}
                    </button>
                  )}
                  <span className="tm-pip">{plural(attendance.length, 'row')}</span>
                </div>
                <div className="tm-tile-body">
                  {attendance.length === 0 ? (
                    <div className="tm-empty">
                      <b>No attendance recorded in this window.</b>
                      <span>
                        Attendance starts counting from the first sign-in after this update: a sign-in, the first
                        minute a tab reports presence, and the sign-out or tab close each land as they happen. There is
                        no history before that.
                        {!attendanceSupported && ' The running backend predates this - restart it and reload.'}
                      </span>
                    </div>
                  ) : (
                    <div className="tm-tablewrap">
                      <table className="tm-attendance">
                        <thead>
                          <tr>
                            <th>Person</th>
                            <th>Day</th>
                            <th>First seen</th>
                            <th>Last seen</th>
                            <th className="tm-num">Active</th>
                            <th className="tm-num">Sign-ins</th>
                            <th>Finished</th>
                          </tr>
                        </thead>
                        <tbody>
                          {attendance.map((row) => {
                            const gone = lastDeparture(row);
                            const tint = tintFor(row.user_id);
                            return (
                              <tr
                                key={`${row.user_id}-${row.day}`}
                                className="tm-hot"
                                onContextMenu={(e) => openMenu(e, { kind: 'attendance', row })}
                              >
                                <td className="tm-who">
                                  <span className="tm-person">
                                    <span className="tm-av tm-av-sm" style={{ ['--tint' as string]: `var(--c-${tint})` }} aria-hidden>
                                      {initials(row.name)}
                                    </span>
                                    <span className="tm-name">{row.name}</span>
                                  </span>
                                </td>
                                <td className="tm-nowrap tm-day">{fmtDay(row.day)}</td>
                                <td className="tm-mono">{fmtClock(row.first_seen)}</td>
                                <td className="tm-mono" title={row.last_seen ? fmtAgo(row.last_seen) : undefined}>
                                  {fmtClock(row.last_seen)}
                                </td>
                                <td className={`tm-num${row.active_seconds === 0 ? ' tm-zero' : ''}`}>{fmtSpan(row.active_seconds)}</td>
                                <td
                                  className={`tm-num${row.logins.length === 0 ? ' tm-zero' : ''}`}
                                  title={row.logins.length ? fmtList(row.logins.map((t2) => fmtClock(t2))) : 'No explicit sign-in recorded'}
                                >
                                  {row.logins.length === 0 ? EM_DASH : row.logins.length}
                                </td>
                                <td className="tm-nowrap">
                                  {row.still_on ? (
                                    <span className="tm-pill tm-pill-on" title={`Last seen ${fmtAgo(row.last_seen)}`}>
                                      still on
                                    </span>
                                  ) : gone ? (
                                    <span className="tm-mono" title={gone.kind === 'logout' ? 'Signed out' : 'Tab closed'}>
                                      {fmtClock(gone.at)}
                                      {gone.kind === 'end' && <span className="tm-hint"> (tab closed)</span>}
                                    </span>
                                  ) : (
                                    <span className="tm-hint" title="Went quiet without a sign-out or tab close being reported">
                                      {EM_DASH}
                                    </span>
                                  )}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              </section>

              <div className="tm-grid2">
                {/* Jobs */}
                <section className="tm-tile" style={{ ['--tint' as string]: 'var(--c-blue)', ['--tint-wash' as string]: 'var(--w-blue)' }}>
                  <div className="tm-tile-head">
                    <h3>Jobs taking the team&apos;s time</h3>
                    <span className="tm-meta">Right-click a job to open it.</span>
                    <span className="tm-spacer" />
                    <span className="tm-pip">{plural(data.jobs.length, 'job')}</span>
                  </div>
                  <div className="tm-tile-body">
                    {data.jobs.length === 0 ? (
                      <p className="tm-hint">No job has tasks or recorded time in this window.</p>
                    ) : (
                      <div className="tm-tablewrap">
                        <table>
                          <thead>
                            <tr>
                              <th>Job</th>
                              <th>Time</th>
                              <th className="tm-num">Open</th>
                              <th className="tm-num">Overdue</th>
                              <th className="tm-num">Done</th>
                              <th>Who</th>
                            </tr>
                          </thead>
                          <tbody>
                            {data.jobs.map((j) => {
                              const tint = tintFor(j.project_id);
                              return (
                                <tr key={j.project_id} className="tm-hot" onContextMenu={(e) => openMenu(e, { kind: 'job', job: j })}>
                                  <td className="tm-jobcell">
                                    {j.code ? (
                                      <span className="tm-code" style={{ ['--tint' as string]: `var(--c-${tint})`, ['--tint-wash' as string]: `var(--w-${tint})` }}>
                                        {j.code}
                                      </span>
                                    ) : (
                                      <span className="tm-code tm-code-none" title="This job has no job number">
                                        No job number
                                      </span>
                                    )}{' '}
                                    <span className="tm-jobname">{j.name || 'Job with no name'}</span>
                                  </td>
                                  <td>
                                    <div className="tm-barcell">
                                      <div className="tm-bar tm-bar-solid">
                                        {j.seconds_total > 0 && jobMax > 0 && (
                                          <span style={{ width: `${Math.max(2, (j.seconds_total / jobMax) * 100)}%`, ['--seg' as string]: `var(--c-${tint})` }} />
                                        )}
                                      </div>
                                      <span className="tm-dur">{fmtSpan(j.seconds_total)}</span>
                                    </div>
                                  </td>
                                  <Num v={j.open_tasks} />
                                  <Num v={j.overdue} crit />
                                  <Num v={j.completed} />
                                  <td>
                                    {j.people.length ? (
                                      <span className="tm-avs" title={j.people.map((p) => `${p.name} ${fmtSpan(p.seconds)}`).join(' · ')}>
                                        {j.people.slice(0, 5).map((p) => (
                                          <span key={p.user_id} className="tm-av tm-av-sm" style={{ ['--tint' as string]: `var(--c-${tintFor(p.user_id)})` }}>
                                            {initials(p.name)}
                                          </span>
                                        ))}
                                        {j.people.length > 5 && <span className="tm-av tm-av-sm" style={{ ['--tint' as string]: 'var(--c-slate)' }}>+{j.people.length - 5}</span>}
                                      </span>
                                    ) : (
                                      <span className="tm-hint" title="No presence recorded against this job">
                                        {EM_DASH}
                                      </span>
                                    )}
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                </section>

                {/* Modules */}
                <section className="tm-tile" style={{ ['--tint' as string]: 'var(--c-teal)', ['--tint-wash' as string]: 'var(--w-teal)' }}>
                  <div className="tm-tile-head">
                    <h3>Where the team is in the ERP</h3>
                    <span className="tm-meta">Time by module, whole team.</span>
                    <span className="tm-spacer" />
                    <span className="tm-pip">{fmtSpan(moduleTotal)}</span>
                  </div>
                  <div className="tm-tile-body">
                    {data.modules.length === 0 ? (
                      <p className="tm-hint">Nothing recorded yet - the beacon counts from the first signed-in minute.</p>
                    ) : (
                      <div className="tm-modrows">
                        {data.modules.map((m) => {
                          const share = moduleTotal > 0 ? (m.seconds / moduleTotal) * 100 : 0;
                          return (
                            <div key={m.module_key} className="tm-modrow">
                              <span className="tm-modname" title={moduleLabel(m.module_key)}>
                                <i style={{ ['--seg' as string]: `var(--c-${tintFor(m.module_key)})` }} />
                                <span className="tm-modname-text">{moduleLabel(m.module_key)}</span>
                              </span>
                              <div className="tm-bar tm-bar-solid">
                                <span style={{ width: `${Math.max(1, share)}%`, ['--seg' as string]: `var(--c-${tintFor(m.module_key)})` }} />
                              </div>
                              <span className="tm-dur">{fmtSpan(m.seconds)}</span>
                              <span className="tm-share">{fmtPercent(share, 0)}</span>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                </section>
              </div>
            </>
          )}
        </div>
      </div>

      {menu && (
        <div
          className="tm-ctx"
          style={{ left: menu.x, top: menu.y }}
          role="menu"
          onMouseDown={(e) => e.stopPropagation()}
        >
          <div className="tm-ctx-head">
            {menu.kind === 'person' && menu.person.name}
            {menu.kind === 'job' && `${menu.job.code || 'No job number'} · ${menu.job.name || 'Job with no name'}`}
            {menu.kind === 'attendance' && `${menu.row.name} · ${fmtDay(menu.row.day)}`}
          </div>
          {menu.kind === 'person' && (
            <button
              type="button"
              onClick={() => {
                setMenu(null);
                navigate('/team-standup');
              }}
            >
              Open their tasks <span className="tm-k">Team Standup</span>
            </button>
          )}
          {menu.kind === 'attendance' && (
            <>
              <button
                type="button"
                onClick={() => {
                  setMenu(null);
                  navigate('/team-standup');
                }}
              >
                Open their tasks <span className="tm-k">Team Standup</span>
              </button>
              <button
                type="button"
                onClick={() => {
                  const line = attendanceLine(menu.row);
                  setMenu(null);
                  void copyText(line).then(() => setCopied(true));
                }}
              >
                Copy times <span className="tm-k">clipboard</span>
              </button>
            </>
          )}
          {menu.kind === 'job' && (
            <button
              type="button"
              onClick={() => {
                const id = menu.job.project_id;
                setMenu(null);
                navigate(`/projects/${encodeURIComponent(id)}`);
              }}
            >
              Open job <span className="tm-k">Projects</span>
            </button>
          )}
        </div>
      )}

      {copied && (
        <div className="tm-toast" role="status">
          Times copied
        </div>
      )}
    </div>
  );
}

function Num({ v, crit = false }: { v: number; crit?: boolean }) {
  const cls = ['tm-num', v === 0 ? 'tm-zero' : '', crit && v > 0 ? 'tm-crit' : ''].filter(Boolean).join(' ');
  // A genuine zero is data here (nothing done, nothing overdue), so it
  // stays a 0 - muted, not an em-dash, which is reserved for "not known".
  return <td className={cls}>{v}</td>;
}
