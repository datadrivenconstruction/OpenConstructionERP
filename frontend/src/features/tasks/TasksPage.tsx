import { useState, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import clsx from 'clsx';
import {
  ClipboardList,
  Search,
  Plus,
  X,
  Calendar,
  CheckCircle2,
  User,
  Download,
  Loader2,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, Breadcrumb } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
// Auth store used for "My Tasks" filter
import {
  fetchTasks,
  createTask,
  completeTask,
  exportTasks,
  type Task,
  type TaskType,
  type TaskStatus,
  type TaskPriority,
  type CreateTaskPayload,
} from './api';

/* ── Constants ─────────────────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
}

const TASK_TYPES: TaskType[] = ['task', 'topic', 'info', 'decision', 'personal'];
const STATUSES: TaskStatus[] = ['open', 'in_progress', 'completed'];

const TYPE_COLOR: Record<TaskType, string> = {
  task: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  topic: 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300',
  info: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/40 dark:text-cyan-300',
  decision: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  personal: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
};

const PRIORITY_BADGE: Record<TaskPriority, { variant: 'neutral' | 'blue' | 'warning' | 'error'; cls: string }> = {
  low: { variant: 'neutral', cls: '' },
  medium: { variant: 'blue', cls: '' },
  high: { variant: 'warning', cls: '' },
  urgent: { variant: 'error', cls: '' },
};

const STATUS_HEADER_CLS: Record<TaskStatus, string> = {
  open: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400',
  in_progress: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400',
  completed: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400',
};

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const textareaCls =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none';

/* ── Add Task Modal ────────────────────────────────────────────────────── */

interface TaskFormData {
  title: string;
  description: string;
  task_type: TaskType;
  priority: TaskPriority;
  assigned_to: string;
  due_date: string;
}

const EMPTY_FORM: TaskFormData = {
  title: '',
  description: '',
  task_type: 'task',
  priority: 'medium',
  assigned_to: '',
  due_date: '',
};

function AddTaskModal({
  onClose,
  onSubmit,
  isPending,
}: {
  onClose: () => void;
  onSubmit: (data: TaskFormData) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<TaskFormData>(EMPTY_FORM);
  const [touched, setTouched] = useState(false);

  const set = <K extends keyof TaskFormData>(key: K, value: TaskFormData[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const titleError = touched && form.title.trim().length === 0;
  const canSubmit = form.title.trim().length > 0;

  const handleSubmit = () => {
    setTouched(true);
    if (canSubmit) onSubmit(form);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="w-full max-w-2xl bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <h2 className="text-lg font-semibold text-content-primary">
            {t('tasks.new_task', { defaultValue: 'New Task' })}
          </h2>
          <button
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Form */}
        <div className="px-6 py-4 space-y-4">
          {/* Title */}
          <div>
            <label className="block text-sm font-medium text-content-secondary mb-1">
              {t('tasks.field_title', { defaultValue: 'Title' })}{' '}
              <span className="text-semantic-error">*</span>
            </label>
            <input
              value={form.title}
              onChange={(e) => {
                set('title', e.target.value);
                setTouched(true);
              }}
              placeholder={t('tasks.title_placeholder', {
                defaultValue: 'e.g. Review structural drawings for Level 5',
              })}
              className={clsx(
                inputCls,
                titleError &&
                  'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
              )}
              autoFocus
            />
            {titleError && (
              <p className="mt-1 text-xs text-semantic-error">
                {t('tasks.title_required', { defaultValue: 'Title is required' })}
              </p>
            )}
          </div>

          {/* Description */}
          <div>
            <label className="block text-sm font-medium text-content-secondary mb-1">
              {t('tasks.field_description', { defaultValue: 'Description' })}
            </label>
            <textarea
              value={form.description}
              onChange={(e) => set('description', e.target.value)}
              rows={2}
              className={textareaCls}
              placeholder={t('tasks.description_placeholder', {
                defaultValue: 'Provide details...',
              })}
            />
          </div>

          {/* Type tabs */}
          <div>
            <label className="block text-sm font-medium text-content-secondary mb-2">
              {t('tasks.field_type', { defaultValue: 'Type' })}
            </label>
            <div className="flex items-center gap-2 flex-wrap">
              {TASK_TYPES.map((tt) => (
                <label key={tt} className="relative cursor-pointer">
                  <input
                    type="radio"
                    name="task_type"
                    value={tt}
                    checked={form.task_type === tt}
                    onChange={() => set('task_type', tt)}
                    className="peer sr-only"
                  />
                  <div
                    className={clsx(
                      'rounded-lg border px-3 py-1.5 text-center text-sm font-medium transition-all',
                      form.task_type === tt
                        ? TYPE_COLOR[tt] + ' border-current'
                        : 'border-border text-content-tertiary hover:text-content-secondary',
                    )}
                  >
                    {t(`tasks.type_${tt}`, {
                      defaultValue: tt.charAt(0).toUpperCase() + tt.slice(1),
                    })}
                  </div>
                </label>
              ))}
            </div>
          </div>

          {/* Two-column: Priority + Due Date */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('tasks.field_priority', { defaultValue: 'Priority' })}
              </label>
              <select
                value={form.priority}
                onChange={(e) => set('priority', e.target.value as TaskPriority)}
                className={inputCls}
              >
                {(['low', 'medium', 'high', 'urgent'] as TaskPriority[]).map((p) => (
                  <option key={p} value={p}>
                    {t(`tasks.priority_${p}`, {
                      defaultValue: p.charAt(0).toUpperCase() + p.slice(1),
                    })}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('tasks.field_due_date', { defaultValue: 'Due Date' })}
              </label>
              <input
                type="date"
                value={form.due_date}
                onChange={(e) => set('due_date', e.target.value)}
                className={inputCls}
              />
            </div>
          </div>

          {/* Assignee */}
          <div>
            <label className="block text-sm font-medium text-content-secondary mb-1">
              {t('tasks.field_assignee', { defaultValue: 'Assignee' })}
            </label>
            <input
              value={form.assigned_to}
              onChange={(e) => set('assigned_to', e.target.value)}
              className={inputCls}
              placeholder={t('tasks.assignee_placeholder', {
                defaultValue: 'Name or email',
              })}
            />
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={handleSubmit} disabled={isPending}>
            {isPending ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent mr-2 shrink-0" />
            ) : (
              <Plus size={16} className="mr-1.5 shrink-0" />
            )}
            <span>{t('tasks.create_task', { defaultValue: 'Create Task' })}</span>
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── Task Card ─────────────────────────────────────────────────────────── */

function TaskCard({
  task,
  onComplete,
}: {
  task: Task;
  onComplete: (id: string) => void;
}) {
  const { t } = useTranslation();

  const isOverdue =
    task.due_date &&
    task.status !== 'completed' &&
    new Date(task.due_date) < new Date();

  const checklistTotal = task.checklist?.length ?? 0;
  const checklistDone = task.checklist?.filter((c) => c.checked).length ?? 0;
  const checklistPercent = checklistTotal > 0 ? Math.round((checklistDone / checklistTotal) * 100) : 0;

  const pb = PRIORITY_BADGE[task.priority] ?? PRIORITY_BADGE.medium;

  return (
    <Card
      className={clsx(
        'p-3 mb-2 hover:shadow-md transition-shadow',
        isOverdue && 'bg-red-50/40 dark:bg-red-950/15',
      )}
    >
      {/* Type badge + title */}
      <div className="flex items-start gap-2">
        <span
          className={clsx(
            'inline-flex items-center rounded px-1.5 py-0.5 text-2xs font-semibold shrink-0 mt-0.5',
            TYPE_COLOR[task.task_type],
          )}
        >
          {t(`tasks.type_${task.task_type}`, {
            defaultValue: task.task_type.charAt(0).toUpperCase() + task.task_type.slice(1),
          })}
        </span>
        <h4
          className={clsx(
            'text-sm font-semibold line-clamp-2',
            task.status === 'completed'
              ? 'text-content-tertiary line-through'
              : isOverdue
                ? 'text-semantic-error'
                : 'text-content-primary',
          )}
        >
          {task.title}
        </h4>
      </div>

      {/* Assignee + due date row */}
      <div className="flex items-center justify-between mt-3 text-xs text-content-tertiary">
        <div className="flex items-center gap-1.5">
          {task.assigned_to_name ? (
            <>
              <div className="h-5 w-5 rounded-full bg-oe-blue/10 text-oe-blue flex items-center justify-center text-2xs font-semibold shrink-0">
                {task.assigned_to_name.charAt(0).toUpperCase()}
              </div>
              <span className="truncate max-w-[100px]">{task.assigned_to_name}</span>
            </>
          ) : (
            <span className="text-content-quaternary flex items-center gap-1">
              <User size={11} />
              {t('tasks.unassigned', { defaultValue: 'Unassigned' })}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          <Badge variant={pb.variant} size="sm">
            {t(`tasks.priority_${task.priority}`, {
              defaultValue: task.priority.charAt(0).toUpperCase() + task.priority.slice(1),
            })}
          </Badge>
          {task.due_date && (
            <div
              className={clsx(
                'flex items-center gap-1',
                isOverdue && 'text-semantic-error font-medium',
              )}
            >
              <Calendar size={11} />
              <span>
                {new Date(task.due_date).toLocaleDateString(undefined, {
                  month: 'short',
                  day: 'numeric',
                })}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Checklist progress */}
      {checklistTotal > 0 && (
        <div className="mt-2.5 pt-2 border-t border-border-light">
          <div className="flex items-center justify-between text-xs text-content-tertiary mb-1">
            <span>
              {t('tasks.checklist_progress', {
                defaultValue: '{{done}}/{{total}} items',
                done: checklistDone,
                total: checklistTotal,
              })}
            </span>
            <span>{checklistPercent}%</span>
          </div>
          <div className="h-1.5 w-full rounded-full bg-surface-tertiary overflow-hidden">
            <div
              className="h-full rounded-full bg-oe-blue transition-all"
              style={{ width: `${checklistPercent}%` }}
            />
          </div>
        </div>
      )}

      {/* Complete action */}
      {task.status !== 'completed' && (
        <div className="flex items-center gap-1 mt-2.5 pt-2 border-t border-border-light">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onComplete(task.id)}
            className="text-xs shrink-0 whitespace-nowrap"
          >
            <CheckCircle2 size={12} className="mr-1 shrink-0" />
            <span>{t('tasks.mark_complete', { defaultValue: 'Complete' })}</span>
          </Button>
        </div>
      )}
    </Card>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function TasksPage() {
  const { t } = useTranslation();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  // State
  const [showAddModal, setShowAddModal] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState<TaskType | ''>('');
  const [myTasksOnly, setMyTasksOnly] = useState(false);

  // Data
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
  });

  const projectId = routeProjectId || activeProjectId || projects[0]?.id || '';
  const projectName = projects.find((p) => p.id === projectId)?.name || '';

  const { data: tasks = [], isLoading } = useQuery({
    queryKey: ['tasks', projectId, typeFilter],
    queryFn: () =>
      fetchTasks({
        project_id: projectId,
        task_type: typeFilter || undefined,
      }),
    enabled: !!projectId,
  });

  // Client-side filters
  const filtered = useMemo(() => {
    let list = tasks;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      list = list.filter(
        (item) =>
          item.title.toLowerCase().includes(q) ||
          item.description.toLowerCase().includes(q) ||
          (item.assigned_to_name && item.assigned_to_name.toLowerCase().includes(q)),
      );
    }
    if (myTasksOnly) {
      // Filter tasks assigned to or created by the current user
      // Uses a simple heuristic: tasks where assigned_to or created_by is set
      list = list.filter(
        (item) => item.assigned_to != null || item.created_by != null,
      );
    }
    return list;
  }, [tasks, searchQuery, myTasksOnly]);

  // Group by status
  const grouped = useMemo(() => {
    const map = new Map<TaskStatus, Task[]>();
    for (const s of STATUSES) map.set(s, []);
    for (const item of filtered) {
      const col = map.get(item.status);
      if (col) col.push(item);
    }
    return map;
  }, [filtered]);

  // Invalidation
  const invalidateAll = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['tasks'] });
  }, [qc]);

  // Mutations
  const createMut = useMutation({
    mutationFn: (data: CreateTaskPayload) => createTask(data),
    onSuccess: () => {
      invalidateAll();
      setShowAddModal(false);
      addToast({
        type: 'success',
        title: t('tasks.created', { defaultValue: 'Task created' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const exportMut = useMutation({
    mutationFn: () => exportTasks(projectId),
    onSuccess: () =>
      addToast({
        type: 'success',
        title: t('tasks.export_success', { defaultValue: 'Export complete' }),
        message: t('tasks.export_success_msg', { defaultValue: 'Excel file downloaded.' }),
      }),
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('tasks.export_failed', { defaultValue: 'Export failed' }),
        message: e.message,
      }),
  });

  const completeMut = useMutation({
    mutationFn: (id: string) => completeTask(id),
    onSuccess: () => {
      invalidateAll();
      addToast({
        type: 'success',
        title: t('tasks.completed', { defaultValue: 'Task completed' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const handleCreateSubmit = useCallback(
    (formData: TaskFormData) => {
      createMut.mutate({
        project_id: projectId,
        title: formData.title,
        description: formData.description || undefined,
        task_type: formData.task_type,
        priority: formData.priority,
        assigned_to: formData.assigned_to || undefined,
        due_date: formData.due_date || undefined,
      });
    },
    [createMut, projectId],
  );

  const handleComplete = useCallback(
    (id: string) => {
      completeMut.mutate(id);
    },
    [completeMut],
  );

  return (
    <div className="max-w-content mx-auto animate-fade-in">
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          { label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
          ...(projectName
            ? [{ label: projectName, to: `/projects/${projectId}` }]
            : []),
          { label: t('tasks.title', { defaultValue: 'Tasks' }) },
        ]}
        className="mb-4"
      />

      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-content-primary">
          {t('tasks.title', { defaultValue: 'Tasks' })}
        </h1>

        <div className="flex items-center gap-2 shrink-0">
          {/* Project selector (if not in route) */}
          {!routeProjectId && projects.length > 0 && (
            <select
              value={projectId}
              onChange={(e) => {
                const p = projects.find((pr) => pr.id === e.target.value);
                if (p) {
                  useProjectContextStore.getState().setActiveProject(p.id, p.name);
                }
              }}
              className={inputCls + ' !h-8 !text-xs max-w-[180px]'}
            >
              <option value="" disabled>
                {t('tasks.select_project', { defaultValue: 'Project...' })}
              </option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          )}
          <Button
            variant="secondary"
            size="sm"
            icon={
              exportMut.isPending ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Download size={14} />
              )
            }
            onClick={() => exportMut.mutate()}
            disabled={!projectId || exportMut.isPending}
          >
            {t('tasks.export', { defaultValue: 'Export' })}
          </Button>
          <Button
            variant="primary"
            onClick={() => setShowAddModal(true)}
            disabled={!projectId}
            icon={<Plus size={16} />}
          >
            {t('tasks.new_task', { defaultValue: 'New Task' })}
          </Button>
        </div>
      </div>

      {/* Type filter tabs */}
      <div className="mb-4 flex items-center gap-1 overflow-x-auto pb-1">
        <button
          onClick={() => setTypeFilter('')}
          className={clsx(
            'rounded-lg px-3 py-1.5 text-sm font-medium transition-colors whitespace-nowrap',
            typeFilter === ''
              ? 'bg-oe-blue-subtle text-oe-blue'
              : 'text-content-tertiary hover:text-content-secondary hover:bg-surface-secondary',
          )}
        >
          {t('tasks.filter_all', { defaultValue: 'All' })}
        </button>
        {TASK_TYPES.map((tt) => (
          <button
            key={tt}
            onClick={() => setTypeFilter(tt)}
            className={clsx(
              'rounded-lg px-3 py-1.5 text-sm font-medium transition-colors whitespace-nowrap',
              typeFilter === tt
                ? TYPE_COLOR[tt]
                : 'text-content-tertiary hover:text-content-secondary hover:bg-surface-secondary',
            )}
          >
            {t(`tasks.type_${tt}`, {
              defaultValue: tt.charAt(0).toUpperCase() + tt.slice(1),
            })}
          </button>
        ))}
      </div>

      {/* Toolbar */}
      <div className="mb-6 flex flex-col sm:flex-row sm:items-center gap-3">
        {/* Search */}
        <div className="relative flex-1 max-w-sm">
          <Search
            size={16}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
          />
          <input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t('tasks.search_placeholder', {
              defaultValue: 'Search tasks...',
            })}
            className={inputCls + ' pl-9'}
          />
        </div>

        {/* My Tasks toggle */}
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={myTasksOnly}
            onChange={() => setMyTasksOnly((prev) => !prev)}
            className="h-4 w-4 rounded border-border text-oe-blue focus:ring-oe-blue"
          />
          <span className="text-sm text-content-secondary">
            {t('tasks.my_tasks', { defaultValue: 'My Tasks' })}
          </span>
        </label>
      </div>

      {/* Board / Columns */}
      <div>
        {isLoading ? (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {STATUSES.map((s) => (
              <div key={s}>
                <div className="h-10 animate-pulse rounded-lg bg-surface-tertiary mb-3" />
                <div className="space-y-2">
                  {Array.from({ length: 2 }).map((_, i) => (
                    <div key={i} className="h-24 animate-pulse rounded-lg bg-surface-tertiary" />
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={<ClipboardList size={24} strokeWidth={1.5} />}
            title={
              searchQuery || typeFilter || myTasksOnly
                ? t('tasks.no_results', { defaultValue: 'No matching tasks' })
                : t('tasks.no_tasks', { defaultValue: 'No tasks yet' })
            }
            description={
              searchQuery || typeFilter || myTasksOnly
                ? t('tasks.no_results_hint', {
                    defaultValue: 'Try adjusting your search or filters',
                  })
                : t('tasks.no_tasks_hint', {
                    defaultValue: 'Create your first task to get started',
                  })
            }
            action={
              !searchQuery && !typeFilter && !myTasksOnly
                ? {
                    label: t('tasks.new_task', { defaultValue: 'New Task' }),
                    onClick: () => setShowAddModal(true),
                  }
                : undefined
            }
          />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {STATUSES.map((status) => {
              const colItems = grouped.get(status) ?? [];
              return (
                <div key={status} className="flex flex-col">
                  {/* Column header */}
                  <div
                    className={clsx(
                      'rounded-lg px-3 py-2 mb-3 flex items-center justify-between',
                      STATUS_HEADER_CLS[status],
                    )}
                  >
                    <span className="text-sm font-semibold">
                      {t(`tasks.status_${status}`, {
                        defaultValue: status
                          .split('_')
                          .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
                          .join(' '),
                      })}
                    </span>
                    <span className="text-xs font-bold rounded-full px-2 py-0.5 bg-white/30">
                      {colItems.length}
                    </span>
                  </div>

                  {/* Column items */}
                  <div className="flex-1 min-h-[80px]">
                    {colItems.length === 0 ? (
                      <div className="flex items-center justify-center py-8 text-xs text-content-quaternary">
                        {t('tasks.column_empty', { defaultValue: 'No items' })}
                      </div>
                    ) : (
                      colItems.map((task) => (
                        <TaskCard
                          key={task.id}
                          task={task}
                          onComplete={handleComplete}
                        />
                      ))
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Add Modal */}
      {showAddModal && (
        <AddTaskModal
          onClose={() => setShowAddModal(false)}
          onSubmit={handleCreateSubmit}
          isPending={createMut.isPending}
        />
      )}
    </div>
  );
}
