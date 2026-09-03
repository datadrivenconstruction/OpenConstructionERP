// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * TeamAvailabilityWidget — the "Project team" tile on the project hub.
 *
 * The Team Strip answers "who is on this job". This tile answers the next
 * question: what are they doing this week? One card per member with the
 * avatar, name, role label and a live availability line:
 *
 *     ● Online now · On site · 3 open tasks · 4 days booked
 *
 * where each part comes from a different module and each part simply drops
 * out when its module has nothing to say (the tile never renders a zero it
 * cannot stand behind):
 *
 *   online dot       team-standup presence → presence/today online flag
 *   status           team-standup board    → today's entry status
 *   open task count  team-standup board    → tasks not in a done stage
 *   days booked      work-requests planner → days this week with allocation
 *
 * Clicking a card opens ``MemberAvailabilityModal``; right-clicking opens a
 * context menu (open availability, change role, jump to their tasks or
 * requests, remove from the project). Role change and removal are behind the
 * same ``canManage`` gate as the Team Strip's add button, which mirrors the
 * backend's owner-only guard.
 *
 * Sorting: online first, then by role group (project leadership → engineering
 * → workshop & site → commercial → external), then by name. So the people you
 * can actually reach right now sit at the top.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Users, Plus, ChevronRight } from 'lucide-react';
import { Card, Skeleton } from '@/shared/ui';
import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';
import {
  Avatar,
  AddMemberModal,
  type ProjectMember,
} from './TeamStrip';
import { groupedRoles, roleLabel, roleSortWeight } from './projectRoles';
import { MemberAvailabilityModal } from './MemberAvailabilityModal';
import {
  allocByDayFor,
  allocatedDayCount,
  isoDay,
  openTasksFor,
  standupStatusLabel,
  usePlannerForDepartments,
  usePresenceToday,
  useStandupBoard,
  useWorkRequestDepartments,
  weekDays,
} from './useTeamAvailability';

export interface TeamAvailabilityWidgetProps {
  projectId: string;
  /** Owner / admin gate — hides add, change-role and remove. */
  canManage?: boolean;
  /** Test seam: skips the members request. */
  initialMembers?: ProjectMember[];
}

interface MenuState {
  member: ProjectMember;
  x: number;
  y: number;
}

export function TeamAvailabilityWidget({
  projectId,
  canManage = true,
  initialMembers,
}: TeamAvailabilityWidgetProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [selected, setSelected] = useState<ProjectMember | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [addError, setAddError] = useState<string | undefined>();
  const [menu, setMenu] = useState<MenuState | null>(null);
  const [roleSubmenu, setRoleSubmenu] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  /* ── Members (shares the Team Strip's cache key) ───────────────────── */
  const { data: members = [], isLoading } = useQuery<ProjectMember[]>({
    queryKey: ['project-members', projectId],
    queryFn: () => apiGet<ProjectMember[]>(`/v1/projects/${projectId}/members/`),
    enabled: !!projectId && initialMembers === undefined,
    initialData: initialMembers,
    staleTime: 30_000,
  });

  /* ── Availability sources ──────────────────────────────────────────── */
  const today = useMemo(() => isoDay(new Date()), []);
  const days = useMemo(() => weekDays(new Date()), []);

  const boardQuery = useStandupBoard(today, !!projectId);
  // Presence, NOT the metrics rollup. Every part of this tile is something the
  // whole team may see - who is about, what they said they were doing, how
  // many tasks are open, how many days they are booked - and all four sources
  // are viewer-level. The manager-only rollup is not read here at all, so an
  // ordinary team member's tile is complete rather than half-blank.
  const presenceQuery = usePresenceToday(projectId, !!projectId);
  const departmentsQuery = useWorkRequestDepartments(!!projectId);

  // Every department, not only the ones project members belong to: people are
  // routinely assigned to a request raised on another department's board, and
  // filtering by membership dropped exactly those days. The availability popup
  // reads the same set, so the two surfaces can never disagree about the same
  // person's week. The queries are shared by key and cached for a minute.
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

  const board = boardQuery.data ?? null;
  const presence = presenceQuery.data ?? null;

  const onlineIds = useMemo(() => {
    const set = new Set<string>();
    for (const p of presence ?? []) if (p.online) set.add(p.user_id);
    return set;
  }, [presence]);

  const statusByUser = useMemo(() => {
    const map = new Map<string, string>();
    for (const e of board?.entries ?? []) map.set(e.user_id, e.status);
    return map;
  }, [board]);

  /** Members with their derived availability, sorted online-first. */
  const rows = useMemo(() => {
    const decorated = members.map((member) => {
      const alloc = allocByDayFor(planner.payloads, member.user_id, days);
      return {
        member,
        online: onlineIds.has(member.user_id),
        status: statusByUser.get(member.user_id) ?? '',
        openTasks: board ? openTasksFor(board, member.user_id).length : null,
        bookedDays: planner.payloads.length > 0 ? allocatedDayCount(alloc) : null,
      };
    });
    return decorated.sort((a, b) => {
      if (a.online !== b.online) return a.online ? -1 : 1;
      const weight = roleSortWeight(a.member.role) - roleSortWeight(b.member.role);
      if (weight !== 0) return weight;
      return (a.member.full_name || a.member.email).localeCompare(
        b.member.full_name || b.member.email,
      );
    });
  }, [members, planner.payloads, days, onlineIds, statusByUser, board]);

  /* ── Mutations ─────────────────────────────────────────────────────── */
  const invalidate = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['project-members', projectId] });
  }, [queryClient, projectId]);

  const addMutation = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: string }) =>
      apiPost<ProjectMember>(`/v1/projects/${projectId}/members/`, {
        user_id: userId,
        role,
      }),
    onSuccess: () => {
      invalidate();
      setAddOpen(false);
      setAddError(undefined);
    },
    onError: (err: unknown) => {
      setAddError(
        (err as { body?: { detail?: string } })?.body?.detail ??
          (err instanceof Error ? err.message : 'Failed to add member'),
      );
    },
  });

  const roleMutation = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: string }) =>
      apiPatch<ProjectMember>(`/v1/projects/${projectId}/members/${userId}/`, {
        role,
      }),
    onSuccess: invalidate,
  });

  const removeMutation = useMutation({
    mutationFn: (userId: string) =>
      apiDelete(`/v1/projects/${projectId}/members/${userId}/`),
    onSuccess: invalidate,
  });

  /* ── Context menu plumbing ─────────────────────────────────────────── */
  const closeMenu = useCallback(() => {
    setMenu(null);
    setRoleSubmenu(false);
  }, []);

  useEffect(() => {
    if (!menu) return undefined;
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) closeMenu();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeMenu();
    };
    window.addEventListener('mousedown', onDown);
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('mousedown', onDown);
      window.removeEventListener('keydown', onKey);
    };
  }, [menu, closeMenu]);

  const roleGroups = useMemo(() => groupedRoles(), []);

  /* ── Render ────────────────────────────────────────────────────────── */
  return (
    <Card padding="sm" className="flex h-full flex-col" data-testid="team-availability-widget">
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-1 items-start gap-2">
          <span className="mt-0.5 shrink-0 text-content-tertiary">
            <Users size={16} />
          </span>
          <div className="min-w-0 flex-1">
            <h3 className="truncate text-sm font-semibold text-content-primary">
              {t('project.widget.team-availability.title', {
                defaultValue: 'Project team',
              })}
            </h3>
            <p className="truncate text-2xs text-content-tertiary">
              {t('project.widget.team-availability.card_subtitle', {
                defaultValue: 'Who is on this job and what they are carrying',
              })}
            </p>
          </div>
        </div>
        {canManage && (
          <button
            type="button"
            onClick={() => setAddOpen(true)}
            className="inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-2xs font-medium text-oe-blue transition-colors hover:bg-oe-blue/10"
            data-testid="team-availability-add"
          >
            <Plus size={12} />
            {t('projects.team.add_member', { defaultValue: 'Add member' })}
          </button>
        )}
      </div>

      {isLoading && members.length === 0 ? (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} height={34} className="w-full" rounded="md" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <p className="py-2 text-center text-2xs text-content-quaternary">
          {t('projects.team.empty', { defaultValue: 'No members yet' })}
        </p>
      ) : (
        <ul className="-mx-1 divide-y divide-border-light" data-testid="team-availability-list">
          {rows.map(({ member, online, status, openTasks, bookedDays }) => (
            <li key={member.user_id}>
              <button
                type="button"
                onClick={() => setSelected(member)}
                onContextMenu={(e) => {
                  e.preventDefault();
                  setRoleSubmenu(false);
                  setMenu({ member, x: e.clientX, y: e.clientY });
                }}
                className="flex w-full items-center gap-2 rounded-md px-1 py-1.5 text-left transition-colors hover:bg-surface-secondary"
                data-testid="team-availability-card"
              >
                <span className="relative shrink-0">
                  <Avatar member={member} size={28} />
                  {online && (
                    <span
                      className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-surface-primary bg-emerald-500"
                      data-testid="team-availability-online-dot"
                      title={t('projects.team.online_now', { defaultValue: 'Online now' })}
                    />
                  )}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-baseline gap-1.5">
                    <span className="truncate text-xs font-medium text-content-primary">
                      {member.full_name || member.email}
                    </span>
                    <span className="shrink-0 truncate text-2xs text-content-tertiary">
                      {roleLabel(member.role)}
                    </span>
                  </span>
                  <span
                    className="block truncate text-2xs text-content-tertiary"
                    data-testid="team-availability-line"
                  >
                    {[
                      online
                        ? t('projects.team.online_now', { defaultValue: 'Online now' })
                        : null,
                      status ? standupStatusLabel(status) : null,
                      // Plural forms spelled out: "1 open tasks" in a line the
                      // PM reads every morning is the kind of small wrongness
                      // that makes the whole tile look unmaintained.
                      openTasks != null
                        ? t('projects.team.open_task_count', {
                            count: openTasks,
                            defaultValue: '{{count}} open task',
                            defaultValue_one: '{{count}} open task',
                            defaultValue_other: '{{count}} open tasks',
                          })
                        : null,
                      bookedDays != null
                        ? t('projects.team.booked_days', {
                            count: bookedDays,
                            defaultValue: '{{count}} day booked',
                            defaultValue_one: '{{count}} day booked',
                            defaultValue_other: '{{count}} days booked',
                          })
                        : null,
                    ]
                      .filter(Boolean)
                      .join(' · ') ||
                      t('projects.team.no_availability', {
                        defaultValue: 'No availability data',
                      })}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {/* ── Right-click menu ─────────────────────────────────────────────
          Portalled to <body>: this Card is inside an animated grid whose
          transform would otherwise become the containing block for the
          menu's `position: fixed`, pinning it inside the tile. */}
      {menu && createPortal(
        <div
          ref={menuRef}
          role="menu"
          data-testid="team-availability-menu"
          className="fixed z-[80] min-w-[13rem] rounded-lg border border-border-light bg-surface-elevated py-1 text-xs shadow-xl"
          style={{
            // Clamp to the viewport so a right-click near the edge doesn't
            // push the menu off-screen.
            left: Math.min(menu.x, (typeof window !== 'undefined' ? window.innerWidth : 1280) - 230),
            top: Math.min(menu.y, (typeof window !== 'undefined' ? window.innerHeight : 800) - 240),
          }}
        >
          <button
            type="button"
            role="menuitem"
            className="block w-full px-3 py-1.5 text-left text-content-primary hover:bg-surface-secondary"
            onClick={() => {
              setSelected(menu.member);
              closeMenu();
            }}
          >
            {t('projects.team.menu_availability', {
              defaultValue: 'Open availability',
            })}
          </button>
          {canManage && !menu.member.is_owner && (
            <div className="relative">
              <button
                type="button"
                role="menuitem"
                aria-haspopup="true"
                aria-expanded={roleSubmenu}
                className="flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-content-primary hover:bg-surface-secondary"
                onClick={() => setRoleSubmenu((v) => !v)}
                data-testid="team-availability-menu-role"
              >
                {t('projects.team.menu_change_role', { defaultValue: 'Change role' })}
                <ChevronRight size={12} className="text-content-tertiary" />
              </button>
              {roleSubmenu && (
                <div className="max-h-64 overflow-y-auto border-y border-border-light bg-surface-secondary/40 py-1">
                  {roleGroups.map((g) => (
                    <div key={g.key}>
                      <div className="px-3 pt-1 text-[10px] font-semibold uppercase tracking-wide text-content-quaternary">
                        {g.label}
                      </div>
                      {g.roles.map((r) => (
                        <button
                          key={r.key}
                          type="button"
                          role="menuitem"
                          className={[
                            'block w-full px-4 py-1 text-left hover:bg-surface-secondary',
                            r.key === menu.member.role
                              ? 'font-semibold text-oe-blue'
                              : 'text-content-secondary',
                          ].join(' ')}
                          onClick={() => {
                            if (r.key !== menu.member.role) {
                              roleMutation.mutate({
                                userId: menu.member.user_id,
                                role: r.key,
                              });
                            }
                            closeMenu();
                          }}
                        >
                          {r.label}
                        </button>
                      ))}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
          <button
            type="button"
            role="menuitem"
            className="block w-full px-3 py-1.5 text-left text-content-primary hover:bg-surface-secondary"
            onClick={() => {
              closeMenu();
              navigate('/team-standup');
            }}
          >
            {t('projects.team.menu_tasks', { defaultValue: 'Open their tasks' })}
          </button>
          <button
            type="button"
            role="menuitem"
            className="block w-full px-3 py-1.5 text-left text-content-primary hover:bg-surface-secondary"
            onClick={() => {
              const id = menu.member.user_id;
              closeMenu();
              navigate(`/work-requests?assignee=${encodeURIComponent(id)}`);
            }}
          >
            {t('projects.team.menu_requests', { defaultValue: 'Open their requests' })}
          </button>
          {canManage && !menu.member.is_owner && (
            <button
              type="button"
              role="menuitem"
              className="block w-full border-t border-border-light px-3 py-1.5 text-left text-semantic-error hover:bg-surface-secondary"
              onClick={() => {
                const id = menu.member.user_id;
                closeMenu();
                removeMutation.mutate(id);
              }}
              data-testid="team-availability-menu-remove"
            >
              {t('projects.team.menu_remove', {
                defaultValue: 'Remove from project',
              })}
            </button>
          )}
        </div>,
        document.body,
      )}

      {selected && (
        <MemberAvailabilityModal
          member={selected}
          projectId={projectId}
          onClose={() => setSelected(null)}
        />
      )}
      {addOpen && (
        <AddMemberModal
          onClose={() => {
            setAddOpen(false);
            setAddError(undefined);
          }}
          isSubmitting={addMutation.isPending}
          errorMessage={addError}
          onSubmit={(userId, role) => addMutation.mutate({ userId, role })}
        />
      )}
    </Card>
  );
}
