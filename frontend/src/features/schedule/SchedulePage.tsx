import { useState, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  CalendarDays,
  ChevronRight,
  ArrowLeft,
  Plus,
  X,
  CheckCircle2,
  Clock,
  AlertTriangle,
  Minus,
  Diamond,
  BarChart3,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, Skeleton, Input } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import { scheduleApi } from './api';
import type { Schedule, Activity, GanttData } from './api';

/* ── Types ─────────────────────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
  description: string;
  classification_standard: string;
}

interface CreateScheduleForm {
  name: string;
  description: string;
  start_date: string;
  end_date: string;
}

interface CreateActivityForm {
  name: string;
  wbs_code: string;
  start_date: string;
  end_date: string;
  activity_type: 'task' | 'milestone' | 'summary';
}

/* ── Helpers ───────────────────────────────────────────────────────────── */

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  });
}

function daysBetween(start: string, end: string): number {
  const ms = new Date(end).getTime() - new Date(start).getTime();
  return Math.max(1, Math.ceil(ms / (1000 * 60 * 60 * 24)));
}

function statusColor(status: string): {
  bg: string;
  fill: string;
  text: string;
  variant: 'neutral' | 'blue' | 'success' | 'warning' | 'error';
} {
  switch (status) {
    case 'completed':
      return {
        bg: 'bg-semantic-success/20',
        fill: 'bg-semantic-success',
        text: 'text-[#15803d]',
        variant: 'success',
      };
    case 'in_progress':
      return {
        bg: 'bg-oe-blue/15',
        fill: 'bg-oe-blue',
        text: 'text-oe-blue',
        variant: 'blue',
      };
    case 'delayed':
      return {
        bg: 'bg-semantic-error/15',
        fill: 'bg-semantic-error',
        text: 'text-semantic-error',
        variant: 'error',
      };
    default:
      return {
        bg: 'bg-content-tertiary/15',
        fill: 'bg-content-tertiary',
        text: 'text-content-tertiary',
        variant: 'neutral',
      };
  }
}

/* ── Modal Overlay ─────────────────────────────────────────────────────── */

function Modal({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative z-10 w-full max-w-md rounded-2xl border border-border-light bg-surface-elevated p-6 shadow-xl animate-fade-in">
        <div className="mb-5 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-content-primary">{title}</h2>
          <button
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary transition-colors hover:bg-surface-secondary hover:text-content-primary"
          >
            <X size={16} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

/* ── Summary Stats ─────────────────────────────────────────────────────── */

function SummaryStats({
  summary,
}: {
  summary: GanttData['summary'];
}) {
  const { t } = useTranslation();

  const stats = [
    {
      label: t('schedule.total_activities', 'Total'),
      value: summary.total_activities,
      icon: BarChart3,
      color: 'text-content-primary',
      bg: 'bg-surface-secondary',
    },
    {
      label: t('schedule.completed', 'Completed'),
      value: summary.completed,
      icon: CheckCircle2,
      color: 'text-[#15803d]',
      bg: 'bg-semantic-success-bg',
    },
    {
      label: t('schedule.in_progress', 'In Progress'),
      value: summary.in_progress,
      icon: Clock,
      color: 'text-oe-blue',
      bg: 'bg-oe-blue-subtle',
    },
    {
      label: t('schedule.delayed', 'Delayed'),
      value: summary.delayed,
      icon: AlertTriangle,
      color: 'text-semantic-error',
      bg: 'bg-semantic-error-bg',
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {stats.map((stat) => {
        const Icon = stat.icon;
        return (
          <Card key={stat.label} padding="sm" className="flex items-center gap-3">
            <div
              className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${stat.bg}`}
            >
              <Icon size={16} className={stat.color} />
            </div>
            <div className="min-w-0">
              <p className="text-xl font-bold tabular-nums text-content-primary">{stat.value}</p>
              <p className="text-2xs text-content-tertiary truncate">{stat.label}</p>
            </div>
          </Card>
        );
      })}
    </div>
  );
}

/* ── Gantt Chart ───────────────────────────────────────────────────────── */

function GanttChart({
  activities,
  onUpdateProgress,
}: {
  activities: Activity[];
  onUpdateProgress: (activityId: string, progress: number) => void;
}) {
  const { t } = useTranslation();

  // Compute timeline bounds
  const { timelineStart, timelineEnd, totalDays } = useMemo(() => {
    if (activities.length === 0) {
      const now = new Date();
      const start = new Date(now);
      start.setDate(start.getDate() - 7);
      const end = new Date(now);
      end.setDate(end.getDate() + 30);
      return {
        timelineStart: start,
        timelineEnd: end,
        totalDays: 37,
      };
    }

    const starts = activities.map((a) => new Date(a.start_date).getTime());
    const ends = activities.map((a) => new Date(a.end_date).getTime());
    const minStart = new Date(Math.min(...starts));
    const maxEnd = new Date(Math.max(...ends));

    // Add padding of 2 days on each side
    minStart.setDate(minStart.getDate() - 2);
    maxEnd.setDate(maxEnd.getDate() + 2);

    const days = daysBetween(minStart.toISOString(), maxEnd.toISOString());

    return {
      timelineStart: minStart,
      timelineEnd: maxEnd,
      totalDays: days,
    };
  }, [activities]);

  // Generate month/week markers
  const monthMarkers = useMemo(() => {
    const markers: Array<{ label: string; offsetPct: number }> = [];
    const current = new Date(timelineStart);
    current.setDate(1);
    current.setMonth(current.getMonth() + 1);

    while (current <= timelineEnd) {
      const dayOffset = daysBetween(timelineStart.toISOString(), current.toISOString());
      const pct = (dayOffset / totalDays) * 100;
      if (pct >= 0 && pct <= 100) {
        markers.push({
          label: current.toLocaleDateString('en-GB', { month: 'short', year: '2-digit' }),
          offsetPct: pct,
        });
      }
      current.setMonth(current.getMonth() + 1);
    }
    return markers;
  }, [timelineStart, timelineEnd, totalDays]);

  // Compute bar positions
  const getBarStyle = useCallback(
    (activity: Activity) => {
      const startOffset = daysBetween(
        timelineStart.toISOString(),
        activity.start_date,
      );
      const duration = daysBetween(activity.start_date, activity.end_date);
      const leftPct = (startOffset / totalDays) * 100;
      const widthPct = (duration / totalDays) * 100;

      return {
        left: `${Math.max(0, leftPct)}%`,
        width: `${Math.max(0.5, widthPct)}%`,
      };
    },
    [timelineStart, totalDays],
  );

  if (activities.length === 0) {
    return (
      <EmptyState
        icon={<CalendarDays size={24} strokeWidth={1.5} />}
        title={t('schedule.no_activities', 'No activities yet')}
        description={t(
          'schedule.no_activities_hint',
          'Add activities to build your project schedule',
        )}
      />
    );
  }

  return (
    <Card padding="none" className="overflow-hidden">
      {/* Header */}
      <div className="flex border-b border-border-light bg-surface-secondary/50">
        {/* Left panel header */}
        <div className="w-[420px] shrink-0 border-r border-border-light px-4 py-2.5">
          <div className="grid grid-cols-[1fr_70px_70px_50px] gap-2 text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
            <span>{t('schedule.activity', 'Activity')}</span>
            <span>{t('schedule.start', 'Start')}</span>
            <span>{t('schedule.end', 'End')}</span>
            <span className="text-right">%</span>
          </div>
        </div>
        {/* Right panel header — month markers */}
        <div className="relative min-w-0 flex-1 px-2 py-2.5">
          {monthMarkers.map((marker) => (
            <span
              key={marker.label}
              className="absolute top-2.5 text-2xs font-medium text-content-tertiary"
              style={{ left: `${marker.offsetPct}%` }}
            >
              {marker.label}
            </span>
          ))}
        </div>
      </div>

      {/* Body rows */}
      <div className="divide-y divide-border-light">
        {activities.map((activity) => {
          const sc = statusColor(activity.status);
          const barStyle = getBarStyle(activity);
          const isMilestone = activity.activity_type === 'milestone';
          const isSummary = activity.activity_type === 'summary';

          return (
            <div
              key={activity.id}
              className="flex transition-colors hover:bg-surface-secondary/30"
            >
              {/* Left panel — activity info */}
              <div className="w-[420px] shrink-0 border-r border-border-light px-4 py-2.5">
                <div className="grid grid-cols-[1fr_70px_70px_50px] items-center gap-2">
                  {/* Name + WBS */}
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      {isMilestone && (
                        <Diamond size={12} className={`shrink-0 ${sc.text}`} fill="currentColor" />
                      )}
                      {isSummary && <Minus size={12} className="shrink-0 text-content-tertiary" />}
                      <span className="text-sm font-medium text-content-primary truncate">
                        {activity.name}
                      </span>
                    </div>
                    {activity.wbs_code && (
                      <span className="text-2xs font-mono text-content-tertiary">
                        {activity.wbs_code}
                      </span>
                    )}
                  </div>

                  {/* Dates */}
                  <span className="text-2xs tabular-nums text-content-secondary">
                    {formatDate(activity.start_date)}
                  </span>
                  <span className="text-2xs tabular-nums text-content-secondary">
                    {formatDate(activity.end_date)}
                  </span>

                  {/* Progress */}
                  <div className="flex items-center justify-end gap-1">
                    <Badge variant={sc.variant} size="sm">
                      {activity.progress_pct}%
                    </Badge>
                  </div>
                </div>

                {/* Progress slider */}
                <div className="mt-1.5 flex items-center gap-2">
                  <input
                    type="range"
                    min={0}
                    max={100}
                    step={5}
                    value={activity.progress_pct}
                    onChange={(e) => onUpdateProgress(activity.id, Number(e.target.value))}
                    className="h-1 w-full cursor-pointer appearance-none rounded-full bg-surface-secondary accent-oe-blue [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-oe-blue [&::-webkit-slider-thumb]:shadow-sm"
                  />
                </div>
              </div>

              {/* Right panel — gantt bar */}
              <div className="relative min-w-0 flex-1 px-2 py-2.5">
                {/* Vertical grid lines for month markers */}
                {monthMarkers.map((marker) => (
                  <div
                    key={`grid-${marker.label}`}
                    className="absolute top-0 bottom-0 w-px bg-border-light/50"
                    style={{ left: `${marker.offsetPct}%` }}
                  />
                ))}

                {isMilestone ? (
                  /* Diamond marker for milestones */
                  <div
                    className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2"
                    style={{ left: barStyle.left }}
                  >
                    <Diamond
                      size={16}
                      className={sc.text}
                      fill="currentColor"
                      strokeWidth={1.5}
                    />
                  </div>
                ) : (
                  /* Standard bar */
                  <div
                    className={`absolute top-1/2 -translate-y-1/2 h-7 rounded-md ${sc.bg} transition-all duration-200`}
                    style={barStyle}
                  >
                    {/* Progress fill */}
                    <div
                      className={`h-full rounded-md ${sc.fill} transition-all duration-300`}
                      style={{ width: `${activity.progress_pct}%` }}
                    />
                    {/* Label overlay */}
                    {parseFloat(barStyle.width) > 4 && (
                      <span className="absolute inset-0 flex items-center px-2 text-2xs font-medium text-content-primary truncate">
                        {activity.name}
                      </span>
                    )}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

/* ── Schedule Detail View ──────────────────────────────────────────────── */

function ScheduleDetail({
  schedule,
  onBack,
}: {
  schedule: Schedule;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [showAddActivity, setShowAddActivity] = useState(false);
  const [activityForm, setActivityForm] = useState<CreateActivityForm>({
    name: '',
    wbs_code: '',
    start_date: '',
    end_date: '',
    activity_type: 'task',
  });

  const { data: ganttData, isLoading } = useQuery({
    queryKey: ['gantt', schedule.id],
    queryFn: () => scheduleApi.getGantt(schedule.id),
  });

  const addActivity = useMutation({
    mutationFn: (data: CreateActivityForm) =>
      scheduleApi.createActivity(schedule.id, {
        name: data.name,
        wbs_code: data.wbs_code,
        start_date: data.start_date,
        end_date: data.end_date,
        activity_type: data.activity_type,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['gantt', schedule.id] });
      setShowAddActivity(false);
      setActivityForm({
        name: '',
        wbs_code: '',
        start_date: '',
        end_date: '',
        activity_type: 'task',
      });
    },
  });

  const updateProgress = useMutation({
    mutationFn: ({ activityId, progress }: { activityId: string; progress: number }) =>
      scheduleApi.updateProgress(activityId, progress),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['gantt', schedule.id] });
    },
  });

  const handleUpdateProgress = useCallback(
    (activityId: string, progress: number) => {
      updateProgress.mutate({ activityId, progress });
    },
    [updateProgress],
  );

  return (
    <div className="animate-fade-in">
      {/* Back button */}
      <button
        onClick={onBack}
        className="mb-4 flex items-center gap-1.5 text-sm text-content-secondary transition-colors hover:text-content-primary"
      >
        <ArrowLeft size={14} />
        {t('schedule.back_to_schedules', 'Back to schedules')}
      </button>

      {/* Header */}
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-content-primary">{schedule.name}</h1>
          {schedule.description && (
            <p className="mt-1 text-sm text-content-secondary">{schedule.description}</p>
          )}
          <div className="mt-3 flex items-center gap-2">
            <Badge variant="blue" size="sm">
              {schedule.status}
            </Badge>
            {schedule.start_date && (
              <Badge variant="neutral" size="sm">
                {formatDate(schedule.start_date)} &ndash;{' '}
                {schedule.end_date ? formatDate(schedule.end_date) : '...'}
              </Badge>
            )}
          </div>
        </div>
        <Button
          variant="primary"
          icon={<Plus size={16} />}
          onClick={() => setShowAddActivity(true)}
        >
          {t('schedule.add_activity', 'Add Activity')}
        </Button>
      </div>

      {/* Summary stats */}
      {ganttData && <SummaryStats summary={ganttData.summary} />}

      {/* Gantt chart */}
      <div className="mt-6">
        {isLoading ? (
          <div className="space-y-3">
            <Skeleton height={40} className="w-full" rounded="lg" />
            {[1, 2, 3, 4].map((i) => (
              <Skeleton key={i} height={56} className="w-full" rounded="lg" />
            ))}
          </div>
        ) : ganttData ? (
          <GanttChart
            activities={ganttData.activities}
            onUpdateProgress={handleUpdateProgress}
          />
        ) : null}
      </div>

      {/* Add Activity Modal */}
      <Modal
        open={showAddActivity}
        onClose={() => setShowAddActivity(false)}
        title={t('schedule.add_activity', 'Add Activity')}
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            addActivity.mutate(activityForm);
          }}
          className="space-y-4"
        >
          <Input
            label={t('schedule.activity_name', 'Activity Name')}
            placeholder={t('schedule.activity_name_placeholder', 'e.g. Foundation Works')}
            value={activityForm.name}
            onChange={(e) => setActivityForm((f) => ({ ...f, name: e.target.value }))}
            required
          />
          <Input
            label={t('schedule.wbs_code', 'WBS Code')}
            placeholder={t('schedule.wbs_code_placeholder', 'e.g. 01.02.003')}
            value={activityForm.wbs_code}
            onChange={(e) => setActivityForm((f) => ({ ...f, wbs_code: e.target.value }))}
          />
          <div className="grid grid-cols-2 gap-3">
            <Input
              label={t('schedule.start_date', 'Start Date')}
              type="date"
              value={activityForm.start_date}
              onChange={(e) => setActivityForm((f) => ({ ...f, start_date: e.target.value }))}
              required
            />
            <Input
              label={t('schedule.end_date', 'End Date')}
              type="date"
              value={activityForm.end_date}
              onChange={(e) => setActivityForm((f) => ({ ...f, end_date: e.target.value }))}
              required
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium text-content-primary">
              {t('schedule.activity_type', 'Type')}
            </label>
            <div className="flex gap-2">
              {(['task', 'milestone', 'summary'] as const).map((type) => (
                <button
                  key={type}
                  type="button"
                  onClick={() => setActivityForm((f) => ({ ...f, activity_type: type }))}
                  className={`flex-1 rounded-lg border px-3 py-2 text-sm font-medium capitalize transition-all ${
                    activityForm.activity_type === type
                      ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue'
                      : 'border-border bg-surface-primary text-content-secondary hover:bg-surface-secondary'
                  }`}
                >
                  {t(`schedule.type_${type}`, type)}
                </button>
              ))}
            </div>
          </div>
          <div className="flex items-center justify-end gap-3 pt-2">
            <Button variant="ghost" type="button" onClick={() => setShowAddActivity(false)}>
              {t('common.cancel', 'Cancel')}
            </Button>
            <Button variant="primary" type="submit" loading={addActivity.isPending}>
              {t('schedule.create_activity', 'Create Activity')}
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}

/* ── Schedule List for a Project ───────────────────────────────────────── */

function ProjectSchedules({
  project,
  onBack,
}: {
  project: Project;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [selectedSchedule, setSelectedSchedule] = useState<Schedule | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState<CreateScheduleForm>({
    name: '',
    description: '',
    start_date: '',
    end_date: '',
  });

  const { data: schedules, isLoading } = useQuery({
    queryKey: ['schedules', project.id],
    queryFn: () => scheduleApi.listSchedules(project.id),
  });

  const createSchedule = useMutation({
    mutationFn: (data: CreateScheduleForm) =>
      scheduleApi.createSchedule({
        project_id: project.id,
        name: data.name,
        description: data.description || undefined,
        start_date: data.start_date || undefined,
        end_date: data.end_date || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schedules', project.id] });
      setShowCreate(false);
      setForm({ name: '', description: '', start_date: '', end_date: '' });
    },
  });

  // If a schedule is selected, show its detail
  if (selectedSchedule) {
    return (
      <ScheduleDetail
        schedule={selectedSchedule}
        onBack={() => setSelectedSchedule(null)}
      />
    );
  }

  return (
    <div className="animate-fade-in">
      {/* Back button */}
      <button
        onClick={onBack}
        className="mb-4 flex items-center gap-1.5 text-sm text-content-secondary transition-colors hover:text-content-primary"
      >
        <ArrowLeft size={14} />
        {t('schedule.back_to_projects', 'Back to projects')}
      </button>

      {/* Header */}
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-content-primary">{project.name}</h1>
          <p className="mt-1 text-sm text-content-secondary">
            {t('schedule.project_schedules', 'Schedules for this project')}
          </p>
        </div>
        <Button
          variant="primary"
          icon={<Plus size={16} />}
          onClick={() => setShowCreate(true)}
        >
          {t('schedule.create_schedule', 'Create Schedule')}
        </Button>
      </div>

      {/* Schedule list */}
      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} height={72} className="w-full" rounded="lg" />
          ))}
        </div>
      ) : !schedules || schedules.length === 0 ? (
        <EmptyState
          icon={<CalendarDays size={24} strokeWidth={1.5} />}
          title={t('schedule.no_schedules', 'No schedules yet')}
          description={t(
            'schedule.no_schedules_hint',
            'Create a schedule to start planning your project timeline',
          )}
          action={
            <Button variant="primary" size="sm" onClick={() => setShowCreate(true)}>
              {t('schedule.create_schedule', 'Create Schedule')}
            </Button>
          }
        />
      ) : (
        <div className="space-y-3">
          {schedules.map((schedule) => (
            <Card
              key={schedule.id}
              hoverable
              padding="none"
              className="cursor-pointer"
              onClick={() => setSelectedSchedule(schedule)}
            >
              <div className="flex items-center gap-3 px-5 py-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue">
                  <CalendarDays size={18} strokeWidth={1.75} />
                </div>
                <div className="min-w-0 flex-1">
                  <h2 className="text-sm font-semibold text-content-primary truncate">
                    {schedule.name}
                  </h2>
                  <p className="mt-0.5 text-xs text-content-secondary truncate">
                    {schedule.description ||
                      (schedule.start_date
                        ? `${formatDate(schedule.start_date)}${schedule.end_date ? ` \u2013 ${formatDate(schedule.end_date)}` : ''}`
                        : t('schedule.no_dates', 'No dates set'))}
                  </p>
                </div>
                <Badge variant={schedule.status === 'active' ? 'blue' : 'neutral'} size="sm">
                  {schedule.status}
                </Badge>
                <ChevronRight size={16} className="shrink-0 text-content-tertiary" />
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* Create Schedule Modal */}
      <Modal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        title={t('schedule.create_schedule', 'Create Schedule')}
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            createSchedule.mutate(form);
          }}
          className="space-y-4"
        >
          <Input
            label={t('schedule.schedule_name', 'Schedule Name')}
            placeholder={t('schedule.schedule_name_placeholder', 'e.g. Main Construction Schedule')}
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            required
          />
          <Input
            label={t('schedule.description', 'Description')}
            placeholder={t('schedule.description_placeholder', 'Optional description')}
            value={form.description}
            onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
          />
          <div className="grid grid-cols-2 gap-3">
            <Input
              label={t('schedule.start_date', 'Start Date')}
              type="date"
              value={form.start_date}
              onChange={(e) => setForm((f) => ({ ...f, start_date: e.target.value }))}
            />
            <Input
              label={t('schedule.end_date', 'End Date')}
              type="date"
              value={form.end_date}
              onChange={(e) => setForm((f) => ({ ...f, end_date: e.target.value }))}
            />
          </div>
          <div className="flex items-center justify-end gap-3 pt-2">
            <Button variant="ghost" type="button" onClick={() => setShowCreate(false)}>
              {t('common.cancel', 'Cancel')}
            </Button>
            <Button variant="primary" type="submit" loading={createSchedule.isPending}>
              {t('common.create', 'Create')}
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function SchedulePage() {
  const { t } = useTranslation();
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);

  const { data: projects, isLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
  });

  // Project schedule detail view
  if (selectedProject) {
    return (
      <div className="max-w-content mx-auto animate-fade-in">
        <ProjectSchedules
          project={selectedProject}
          onBack={() => setSelectedProject(null)}
        />
      </div>
    );
  }

  // Project list view
  return (
    <div className="max-w-content mx-auto animate-fade-in">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-content-primary">
          {t('schedule.title', '4D Schedule')}
        </h1>
        <p className="mt-1 text-sm text-content-secondary">
          {t(
            'schedule.subtitle',
            'Select a project to view and manage its construction schedule',
          )}
        </p>
      </div>

      {isLoading ? (
        <div className="space-y-4">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} height={72} className="w-full" rounded="lg" />
          ))}
        </div>
      ) : !projects || projects.length === 0 ? (
        <EmptyState
          icon={<CalendarDays size={24} strokeWidth={1.5} />}
          title={t('schedule.no_projects', 'No projects available')}
          description={t(
            'schedule.no_projects_hint',
            'Create a project first, then add schedules to it',
          )}
        />
      ) : (
        <div className="space-y-3">
          {projects.map((project) => (
            <Card
              key={project.id}
              hoverable
              padding="none"
              className="cursor-pointer"
              onClick={() => setSelectedProject(project)}
            >
              <div className="flex items-center gap-3 px-5 py-4">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue font-bold">
                  {project.name.charAt(0).toUpperCase()}
                </div>
                <div className="min-w-0 flex-1">
                  <h2 className="text-sm font-semibold text-content-primary truncate">
                    {project.name}
                  </h2>
                  {project.description && (
                    <p className="mt-0.5 text-xs text-content-secondary truncate">
                      {project.description}
                    </p>
                  )}
                </div>
                <Badge variant="blue" size="sm">
                  {project.classification_standard}
                </Badge>
                <ChevronRight size={16} className="shrink-0 text-content-tertiary" />
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
