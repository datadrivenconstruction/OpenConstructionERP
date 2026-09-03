// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * MemberAvailabilityModal — "what is this person actually carrying?"
 *
 * Opened from a card on the Project-team tile. Six sections, each fed by a
 * different read-only module and each degrading to a single honest line when
 * that module answers 404 or has nothing to say:
 *
 *   1. Week at a glance  — 7-day Mon→Sun strip: people booked on their jobs
 *                          that day (work-requests planner) + a dot for the
 *                          days they posted a standup (team-standup week).
 *   2. Open work requests — /work-requests/requests?assignee_id=…
 *   3. Open standup tasks — the full-board tasks assigned to them that are
 *                          not in a done stage.
 *   4. Attendance (7 days)— team-standup metrics attendance rows. This is the
 *                          ONE manager-only section: /metrics carries every
 *                          colleague's throughput and history, so it 403s for
 *                          an ordinary team member and the section says so.
 *                          Every other section, the "Online now" badge and
 *                          today's status included, is viewer-level and must
 *                          stay that way.
 *   5. Departments        — work-requests departments they are in / lead.
 *
 * Every query is gated on ``open`` so nothing is fetched until the popup is
 * actually opened, and the board / metrics / departments queries share their
 * cache keys with the tile, so opening a popup usually costs one request (the
 * member's own work requests).
 */

import { useMemo } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import {
  X,
  CalendarDays,
  Wrench,
  ListChecks,
  Clock3,
  Building2,
  ExternalLink,
  AlertTriangle,
} from 'lucide-react';
import { Avatar, type ProjectMember } from './TeamStrip';
import { roleLabel } from './projectRoles';
import {
  allocByDayFor,
  departmentsFor,
  formatActiveSeconds,
  formatClock,
  isoDay,
  openTasksFor,
  standupStatusLabel,
  useMemberRequests,
  usePlannerForDepartments,
  usePresenceToday,
  useStandupBoard,
  useStandupMetrics,
  useWorkRequestDepartments,
  weekDays,
} from './useTeamAvailability';
import { useModalDismiss } from './useModalDismiss';
import { fmtFixed } from '@/shared/lib/formatters';

const DAY_INITIALS = ['M', 'T', 'W', 'T', 'F', 'S', 'S'] as const;

export interface MemberAvailabilityModalProps {
  member: ProjectMember;
  /** The job this popup was opened from — scopes the presence query, and
   *  shares its cache key with the tile so opening a popup costs no request. */
  projectId?: string;
  onClose: () => void;
}

/** One-liner used whenever a module is offline or simply has nothing. */
function SectionNote({ children }: { children: React.ReactNode }) {
  return (
    <p className="px-1 py-2 text-xs text-content-tertiary" data-testid="availability-note">
      {children}
    </p>
  );
}

function SectionHeading({
  icon,
  children,
}: {
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <h3 className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-content-secondary">
      <span className="text-content-tertiary">{icon}</span>
      {children}
    </h3>
  );
}

export function MemberAvailabilityModal({
  member,
  projectId,
  onClose,
}: MemberAvailabilityModalProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  useModalDismiss(true, onClose);

  const today = useMemo(() => isoDay(new Date()), []);
  const days = useMemo(() => weekDays(new Date()), []);

  const boardQuery = useStandupBoard(today, true);
  // Presence is viewer-level and shares the tile's cache key; the rollup is
  // manager-only and feeds the attendance section alone.
  const presenceQuery = usePresenceToday(projectId, true);
  const metricsQuery = useStandupMetrics(7, true);
  const departmentsQuery = useWorkRequestDepartments(true);
  const requestsQuery = useMemberRequests(member.user_id, true);

  const board = boardQuery.data ?? null;
  const metrics = metricsQuery.data?.metrics ?? null;
  const metricsForbidden = metricsQuery.data?.forbidden ?? false;

  const memberDepartments = useMemo(
    () => departmentsFor(departmentsQuery.data, member.user_id),
    [departmentsQuery.data, member.user_id],
  );
  // Deliberately EVERY department, not just the ones they belong to. People
  // are routinely assigned to a request raised on another department's board
  // (an engineer on a drafting job), and pulling only their own departments'
  // planners silently dropped those days - the tile, which pulls every
  // department any project member is in, then disagreed with this popup about
  // the same person's week.
  const plannerKeys = useMemo(
    () => (departmentsQuery.data ?? []).map((d) => d.key),
    [departmentsQuery.data],
  );
  const planner = usePlannerForDepartments(
    plannerKeys,
    days[0]!,
    days[6]!,
    plannerKeys.length > 0,
  );

  const alloc = useMemo(
    () => allocByDayFor(planner.payloads, member.user_id, days),
    [planner.payloads, member.user_id, days],
  );

  /** ISO days this week on which they posted a standup. */
  const postedDays = useMemo(() => {
    const set = new Set<string>();
    for (const e of board?.week?.entries ?? []) {
      if (e.user_id === member.user_id) set.add(e.day);
    }
    // The board's `entries` (today) are not always inside `week.entries` when
    // the week window starts later; fold them in so today never reads blank.
    for (const e of board?.entries ?? []) {
      if (e.user_id === member.user_id) set.add(e.day);
    }
    return set;
  }, [board, member.user_id]);

  const todayEntry = useMemo(
    () => (board?.entries ?? []).find((e) => e.user_id === member.user_id) ?? null,
    [board, member.user_id],
  );

  const openTasks = useMemo(
    () => openTasksFor(board, member.user_id),
    [board, member.user_id],
  );

  const stageName = useMemo(() => {
    const map = new Map<string, string>();
    for (const s of board?.stages ?? []) map.set(String(s.id), s.name);
    return map;
  }, [board]);

  const jobLabel = useMemo(() => {
    const map = new Map<string, string>();
    for (const j of board?.jobs ?? []) map.set(String(j.id), j.label || j.code || j.name);
    return map;
  }, [board]);

  const presence = useMemo(
    () =>
      (presenceQuery.data ?? []).find((p) => p.user_id === member.user_id) ?? null,
    [presenceQuery.data, member.user_id],
  );
  const attendance = useMemo(
    () => (metrics?.attendance ?? []).filter((a) => a.user_id === member.user_id),
    [metrics, member.user_id],
  );

  const online = presence?.online ?? false;
  const requests = requestsQuery.data ?? null;
  const displayName = member.full_name || member.email;

  // Portalled to <body>. The tile lives inside a Card whose entry animation
  // sets a transform, and a transformed ancestor becomes the containing block
  // for `position: fixed` — without the portal this "full-screen" overlay
  // renders trapped inside the widget's grid cell.
  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t('projects.team.availability_of', {
        name: displayName,
        defaultValue: 'Availability — {{name}}',
      })}
      className="fixed inset-0 z-[70] flex items-start justify-center overflow-y-auto bg-black/50 p-4 sm:items-center"
      onClick={onClose}
      data-testid="member-availability-modal"
    >
      <div
        className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-xl bg-surface-primary shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* ── Header ─────────────────────────────────────────────────── */}
        <div className="flex items-start gap-3 border-b border-border-light px-4 py-3">
          <Avatar member={member} size={40} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h2 className="truncate text-base font-semibold text-content-primary">
                {displayName}
              </h2>
              {online && (
                <span
                  className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-2xs font-medium text-emerald-600 dark:text-emerald-400"
                  data-testid="availability-online"
                >
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                  {t('projects.team.online_now', { defaultValue: 'Online now' })}
                </span>
              )}
            </div>
            <p className="truncate text-xs text-content-tertiary">
              {roleLabel(member.role)} · {member.email}
            </p>
            <p className="mt-0.5 text-xs text-content-secondary" data-testid="availability-status">
              {todayEntry
                ? t('projects.team.status_today', {
                    status: standupStatusLabel(todayEntry.status),
                    defaultValue: 'Today: {{status}}',
                  })
                : boardQuery.isLoading
                  ? t('common.loading', { defaultValue: 'Loading…' })
                  : t('projects.team.no_standup_today', {
                      defaultValue: 'No standup posted today.',
                    })}
              {/* Presence, and only presence — viewer-level, so this line is
                  here for everyone. When they are online the badge above
                  already says so; otherwise the useful fact is when they were
                  last about today. */}
              {!online && presence?.last_seen ? (
                <span data-testid="availability-last-seen">
                  {' · '}
                  {t('projects.team.last_seen_at', {
                    time: formatClock(presence.last_seen),
                    defaultValue: 'Last seen {{time}}',
                  })}
                </span>
              ) : null}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 text-content-tertiary hover:text-content-primary"
            aria-label={t('common.close', { defaultValue: 'Close' })}
            data-testid="availability-close"
          >
            <X size={18} />
          </button>
        </div>

        <div className="space-y-5 overflow-y-auto px-4 py-4">
          {/* ── 1. Week at a glance ──────────────────────────────────── */}
          <section>
            <SectionHeading icon={<CalendarDays size={13} />}>
              {t('projects.team.week_at_a_glance', {
                defaultValue: 'Week at a glance',
              })}
            </SectionHeading>
            {plannerKeys.length === 0 && !departmentsQuery.isLoading ? (
              <SectionNote>
                {t('projects.team.no_planner', {
                  defaultValue:
                    'No planner data — the work-request module has no departments to read.',
                })}
              </SectionNote>
            ) : (
              <>
                <div className="grid grid-cols-7 gap-1" data-testid="availability-week">
                  {days.map((day, i) => {
                    const booked = alloc[day] ?? 0;
                    const posted = postedDays.has(day);
                    const isToday = day === today;
                    return (
                      <div
                        key={day}
                        title={t('projects.team.day_tooltip', {
                          day,
                          booked,
                          defaultValue: '{{day}} — {{booked}} booked',
                        })}
                        className={[
                          'rounded-lg border px-1 py-1.5 text-center',
                          isToday
                            ? 'border-oe-blue bg-oe-blue/5'
                            : 'border-border-light bg-surface-secondary/40',
                        ].join(' ')}
                      >
                        <div className="text-2xs font-medium text-content-tertiary">
                          {DAY_INITIALS[i]}
                        </div>
                        <div
                          className={[
                            'text-sm font-semibold tabular-nums',
                            booked > 0 ? 'text-content-primary' : 'text-content-quaternary',
                          ].join(' ')}
                        >
                          {booked > 0 ? booked : '·'}
                        </div>
                        <div className="mt-0.5 flex h-1.5 items-center justify-center">
                          {posted ? (
                            <span
                              className="h-1.5 w-1.5 rounded-full bg-emerald-500"
                              title={t('projects.team.standup_posted', {
                                defaultValue: 'Standup posted',
                              })}
                            />
                          ) : null}
                        </div>
                      </div>
                    );
                  })}
                </div>
                <p className="mt-1.5 text-2xs text-content-quaternary">
                  {t('projects.team.week_legend', {
                    defaultValue:
                      'Number = people booked on the requests they are assigned to that day (planner). Green dot = standup posted.',
                  })}
                </p>
              </>
            )}
          </section>

          {/* ── 2. Open work requests ────────────────────────────────── */}
          <section>
            <SectionHeading icon={<Wrench size={13} />}>
              {t('projects.team.open_requests', {
                defaultValue: 'Open work requests',
              })}
            </SectionHeading>
            {requestsQuery.isLoading ? (
              <SectionNote>{t('common.loading', { defaultValue: 'Loading…' })}</SectionNote>
            ) : !requests ? (
              <SectionNote>
                {t('projects.team.requests_unavailable', {
                  defaultValue: 'Work requests are not available on this install.',
                })}
              </SectionNote>
            ) : requests.length === 0 ? (
              <SectionNote>
                {t('projects.team.no_open_requests', {
                  defaultValue: 'No open work requests assigned to them.',
                })}
              </SectionNote>
            ) : (
              <ul className="divide-y divide-border-light rounded-lg border border-border-light">
                {requests.slice(0, 8).map((r) => (
                  <li
                    key={r.id}
                    className="flex items-center gap-2 px-2.5 py-1.5 text-xs"
                    data-testid="availability-request-row"
                  >
                    <span className="w-24 shrink-0 truncate font-mono text-2xs text-content-tertiary">
                      {r.reference}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-content-primary">
                      {r.title}
                    </span>
                    <span className="hidden w-28 shrink-0 truncate text-content-tertiary sm:block">
                      {r.department_name || r.department}
                    </span>
                    <span
                      className={[
                        'w-20 shrink-0 text-right tabular-nums',
                        r.is_overdue ? 'text-semantic-error' : 'text-content-tertiary',
                      ].join(' ')}
                    >
                      {r.due_date ?? '—'}
                    </span>
                    <span className="w-20 shrink-0 text-right tabular-nums text-content-tertiary">
                      {fmtFixed(r.hours_logged ?? 0, 1)}
                      {r.quoted_hours != null ? `/${r.quoted_hours}` : ''}h
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* ── 3. Open standup tasks ────────────────────────────────── */}
          <section>
            <SectionHeading icon={<ListChecks size={13} />}>
              {t('projects.team.open_tasks', { defaultValue: 'Open standup tasks' })}
            </SectionHeading>
            {boardQuery.isLoading ? (
              <SectionNote>{t('common.loading', { defaultValue: 'Loading…' })}</SectionNote>
            ) : !board ? (
              <SectionNote>
                {t('projects.team.standup_unavailable', {
                  defaultValue: 'The team standup board is not available on this install.',
                })}
              </SectionNote>
            ) : openTasks.length === 0 ? (
              <SectionNote>
                {t('projects.team.no_open_tasks', {
                  defaultValue: 'No open tasks on the standup board.',
                })}
              </SectionNote>
            ) : (
              <ul className="divide-y divide-border-light rounded-lg border border-border-light">
                {openTasks.slice(0, 8).map((task) => (
                  <li
                    key={task.id}
                    className="flex items-center gap-2 px-2.5 py-1.5 text-xs"
                    data-testid="availability-task-row"
                  >
                    <span className="min-w-0 flex-1 truncate text-content-primary">
                      {task.waiting_on ? (
                        <AlertTriangle
                          size={11}
                          className="mr-1 inline text-amber-500"
                          aria-label={t('projects.team.waiting', {
                            defaultValue: 'Waiting',
                          })}
                        />
                      ) : null}
                      {task.title}
                    </span>
                    <span className="hidden w-24 shrink-0 truncate text-content-tertiary sm:block">
                      {jobLabel.get(String(task.project_id)) ?? '—'}
                    </span>
                    <span className="w-24 shrink-0 truncate text-right text-content-tertiary">
                      {stageName.get(String(task.stage_id)) ?? '—'}
                    </span>
                    <span className="w-20 shrink-0 text-right tabular-nums text-content-tertiary">
                      {task.due || '—'}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* ── 4. Attendance ────────────────────────────────────────── */}
          <section>
            <SectionHeading icon={<Clock3 size={13} />}>
              {t('projects.team.attendance_7d', {
                defaultValue: 'Attendance — last 7 days',
              })}
            </SectionHeading>
            {metricsQuery.isLoading ? (
              <SectionNote>{t('common.loading', { defaultValue: 'Loading…' })}</SectionNote>
            ) : metricsForbidden ? (
              // A 403, not a missing module. Attendance history is management
              // information about a colleague, so it is manager-only - say
              // that plainly rather than repeating the "not on this install"
              // line, which would be false to a team member whose manager can
              // see the very same section on the same deployment.
              <SectionNote>
                {t('projects.team.attendance_manager_only', {
                  defaultValue:
                    'Attendance history is only visible to managers. Their status and presence above are up to date.',
                })}
              </SectionNote>
            ) : !metrics ? (
              <SectionNote>
                {t('projects.team.attendance_unavailable', {
                  defaultValue: 'Attendance data is not available on this install.',
                })}
              </SectionNote>
            ) : attendance.length === 0 ? (
              <SectionNote>
                {t('projects.team.no_attendance', {
                  defaultValue: 'No sign-ins recorded for them in the last 7 days.',
                })}
              </SectionNote>
            ) : (
              <ul className="divide-y divide-border-light rounded-lg border border-border-light">
                {attendance.slice(0, 7).map((a) => (
                  <li
                    key={a.day}
                    className="flex items-center gap-2 px-2.5 py-1.5 text-xs"
                    data-testid="availability-attendance-row"
                  >
                    <span className="w-24 shrink-0 tabular-nums text-content-secondary">
                      {a.day}
                    </span>
                    <span className="flex-1 tabular-nums text-content-tertiary">
                      {formatClock(a.first_seen)} → {formatClock(a.last_seen)}
                    </span>
                    <span className="w-20 shrink-0 text-right tabular-nums text-content-primary">
                      {formatActiveSeconds(a.active_seconds)}
                    </span>
                    <span className="w-16 shrink-0 text-right">
                      {a.still_on ? (
                        <span className="text-2xs font-medium text-emerald-600 dark:text-emerald-400">
                          {t('projects.team.still_on', { defaultValue: 'Still on' })}
                        </span>
                      ) : null}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* ── 5. Departments ───────────────────────────────────────── */}
          <section>
            <SectionHeading icon={<Building2 size={13} />}>
              {t('projects.team.departments', { defaultValue: 'Departments' })}
            </SectionHeading>
            {departmentsQuery.isLoading ? (
              <SectionNote>{t('common.loading', { defaultValue: 'Loading…' })}</SectionNote>
            ) : !departmentsQuery.data ? (
              <SectionNote>
                {t('projects.team.departments_unavailable', {
                  defaultValue: 'Departments are not available on this install.',
                })}
              </SectionNote>
            ) : memberDepartments.length === 0 ? (
              <SectionNote>
                {t('projects.team.no_departments', {
                  defaultValue: 'They are not a member of any department.',
                })}
              </SectionNote>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {memberDepartments.map((d) => (
                  <span
                    key={d.key}
                    className="inline-flex items-center gap-1 rounded-full bg-surface-secondary px-2.5 py-0.5 text-2xs font-medium text-content-secondary"
                    data-testid="availability-department"
                  >
                    {d.name || d.key}
                    {d.lead_user_id === member.user_id ? (
                      <span className="text-oe-blue">
                        · {t('projects.team.lead', { defaultValue: 'Lead' })}
                      </span>
                    ) : null}
                  </span>
                ))}
              </div>
            )}
          </section>
        </div>

        {/* ── Footer ─────────────────────────────────────────────────── */}
        <div className="flex justify-end gap-2 border-t border-border-light px-4 py-2.5">
          <button
            type="button"
            onClick={() => navigate('/team-standup')}
            className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs text-content-secondary hover:bg-surface-secondary"
          >
            <ExternalLink size={12} />
            {t('projects.team.open_standup', { defaultValue: 'Open their tasks' })}
          </button>
          <button
            type="button"
            onClick={() =>
              navigate(`/work-requests?assignee=${encodeURIComponent(member.user_id)}`)
            }
            className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs text-content-secondary hover:bg-surface-secondary"
          >
            <ExternalLink size={12} />
            {t('projects.team.open_requests_page', { defaultValue: 'Open their requests' })}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
