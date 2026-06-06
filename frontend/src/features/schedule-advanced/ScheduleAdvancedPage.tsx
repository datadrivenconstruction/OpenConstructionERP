import { useState, useMemo, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTabKeyboardNav } from '@/shared/hooks/useTabKeyboardNav';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  Calendar,
  LayoutGrid,
  Clock,
  ClipboardCheck,
  AlertCircle,
  GitBranch,
  Plus,
  Check,
  ArrowUpCircle,
  Trash2,
  Pencil,
  List as ListIcon,
  Table as TableIcon,
  GanttChart,
  Sparkles,
  PlayCircle,
  Download,
  AlertTriangle,
  Diamond,
  Search,
  X,
  Loader2,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  DismissibleInfo,
  RecoveryCard,
  SkeletonTable,
  WideModal,
  ConfirmDialog,
  InfoHint,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { PlanningCrossLinks } from '@/features/schedule/PlanningCrossLinks';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { getErrorMessage } from '@/shared/lib/api';
import { projectsApi } from '@/features/projects/api';
import {
  listMasterSchedules,
  createMasterSchedule,
  updateMasterSchedule,
  deleteMasterSchedule,
  listPhasePlans,
  createPhasePlan,
  updatePhasePlan,
  deletePhasePlan,
  applyPhaseTemplate,
  PHASE_TEMPLATES,
  pullPhase,
  startPhase,
  completePhase,
  listLookAheads,
  createLookAhead,
  publishLookAhead,
  listConstraints,
  createConstraint,
  clearConstraint,
  escalateConstraint,
  deleteConstraint,
  listWeeklyPlans,
  createWeeklyPlan,
  commitWeeklyPlan,
  closeWeeklyPlan,
  listCommitments,
  createCommitment,
  commitCommitment,
  completeCommitment,
  missCommitment,
  listBaselines,
  captureBaseline,
  baselineDelta,
  type MasterSchedule,
  type PhasePlan,
  type PhaseStatus,
  type LookAheadPlan,
  type Constraint,
  type ConstraintStatus,
  type WeeklyWorkPlan,
  type WeeklyStatus,
  type Commitment,
  type CommitmentStatus,
  type RNCCategory,
  type Baseline,
  type BaselineDeltaEntry,
  type ConstraintType,
  currentTasksForMaster,
} from './api';
import { fetchTasks, type Task } from '@/features/tasks/api';

const SCHEDULE_TAB_IDS = [
  'master',
  'phases',
  'look_ahead',
  'weekly',
  'constraints',
  'baselines',
] as const;
type Tab = (typeof SCHEDULE_TAB_IDS)[number];

const PHASE_VARIANT: Record<PhaseStatus, 'neutral' | 'blue' | 'success' | 'warning'> = {
  in_planning: 'neutral',
  pulled: 'blue',
  active: 'warning',
  completed: 'success',
};

const CONSTRAINT_VARIANT: Record<
  ConstraintStatus,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  open: 'warning',
  in_progress: 'blue',
  cleared: 'success',
  escalated: 'error',
  cannot_clear: 'error',
};

const COMMITMENT_VARIANT: Record<
  CommitmentStatus,
  'neutral' | 'blue' | 'success' | 'warning' | 'error'
> = {
  planned: 'neutral',
  committed: 'blue',
  in_progress: 'warning',
  completed: 'success',
  at_risk: 'warning',
  missed: 'error',
};

const WEEKLY_VARIANT: Record<WeeklyStatus, 'neutral' | 'blue' | 'success' | 'warning'> = {
  draft: 'neutral',
  committed: 'blue',
  in_progress: 'warning',
  closed: 'success',
};

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

const labelCls = 'block text-xs font-medium text-content-secondary mb-1';

/* ── helpers ─────────────────────────────────────────────────────────── */

function todayIso(offsetDays = 0): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return d.toISOString().slice(0, 10);
}

function pctNumber(value: string | number | null | undefined): number {
  if (value == null) return 0;
  const n = typeof value === 'string' ? Number(value) : value;
  if (Number.isNaN(n)) return 0;
  // Backend ppc_percent is always a 0-100 percentage (Numeric(5,2) from
  // compute_ppc, which already multiplies by 100). The old `n > 1 ? n
  // : n * 100` heuristic corrupted legitimate sub-1% values (a true
  // 1.00% PPC rendered as 100%). Just clamp into range.
  return Math.min(100, Math.max(0, n));
}

/* ── Task picker ─────────────────────────────────────────────────────────
 *
 * Last Planner commitments and constraints both link to a real project
 * task by its UUID (``task_ref``). The legacy UI made the user paste a
 * raw UUID into a free-text box, which is a hard data-island: there is no
 * way to know a task's id by hand. This picker loads the project's tasks
 * (fetchTasks by project) and lets the user search by title, emitting the
 * task UUID on select. Reused by both the Add-commitment and New-constraint
 * modals so the two flows stay consistent.
 */
function TaskPicker({
  projectId,
  value,
  onChange,
  autoFocus,
}: {
  projectId: string;
  value: string;
  /** Emits the selected task UUID (or '' when cleared). */
  onChange: (taskId: string) => void;
  autoFocus?: boolean;
}) {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const tasksQ = useQuery({
    queryKey: ['schedule-advanced', 'task-picker', projectId],
    queryFn: () => fetchTasks({ project_id: projectId }),
    enabled: !!projectId,
  });

  // Close on outside click.
  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, []);

  const tasks = tasksQ.data ?? [];
  const selected: Task | undefined = useMemo(
    () => tasks.find((tk) => tk.id === value),
    [tasks, value],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const base = q
      ? tasks.filter(
          (tk) =>
            tk.title.toLowerCase().includes(q) ||
            tk.id.toLowerCase().startsWith(q),
        )
      : tasks;
    return base.slice(0, 50);
  }, [tasks, query]);

  const statusVariant: Record<Task['status'], string> = {
    draft: 'text-content-tertiary',
    open: 'text-oe-blue',
    in_progress: 'text-amber-600 dark:text-amber-400',
    completed: 'text-emerald-600 dark:text-emerald-400',
  };

  return (
    <div ref={containerRef} className="relative">
      <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-content-tertiary">
        <Search size={14} />
      </div>
      <input
        type="text"
        value={open ? query : selected ? selected.title : query}
        onChange={(e) => {
          setQuery(e.target.value);
          if (value) onChange('');
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        autoFocus={autoFocus}
        className={clsx(inputCls, 'pl-9', value && 'pr-8')}
        placeholder={t('schedule_advanced.task_picker_placeholder', {
          defaultValue: 'Search project tasks…',
        })}
        role="combobox"
        aria-expanded={open}
        aria-controls="task-picker-list"
      />
      {value && (
        <button
          type="button"
          onClick={() => {
            onChange('');
            setQuery('');
          }}
          aria-label={t('common.clear', { defaultValue: 'Clear' })}
          className="absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary hover:text-content-primary"
        >
          <X size={14} />
        </button>
      )}
      {open && (
        <div
          id="task-picker-list"
          role="listbox"
          className="absolute left-0 top-full z-50 mt-1 max-h-56 w-full overflow-y-auto rounded-lg border border-border-light bg-surface-elevated shadow-md"
        >
          {tasksQ.isLoading ? (
            <div className="flex items-center justify-center gap-2 px-3 py-3 text-xs text-content-tertiary">
              <Loader2 size={14} className="animate-spin" />
              {t('common.loading', { defaultValue: 'Loading...' })}
            </div>
          ) : tasksQ.isError ? (
            <div className="px-3 py-3 text-xs text-semantic-error">
              {t('schedule_advanced.task_picker_error', {
                defaultValue: 'Could not load tasks.',
              })}
            </div>
          ) : filtered.length === 0 ? (
            <div className="px-3 py-3 text-xs text-content-tertiary">
              {tasks.length === 0
                ? t('schedule_advanced.task_picker_none', {
                    defaultValue: 'No tasks in this project yet.',
                  })
                : t('schedule_advanced.task_picker_no_match', {
                    defaultValue: 'No tasks match your search.',
                  })}
            </div>
          ) : (
            filtered.map((tk) => (
              <button
                key={tk.id}
                type="button"
                role="option"
                aria-selected={tk.id === value}
                onClick={() => {
                  onChange(tk.id);
                  setQuery('');
                  setOpen(false);
                }}
                className={clsx(
                  'flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors hover:bg-surface-secondary',
                  tk.id === value && 'bg-oe-blue-subtle/40',
                )}
              >
                <span className="min-w-0 flex-1 truncate text-content-primary">{tk.title}</span>
                <span className={clsx('shrink-0 text-2xs capitalize', statusVariant[tk.status])}>
                  {tk.status.replace('_', ' ')}
                </span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

/* ── Page ────────────────────────────────────────────────────────────── */

export function ScheduleAdvancedPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>('master');
  // Arrow-key navigation across the schedule advanced tab strip (WCAG 2.1.1).
  const onTabKeyDown = useTabKeyboardNav<Tab>({
    ids: SCHEDULE_TAB_IDS,
    activeId: tab,
    onChange: setTab,
    orientation: 'horizontal',
  });
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const [projectId, setProjectId] = useState<string>('');
  const [masterId, setMasterId] = useState<string>('');
  const [lookAheadId, setLookAheadId] = useState<string>('');
  const [weekPlanId, setWeekPlanId] = useState<string>('');
  const [constraintFilter, setConstraintFilter] = useState<string>('');
  const [createMaster, setCreateMaster] = useState(false);
  const [editMaster, setEditMaster] = useState<MasterSchedule | null>(null);
  const [deleteMaster, setDeleteMaster] = useState<MasterSchedule | null>(null);
  const [createWeek, setCreateWeek] = useState(false);
  const [createLA, setCreateLA] = useState(false);
  const [createBaselineOpen, setCreateBaselineOpen] = useState(false);

  const projectsQ = useQuery({
    queryKey: ['projects-list-for-schedule'],
    queryFn: () => projectsApi.list(),
  });

  // Project selection lives in the global top-bar selector. Follow the
  // active project; fall back to the first project only when nothing is
  // active yet. Reset dependent selections whenever the project changes.
  useEffect(() => {
    const next = activeProjectId || projectsQ.data?.[0]?.id || '';
    if (!next || next === projectId) return;
    setProjectId(next);
    setMasterId('');
    setLookAheadId('');
    setWeekPlanId('');
  }, [activeProjectId, projectsQ.data, projectId]);

  const masterQ = useQuery({
    queryKey: ['schedule-advanced', 'master', projectId],
    queryFn: () => listMasterSchedules({ project_id: projectId, limit: 100 }),
    enabled: !!projectId,
  });

  // Auto-select first master once loaded
  useEffect(() => {
    if (!masterId && masterQ.data && masterQ.data.length > 0) {
      const first = masterQ.data[0];
      if (first) setMasterId(first.id);
    }
  }, [masterId, masterQ.data]);

  const phasesQ = useQuery({
    queryKey: ['schedule-advanced', 'phases', masterId],
    queryFn: () => listPhasePlans(masterId),
    enabled: !!masterId && tab === 'phases',
  });

  const lookAheadsQ = useQuery({
    queryKey: ['schedule-advanced', 'look-aheads', masterId],
    queryFn: () => listLookAheads(masterId),
    enabled: !!masterId && (tab === 'look_ahead' || tab === 'constraints'),
  });

  useEffect(() => {
    if (
      !lookAheadId &&
      lookAheadsQ.data &&
      lookAheadsQ.data.length > 0
    ) {
      const first = lookAheadsQ.data[0];
      if (first) setLookAheadId(first.id);
    }
  }, [lookAheadId, lookAheadsQ.data]);

  const constraintsQ = useQuery({
    queryKey: ['schedule-advanced', 'constraints', lookAheadId],
    queryFn: () => listConstraints(lookAheadId),
    enabled: !!lookAheadId && tab === 'constraints',
  });

  const weeklyQ = useQuery({
    queryKey: ['schedule-advanced', 'weekly', masterId],
    queryFn: () => listWeeklyPlans(masterId, 52),
    enabled: !!masterId && tab === 'weekly',
  });

  useEffect(() => {
    if (!weekPlanId && weeklyQ.data && weeklyQ.data.length > 0) {
      const first = weeklyQ.data[0];
      if (first) setWeekPlanId(first.id);
    }
  }, [weekPlanId, weeklyQ.data]);

  const commitmentsQ = useQuery({
    queryKey: ['schedule-advanced', 'commitments', weekPlanId],
    queryFn: () => listCommitments(weekPlanId),
    enabled: !!weekPlanId && tab === 'weekly',
  });

  const baselinesQ = useQuery({
    queryKey: ['schedule-advanced', 'baselines', masterId],
    queryFn: () => listBaselines(masterId),
    enabled: !!masterId && tab === 'baselines',
  });

  const filteredConstraints = useMemo(() => {
    const items = constraintsQ.data ?? [];
    if (!constraintFilter) return items;
    return items.filter((c) => c.status === constraintFilter);
  }, [constraintsQ.data, constraintFilter]);

  const currentMaster: MasterSchedule | undefined = useMemo(
    () => (masterQ.data ?? []).find((m) => m.id === masterId),
    [masterQ.data, masterId],
  );

  const currentWeek: WeeklyWorkPlan | undefined = useMemo(
    () => (weeklyQ.data ?? []).find((w) => w.id === weekPlanId),
    [weeklyQ.data, weekPlanId],
  );

  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const deleteMasterMut = useMutation({
    mutationFn: (id: string) => deleteMasterSchedule(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({
        queryKey: ['schedule-advanced', 'master', projectId],
      });
      // If the deleted master was the active selection, drop every
      // dependent selection so child tabs don't query a dangling parent.
      if (id === masterId) {
        setMasterId('');
        setLookAheadId('');
        setWeekPlanId('');
      }
      setDeleteMaster(null);
      addToast({
        type: 'success',
        title: t('schedule_advanced.master_deleted', {
          defaultValue: 'Master schedule deleted',
        }),
      });
    },
    onError: (err) => {
      setDeleteMaster(null);
      addToast({ type: 'error', title: getErrorMessage(err) });
    },
  });

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          {
            label: t('nav.schedule_advanced', {
              defaultValue: 'Last Planner / CPM',
            }),
          },
        ]}
      />

      <PageHeader
        srTitle={t('nav.schedule_advanced', { defaultValue: 'Last Planner / CPM' })}
        subtitle={t('schedule_advanced.subtitle', {
          defaultValue:
            'Pull-planning, lookaheads, weekly commitments, constraints and baselines.',
        })}
        actions={
          <Button
            variant="primary"
            icon={<Plus size={14} />}
            onClick={() => setCreateMaster(true)}
            disabled={!projectId}
          >
            {t('schedule_advanced.new_master', { defaultValue: 'New Master Schedule' })}
          </Button>
        }
      />

      <DismissibleInfo
        storageKey="schedule-advanced"
        title={t('schedule_advanced.intro_title', {
          defaultValue: 'Keep the weekly promises the plan depends on',
        })}
        links={[
          { label: t('schedule_advanced.intro_link_schedule', { defaultValue: '4D Schedule' }), onClick: () => navigate('/schedule') },
          { label: t('schedule_advanced.intro_link_takt', { defaultValue: 'Takt planning' }), onClick: () => navigate('/takt') },
        ]}
      >
        {t('schedule_advanced.intro_body', {
          defaultValue:
            'Builds the Last Planner stack on top of a master schedule: break the project into phases, roll a six-week look-ahead to clear constraints, and capture weekly commitments from trade foremen. Missed commitments record a reason for non-completion that feeds root-cause analysis, and baselines track variance against the plan.',
        })}
      </DismissibleInfo>

      {/* Cross-module navigation — connects the planning value chain */}
      <PlanningCrossLinks active="schedule-advanced" />

      {/* Tabs */}
      <div className="border-b border-border-light">
        <nav
          className="flex gap-1 -mb-px overflow-x-auto"
          role="tablist"
          aria-label={t('schedule_advanced.tabs_aria', {
            defaultValue: 'Schedule sections',
          })}
          onKeyDown={onTabKeyDown}
        >
          {(
            [
              { id: 'master', label: t('schedule_advanced.tab_master', { defaultValue: 'Master' }), icon: Calendar },
              { id: 'phases', label: t('schedule_advanced.tab_phases', { defaultValue: 'Phase Plans' }), icon: LayoutGrid },
              { id: 'look_ahead', label: t('schedule_advanced.tab_look_ahead', { defaultValue: 'Look-Ahead' }), icon: Clock },
              { id: 'weekly', label: t('schedule_advanced.tab_weekly', { defaultValue: 'Weekly Plan' }), icon: ClipboardCheck },
              { id: 'constraints', label: t('schedule_advanced.tab_constraints', { defaultValue: 'Constraints' }), icon: AlertCircle },
              { id: 'baselines', label: t('schedule_advanced.tab_baselines', { defaultValue: 'Baselines' }), icon: GitBranch },
            ] as { id: Tab; label: string; icon: React.ElementType }[]
          ).map((it) => {
            const Icon = it.icon;
            const isActive = tab === it.id;
            return (
              <button
                key={it.id}
                type="button"
                role="tab"
                id={`sched-tab-${it.id}`}
                aria-selected={isActive}
                aria-controls={`sched-panel-${it.id}`}
                tabIndex={isActive ? 0 : -1}
                onClick={() => setTab(it.id)}
                className={clsx(
                  'flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap',
                  isActive
                    ? 'border-oe-blue text-oe-blue'
                    : 'border-transparent text-content-secondary hover:text-content-primary',
                )}
              >
                <Icon size={14} />
                {it.label}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Empty state when no project */}
      {!projectId ? (
        <Card>
          {projectsQ.isLoading ? (
            <SkeletonTable rows={6} columns={3} />
          ) : projectsQ.isError ? (
            <RecoveryCard error={projectsQ.error} onRetry={() => projectsQ.refetch()} />
          ) : (
            <RequiresProject
              emptyHint={t('schedule_advanced.no_project_desc', {
                defaultValue: 'Create a project first to start pull-planning.',
              })}
            >
              {null}
            </RequiresProject>
          )}
        </Card>
      ) : tab === 'master' ? (
        <MasterTab
          masters={masterQ.data ?? []}
          loading={masterQ.isLoading}
          isError={masterQ.isError}
          onRetry={() => masterQ.refetch()}
          masterId={masterId}
          onSelect={setMasterId}
          onCreate={() => setCreateMaster(true)}
          onEdit={setEditMaster}
          onDelete={setDeleteMaster}
          current={currentMaster}
        />
      ) : !masterId ? (
        <Card>
          <EmptyState
            icon={<Calendar size={22} />}
            title={t('schedule_advanced.no_master', { defaultValue: 'No master schedule yet' })}
            description={t('schedule_advanced.no_master_desc', {
              defaultValue: 'Create a master schedule on the Master tab first.',
            })}
            action={{
              label: t('schedule_advanced.create_master', { defaultValue: 'Create Master' }),
              onClick: () => {
                setTab('master');
                setCreateMaster(true);
              },
            }}
          />
        </Card>
      ) : tab === 'phases' ? (
        <PhasesTab
          phases={phasesQ.data ?? []}
          loading={phasesQ.isLoading}
          isError={phasesQ.isError}
          onRetry={() => phasesQ.refetch()}
          masterId={masterId}
        />
      ) : tab === 'look_ahead' ? (
        <LookAheadTab
          lookAheads={lookAheadsQ.data ?? []}
          loading={lookAheadsQ.isLoading}
          isError={lookAheadsQ.isError}
          onRetry={() => lookAheadsQ.refetch()}
          lookAheadId={lookAheadId}
          onSelect={setLookAheadId}
          onCreate={() => setCreateLA(true)}
        />
      ) : tab === 'weekly' ? (
        <WeeklyTab
          projectId={projectId}
          plans={weeklyQ.data ?? []}
          loading={weeklyQ.isLoading}
          isError={weeklyQ.isError}
          onRetry={() => weeklyQ.refetch()}
          weekPlanId={weekPlanId}
          onSelect={setWeekPlanId}
          commitments={commitmentsQ.data ?? []}
          commitmentsLoading={commitmentsQ.isLoading}
          commitmentsError={commitmentsQ.isError}
          onRetryCommitments={() => commitmentsQ.refetch()}
          currentWeek={currentWeek}
          onCreate={() => setCreateWeek(true)}
        />
      ) : tab === 'constraints' ? (
        <ConstraintsTab
          projectId={projectId}
          lookAheads={lookAheadsQ.data ?? []}
          lookAheadId={lookAheadId}
          onSelectLA={setLookAheadId}
          constraints={filteredConstraints}
          loading={constraintsQ.isLoading}
          isError={constraintsQ.isError}
          onRetry={() => constraintsQ.refetch()}
          filter={constraintFilter}
          onFilter={setConstraintFilter}
        />
      ) : (
        <BaselinesTab
          masterId={masterId}
          baselines={baselinesQ.data ?? []}
          loading={baselinesQ.isLoading}
          isError={baselinesQ.isError}
          onRetry={() => baselinesQ.refetch()}
          onCapture={() => setCreateBaselineOpen(true)}
        />
      )}

      {/* Modals */}
      {createMaster && projectId && (
        <MasterFormModal
          projectId={projectId}
          onClose={() => setCreateMaster(false)}
        />
      )}
      {editMaster && (
        <MasterFormModal
          projectId={editMaster.project_id}
          master={editMaster}
          onClose={() => setEditMaster(null)}
        />
      )}
      <ConfirmDialog
        open={!!deleteMaster}
        title={t('schedule_advanced.delete_master_title', {
          defaultValue: 'Delete master schedule?',
        })}
        message={
          deleteMaster
            ? t('schedule_advanced.delete_master_message', {
                name: deleteMaster.name,
                defaultValue:
                  '"{{name}}" and everything under it - phase plans, look-aheads, weekly work plans, commitments and baselines - will be permanently deleted. This cannot be undone.',
              })
            : ''
        }
        onConfirm={() =>
          deleteMaster && deleteMasterMut.mutate(deleteMaster.id)
        }
        onCancel={() => setDeleteMaster(null)}
        loading={deleteMasterMut.isPending}
      />
      {createWeek && masterId && (
        <CreateWeeklyModal
          masterId={masterId}
          onClose={() => setCreateWeek(false)}
        />
      )}
      {createLA && masterId && (
        <CreateLookAheadModal
          masterId={masterId}
          onClose={() => setCreateLA(false)}
        />
      )}
      {createBaselineOpen && masterId && (
        <CreateBaselineModal
          masterId={masterId}
          onClose={() => setCreateBaselineOpen(false)}
        />
      )}
    </div>
  );
}

/* ── Master tab ──────────────────────────────────────────────────────── */

function MasterTab({
  masters,
  loading,
  isError,
  onRetry,
  masterId,
  onSelect,
  onCreate,
  onEdit,
  onDelete,
  current,
}: {
  masters: MasterSchedule[];
  loading: boolean;
  isError?: boolean;
  onRetry?: () => void;
  masterId: string;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onEdit: (m: MasterSchedule) => void;
  onDelete: (m: MasterSchedule) => void;
  current: MasterSchedule | undefined;
}) {
  const { t } = useTranslation();
  if (loading) {
    return (
      <Card padding="md">
        <SkeletonTable rows={4} columns={3} />
      </Card>
    );
  }
  if (isError) {
    return <ErrorCard onRetry={onRetry} />;
  }
  if (masters.length === 0) {
    return (
      <Card>
        <EmptyState
          icon={<Calendar size={22} />}
          title={t('schedule_advanced.no_master_yet', { defaultValue: 'No master schedule yet' })}
          description={t('schedule_advanced.no_master_yet_desc', {
            defaultValue:
              'The master schedule is the top-level plan that every phase plan, look-ahead and weekly work plan rolls up to. Create one to start pull-planning - you can rename it, change its dates, or delete it at any time.',
          })}
          action={{
            label: t('schedule_advanced.create_master', { defaultValue: 'Create Master' }),
            onClick: onCreate,
          }}
        />
      </Card>
    );
  }
  return (
    <div className="space-y-4">
      <InfoHint
        text={t('schedule_advanced.master_hint', {
          defaultValue:
            'Select a master schedule to make it the working plan for the Phases, Look-Ahead, Weekly and Constraints tabs. Use the row actions to rename it, change its planned dates and status, or delete it.',
        })}
      />

      <div className="flex justify-end">
        <Button
          variant="primary"
          size="sm"
          icon={<Plus size={14} />}
          onClick={onCreate}
        >
          {t('schedule_advanced.create_master', { defaultValue: 'Create Master' })}
        </Button>
      </div>

      <Card padding="none">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
              <tr>
                <th className="px-4 py-2.5 text-left">{t('common.name')}</th>
                <th className="px-4 py-2.5 text-left">{t('schedule_advanced.planned_start', { defaultValue: 'Planned start' })}</th>
                <th className="px-4 py-2.5 text-left">{t('schedule_advanced.planned_finish', { defaultValue: 'Planned finish' })}</th>
                <th className="px-4 py-2.5 text-left">{t('common.status', { defaultValue: 'Status' })}</th>
                <th className="px-4 py-2.5 text-right">{t('common.actions', { defaultValue: 'Actions' })}</th>
              </tr>
            </thead>
            <tbody>
              {masters.map((m) => {
                const selected = m.id === masterId;
                return (
                  <tr
                    key={m.id}
                    onClick={() => onSelect(m.id)}
                    className={clsx(
                      'border-t border-border-light hover:bg-surface-secondary cursor-pointer',
                      selected && 'bg-oe-blue-subtle/30',
                    )}
                  >
                    <td className="px-4 py-2 font-medium">
                      <span className="flex items-center gap-2">
                        <span
                          className={clsx(
                            'inline-block h-1.5 w-1.5 shrink-0 rounded-full',
                            selected ? 'bg-oe-blue' : 'bg-transparent',
                          )}
                          aria-hidden
                        />
                        <span className="truncate" title={m.name}>{m.name}</span>
                        {selected && (
                          <Badge variant="blue">
                            {t('schedule_advanced.active_selection', { defaultValue: 'Working plan' })}
                          </Badge>
                        )}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-content-secondary text-xs">
                      {m.planned_start ? <DateDisplay value={m.planned_start} /> : '—'}
                    </td>
                    <td className="px-4 py-2 text-content-secondary text-xs">
                      {m.planned_finish ? <DateDisplay value={m.planned_finish} /> : '—'}
                    </td>
                    <td className="px-4 py-2">
                      <Badge variant={m.status === 'active' ? 'success' : 'neutral'} dot>
                        {t(`schedule_advanced.master_status.${m.status}`, { defaultValue: m.status })}
                      </Badge>
                    </td>
                    <td className="px-4 py-2">
                      <div className="flex justify-end gap-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          icon={<Pencil size={12} />}
                          onClick={(e) => {
                            e.stopPropagation();
                            onEdit(m);
                          }}
                          aria-label={t('common.edit', { defaultValue: 'Edit' })}
                        />
                        <Button
                          size="sm"
                          variant="ghost"
                          icon={<Trash2 size={12} />}
                          onClick={(e) => {
                            e.stopPropagation();
                            onDelete(m);
                          }}
                          aria-label={t('common.delete', { defaultValue: 'Delete' })}
                        />
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      {current && (
        <Card padding="md">
          <h3 className="text-base font-semibold mb-3">
            {t('schedule_advanced.summary', { defaultValue: 'Summary' })}
          </h3>
          <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <Stat
              label={t('schedule_advanced.planned_start', { defaultValue: 'Planned start' })}
              value={current.planned_start ? <DateDisplay value={current.planned_start} /> : '—'}
            />
            <Stat
              label={t('schedule_advanced.planned_finish', { defaultValue: 'Planned finish' })}
              value={current.planned_finish ? <DateDisplay value={current.planned_finish} /> : '—'}
            />
            <Stat
              label={t('schedule_advanced.baseline_date', { defaultValue: 'Baseline date' })}
              value={current.baseline_date ? <DateDisplay value={current.baseline_date} /> : '—'}
            />
            <Stat
              label={t('common.status', { defaultValue: 'Status' })}
              value={<Badge variant={current.status === 'active' ? 'success' : 'neutral'} dot>{current.status}</Badge>}
            />
          </dl>
          {current.notes && (
            <p className="mt-4 text-sm text-content-secondary whitespace-pre-wrap">
              {current.notes}
            </p>
          )}
        </Card>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-content-tertiary">
        {label}
      </dt>
      <dd className="mt-0.5 text-sm text-content-primary">{value}</dd>
    </div>
  );
}

/* Shared failed-query surface — a failed fetch must NOT masquerade as an
 * empty success. Routes through RecoveryCard so 401/403 get the correct
 * sign-in / request-access CTA instead of a generic retry. */
function ErrorCard({ onRetry, error }: { onRetry?: () => void; error?: unknown }) {
  return (
    <Card className="py-12">
      <RecoveryCard error={error} onRetry={onRetry} />
    </Card>
  );
}

/* ── Phase plans tab (fully built out — replaces v3.0.x placeholder) ──── */

type PhasesView = 'cards' | 'table' | 'timeline';

function phasePercent(p: PhasePlan): number {
  if (p.pulled_status === 'completed') return 100;
  if (p.pulled_status === 'in_planning') return 0;
  if (p.pulled_status === 'pulled') return 10;
  if (!p.planned_start || !p.planned_finish) return 50;
  const s = new Date(p.planned_start).getTime();
  const f = new Date(p.planned_finish).getTime();
  const now = Date.now();
  if (f <= s) return 50;
  const pct = ((now - s) / (f - s)) * 100;
  return Math.max(15, Math.min(95, Math.round(pct)));
}

function phaseDurationDays(p: PhasePlan): number | null {
  if (!p.planned_start || !p.planned_finish) return null;
  const s = new Date(p.planned_start).getTime();
  const f = new Date(p.planned_finish).getTime();
  const days = Math.round((f - s) / 86_400_000);
  return days >= 0 ? days : null;
}

function isPhaseDelayed(p: PhasePlan): boolean {
  if (!p.planned_finish) return false;
  if (p.pulled_status === 'completed') return false;
  return new Date(p.planned_finish).getTime() < Date.now();
}

/**
 * A phase is treated as a milestone (diamond glyph) when start == finish.
 * Zero-duration phases happen naturally for gates / inspections / TOCs.
 */
function isPhaseMilestone(p: PhasePlan): boolean {
  if (!p.planned_start || !p.planned_finish) return false;
  return p.planned_start === p.planned_finish;
}

/**
 * Look-ahead horizon in weeks. ``null`` means show everything (default).
 * The Gantt and card grid both honour this filter so the foreman can
 * focus on near-term work instead of scrolling through years.
 */
type LookAheadHorizon = null | 1 | 2 | 4;

function withinHorizon(p: PhasePlan, horizon: LookAheadHorizon): boolean {
  if (horizon == null) return true;
  if (!p.planned_start) return true; // undated rows always pass — don't hide them
  const start = new Date(p.planned_start).getTime();
  const cutoff = Date.now() + horizon * 7 * 86_400_000;
  return start <= cutoff;
}

/**
 * Crude critical-path heuristic for the LPS Phase Plans view. We don't
 * have explicit predecessors here (those live in the proper CPM module
 * on /schedule), so we mark a phase as "on the critical path" when:
 *   - it is currently delayed (planned_finish < today, not completed), OR
 *   - it sits on the longest chronological chain of phases (the longest
 *     contiguous span — what would drive the project finish in a simple
 *     FS-only network).
 *
 * This is intentionally additive: the real CPM lives in /schedule. This
 * helper gives the foreman a visual cue without overstating accuracy.
 */
function computeCriticalPhaseIds(phases: PhasePlan[]): Set<string> {
  const out = new Set<string>();
  for (const p of phases) {
    if (isPhaseDelayed(p)) out.add(p.id);
  }
  // Longest dated span = candidate critical chain.
  const dated = phases.filter((p) => p.planned_start && p.planned_finish);
  if (dated.length > 0) {
    const sorted = [...dated].sort((a, b) => {
      const da = phaseDurationDays(a) ?? 0;
      const db = phaseDurationDays(b) ?? 0;
      return db - da;
    });
    const longest = sorted[0];
    if (longest) out.add(longest.id);
  }
  return out;
}

/**
 * Variance vs baseline for one phase. Returns delta in days
 * (positive = late, negative = early), or ``null`` when the phase
 * isn't in the snapshot (e.g. created after capture).
 */
function phaseVarianceDays(
  phase: PhasePlan,
  deltas: BaselineDeltaEntry[] | null | undefined,
): number | null {
  if (!deltas || deltas.length === 0) return null;
  const hit = deltas.find((d) => d.task_ref === phase.id);
  if (!hit) return null;
  if (typeof hit.schedule_variance_days !== 'number') return null;
  return hit.schedule_variance_days;
}

function VarianceBadge({ days }: { days: number | null }) {
  if (days == null) return null;
  if (days === 0) {
    return (
      <span
        className="inline-flex items-center rounded-md bg-surface-secondary px-1.5 py-px text-2xs font-medium text-content-tertiary tabular-nums"
        data-testid="phase-variance-onplan"
        title="On plan vs baseline"
      >
        ±0d
      </span>
    );
  }
  const positive = days > 0;
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded-md px-1.5 py-px text-2xs font-medium tabular-nums',
        positive
          ? 'bg-rose-500/15 text-rose-700 dark:text-rose-300'
          : 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300',
      )}
      data-testid={positive ? 'phase-variance-late' : 'phase-variance-early'}
      title={positive ? 'Slipped vs baseline' : 'Ahead of baseline'}
    >
      {positive ? '+' : ''}
      {days}d
    </span>
  );
}

function PhasesTab({
  phases,
  loading,
  isError,
  onRetry,
  masterId,
}: {
  phases: PhasePlan[];
  loading: boolean;
  isError?: boolean;
  onRetry?: () => void;
  masterId: string;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [view, setView] = useState<PhasesView>('cards');
  const [statusFilter, setStatusFilter] = useState<PhaseStatus | ''>('');
  const [createOpen, setCreateOpen] = useState(false);
  const [editPhase, setEditPhase] = useState<PhasePlan | null>(null);
  const [deletePhase, setDeletePhase] = useState<PhasePlan | null>(null);
  const [templateOpen, setTemplateOpen] = useState(false);
  const [horizon, setHorizon] = useState<LookAheadHorizon>(null);

  // Pull the active baseline (if any) and compute deltas vs the current
  // phases so we can render +5d / −2d variance badges in-line. Failure
  // is silent — variance is a nice-to-have, not a blocker for the page.
  const baselinesQ = useQuery({
    queryKey: ['schedule-advanced', 'baselines', masterId],
    queryFn: () => listBaselines(masterId),
    enabled: !!masterId,
  });
  const activeBaseline = useMemo(
    () => (baselinesQ.data ?? []).find((b) => b.status === 'active'),
    [baselinesQ.data],
  );
  const baselineDeltaQ = useQuery({
    queryKey: ['schedule-advanced', 'baseline-delta', activeBaseline?.id, masterId],
    queryFn: async () => {
      if (!activeBaseline || !masterId) return null;
      const current = await currentTasksForMaster(masterId);
      return baselineDelta(activeBaseline.id, current);
    },
    enabled: !!activeBaseline && !!masterId,
  });
  const deltas: BaselineDeltaEntry[] = baselineDeltaQ.data?.entries ?? [];

  const filtered = useMemo(() => {
    let arr = phases;
    if (statusFilter) arr = arr.filter((p) => p.pulled_status === statusFilter);
    if (horizon != null) arr = arr.filter((p) => withinHorizon(p, horizon));
    return arr;
  }, [phases, statusFilter, horizon]);

  const criticalIds = useMemo(() => computeCriticalPhaseIds(phases), [phases]);

  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ['schedule-advanced', 'phases', masterId] });

  const pullMut = useMutation({
    mutationFn: (id: string) => pullPhase(id),
    onSuccess: () => {
      invalidate();
      addToast({ type: 'success', title: t('schedule_advanced.phase_pulled', { defaultValue: 'Phase pulled' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const startMut = useMutation({
    mutationFn: (id: string) => startPhase(id),
    onSuccess: () => {
      invalidate();
      addToast({ type: 'success', title: t('schedule_advanced.phase_started', { defaultValue: 'Phase started' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const completeMut = useMutation({
    mutationFn: (id: string) => completePhase(id),
    onSuccess: () => {
      invalidate();
      addToast({ type: 'success', title: t('schedule_advanced.phase_completed', { defaultValue: 'Phase completed' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const deleteMut = useMutation({
    mutationFn: (id: string) => deletePhasePlan(id),
    onSuccess: () => {
      invalidate();
      setDeletePhase(null);
      addToast({ type: 'success', title: t('schedule_advanced.phase_deleted', { defaultValue: 'Phase deleted' }) });
    },
    onError: (err) => {
      setDeletePhase(null);
      addToast({ type: 'error', title: getErrorMessage(err) });
    },
  });

  if (loading) {
    return (
      <Card padding="md">
        <SkeletonTable rows={4} columns={5} />
      </Card>
    );
  }

  if (isError) {
    return <ErrorCard onRetry={onRetry} />;
  }

  if (phases.length === 0) {
    return (
      <>
        <Card>
          <EmptyState
            icon={<LayoutGrid size={22} />}
            title={t('schedule_advanced.no_phases', { defaultValue: 'No phase plans yet' })}
            description={t('schedule_advanced.no_phases_desc', {
              defaultValue:
                'Phase plans break the project into high-level construction phases (foundation, structure, MEP, finishes…) so weekly commitments can roll up to a milestone target.',
            })}
            action={{
              label: t('schedule_advanced.create_phase', { defaultValue: 'New phase' }),
              onClick: () => setCreateOpen(true),
            }}
          />
          <div className="-mt-4 flex justify-center pb-6">
            <Button
              variant="ghost"
              size="sm"
              icon={<Sparkles size={14} />}
              onClick={() => setTemplateOpen(true)}
            >
              {t('schedule_advanced.use_template', { defaultValue: 'Use a template' })}
            </Button>
          </div>
        </Card>
        {createOpen && (
          <PhaseFormModal
            masterId={masterId}
            onClose={() => setCreateOpen(false)}
            onSaved={invalidate}
          />
        )}
        {templateOpen && (
          <PhaseTemplateModal
            masterId={masterId}
            onClose={() => setTemplateOpen(false)}
            onSaved={invalidate}
          />
        )}
      </>
    );
  }

  const counts: Record<PhaseStatus | 'all', number> = {
    all: phases.length,
    in_planning: phases.filter((p) => p.pulled_status === 'in_planning').length,
    pulled: phases.filter((p) => p.pulled_status === 'pulled').length,
    active: phases.filter((p) => p.pulled_status === 'active').length,
    completed: phases.filter((p) => p.pulled_status === 'completed').length,
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <FilterChip
            label={t('common.all', { defaultValue: 'All' })}
            count={counts.all}
            active={statusFilter === ''}
            onClick={() => setStatusFilter('')}
          />
          <FilterChip
            label={t('schedule_advanced.phase_status.in_planning', { defaultValue: 'In planning' })}
            count={counts.in_planning}
            active={statusFilter === 'in_planning'}
            onClick={() => setStatusFilter('in_planning')}
          />
          <FilterChip
            label={t('schedule_advanced.phase_status.pulled', { defaultValue: 'Pulled' })}
            count={counts.pulled}
            active={statusFilter === 'pulled'}
            onClick={() => setStatusFilter('pulled')}
          />
          <FilterChip
            label={t('schedule_advanced.phase_status.active', { defaultValue: 'Active' })}
            count={counts.active}
            active={statusFilter === 'active'}
            onClick={() => setStatusFilter('active')}
          />
          <FilterChip
            label={t('schedule_advanced.phase_status.completed', { defaultValue: 'Completed' })}
            count={counts.completed}
            active={statusFilter === 'completed'}
            onClick={() => setStatusFilter('completed')}
          />
        </div>
        <div
          role="tablist"
          aria-label={t('schedule_advanced.view', { defaultValue: 'View' })}
          className="ml-auto inline-flex rounded-lg border border-border-light bg-surface-secondary p-0.5"
        >
          <ViewToggle active={view === 'cards'} onClick={() => setView('cards')} icon={<ListIcon size={12} />} label={t('schedule_advanced.view_cards', { defaultValue: 'Cards' })} />
          <ViewToggle active={view === 'table'} onClick={() => setView('table')} icon={<TableIcon size={12} />} label={t('schedule_advanced.view_table', { defaultValue: 'Table' })} />
          <ViewToggle active={view === 'timeline'} onClick={() => setView('timeline')} icon={<GanttChart size={12} />} label={t('schedule_advanced.view_timeline', { defaultValue: 'Timeline' })} />
        </div>
        <Button variant="ghost" size="sm" icon={<Sparkles size={14} />} onClick={() => setTemplateOpen(true)}>
          {t('schedule_advanced.use_template', { defaultValue: 'Use a template' })}
        </Button>
        <Button variant="primary" size="sm" icon={<Plus size={14} />} onClick={() => setCreateOpen(true)}>
          {t('schedule_advanced.create_phase', { defaultValue: 'New phase' })}
        </Button>
      </div>

      {/* Look-ahead horizon chips — independent of status filter so the
          foreman can instantly focus on near-term work. Lives below the
          main toolbar to avoid crowding. */}
      <div
        className="flex flex-wrap items-center gap-1.5 text-xs"
        role="group"
        aria-label={t('schedule_advanced.look_ahead_aria', { defaultValue: 'Look-ahead horizon' })}
        data-testid="phase-horizon-chips"
      >
        <span className="text-content-tertiary mr-1">
          {t('schedule_advanced.look_ahead', { defaultValue: 'Look-ahead' })}:
        </span>
        <FilterChip
          label={t('common.all', { defaultValue: 'All' })}
          count={phases.length}
          active={horizon == null}
          onClick={() => setHorizon(null)}
        />
        <FilterChip
          label={t('schedule_advanced.next_1w', { defaultValue: '1 week' })}
          count={phases.filter((p) => withinHorizon(p, 1)).length}
          active={horizon === 1}
          onClick={() => setHorizon(1)}
        />
        <FilterChip
          label={t('schedule_advanced.next_2w', { defaultValue: '2 weeks' })}
          count={phases.filter((p) => withinHorizon(p, 2)).length}
          active={horizon === 2}
          onClick={() => setHorizon(2)}
        />
        <FilterChip
          label={t('schedule_advanced.next_4w', { defaultValue: '4 weeks' })}
          count={phases.filter((p) => withinHorizon(p, 4)).length}
          active={horizon === 4}
          onClick={() => setHorizon(4)}
        />
        {activeBaseline && (
          <span
            className="ml-auto text-content-tertiary"
            data-testid="phase-baseline-ref"
            title={`Baseline: ${activeBaseline.name}`}
          >
            {t('schedule_advanced.compared_against', {
              name: activeBaseline.name,
              defaultValue: 'Variance vs "{{name}}"',
            })}
          </span>
        )}
      </div>

      {filtered.length === 0 ? (
        <Card padding="md">
          <p className="text-center text-sm text-content-tertiary py-6">
            {t('schedule_advanced.no_phases_for_filter', {
              defaultValue: 'No phases match this filter.',
            })}
          </p>
        </Card>
      ) : view === 'cards' ? (
        <PhasesCardGrid
          phases={filtered}
          deltas={deltas}
          criticalIds={criticalIds}
          onEdit={setEditPhase}
          onDelete={setDeletePhase}
          onPull={(id) => pullMut.mutate(id)}
          onStart={(id) => startMut.mutate(id)}
          onComplete={(id) => completeMut.mutate(id)}
          pulling={pullMut.isPending}
          starting={startMut.isPending}
          completing={completeMut.isPending}
        />
      ) : view === 'table' ? (
        <PhasesTableView
          phases={filtered}
          deltas={deltas}
          criticalIds={criticalIds}
          onEdit={setEditPhase}
          onDelete={setDeletePhase}
          onPull={(id) => pullMut.mutate(id)}
          onStart={(id) => startMut.mutate(id)}
          onComplete={(id) => completeMut.mutate(id)}
        />
      ) : (
        <PhasesTimelineView
          phases={filtered}
          deltas={deltas}
          criticalIds={criticalIds}
          onEdit={setEditPhase}
        />
      )}

      {createOpen && (
        <PhaseFormModal masterId={masterId} onClose={() => setCreateOpen(false)} onSaved={invalidate} />
      )}
      {editPhase && (
        <PhaseFormModal masterId={masterId} phase={editPhase} onClose={() => setEditPhase(null)} onSaved={invalidate} />
      )}
      {templateOpen && (
        <PhaseTemplateModal masterId={masterId} onClose={() => setTemplateOpen(false)} onSaved={invalidate} />
      )}
      <ConfirmDialog
        open={!!deletePhase}
        title={t('schedule_advanced.delete_phase_title', { defaultValue: 'Delete phase?' })}
        message={
          deletePhase
            ? t('schedule_advanced.delete_phase_message', {
                name: deletePhase.name,
                defaultValue:
                  '"{{name}}" will be permanently removed. Any commitments linked to this phase will need to be re-targeted.',
              })
            : ''
        }
        onConfirm={() => deletePhase && deleteMut.mutate(deletePhase.id)}
        onCancel={() => setDeletePhase(null)}
        loading={deleteMut.isPending}
      />
    </div>
  );
}

function FilterChip({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 transition-colors',
        active
          ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text'
          : 'border-border-light bg-surface-secondary text-content-secondary hover:bg-surface-tertiary',
      )}
    >
      {label}
      <span
        className={clsx(
          'rounded-full px-1.5 py-px text-2xs',
          active ? 'bg-oe-blue/10 text-oe-blue' : 'bg-surface-primary text-content-tertiary',
        )}
      >
        {count}
      </span>
    </button>
  );
}

function ViewToggle({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={clsx(
        'inline-flex items-center gap-1 rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
        active
          ? 'bg-surface-primary text-content-primary shadow-xs'
          : 'text-content-secondary hover:text-content-primary',
      )}
    >
      {icon}
      {label}
    </button>
  );
}

function PhasesCardGrid({
  phases,
  deltas,
  criticalIds,
  onEdit,
  onDelete,
  onPull,
  onStart,
  onComplete,
  pulling,
  starting,
  completing,
}: {
  phases: PhasePlan[];
  deltas: BaselineDeltaEntry[];
  criticalIds: Set<string>;
  onEdit: (p: PhasePlan) => void;
  onDelete: (p: PhasePlan) => void;
  onPull: (id: string) => void;
  onStart: (id: string) => void;
  onComplete: (id: string) => void;
  pulling: boolean;
  starting: boolean;
  completing: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {phases.map((p) => {
        const delayed = isPhaseDelayed(p);
        const milestone = isPhaseMilestone(p);
        const onCritical = criticalIds.has(p.id);
        const variance = phaseVarianceDays(p, deltas);
        const colorClass =
          p.pulled_status === 'completed'
            ? 'border-semantic-success/30 bg-semantic-success-bg/40'
            : p.pulled_status === 'active'
              ? 'border-semantic-warning/40 bg-semantic-warning-bg/40'
              : p.pulled_status === 'pulled'
                ? 'border-oe-blue/30 bg-oe-blue-subtle/30'
                : 'border-border-light bg-surface-secondary/40';
        const pct = phasePercent(p);
        return (
          <Card
            key={p.id}
            padding="md"
            className={clsx(
              'border flex flex-col relative',
              colorClass,
              onCritical && 'ring-1 ring-rose-400/60',
            )}
            data-phase-id={p.id}
            data-critical={onCritical ? 'true' : 'false'}
          >
            {onCritical && (
              <span
                className="absolute top-2 right-2 inline-flex items-center gap-0.5 rounded-md bg-rose-500/15 px-1.5 py-px text-2xs font-semibold text-rose-700 dark:text-rose-300"
                title={t('schedule_advanced.cp_tooltip', { defaultValue: 'On the critical path - slipping this phase delays the project finish' })}
                data-testid="phase-cp-badge"
              >
                <AlertTriangle size={9} />
                CP
              </span>
            )}
            <div className="flex items-start justify-between gap-2 pr-12">
              <h4 className="text-sm font-semibold truncate flex items-center gap-1.5" title={p.name}>
                {milestone && (
                  <Diamond
                    size={11}
                    className="text-amber-500 shrink-0 rotate-45"
                    aria-label={t('schedule_advanced.milestone', { defaultValue: 'Milestone' })}
                    data-testid="phase-milestone-glyph"
                  />
                )}
                {p.name}
                {p.pulled_status === 'completed' && (
                  <Check
                    size={11}
                    className="text-emerald-600 shrink-0"
                    aria-label={t('schedule_advanced.phase_status.completed', { defaultValue: 'Completed' })}
                  />
                )}
              </h4>
              <div className="flex items-center gap-1 shrink-0">
                <VarianceBadge days={variance} />
                <Badge variant={delayed ? 'error' : PHASE_VARIANT[p.pulled_status]} dot>
                  {delayed
                    ? t('schedule_advanced.phase_status.delayed', { defaultValue: 'Delayed' })
                    : t(`schedule_advanced.phase_status.${p.pulled_status}`, { defaultValue: p.pulled_status })}
                </Badge>
              </div>
            </div>
            <p className="mt-1 text-xs text-content-tertiary">
              {p.planned_start && p.planned_finish ? (
                <>
                  <DateDisplay value={p.planned_start} /> → <DateDisplay value={p.planned_finish} />
                </>
              ) : '—'}
            </p>
            <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-surface-primary/60">
              <div
                className={clsx(
                  'h-full transition-all',
                  p.pulled_status === 'completed'
                    ? 'bg-emerald-500'
                    : delayed
                      ? 'bg-rose-500'
                      : 'bg-blue-500',
                )}
                style={{ width: `${pct}%` }}
              />
            </div>
            <p className="mt-1 text-2xs text-content-tertiary tabular-nums">{pct}%</p>
            {p.notes && (
              <p className="mt-2 text-xs text-content-secondary line-clamp-3">{p.notes}</p>
            )}
            <div className="mt-auto pt-3 flex flex-wrap gap-1.5">
              {p.pulled_status === 'in_planning' && (
                <Button size="sm" variant="secondary" onClick={() => onPull(p.id)} loading={pulling}>
                  {t('schedule_advanced.pull', { defaultValue: 'Pull' })}
                </Button>
              )}
              {p.pulled_status === 'pulled' && (
                <Button size="sm" variant="secondary" icon={<PlayCircle size={12} />} onClick={() => onStart(p.id)} loading={starting}>
                  {t('schedule_advanced.start', { defaultValue: 'Start' })}
                </Button>
              )}
              {p.pulled_status === 'active' && (
                <Button size="sm" variant="primary" icon={<Check size={12} />} onClick={() => onComplete(p.id)} loading={completing}>
                  {t('schedule_advanced.complete', { defaultValue: 'Complete' })}
                </Button>
              )}
              <Button size="sm" variant="ghost" icon={<Pencil size={12} />} onClick={() => onEdit(p)} aria-label={t('common.edit', { defaultValue: 'Edit' })} />
              <Button size="sm" variant="ghost" icon={<Trash2 size={12} />} onClick={() => onDelete(p)} aria-label={t('common.delete', { defaultValue: 'Delete' })} />
            </div>
          </Card>
        );
      })}
    </div>
  );
}

function PhasesTableView({
  phases,
  deltas,
  criticalIds,
  onEdit,
  onDelete,
  onPull,
  onStart,
  onComplete,
}: {
  phases: PhasePlan[];
  deltas: BaselineDeltaEntry[];
  criticalIds: Set<string>;
  onEdit: (p: PhasePlan) => void;
  onDelete: (p: PhasePlan) => void;
  onPull: (id: string) => void;
  onStart: (id: string) => void;
  onComplete: (id: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <Card padding="none">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
            <tr>
              <th className="px-4 py-2.5 text-left">#</th>
              <th className="px-4 py-2.5 text-left">{t('common.name')}</th>
              <th className="px-4 py-2.5 text-left">{t('schedule_advanced.planned_start', { defaultValue: 'Start' })}</th>
              <th className="px-4 py-2.5 text-left">{t('schedule_advanced.planned_finish', { defaultValue: 'Finish' })}</th>
              <th className="px-4 py-2.5 text-right">{t('schedule_advanced.duration_days', { defaultValue: 'Days' })}</th>
              <th className="px-4 py-2.5 text-right">{t('schedule_advanced.variance', { defaultValue: 'Δ' })}</th>
              <th className="px-4 py-2.5 text-left">{t('common.status', { defaultValue: 'Status' })}</th>
              <th className="px-4 py-2.5 text-right">{t('schedule_advanced.progress', { defaultValue: 'Progress' })}</th>
              <th className="px-4 py-2.5 text-right">{t('common.actions', { defaultValue: 'Actions' })}</th>
            </tr>
          </thead>
          <tbody>
            {phases.map((p, idx) => {
              const delayed = isPhaseDelayed(p);
              const pct = phasePercent(p);
              const days = phaseDurationDays(p);
              const variance = phaseVarianceDays(p, deltas);
              const onCritical = criticalIds.has(p.id);
              return (
                <tr
                  key={p.id}
                  className={clsx(
                    'border-t border-border-light hover:bg-surface-secondary',
                    onCritical && 'bg-rose-500/5',
                  )}
                  data-phase-id={p.id}
                  data-critical={onCritical ? 'true' : 'false'}
                >
                  <td className="px-4 py-2 text-xs text-content-tertiary tabular-nums">{idx + 1}</td>
                  <td className="px-4 py-2 font-medium">
                    <button type="button" className="text-left hover:text-oe-blue flex items-center gap-1.5" onClick={() => onEdit(p)}>
                      {isPhaseMilestone(p) && <Diamond size={10} className="text-amber-500 rotate-45 shrink-0" aria-hidden />}
                      {p.name}
                      {onCritical && (
                        <span className="rounded-md bg-rose-500/15 px-1 py-px text-2xs font-semibold text-rose-700 dark:text-rose-300" title={t('schedule_advanced.cp_tooltip', { defaultValue: 'On the critical path - slipping this phase delays the project finish' })} data-testid="phase-cp-badge">CP</span>
                      )}
                    </button>
                  </td>
                  <td className="px-4 py-2 text-xs text-content-secondary">
                    {p.planned_start ? <DateDisplay value={p.planned_start} /> : '—'}
                  </td>
                  <td className="px-4 py-2 text-xs text-content-secondary">
                    {p.planned_finish ? <DateDisplay value={p.planned_finish} /> : '—'}
                  </td>
                  <td className="px-4 py-2 text-right font-mono text-xs">{days == null ? '—' : days}</td>
                  <td className="px-4 py-2 text-right">
                    {variance != null ? <VarianceBadge days={variance} /> : <span className="text-content-tertiary">—</span>}
                  </td>
                  <td className="px-4 py-2">
                    <Badge variant={delayed ? 'error' : PHASE_VARIANT[p.pulled_status]} dot>
                      {delayed
                        ? t('schedule_advanced.phase_status.delayed', { defaultValue: 'Delayed' })
                        : t(`schedule_advanced.phase_status.${p.pulled_status}`, { defaultValue: p.pulled_status })}
                    </Badge>
                  </td>
                  <td className="px-4 py-2">
                    <div className="ml-auto flex items-center justify-end gap-2">
                      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-surface-secondary">
                        <div
                          className={clsx(
                            'h-full',
                            p.pulled_status === 'completed'
                              ? 'bg-emerald-500'
                              : delayed
                                ? 'bg-rose-500'
                                : 'bg-blue-500',
                          )}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <span className="font-mono text-2xs text-content-tertiary tabular-nums w-8 text-right">{pct}%</span>
                    </div>
                  </td>
                  <td className="px-4 py-2">
                    <div className="flex justify-end gap-1">
                      {p.pulled_status === 'in_planning' && (
                        <Button size="sm" variant="ghost" onClick={() => onPull(p.id)}>
                          {t('schedule_advanced.pull', { defaultValue: 'Pull' })}
                        </Button>
                      )}
                      {p.pulled_status === 'pulled' && (
                        <Button size="sm" variant="ghost" onClick={() => onStart(p.id)}>
                          {t('schedule_advanced.start', { defaultValue: 'Start' })}
                        </Button>
                      )}
                      {p.pulled_status === 'active' && (
                        <Button size="sm" variant="ghost" icon={<Check size={12} />} onClick={() => onComplete(p.id)} aria-label={t('schedule_advanced.complete', { defaultValue: 'Complete' })} />
                      )}
                      <Button size="sm" variant="ghost" icon={<Pencil size={12} />} onClick={() => onEdit(p)} aria-label={t('common.edit', { defaultValue: 'Edit' })} />
                      <Button size="sm" variant="ghost" icon={<Trash2 size={12} />} onClick={() => onDelete(p)} aria-label={t('common.delete', { defaultValue: 'Delete' })} />
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function PhasesTimelineView({
  phases,
  deltas,
  criticalIds,
  onEdit,
}: {
  phases: PhasePlan[];
  deltas: BaselineDeltaEntry[];
  criticalIds: Set<string>;
  onEdit: (p: PhasePlan) => void;
}) {
  const { t } = useTranslation();
  const dated = phases.filter((p) => p.planned_start && p.planned_finish);
  if (dated.length === 0) {
    return (
      <Card padding="md">
        <p className="text-center text-sm text-content-tertiary py-4">
          {t('schedule_advanced.timeline_no_dates', {
            defaultValue: 'Add start and finish dates to phases to see them on the timeline.',
          })}
        </p>
      </Card>
    );
  }
  const minStart = Math.min(...dated.map((p) => new Date(p.planned_start!).getTime()));
  const maxEnd = Math.max(...dated.map((p) => new Date(p.planned_finish!).getTime()));
  const span = Math.max(1, maxEnd - minStart);
  const todayMs = Date.now();
  const todayPct = todayMs >= minStart && todayMs <= maxEnd ? ((todayMs - minStart) / span) * 100 : null;

  const sorted = [...phases].sort((a, b) => {
    const sa = a.planned_start ? new Date(a.planned_start).getTime() : Number.MAX_SAFE_INTEGER;
    const sb = b.planned_start ? new Date(b.planned_start).getTime() : Number.MAX_SAFE_INTEGER;
    return sa - sb;
  });

  return (
    <Card padding="md" data-testid="phases-gantt">
      {/* Mobile (narrow) fallback — Gantt bars don't have enough room on
          phones. Render the same data as a vertical status list with
          coloured pips. The Tailwind `sm:hidden` flip happens at 640px
          which matches the rest of the page's responsive cutoffs. */}
      <ul className="block sm:hidden space-y-2" data-testid="phases-gantt-mobile">
        {sorted.map((p) => {
          const delayed = isPhaseDelayed(p);
          const onCritical = criticalIds.has(p.id);
          const variance = phaseVarianceDays(p, deltas);
          const pipColor =
            p.pulled_status === 'completed'
              ? 'bg-emerald-500'
              : delayed
                ? 'bg-rose-500'
                : p.pulled_status === 'active'
                  ? 'bg-amber-500'
                  : p.pulled_status === 'pulled'
                    ? 'bg-blue-500'
                    : 'bg-slate-400';
          return (
            <li
              key={p.id}
              className="flex items-center gap-3 rounded-md border border-border-light bg-surface-primary px-3 py-2"
              data-phase-id={p.id}
            >
              <span className={clsx('inline-block h-2.5 w-2.5 shrink-0 rounded-full', pipColor)} aria-hidden />
              {isPhaseMilestone(p) && <Diamond size={12} className="text-amber-500 rotate-45 shrink-0" aria-label={t('schedule_advanced.milestone', { defaultValue: 'Milestone' })} />}
              <button
                type="button"
                className="flex-1 truncate text-left text-sm font-medium hover:text-oe-blue"
                onClick={() => onEdit(p)}
              >
                {p.name}
              </button>
              {onCritical && (
                <span className="rounded-md bg-rose-500/15 px-1.5 py-px text-2xs font-semibold text-rose-700 dark:text-rose-300" data-testid="phase-cp-badge">CP</span>
              )}
              <VarianceBadge days={variance} />
            </li>
          );
        })}
      </ul>

      {/* Desktop / tablet — proper Gantt bars. */}
      <div className="hidden sm:block">
        <div className="flex items-center justify-between text-xs text-content-tertiary mb-3">
          <span><DateDisplay value={new Date(minStart).toISOString().slice(0, 10)} /></span>
          <span className="flex items-center gap-3">
            {/* Legend — keeps colour semantics discoverable */}
            <span className="inline-flex items-center gap-1"><span className="inline-block h-2 w-3 rounded-sm bg-blue-500" />{t('schedule_advanced.legend_planned', { defaultValue: 'Planned' })}</span>
            <span className="inline-flex items-center gap-1"><span className="inline-block h-2 w-3 rounded-sm bg-amber-500" />{t('schedule_advanced.legend_active', { defaultValue: 'Active' })}</span>
            <span className="inline-flex items-center gap-1"><span className="inline-block h-2 w-3 rounded-sm bg-emerald-500" />{t('schedule_advanced.legend_done', { defaultValue: 'Done' })}</span>
            <span className="inline-flex items-center gap-1"><span className="inline-block h-2 w-3 rounded-sm bg-rose-500" />{t('schedule_advanced.legend_delayed', { defaultValue: 'Delayed' })}</span>
            <span className="inline-flex items-center gap-1 ml-2"><span className="inline-block h-3 w-px bg-rose-500" />{t('schedule_advanced.today', { defaultValue: 'Today' })}</span>
          </span>
          <span><DateDisplay value={new Date(maxEnd).toISOString().slice(0, 10)} /></span>
        </div>
        <div className="relative">
          {todayPct != null && (
            <div
              className="absolute top-0 bottom-0 w-px bg-rose-500 pointer-events-none z-10"
              style={{ left: `calc(180px + (100% - 180px) * ${todayPct / 100})` }}
              aria-hidden
              data-testid="phases-gantt-today"
            />
          )}
          <ul className="space-y-2">
            {sorted.map((p) => {
              const hasDates = p.planned_start && p.planned_finish;
              const s = hasDates ? new Date(p.planned_start!).getTime() : minStart;
              const f = hasDates ? new Date(p.planned_finish!).getTime() : minStart;
              const left = ((s - minStart) / span) * 100;
              const width = Math.max(0.5, ((f - s) / span) * 100);
              const delayed = isPhaseDelayed(p);
              const onCritical = criticalIds.has(p.id);
              const variance = phaseVarianceDays(p, deltas);
              const milestone = isPhaseMilestone(p);
              const barColor =
                p.pulled_status === 'completed'
                  ? 'bg-emerald-500'
                  : p.pulled_status === 'active'
                    ? delayed
                      ? 'bg-rose-500'
                      : 'bg-amber-500'
                    : p.pulled_status === 'pulled'
                      ? 'bg-blue-500'
                      : 'bg-slate-400';
              return (
                <li
                  key={p.id}
                  className="grid grid-cols-[180px_1fr] items-center gap-3"
                  data-phase-id={p.id}
                  data-critical={onCritical ? 'true' : 'false'}
                >
                  <button
                    type="button"
                    className="truncate text-left text-sm font-medium text-content-primary hover:text-oe-blue flex items-center gap-1.5"
                    onClick={() => onEdit(p)}
                    title={p.name}
                  >
                    {onCritical && (
                      <span className="rounded-sm bg-rose-500/15 px-1 py-px text-2xs font-semibold text-rose-700 dark:text-rose-300" title={t('schedule_advanced.cp_tooltip', { defaultValue: 'On the critical path - slipping this phase delays the project finish' })} data-testid="phase-cp-badge">CP</span>
                    )}
                    <span className="truncate">{p.name}</span>
                    <VarianceBadge days={variance} />
                  </button>
                  <div className="relative h-7 rounded-md bg-surface-secondary/40 border border-border-light">
                    {hasDates && (
                      <>
                        {/* Baseline ghost bar — drawn behind the live bar so
                            the user can eyeball the shift. Only drawn when
                            there's a baseline entry for this phase. */}
                        {(() => {
                          const hit = deltas.find((d) => d.task_ref === p.id);
                          if (!hit?.planned_start_baseline || !hit?.planned_finish_baseline) return null;
                          const bs = new Date(hit.planned_start_baseline).getTime();
                          const bf = new Date(hit.planned_finish_baseline).getTime();
                          const bl = ((bs - minStart) / span) * 100;
                          const bw = Math.max(0.5, ((bf - bs) / span) * 100);
                          return (
                            <div
                              className="absolute top-0 h-1 rounded-sm bg-content-tertiary/40"
                              style={{ left: `${bl}%`, width: `${bw}%` }}
                              aria-hidden
                              data-testid="phase-gantt-baseline-bar"
                              title={`Baseline: ${hit.planned_start_baseline} → ${hit.planned_finish_baseline}`}
                            />
                          );
                        })()}
                        {milestone ? (
                          <div
                            className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 z-10"
                            style={{ left: `${left}%` }}
                            title={p.planned_start ?? ''}
                          >
                            <Diamond size={14} className={clsx('rotate-45', delayed ? 'text-rose-500 fill-rose-500' : 'text-amber-500 fill-amber-400')} />
                          </div>
                        ) : (
                          <div
                            className={clsx(
                              'absolute top-1 bottom-1 rounded-sm flex items-center justify-center text-2xs font-medium text-white px-2 truncate',
                              barColor,
                              onCritical && 'ring-1 ring-rose-300 ring-offset-1 ring-offset-surface-primary',
                            )}
                            style={{ left: `${left}%`, width: `${width}%` }}
                            title={`${p.planned_start} → ${p.planned_finish}`}
                            data-testid="phase-gantt-bar"
                          >
                            <span className="truncate">{phasePercent(p)}%</span>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      </div>
    </Card>
  );
}

function PhaseFormModal({
  masterId,
  phase,
  onClose,
  onSaved,
}: {
  masterId: string;
  phase?: PhasePlan;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const isEdit = !!phase;
  const [name, setName] = useState(phase?.name ?? '');
  const [start, setStart] = useState(phase?.planned_start ?? todayIso());
  const [finish, setFinish] = useState(phase?.planned_finish ?? todayIso(30));
  const [notes, setNotes] = useState(phase?.notes ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const validate = (): string | null => {
    if (!name.trim()) {
      return t('schedule_advanced.err_name_required', { defaultValue: 'Phase name is required.' });
    }
    if (start && finish && new Date(finish).getTime() < new Date(start).getTime()) {
      return t('schedule_advanced.err_finish_after_start', {
        defaultValue: 'Planned finish must be on or after planned start.',
      });
    }
    return null;
  };

  const submit = async () => {
    const v = validate();
    if (v) {
      setError(v);
      return;
    }
    setError(null);
    setBusy(true);
    try {
      if (isEdit && phase) {
        await updatePhasePlan(phase.id, {
          name: name.trim(),
          planned_start: start || null,
          planned_finish: finish || null,
          notes,
        });
        addToast({ type: 'success', title: t('schedule_advanced.phase_updated', { defaultValue: 'Phase updated' }) });
      } else {
        await createPhasePlan({
          master_schedule_id: masterId,
          name: name.trim(),
          planned_start: start || undefined,
          planned_finish: finish || undefined,
          notes,
        });
        addToast({ type: 'success', title: t('schedule_advanced.phase_created', { defaultValue: 'Phase created' }) });
      }
      onSaved();
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <WideModal
      open
      onClose={onClose}
      title={isEdit ? t('schedule_advanced.edit_phase', { defaultValue: 'Edit phase' }) : t('schedule_advanced.create_phase', { defaultValue: 'New phase' })}
      subtitle={t('schedule_advanced.phase_modal_subtitle', {
        defaultValue:
          'Phases are high-level project segments - typically 4–12 weeks each. Use the lifecycle buttons on the card to pull, start, and complete a phase.',
      })}
      size="lg"
      busy={busy}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>{t('common.cancel', { defaultValue: 'Cancel' })}</Button>
          <Button variant="primary" onClick={submit} loading={busy} disabled={!name.trim()}>
            {isEdit ? t('common.save', { defaultValue: 'Save' }) : t('common.create', { defaultValue: 'Create' })}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {error && (
          <div className="rounded-md border border-semantic-error/30 bg-semantic-error-bg/40 px-3 py-2 text-sm text-semantic-error">{error}</div>
        )}
        <div>
          <label className={labelCls}>{t('schedule_advanced.phase_name', { defaultValue: 'Phase name' })} *</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className={inputCls}
            placeholder={t('schedule_advanced.phase_name_placeholder', { defaultValue: 'e.g. Foundation, Structure, MEP rough-in…' })}
            autoFocus
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>{t('schedule_advanced.planned_start', { defaultValue: 'Planned start' })}</label>
            <input type="date" value={start} onChange={(e) => setStart(e.target.value)} className={inputCls} />
          </div>
          <div>
            <label className={labelCls}>{t('schedule_advanced.planned_finish', { defaultValue: 'Planned finish' })}</label>
            <input type="date" value={finish} onChange={(e) => setFinish(e.target.value)} className={inputCls} />
          </div>
        </div>
        <div>
          <label className={labelCls}>{t('common.notes', { defaultValue: 'Notes' })}</label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            className={clsx(inputCls, 'h-auto py-2')}
            placeholder={t('schedule_advanced.phase_notes_placeholder', { defaultValue: 'Scope, owner, key deliverables…' })}
          />
        </div>
        {isEdit && phase && (
          <p className="text-xs text-content-tertiary">
            {t('schedule_advanced.current_status', { defaultValue: 'Current status' })}:{' '}
            <Badge variant={PHASE_VARIANT[phase.pulled_status]} dot>
              {t(`schedule_advanced.phase_status.${phase.pulled_status}`, { defaultValue: phase.pulled_status })}
            </Badge>
          </p>
        )}
      </div>
    </WideModal>
  );
}

function PhaseTemplateModal({
  masterId,
  onClose,
  onSaved,
}: {
  masterId: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [template, setTemplate] = useState<'residential' | 'commercial' | 'infrastructure'>('residential');
  const [start, setStart] = useState(todayIso());
  const [busy, setBusy] = useState(false);

  const apply = async () => {
    setBusy(true);
    try {
      const created = await applyPhaseTemplate(masterId, template, start);
      addToast({
        type: 'success',
        title: t('schedule_advanced.template_applied', { count: created.length, defaultValue: '{{count}} phases created' }),
      });
      onSaved();
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  const templateOptions: Array<{ key: typeof template; title: string; description: string }> = [
    {
      key: 'residential',
      title: t('schedule_advanced.template_residential', { defaultValue: 'Residential' }),
      description: t('schedule_advanced.template_residential_desc', {
        defaultValue: 'Single-family / multi-family build - site prep through handover.',
      }),
    },
    {
      key: 'commercial',
      title: t('schedule_advanced.template_commercial', { defaultValue: 'Commercial' }),
      description: t('schedule_advanced.template_commercial_desc', {
        defaultValue: 'Office / retail / institutional - includes commissioning phase.',
      }),
    },
    {
      key: 'infrastructure',
      title: t('schedule_advanced.template_infrastructure', { defaultValue: 'Infrastructure' }),
      description: t('schedule_advanced.template_infrastructure_desc', {
        defaultValue: 'Roads / utilities - earthworks-heavy with final inspection.',
      }),
    },
  ];

  const preview = PHASE_TEMPLATES[template];

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('schedule_advanced.apply_template', { defaultValue: 'Apply phase template' })}
      subtitle={t('schedule_advanced.apply_template_subtitle', {
        defaultValue:
          'Pick a starter set of construction phases. Each phase gets a default duration - you can edit names, dates, and notes after applying.',
      })}
      size="xl"
      busy={busy}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>{t('common.cancel', { defaultValue: 'Cancel' })}</Button>
          <Button variant="primary" onClick={apply} loading={busy}>
            {t('schedule_advanced.apply_n_phases', { count: preview.length, defaultValue: 'Create {{count}} phases' })}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          {templateOptions.map((opt) => (
            <button
              key={opt.key}
              type="button"
              onClick={() => setTemplate(opt.key)}
              className={clsx(
                'rounded-lg border p-3 text-left transition-all',
                template === opt.key
                  ? 'border-oe-blue bg-oe-blue-subtle/30 ring-1 ring-oe-blue'
                  : 'border-border-light hover:border-border hover:bg-surface-secondary',
              )}
            >
              <div className="text-sm font-semibold text-content-primary">{opt.title}</div>
              <div className="mt-0.5 text-xs text-content-secondary">{opt.description}</div>
            </button>
          ))}
        </div>
        <div>
          <label className={labelCls}>{t('schedule_advanced.template_start_date', { defaultValue: 'Start date (first phase)' })}</label>
          <input type="date" value={start} onChange={(e) => setStart(e.target.value)} className={clsx(inputCls, 'max-w-xs')} />
        </div>
        <div>
          <div className="text-xs uppercase tracking-wide text-content-tertiary mb-2">{t('schedule_advanced.template_preview', { defaultValue: 'Preview' })}</div>
          <ul className="space-y-1 text-sm">
            {preview.map((p, idx) => (
              <li key={p.name} className="flex items-center justify-between rounded-md bg-surface-secondary/60 px-3 py-1.5">
                <span className="flex items-center gap-2">
                  <span className="font-mono text-2xs text-content-tertiary tabular-nums w-6 text-right">{idx + 1}.</span>
                  {t(`schedule_advanced.template_phase.${slug(p.name)}`, { defaultValue: p.name })}
                </span>
                <span className="font-mono text-2xs text-content-tertiary">{p.days} {t('schedule_advanced.days', { defaultValue: 'days' })}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </WideModal>
  );
}

function slug(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
}

/* ── Look-ahead tab ──────────────────────────────────────────────────── */

function LookAheadTab({
  lookAheads,
  loading,
  isError,
  onRetry,
  lookAheadId,
  onSelect,
  onCreate,
}: {
  lookAheads: LookAheadPlan[];
  loading: boolean;
  isError?: boolean;
  onRetry?: () => void;
  lookAheadId: string;
  onSelect: (id: string) => void;
  onCreate: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const publishMut = useMutation({
    mutationFn: (id: string) => publishLookAhead(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['schedule-advanced', 'look-aheads'] });
      addToast({ type: 'success', title: t('schedule_advanced.la_published', { defaultValue: 'Look-ahead published' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  if (loading) {
    return (
      <Card padding="md">
        <SkeletonTable rows={4} columns={5} />
      </Card>
    );
  }

  if (isError) {
    return <ErrorCard onRetry={onRetry} />;
  }

  if (lookAheads.length === 0) {
    return (
      <Card>
        <EmptyState
          icon={<Clock size={22} />}
          title={t('schedule_advanced.no_la', { defaultValue: 'No look-ahead plans yet' })}
          description={t('schedule_advanced.no_la_desc', {
            defaultValue: 'Look-aheads roll a 6-week window for constraint clearing.',
          })}
          action={{
            label: t('schedule_advanced.create_la', { defaultValue: 'Create Look-Ahead' }),
            onClick: onCreate,
          }}
        />
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button
          variant="primary"
          size="sm"
          icon={<Plus size={14} />}
          onClick={onCreate}
        >
          {t('schedule_advanced.create_la', { defaultValue: 'Create Look-Ahead' })}
        </Button>
      </div>
      <Card padding="none">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
              <tr>
                <th className="px-4 py-2.5 text-left">{t('schedule_advanced.period_start', { defaultValue: 'Start' })}</th>
                <th className="px-4 py-2.5 text-left">{t('schedule_advanced.period_end', { defaultValue: 'End' })}</th>
                <th className="px-4 py-2.5 text-left">{t('schedule_advanced.weeks', { defaultValue: 'Weeks' })}</th>
                <th className="px-4 py-2.5 text-left">{t('common.status', { defaultValue: 'Status' })}</th>
                <th className="px-4 py-2.5 text-right">{t('common.actions', { defaultValue: 'Actions' })}</th>
              </tr>
            </thead>
            <tbody>
              {lookAheads.map((la) => (
                <tr
                  key={la.id}
                  onClick={() => onSelect(la.id)}
                  className={clsx(
                    'border-t border-border-light hover:bg-surface-secondary cursor-pointer',
                    la.id === lookAheadId && 'bg-oe-blue-subtle/30',
                  )}
                >
                  <td className="px-4 py-2 text-xs text-content-secondary">
                    <DateDisplay value={la.period_start} />
                  </td>
                  <td className="px-4 py-2 text-xs text-content-secondary">
                    <DateDisplay value={la.period_end} />
                  </td>
                  <td className="px-4 py-2 text-xs text-content-secondary">
                    {la.window_weeks}
                  </td>
                  <td className="px-4 py-2">
                    <Badge
                      variant={
                        la.status === 'published'
                          ? 'success'
                          : la.status === 'reviewed'
                            ? 'blue'
                            : 'neutral'
                      }
                      dot
                    >
                      {la.status}
                    </Badge>
                  </td>
                  <td className="px-4 py-2 text-right">
                    {la.status !== 'published' && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={(e) => {
                          e.stopPropagation();
                          publishMut.mutate(la.id);
                        }}
                      >
                        {t('schedule_advanced.publish', { defaultValue: 'Publish' })}
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

/* ── Weekly plan tab ─────────────────────────────────────────────────── */

function WeeklyTab({
  projectId,
  plans,
  loading,
  isError,
  onRetry,
  weekPlanId,
  onSelect,
  commitments,
  commitmentsLoading,
  commitmentsError,
  onRetryCommitments,
  currentWeek,
  onCreate,
}: {
  projectId: string;
  plans: WeeklyWorkPlan[];
  loading: boolean;
  isError?: boolean;
  onRetry?: () => void;
  weekPlanId: string;
  onSelect: (id: string) => void;
  commitments: Commitment[];
  commitmentsLoading: boolean;
  commitmentsError?: boolean;
  onRetryCommitments?: () => void;
  currentWeek: WeeklyWorkPlan | undefined;
  onCreate: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const commitMut = useMutation({
    mutationFn: (id: string) => commitWeeklyPlan(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['schedule-advanced', 'weekly'] });
      addToast({ type: 'success', title: t('schedule_advanced.week_committed', { defaultValue: 'Week committed' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const closeMut = useMutation({
    mutationFn: (id: string) => closeWeeklyPlan(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['schedule-advanced', 'weekly'] });
      addToast({ type: 'success', title: t('schedule_advanced.week_closed', { defaultValue: 'Week closed' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  const [addCommitment, setAddCommitment] = useState(false);
  const [missTarget, setMissTarget] = useState<Commitment | null>(null);

  const invalidateCommitments = () =>
    qc.invalidateQueries({
      queryKey: ['schedule-advanced', 'commitments', weekPlanId],
    });

  const commitCommitmentMut = useMutation({
    mutationFn: (id: string) => commitCommitment(id),
    onSuccess: () => {
      invalidateCommitments();
      addToast({ type: 'success', title: t('schedule_advanced.commitment_made', { defaultValue: 'Commitment made' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const completeCommitmentMut = useMutation({
    mutationFn: (id: string) => completeCommitment(id),
    onSuccess: () => {
      invalidateCommitments();
      addToast({ type: 'success', title: t('schedule_advanced.commitment_completed', { defaultValue: 'Commitment completed' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const missCommitmentMut = useMutation({
    mutationFn: (vars: { id: string; category: RNCCategory; description: string }) =>
      missCommitment(vars.id, { category: vars.category, description: vars.description }),
    onSuccess: () => {
      invalidateCommitments();
      setMissTarget(null);
      addToast({ type: 'success', title: t('schedule_advanced.commitment_missed', { defaultValue: 'Commitment marked missed' }) });
    },
    onError: (err) => {
      addToast({ type: 'error', title: getErrorMessage(err) });
    },
  });

  if (loading) {
    return (
      <Card padding="md">
        <SkeletonTable rows={4} columns={5} />
      </Card>
    );
  }

  if (isError) {
    return <ErrorCard onRetry={onRetry} />;
  }

  if (plans.length === 0) {
    return (
      <Card>
        <EmptyState
          icon={<ClipboardCheck size={22} />}
          title={t('schedule_advanced.no_weekly', { defaultValue: 'No weekly plans yet' })}
          description={t('schedule_advanced.no_weekly_desc', {
            defaultValue: 'Weekly work plans capture the commitments due this week.',
          })}
          action={{
            label: t('schedule_advanced.create_weekly', { defaultValue: 'Create Weekly Plan' }),
            onClick: onCreate,
          }}
        />
      </Card>
    );
  }

  const ppc = pctNumber(currentWeek?.ppc_percent);
  const completed = commitments.filter((c) => c.status === 'completed').length;
  const missed = commitments.filter((c) => c.status === 'missed').length;

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
      <div className="xl:col-span-2 space-y-4">
        <div className="flex justify-end">
          <Button
            variant="primary"
            size="sm"
            icon={<Plus size={14} />}
            onClick={onCreate}
          >
            {t('schedule_advanced.create_weekly', { defaultValue: 'Create Weekly Plan' })}
          </Button>
        </div>

        <Card padding="none">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
                <tr>
                  <th className="px-4 py-2.5 text-left">{t('schedule_advanced.week_start', { defaultValue: 'Week start' })}</th>
                  <th className="px-4 py-2.5 text-left">{t('schedule_advanced.week_end', { defaultValue: 'Week end' })}</th>
                  <th className="px-4 py-2.5 text-left">{t('common.status', { defaultValue: 'Status' })}</th>
                  <th className="px-4 py-2.5 text-right">{t('schedule_advanced.ppc', { defaultValue: 'PPC' })}</th>
                  <th className="px-4 py-2.5 text-right">{t('common.actions', { defaultValue: 'Actions' })}</th>
                </tr>
              </thead>
              <tbody>
                {plans.map((w) => (
                  <tr
                    key={w.id}
                    onClick={() => onSelect(w.id)}
                    className={clsx(
                      'border-t border-border-light hover:bg-surface-secondary cursor-pointer',
                      w.id === weekPlanId && 'bg-oe-blue-subtle/30',
                    )}
                  >
                    <td className="px-4 py-2 text-xs text-content-secondary">
                      <DateDisplay value={w.week_start_date} />
                    </td>
                    <td className="px-4 py-2 text-xs text-content-secondary">
                      <DateDisplay value={w.week_end_date} />
                    </td>
                    <td className="px-4 py-2">
                      <Badge variant={WEEKLY_VARIANT[w.status]} dot>
                        {w.status}
                      </Badge>
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-xs">
                      {pctNumber(w.ppc_percent).toFixed(0)}%
                    </td>
                    <td className="px-4 py-2 text-right">
                      {w.status === 'draft' && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={(e) => {
                            e.stopPropagation();
                            commitMut.mutate(w.id);
                          }}
                        >
                          {t('schedule_advanced.commit', { defaultValue: 'Commit' })}
                        </Button>
                      )}
                      {(w.status === 'committed' || w.status === 'in_progress') && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={(e) => {
                            e.stopPropagation();
                            closeMut.mutate(w.id);
                          }}
                        >
                          {t('schedule_advanced.close', { defaultValue: 'Close' })}
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        {weekPlanId && (
          <Card padding="none">
            <div className="flex items-center justify-between border-b border-border-light px-4 py-2.5 bg-surface-secondary/50">
              <h3 className="text-sm font-semibold">
                {t('schedule_advanced.commitments', { defaultValue: 'Commitments' })}
              </h3>
              <Button
                size="sm"
                variant="secondary"
                icon={<Plus size={12} />}
                onClick={() => setAddCommitment(true)}
                disabled={currentWeek?.status === 'closed'}
              >
                {t('schedule_advanced.add_commitment', { defaultValue: 'Add commitment' })}
              </Button>
            </div>
            {commitmentsLoading ? (
              <div className="p-4">
                <SkeletonTable rows={4} columns={4} />
              </div>
            ) : commitmentsError ? (
              <EmptyState
                icon={<AlertCircle size={20} strokeWidth={1.5} />}
                title={t('common.error', { defaultValue: 'Error' })}
                description={t('schedule_advanced.commitments_load_error', {
                  defaultValue: 'Failed to load commitments. Please try again.',
                })}
                action={
                  onRetryCommitments
                    ? {
                        label: t('common.retry', { defaultValue: 'Retry' }),
                        onClick: onRetryCommitments,
                      }
                    : undefined
                }
              />
            ) : commitments.length === 0 ? (
              <EmptyState
                icon={<ClipboardCheck size={20} />}
                title={t('schedule_advanced.no_commitments', { defaultValue: 'No commitments' })}
                description={t('schedule_advanced.no_commitments_desc', {
                  defaultValue: 'Add commitments to this week to track progress.',
                })}
                action={{
                  label: t('schedule_advanced.add_commitment', { defaultValue: 'Add commitment' }),
                  onClick: () => setAddCommitment(true),
                }}
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
                    <tr>
                      <th className="px-4 py-2 text-left">{t('schedule_advanced.crew', { defaultValue: 'Crew' })}</th>
                      <th className="px-4 py-2 text-right">{t('schedule_advanced.promised', { defaultValue: 'Promised' })}</th>
                      <th className="px-4 py-2 text-right">{t('schedule_advanced.actual', { defaultValue: 'Actual' })}</th>
                      <th className="px-4 py-2 text-left">{t('common.status', { defaultValue: 'Status' })}</th>
                      <th className="px-4 py-2 text-right">{t('common.actions', { defaultValue: 'Actions' })}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {commitments.map((c) => {
                      const canCommit = c.status === 'planned' || c.status === 'at_risk';
                      const canResolve =
                        c.status === 'committed' ||
                        c.status === 'in_progress' ||
                        c.status === 'at_risk';
                      const busy =
                        (commitCommitmentMut.isPending &&
                          commitCommitmentMut.variables === c.id) ||
                        (completeCommitmentMut.isPending &&
                          completeCommitmentMut.variables === c.id);
                      return (
                        <tr key={c.id} className="border-t border-border-light">
                          <td className="px-4 py-2 truncate max-w-[200px]">
                            {c.worker_or_crew || '—'}
                          </td>
                          <td className="px-4 py-2 text-right font-mono text-xs">
                            {String(c.promised_qty)} {c.unit}
                          </td>
                          <td className="px-4 py-2 text-right font-mono text-xs">
                            {c.actual_qty != null ? String(c.actual_qty) : '—'}
                          </td>
                          <td className="px-4 py-2">
                            <Badge variant={COMMITMENT_VARIANT[c.status]} dot>
                              {c.status}
                            </Badge>
                          </td>
                          <td className="px-4 py-2">
                            <div className="flex justify-end gap-1">
                              {canCommit && (
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  loading={busy}
                                  onClick={() => commitCommitmentMut.mutate(c.id)}
                                >
                                  {t('schedule_advanced.commit', { defaultValue: 'Commit' })}
                                </Button>
                              )}
                              {canResolve && (
                                <>
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    icon={<Check size={12} />}
                                    loading={busy}
                                    onClick={() => completeCommitmentMut.mutate(c.id)}
                                    aria-label={t('schedule_advanced.complete', { defaultValue: 'Complete' })}
                                  />
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    onClick={() => setMissTarget(c)}
                                  >
                                    {t('schedule_advanced.miss', { defaultValue: 'Miss' })}
                                  </Button>
                                </>
                              )}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        )}
      </div>

      <Card padding="md" className="h-fit">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-content-secondary mb-3">
          {t('schedule_advanced.ppc_title', { defaultValue: 'Percent Plan Complete' })}
        </h3>
        <div className="flex flex-col items-center justify-center py-6">
          <div className="text-5xl font-bold text-oe-blue">
            {ppc.toFixed(0)}%
          </div>
          <div className="mt-3 h-2 w-full max-w-[200px] rounded-full bg-surface-secondary overflow-hidden">
            <div
              className="h-full bg-oe-blue transition-all"
              style={{ width: `${Math.min(ppc, 100)}%` }}
            />
          </div>
          <p className="mt-4 text-xs text-content-tertiary">
            {t('schedule_advanced.this_week', { defaultValue: 'This week' })}
          </p>
        </div>
        <dl className="mt-3 grid grid-cols-3 gap-2 text-center">
          <div>
            <dt className="text-2xs uppercase tracking-wide text-content-tertiary">
              {t('schedule_advanced.total', { defaultValue: 'Total' })}
            </dt>
            <dd className="text-base font-semibold">{commitments.length}</dd>
          </div>
          <div>
            <dt className="text-2xs uppercase tracking-wide text-content-tertiary">
              {t('schedule_advanced.completed', { defaultValue: 'Completed' })}
            </dt>
            <dd className="text-base font-semibold text-semantic-success">{completed}</dd>
          </div>
          <div>
            <dt className="text-2xs uppercase tracking-wide text-content-tertiary">
              {t('schedule_advanced.missed', { defaultValue: 'Missed' })}
            </dt>
            <dd className="text-base font-semibold text-semantic-error">{missed}</dd>
          </div>
        </dl>
      </Card>

      {addCommitment && weekPlanId && (
        <AddCommitmentModal
          projectId={projectId}
          weekPlanId={weekPlanId}
          onClose={() => setAddCommitment(false)}
          onSaved={invalidateCommitments}
        />
      )}
      <MissCommitmentDialog
        commitment={missTarget}
        onCancel={() => setMissTarget(null)}
        onConfirm={(category, description) =>
          missTarget &&
          missCommitmentMut.mutate({ id: missTarget.id, category, description })
        }
        loading={missCommitmentMut.isPending}
      />
    </div>
  );
}

function AddCommitmentModal({
  projectId,
  weekPlanId,
  onClose,
  onSaved,
}: {
  projectId: string;
  weekPlanId: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [taskRef, setTaskRef] = useState('');
  const [crew, setCrew] = useState('');
  const [qty, setQty] = useState('');
  const [unit, setUnit] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!taskRef.trim()) {
      setError(
        t('schedule_advanced.err_task_pick', {
          defaultValue: 'Pick the task this commitment delivers.',
        }),
      );
      return;
    }
    setError(null);
    setBusy(true);
    try {
      await createCommitment({
        week_plan_id: weekPlanId,
        task_ref: taskRef.trim(),
        worker_or_crew: crew || undefined,
        promised_qty: qty || undefined,
        unit: unit || undefined,
      });
      addToast({
        type: 'success',
        title: t('schedule_advanced.commitment_created', { defaultValue: 'Commitment added' }),
      });
      onSaved();
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalShell
      title={t('schedule_advanced.add_commitment', { defaultValue: 'Add commitment' })}
      subtitle={t('schedule_advanced.add_commitment_subtitle', {
        defaultValue:
          'A weekly promise made by a trade foreman. Link it to the task it delivers and the promised quantity.',
      })}
      onClose={onClose}
      onSubmit={submit}
      busy={busy}
      disabled={!taskRef.trim()}
    >
      {error && (
        <div className="rounded-md border border-semantic-error/30 bg-semantic-error-bg/40 px-3 py-2 text-sm text-semantic-error">
          {error}
        </div>
      )}
      <div>
        <label className={labelCls}>
          {t('schedule_advanced.task', { defaultValue: 'Task' })} *
        </label>
        <TaskPicker projectId={projectId} value={taskRef} onChange={setTaskRef} autoFocus />
      </div>
      <div>
        <label className={labelCls}>{t('schedule_advanced.crew', { defaultValue: 'Crew' })}</label>
        <input
          value={crew}
          onChange={(e) => setCrew(e.target.value)}
          className={inputCls}
          placeholder={t('schedule_advanced.crew_placeholder', { defaultValue: 'e.g. Concrete crew A' })}
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={labelCls}>{t('schedule_advanced.promised', { defaultValue: 'Promised' })}</label>
          <input
            type="number"
            min={0}
            value={qty}
            onChange={(e) => setQty(e.target.value)}
            className={inputCls}
          />
        </div>
        <div>
          <label className={labelCls}>{t('schedule_advanced.unit', { defaultValue: 'Unit' })}</label>
          <input
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
            className={inputCls}
            placeholder="m2, m3, lm…"
          />
        </div>
      </div>
    </ModalShell>
  );
}

const RNC_CATEGORIES: RNCCategory[] = [
  'manpower',
  'material',
  'equipment',
  'info',
  'weather',
  'predecessor',
  'changes',
  'quality',
  'other',
];

function MissCommitmentDialog({
  commitment,
  onCancel,
  onConfirm,
  loading,
}: {
  commitment: Commitment | null;
  onCancel: () => void;
  onConfirm: (category: RNCCategory, description: string) => void;
  loading: boolean;
}) {
  const { t } = useTranslation();
  const [category, setCategory] = useState<RNCCategory>('manpower');
  const [description, setDescription] = useState('');

  useEffect(() => {
    if (commitment) {
      setCategory('manpower');
      setDescription('');
    }
  }, [commitment]);

  if (!commitment) return null;

  return (
    <ModalShell
      title={t('schedule_advanced.miss_commitment_title', { defaultValue: 'Mark commitment missed' })}
      subtitle={t('schedule_advanced.miss_commitment_subtitle', {
        defaultValue:
          'Last Planner® requires a documented Reason-for-Non-Completion. This feeds the RNC Pareto for root-cause analysis.',
      })}
      onClose={onCancel}
      onSubmit={() => onConfirm(category, description)}
      busy={loading}
    >
      <div>
        <label className={labelCls}>
          {t('schedule_advanced.rnc_category', { defaultValue: 'Reason category' })} *
        </label>
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value as RNCCategory)}
          className={inputCls}
        >
          {RNC_CATEGORIES.map((cat) => (
            <option key={cat} value={cat}>
              {t(`schedule_advanced.rnc.${cat}`, { defaultValue: cat })}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className={labelCls}>{t('common.description', { defaultValue: 'Description' })}</label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
          className={clsx(inputCls, 'h-auto py-2')}
          placeholder={t('schedule_advanced.rnc_desc_placeholder', {
            defaultValue: 'What blocked completion?',
          })}
        />
      </div>
    </ModalShell>
  );
}

/* ── Constraints tab ─────────────────────────────────────────────────── */

function ConstraintsTab({
  projectId,
  lookAheads,
  lookAheadId,
  onSelectLA,
  constraints,
  loading,
  isError,
  onRetry,
  filter,
  onFilter,
}: {
  projectId: string;
  lookAheads: LookAheadPlan[];
  lookAheadId: string;
  onSelectLA: (id: string) => void;
  constraints: Constraint[];
  loading: boolean;
  isError?: boolean;
  onRetry?: () => void;
  filter: string;
  onFilter: (s: string) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [createOpen, setCreateOpen] = useState(false);

  const invalidateConstraints = () =>
    qc.invalidateQueries({
      queryKey: ['schedule-advanced', 'constraints', lookAheadId],
    });

  const clearMut = useMutation({
    mutationFn: (id: string) => clearConstraint(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['schedule-advanced', 'constraints'] });
      addToast({ type: 'success', title: t('schedule_advanced.constraint_cleared', { defaultValue: 'Constraint cleared' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const escalateMut = useMutation({
    mutationFn: (id: string) => escalateConstraint(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['schedule-advanced', 'constraints'] });
      addToast({ type: 'success', title: t('schedule_advanced.constraint_escalated', { defaultValue: 'Constraint escalated' }) });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });
  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteConstraint(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['schedule-advanced', 'constraints'] });
    },
    onError: (err) => addToast({ type: 'error', title: getErrorMessage(err) }),
  });

  if (lookAheads.length === 0) {
    return (
      <Card>
        <EmptyState
          icon={<AlertCircle size={22} />}
          title={t('schedule_advanced.no_la_for_constraints', { defaultValue: 'No look-aheads' })}
          description={t('schedule_advanced.no_la_for_constraints_desc', {
            defaultValue: 'Constraints belong to a look-ahead - create one first.',
          })}
        />
      </Card>
    );
  }

  const openCount = constraints.filter((c) => c.status === 'open').length;
  const clearedCount = constraints.filter((c) => c.status === 'cleared').length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={lookAheadId}
          onChange={(e) => onSelectLA(e.target.value)}
          className={clsx(inputCls, 'max-w-[260px]')}
        >
          {lookAheads.map((la) => (
            <option key={la.id} value={la.id}>
              {la.period_start} → {la.period_end}
            </option>
          ))}
        </select>
        <select
          value={filter}
          onChange={(e) => onFilter(e.target.value)}
          className={clsx(inputCls, 'max-w-[180px]')}
        >
          <option value="">
            {t('common.all_statuses', { defaultValue: 'All statuses' })}
          </option>
          {(['open', 'in_progress', 'cleared', 'escalated', 'cannot_clear'] as const).map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <div className="flex items-center gap-2 ml-auto text-xs">
          <span className="rounded-md bg-semantic-warning-bg px-2 py-1 text-[#b45309]">
            {t('schedule_advanced.open_count', { count: openCount, defaultValue: '{{count}} open' })}
          </span>
          <span className="rounded-md bg-semantic-success-bg px-2 py-1 text-semantic-success">
            {t('schedule_advanced.cleared_count', { count: clearedCount, defaultValue: '{{count}} cleared' })}
          </span>
          <Button
            variant="primary"
            size="sm"
            icon={<Plus size={14} />}
            onClick={() => setCreateOpen(true)}
            disabled={!lookAheadId}
          >
            {t('schedule_advanced.new_constraint', { defaultValue: 'New constraint' })}
          </Button>
        </div>
      </div>

      <Card padding="none">
        {loading ? (
          <div className="p-4">
            <SkeletonTable rows={6} columns={5} />
          </div>
        ) : isError ? (
          <div className="p-4">
            <RecoveryCard onRetry={onRetry} error={undefined} />
          </div>
        ) : constraints.length === 0 ? (
          <EmptyState
            icon={<AlertCircle size={22} />}
            title={t('schedule_advanced.no_constraints', { defaultValue: 'No constraints' })}
            description={t('schedule_advanced.no_constraints_desc', {
              defaultValue:
                'Constraints are the things blocking a task from being ready to start - missing material, permits, predecessors or information. Log one against a task so it can be cleared before the work is committed.',
            })}
            action={{
              label: t('schedule_advanced.new_constraint', { defaultValue: 'New constraint' }),
              onClick: () => setCreateOpen(true),
            }}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
                <tr>
                  <th className="px-4 py-2.5 text-left">{t('schedule_advanced.type', { defaultValue: 'Type' })}</th>
                  <th className="px-4 py-2.5 text-left">{t('common.description', { defaultValue: 'Description' })}</th>
                  <th className="px-4 py-2.5 text-left">{t('schedule_advanced.target_clear', { defaultValue: 'Target clear' })}</th>
                  <th className="px-4 py-2.5 text-left">{t('common.status', { defaultValue: 'Status' })}</th>
                  <th className="px-4 py-2.5 text-right">{t('common.actions', { defaultValue: 'Actions' })}</th>
                </tr>
              </thead>
              <tbody>
                {constraints.map((c) => (
                  <tr key={c.id} className="border-t border-border-light hover:bg-surface-secondary">
                    <td className="px-4 py-2 text-xs text-content-secondary">
                      {c.constraint_type}
                    </td>
                    <td className="px-4 py-2 truncate max-w-[360px]">
                      {c.description || '—'}
                    </td>
                    <td className="px-4 py-2 text-xs text-content-secondary">
                      {c.target_clear_date ? <DateDisplay value={c.target_clear_date} /> : '—'}
                    </td>
                    <td className="px-4 py-2">
                      <Badge variant={CONSTRAINT_VARIANT[c.status]} dot>
                        {c.status}
                      </Badge>
                    </td>
                    <td className="px-4 py-2">
                      <div className="flex justify-end gap-1">
                        {c.status !== 'cleared' && (
                          <Button
                            size="sm"
                            variant="ghost"
                            icon={<Check size={12} />}
                            onClick={() => clearMut.mutate(c.id)}
                            aria-label={t('schedule_advanced.clear', { defaultValue: 'Clear' })}
                          >
                            {t('schedule_advanced.clear', { defaultValue: 'Clear' })}
                          </Button>
                        )}
                        {c.status === 'open' && (
                          <Button
                            size="sm"
                            variant="ghost"
                            icon={<ArrowUpCircle size={12} />}
                            onClick={() => escalateMut.mutate(c.id)}
                            aria-label={t('schedule_advanced.escalate', { defaultValue: 'Escalate' })}
                          />
                        )}
                        <Button
                          size="sm"
                          variant="ghost"
                          icon={<Trash2 size={12} />}
                          onClick={() => deleteMut.mutate(c.id)}
                          aria-label={t('common.delete', { defaultValue: 'Delete' })}
                        />
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {createOpen && lookAheadId && (
        <NewConstraintModal
          projectId={projectId}
          lookAheadId={lookAheadId}
          onClose={() => setCreateOpen(false)}
          onSaved={invalidateConstraints}
        />
      )}
    </div>
  );
}

const CONSTRAINT_TYPES: ConstraintType[] = [
  'info',
  'material',
  'labor',
  'equipment',
  'permit',
  'predecessor',
  'weather',
  'other',
];

function NewConstraintModal({
  projectId,
  lookAheadId,
  onClose,
  onSaved,
}: {
  projectId: string;
  lookAheadId: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [taskRef, setTaskRef] = useState('');
  const [constraintType, setConstraintType] = useState<ConstraintType>('material');
  const [description, setDescription] = useState('');
  const [targetClear, setTargetClear] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!taskRef.trim()) {
      setError(
        t('schedule_advanced.err_task_pick', {
          defaultValue: 'Pick the task this commitment delivers.',
        }),
      );
      return;
    }
    setError(null);
    setBusy(true);
    try {
      await createConstraint({
        look_ahead_id: lookAheadId,
        task_ref: taskRef.trim(),
        constraint_type: constraintType,
        description: description.trim() || undefined,
        target_clear_date: targetClear || undefined,
      });
      addToast({
        type: 'success',
        title: t('schedule_advanced.constraint_created', { defaultValue: 'Constraint added' }),
      });
      onSaved();
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalShell
      title={t('schedule_advanced.new_constraint', { defaultValue: 'New constraint' })}
      subtitle={t('schedule_advanced.new_constraint_subtitle', {
        defaultValue:
          'Log what is blocking a task from being ready - material, permit, predecessor or information - so it can be cleared before the work is committed.',
      })}
      onClose={onClose}
      onSubmit={submit}
      busy={busy}
      disabled={!taskRef.trim()}
    >
      {error && (
        <div className="rounded-md border border-semantic-error/30 bg-semantic-error-bg/40 px-3 py-2 text-sm text-semantic-error">
          {error}
        </div>
      )}
      <div>
        <label className={labelCls}>
          {t('schedule_advanced.task', { defaultValue: 'Task' })} *
        </label>
        <TaskPicker projectId={projectId} value={taskRef} onChange={setTaskRef} autoFocus />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={labelCls}>
            {t('schedule_advanced.type', { defaultValue: 'Type' })}
          </label>
          <select
            value={constraintType}
            onChange={(e) => setConstraintType(e.target.value as ConstraintType)}
            className={inputCls}
          >
            {CONSTRAINT_TYPES.map((ct) => (
              <option key={ct} value={ct}>
                {t(`schedule_advanced.constraint_type.${ct}`, { defaultValue: ct })}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className={labelCls}>
            {t('schedule_advanced.target_clear', { defaultValue: 'Target clear' })}
          </label>
          <input
            type="date"
            value={targetClear}
            onChange={(e) => setTargetClear(e.target.value)}
            className={inputCls}
          />
        </div>
      </div>
      <div>
        <label className={labelCls}>{t('common.description', { defaultValue: 'Description' })}</label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
          className={clsx(inputCls, 'h-auto py-2')}
          placeholder={t('schedule_advanced.constraint_desc_placeholder', {
            defaultValue: 'What is blocking this task?',
          })}
        />
      </div>
    </ModalShell>
  );
}

/* ── Baselines tab ───────────────────────────────────────────────────── */

function BaselinesTab({
  masterId,
  baselines,
  loading,
  isError,
  onRetry,
  onCapture,
}: {
  masterId: string;
  baselines: Baseline[];
  loading: boolean;
  isError?: boolean;
  onRetry?: () => void;
  onCapture: () => void;
}) {
  const { t } = useTranslation();
  const [compareId, setCompareId] = useState<string>('');
  const [deltaEntries, setDeltaEntries] = useState<BaselineDeltaEntry[]>([]);
  const [delaying, setDelaying] = useState(0);
  const [accelerating, setAccelerating] = useState(0);
  const [comparing, setComparing] = useState(false);
  const addToast = useToastStore((s) => s.addToast);

  const compare = async (id: string) => {
    setCompareId(id);
    setComparing(true);
    try {
      // Always send the live phase list as "current tasks" so the
      // backend can actually compute variance. The legacy empty-array
      // call returned an empty entries list because there was nothing
      // to diff against.
      const current = masterId ? await currentTasksForMaster(masterId) : [];
      const res = await baselineDelta(id, current);
      setDeltaEntries(res.entries);
      setDelaying(res.delayed_tasks);
      setAccelerating(res.accelerated_tasks);
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setComparing(false);
    }
  };

  /**
   * Export the current delta as a CSV file so PMs can paste it into
   * Excel / share with subcontractors. Pure browser side — no server
   * round-trip, no extra dependency.
   */
  const exportCsv = () => {
    const rows = [
      ['task_ref', 'name', 'baseline_start', 'current_start', 'baseline_finish', 'current_finish', 'variance_days'],
      ...deltaEntries.map((e) => [
        e.task_ref,
        e.name ?? '',
        e.planned_start_baseline ?? '',
        e.planned_start_current ?? '',
        e.planned_finish_baseline ?? '',
        e.planned_finish_current ?? '',
        String(e.schedule_variance_days ?? 0),
      ]),
    ];
    const csv = rows
      .map((r) => r.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(','))
      .join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `baseline-variance-${compareId.slice(0, 8)}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  // Top 5 most-delayed tasks — keeps the variance card actionable
  // instead of just totals.
  const topDelays = useMemo(() => {
    return [...deltaEntries]
      .filter((e) => (e.schedule_variance_days ?? 0) > 0)
      .sort((a, b) => (b.schedule_variance_days ?? 0) - (a.schedule_variance_days ?? 0))
      .slice(0, 5);
  }, [deltaEntries]);

  if (loading) {
    return (
      <Card padding="md">
        <SkeletonTable rows={4} columns={4} />
      </Card>
    );
  }

  if (isError) {
    return <ErrorCard onRetry={onRetry} />;
  }

  if (baselines.length === 0) {
    return (
      <Card>
        <EmptyState
          icon={<GitBranch size={22} />}
          title={t('schedule_advanced.no_baselines', { defaultValue: 'No baselines yet' })}
          description={t('schedule_advanced.no_baselines_desc', {
            defaultValue: 'Capture a baseline to track variance against today’s schedule.',
          })}
          action={{
            label: t('schedule_advanced.capture_baseline', { defaultValue: 'Capture Baseline' }),
            onClick: onCapture,
          }}
        />
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button
          variant="primary"
          size="sm"
          icon={<Plus size={14} />}
          onClick={onCapture}
        >
          {t('schedule_advanced.capture_baseline', { defaultValue: 'Capture Baseline' })}
        </Button>
      </div>
      <Card padding="none">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
              <tr>
                <th className="px-4 py-2.5 text-left">{t('common.name', { defaultValue: 'Name' })}</th>
                <th className="px-4 py-2.5 text-left">{t('schedule_advanced.captured_at', { defaultValue: 'Captured' })}</th>
                <th className="px-4 py-2.5 text-left">{t('common.status', { defaultValue: 'Status' })}</th>
                <th className="px-4 py-2.5 text-right">{t('schedule_advanced.delta', { defaultValue: 'Delta vs current' })}</th>
              </tr>
            </thead>
            <tbody>
              {baselines.map((b) => (
                <tr
                  key={b.id}
                  className={clsx(
                    'border-t border-border-light hover:bg-surface-secondary',
                    b.id === compareId && 'bg-oe-blue-subtle/30',
                  )}
                >
                  <td className="px-4 py-2 font-medium">{b.name}</td>
                  <td className="px-4 py-2 text-xs text-content-secondary">
                    {b.captured_at ? <DateDisplay value={b.captured_at} /> : '—'}
                  </td>
                  <td className="px-4 py-2">
                    <Badge
                      variant={
                        b.status === 'active'
                          ? 'success'
                          : b.status === 'superseded'
                            ? 'warning'
                            : 'neutral'
                      }
                      dot
                    >
                      {b.status}
                    </Badge>
                  </td>
                  <td className="px-4 py-2 text-right">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => compare(b.id)}
                      loading={comparing && b.id === compareId}
                    >
                      {t('schedule_advanced.compare', { defaultValue: 'Compare' })}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {compareId && (
        <Card padding="md" data-testid="baseline-variance-card">
          <div className="flex items-center justify-between mb-3 gap-2 flex-wrap">
            <h3 className="text-sm font-semibold">
              {t('schedule_advanced.variance_summary', { defaultValue: 'Variance summary' })}
            </h3>
            {deltaEntries.length > 0 && (
              <Button
                size="sm"
                variant="ghost"
                icon={<Download size={12} />}
                onClick={exportCsv}
                data-testid="baseline-export-csv"
              >
                {t('schedule_advanced.export_csv', { defaultValue: 'Export CSV' })}
              </Button>
            )}
          </div>
          <dl className="grid grid-cols-3 gap-3 text-center">
            <div>
              <dt className="text-xs uppercase tracking-wide text-content-tertiary">
                {t('schedule_advanced.tasks_total', { defaultValue: 'Total tasks' })}
              </dt>
              <dd className="text-xl font-semibold">{deltaEntries.length}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-content-tertiary">
                {t('schedule_advanced.delayed', { defaultValue: 'Delayed' })}
              </dt>
              <dd className="text-xl font-semibold text-semantic-error">{delaying}</dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-content-tertiary">
                {t('schedule_advanced.accelerated', { defaultValue: 'Accelerated' })}
              </dt>
              <dd className="text-xl font-semibold text-semantic-success">{accelerating}</dd>
            </div>
          </dl>
          {deltaEntries.length === 0 && (
            <p className="mt-3 text-center text-xs text-content-tertiary">
              {t('schedule_advanced.no_variance_entries', {
                defaultValue:
                  'No variance data - the baseline snapshot was empty. Capture a new baseline now to start tracking variance.',
              })}
            </p>
          )}
          {topDelays.length > 0 && (
            <div className="mt-4">
              <div className="text-xs uppercase tracking-wide text-content-tertiary mb-2">
                {t('schedule_advanced.top_delays', { defaultValue: 'Top delays' })}
              </div>
              <ul className="space-y-1 text-sm" data-testid="baseline-top-delays">
                {topDelays.map((e) => (
                  <li
                    key={e.task_ref}
                    className="flex items-center justify-between rounded-md bg-surface-secondary/60 px-3 py-1.5"
                  >
                    <span className="truncate" title={e.name ?? e.task_ref}>
                      {e.name || `${e.task_ref.slice(0, 8)}…`}
                    </span>
                    <VarianceBadge days={e.schedule_variance_days ?? 0} />
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

/* ── Modals ──────────────────────────────────────────────────────────── */

// ModalShell is the local wrapper used by every "Create … " modal in
// the Schedule Advanced page (master schedule / weekly plan / look-ahead
// / baseline). It now delegates to the shared <WideModal> so the page
// inherits Escape handling, backdrop-click-to-close, body-scroll lock
// and the wider/cleaner layout. Callers stay unchanged.
function ModalShell({
  title,
  subtitle,
  children,
  onClose,
  onSubmit,
  busy,
  disabled,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  onClose: () => void;
  onSubmit: () => void;
  busy: boolean;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <WideModal
      open
      onClose={onClose}
      title={title}
      subtitle={subtitle}
      size="lg"
      busy={busy}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={onSubmit}
            loading={busy}
            disabled={disabled}
          >
            {t('common.create', { defaultValue: 'Create' })}
          </Button>
        </>
      }
    >
      <div className="space-y-3">{children}</div>
    </WideModal>
  );
}

function MasterFormModal({
  projectId,
  master,
  onClose,
}: {
  projectId: string;
  master?: MasterSchedule;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const isEdit = !!master;
  const [name, setName] = useState(master?.name ?? '');
  const [start, setStart] = useState(master?.planned_start ?? todayIso());
  const [finish, setFinish] = useState(master?.planned_finish ?? todayIso(180));
  const [status, setStatus] = useState<'active' | 'archived'>(
    master?.status ?? 'active',
  );
  const [notes, setNotes] = useState(master?.notes ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const validate = (): string | null => {
    if (!name.trim()) {
      return t('schedule_advanced.err_master_name_required', {
        defaultValue: 'Master schedule name is required.',
      });
    }
    if (start && finish && new Date(finish).getTime() < new Date(start).getTime()) {
      return t('schedule_advanced.err_finish_after_start', {
        defaultValue: 'Planned finish must be on or after planned start.',
      });
    }
    return null;
  };

  const submit = async () => {
    const v = validate();
    if (v) {
      setError(v);
      return;
    }
    setError(null);
    setBusy(true);
    try {
      if (isEdit && master) {
        await updateMasterSchedule(master.id, {
          name: name.trim(),
          planned_start: start || null,
          planned_finish: finish || null,
          status,
          notes,
        });
        addToast({
          type: 'success',
          title: t('schedule_advanced.master_updated', {
            defaultValue: 'Master schedule updated',
          }),
        });
      } else {
        await createMasterSchedule({
          project_id: projectId,
          name: name.trim(),
          planned_start: start || undefined,
          planned_finish: finish || undefined,
          notes,
        });
        addToast({
          type: 'success',
          title: t('schedule_advanced.master_created', {
            defaultValue: 'Master schedule created',
          }),
        });
      }
      qc.invalidateQueries({ queryKey: ['schedule-advanced', 'master', projectId] });
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <WideModal
      open
      onClose={onClose}
      title={
        isEdit
          ? t('schedule_advanced.edit_master', { defaultValue: 'Edit master schedule' })
          : t('schedule_advanced.create_master', { defaultValue: 'New master schedule' })
      }
      subtitle={t('schedule_advanced.create_master_subtitle', {
        defaultValue:
          'The master schedule is the top-level plan for this project. Phase plans, weekly plans and look-aheads all roll up to it.',
      })}
      size="lg"
      busy={busy}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            loading={busy}
            disabled={!name.trim()}
          >
            {isEdit
              ? t('common.save', { defaultValue: 'Save' })
              : t('common.create', { defaultValue: 'Create' })}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {error && (
          <div className="rounded-md border border-semantic-error/30 bg-semantic-error-bg/40 px-3 py-2 text-sm text-semantic-error">
            {error}
          </div>
        )}
        <div>
          <label className={labelCls}>{t('common.name', { defaultValue: 'Name' })} *</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className={inputCls}
            placeholder={t('schedule_advanced.master_name_placeholder', {
              defaultValue: 'e.g. Construction master schedule',
            })}
            autoFocus
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>
              {t('schedule_advanced.planned_start', { defaultValue: 'Planned start' })}
            </label>
            <input
              type="date"
              value={start}
              onChange={(e) => setStart(e.target.value)}
              className={inputCls}
            />
          </div>
          <div>
            <label className={labelCls}>
              {t('schedule_advanced.planned_finish', { defaultValue: 'Planned finish' })}
            </label>
            <input
              type="date"
              value={finish}
              onChange={(e) => setFinish(e.target.value)}
              className={inputCls}
            />
          </div>
        </div>
        {isEdit && (
          <div>
            <label className={labelCls}>{t('common.status', { defaultValue: 'Status' })}</label>
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value as 'active' | 'archived')}
              className={inputCls}
            >
              <option value="active">
                {t('schedule_advanced.master_status.active', { defaultValue: 'Active' })}
              </option>
              <option value="archived">
                {t('schedule_advanced.master_status.archived', { defaultValue: 'Archived' })}
              </option>
            </select>
            <p className="mt-1 text-xs text-content-tertiary">
              {t('schedule_advanced.master_status_hint', {
                defaultValue:
                  'Archive a schedule to keep its history without it being the working plan. Archived schedules can be reactivated here at any time.',
              })}
            </p>
          </div>
        )}
        <div>
          <label className={labelCls}>{t('common.notes', { defaultValue: 'Notes' })}</label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            className={clsx(inputCls, 'h-auto py-2')}
            placeholder={t('schedule_advanced.master_notes_placeholder', {
              defaultValue: 'Scope, contract reference, key milestones…',
            })}
          />
        </div>
      </div>
    </WideModal>
  );
}

function CreateWeeklyModal({
  masterId,
  onClose,
}: {
  masterId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [start, setStart] = useState(todayIso());
  const [end, setEnd] = useState(todayIso(7));
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      await createWeeklyPlan({
        master_schedule_id: masterId,
        week_start_date: start,
        week_end_date: end,
      });
      qc.invalidateQueries({ queryKey: ['schedule-advanced', 'weekly', masterId] });
      addToast({ type: 'success', title: t('schedule_advanced.week_created', { defaultValue: 'Weekly plan created' }) });
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalShell
      title={t('schedule_advanced.create_weekly', { defaultValue: 'New weekly work plan' })}
      subtitle={t('schedule_advanced.create_weekly_subtitle', {
        defaultValue:
          'Last Planner® weekly plan - pick the work week you want to commit to delivering.',
      })}
      onClose={onClose}
      onSubmit={submit}
      busy={busy}
    >
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={labelCls}>
            {t('schedule_advanced.week_start', { defaultValue: 'Week start' })}
          </label>
          <input
            type="date"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            className={inputCls}
          />
        </div>
        <div>
          <label className={labelCls}>
            {t('schedule_advanced.week_end', { defaultValue: 'Week end' })}
          </label>
          <input
            type="date"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            className={inputCls}
          />
        </div>
      </div>
    </ModalShell>
  );
}

function CreateLookAheadModal({
  masterId,
  onClose,
}: {
  masterId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [start, setStart] = useState(todayIso());
  const [end, setEnd] = useState(todayIso(42));
  const [weeks, setWeeks] = useState(6);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      await createLookAhead({
        master_schedule_id: masterId,
        period_start: start,
        period_end: end,
        window_weeks: weeks,
      });
      qc.invalidateQueries({ queryKey: ['schedule-advanced', 'look-aheads', masterId] });
      addToast({ type: 'success', title: t('schedule_advanced.la_created', { defaultValue: 'Look-ahead created' }) });
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalShell
      title={t('schedule_advanced.create_la', { defaultValue: 'New look-ahead plan' })}
      subtitle={t('schedule_advanced.create_la_subtitle', {
        defaultValue:
          '6-week rolling window of activities ready to be planned at the weekly level. Surfaces constraints that need clearing.',
      })}
      onClose={onClose}
      onSubmit={submit}
      busy={busy}
    >
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={labelCls}>
            {t('schedule_advanced.period_start', { defaultValue: 'Period start' })}
          </label>
          <input
            type="date"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            className={inputCls}
          />
        </div>
        <div>
          <label className={labelCls}>
            {t('schedule_advanced.period_end', { defaultValue: 'Period end' })}
          </label>
          <input
            type="date"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            className={inputCls}
          />
        </div>
      </div>
      <div>
        <label className={labelCls}>
          {t('schedule_advanced.window_weeks', { defaultValue: 'Window (weeks)' })}
        </label>
        <input
          type="number"
          min={1}
          max={24}
          value={weeks}
          onChange={(e) => setWeeks(Number(e.target.value) || 6)}
          className={inputCls}
        />
      </div>
    </ModalShell>
  );
}

function CreateBaselineModal({
  masterId,
  onClose,
}: {
  masterId: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [name, setName] = useState('');
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      await captureBaseline({
        master_schedule_id: masterId,
        name: name || 'Baseline',
        notes,
      });
      qc.invalidateQueries({ queryKey: ['schedule-advanced', 'baselines', masterId] });
      addToast({ type: 'success', title: t('schedule_advanced.baseline_created', { defaultValue: 'Baseline captured' }) });
      onClose();
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalShell
      title={t('schedule_advanced.capture_baseline', { defaultValue: 'Capture baseline' })}
      subtitle={t('schedule_advanced.capture_baseline_subtitle', {
        defaultValue:
          'Snapshot the current schedule so you can measure variance later. Pick a meaningful label, e.g. "Contract signed" or "Q2 rebaseline".',
      })}
      onClose={onClose}
      onSubmit={submit}
      busy={busy}
      disabled={!name.trim()}
    >
      <div>
        <label className={labelCls}>{t('common.name', { defaultValue: 'Name' })} *</label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className={inputCls}
        />
      </div>
      <div>
        <label className={labelCls}>{t('common.notes', { defaultValue: 'Notes' })}</label>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={3}
          className={clsx(inputCls, 'h-auto py-2')}
        />
      </div>
    </ModalShell>
  );
}
