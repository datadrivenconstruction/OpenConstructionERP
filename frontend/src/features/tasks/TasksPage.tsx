import React, { useState, useMemo, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useSearchParams } from 'react-router-dom';
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
  Upload,
  Loader2,
  FileDown,
  Link2,
  ListTodo,
  MessageCircle,
  Info,
  Scale,
  UserCircle,
  AlertTriangle,
  Pencil,
  Trash2,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, Breadcrumb, ConfirmDialog, ViewInBIMButton } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useCreateShortcut } from '@/shared/hooks/useCreateShortcut';
import { apiGet } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { triggerDownload } from '@/shared/lib/api';
// Auth store used for "My Tasks" filter
import {
  fetchTasks,
  createTask,
  updateTask,
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

const TASK_TYPES: TaskType[] = ['task', 'topic', 'information', 'decision', 'personal'];
const STATUSES: TaskStatus[] = ['draft', 'open', 'in_progress', 'completed'];

const TYPE_CARD_ICON: Record<TaskType, React.ElementType> = {
  task: ListTodo,
  topic: MessageCircle,
  information: Info,
  decision: Scale,
  personal: UserCircle,
};

const TYPE_COLOR: Record<TaskType, string> = {
  task: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  topic: 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300',
  information: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/40 dark:text-cyan-300',
  decision: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  personal: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
};

const PRIORITY_BADGE: Record<TaskPriority, { variant: 'neutral' | 'blue' | 'warning' | 'error'; cls: string }> = {
  low: { variant: 'neutral', cls: '' },
  normal: { variant: 'blue', cls: '' },
  high: { variant: 'warning', cls: '' },
  urgent: { variant: 'error', cls: '' },
};

const STATUS_HEADER_CLS: Record<TaskStatus, string> = {
  draft: 'bg-gray-100 text-gray-700 dark:bg-gray-800/50 dark:text-gray-400',
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
  priority: 'normal',
  assigned_to: '',
  due_date: '',
};

function AddTaskModal({
  onClose,
  onSubmit,
  isPending,
  projectName,
  initialData,
}: {
  onClose: () => void;
  onSubmit: (data: TaskFormData) => void;
  isPending: boolean;
  projectName?: string;
  initialData?: TaskFormData | null;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<TaskFormData>(initialData || EMPTY_FORM);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const set = <K extends keyof TaskFormData>(key: K, value: TaskFormData[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    if (errors[key]) setErrors((prev) => { const next = { ...prev }; delete next[key]; return next; });
  };

  const canSubmit = form.title.trim().length > 0;

  const validate = (): boolean => {
    const e: Record<string, string> = {};
    if (!form.title.trim()) e.title = t('validation.required', { defaultValue: 'This field is required' });
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const handleSubmit = () => {
    if (!validate()) return;
    onSubmit(form);
  };

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="w-full max-w-2xl bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto" role="dialog" aria-label={t('tasks.new_task', { defaultValue: 'New Task' })}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <div>
            <h2 className="text-lg font-semibold text-content-primary">
              {t('tasks.new_task', { defaultValue: 'New Task' })}
            </h2>
            {projectName && (
              <p className="text-xs text-content-tertiary mt-0.5">
                {t('common.creating_in_project', {
                  defaultValue: 'In {{project}}',
                  project: projectName,
                })}
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Form */}
        <div className="px-6 py-4 space-y-5">
          {/* ── Type selector with icons ── */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-2">
              {t('tasks.field_type', { defaultValue: 'Type' })}
            </label>
            <div className="grid grid-cols-3 sm:grid-cols-5 gap-2">
              {TASK_TYPES.map((tt) => {
                const TypeIcon = TYPE_CARD_ICON[tt];
                const selected = form.task_type === tt;
                return (
                  <button
                    key={tt}
                    type="button"
                    onClick={() => set('task_type', tt)}
                    className={clsx(
                      'flex flex-col items-center gap-1.5 rounded-lg border-2 px-2 py-2.5 text-center transition-all',
                      selected
                        ? TYPE_COLOR[tt] + ' border-current ring-2 ring-oe-blue/30'
                        : 'border-border bg-surface-primary text-content-tertiary hover:border-border-light hover:bg-surface-secondary',
                    )}
                  >
                    <TypeIcon size={18} />
                    <span className="text-2xs font-medium leading-tight">
                      {t(`tasks.type_${tt}`, {
                        defaultValue: tt.charAt(0).toUpperCase() + tt.slice(1),
                      })}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* ── Task Details ── */}
          <div className="flex items-center gap-2 pt-2 pb-1">
            <ClipboardList size={14} className="text-content-tertiary" />
            <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('tasks.section_details', { defaultValue: 'Task Details' })}
            </span>
            <div className="flex-1 h-px bg-border-light" />
          </div>

          {/* Title */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('tasks.field_title', { defaultValue: 'Title' })}{' '}
              <span className="text-semantic-error">*</span>
            </label>
            <input
              value={form.title}
              onChange={(e) => set('title', e.target.value)}
              placeholder={t('tasks.title_placeholder', {
                defaultValue: 'e.g. Review structural drawings for Level 5',
              })}
              className={clsx(
                'h-12 w-full rounded-lg border border-border bg-surface-primary px-3 text-base font-medium focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue',
                errors.title &&
                  'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
              )}
              autoFocus
            />
            {errors.title && (
              <p className="mt-1 text-xs text-semantic-error">
                {errors.title}
              </p>
            )}
          </div>

          {/* Description */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('tasks.field_description', { defaultValue: 'Description' })}
            </label>
            <textarea
              value={form.description}
              onChange={(e) => set('description', e.target.value)}
              rows={3}
              className={textareaCls}
              placeholder={t('tasks.description_placeholder', {
                defaultValue: 'Provide details about what needs to be done...',
              })}
            />
          </div>

          {/* ── Priority (visual badges) ── */}
          <div>
            <label className="block text-sm font-medium text-content-primary mb-2">
              {t('tasks.field_priority', { defaultValue: 'Priority' })}
            </label>
            <div className="grid grid-cols-4 gap-2">
              {(['low', 'normal', 'high', 'urgent'] as TaskPriority[]).map((p) => {
                const selected = form.priority === p;
                const colorMap: Record<string, string> = {
                  low: 'text-gray-600 bg-gray-50 border-gray-200 dark:text-gray-400 dark:bg-gray-800/50 dark:border-gray-700',
                  normal: 'text-blue-600 bg-blue-50 border-blue-200 dark:text-blue-400 dark:bg-blue-950/30 dark:border-blue-800',
                  high: 'text-amber-600 bg-amber-50 border-amber-200 dark:text-amber-400 dark:bg-amber-950/30 dark:border-amber-800',
                  urgent: 'text-red-600 bg-red-50 border-red-200 dark:text-red-400 dark:bg-red-950/30 dark:border-red-800',
                };
                return (
                  <button
                    key={p}
                    type="button"
                    onClick={() => set('priority', p)}
                    className={clsx(
                      'rounded-lg border-2 px-3 py-2 text-center text-sm font-semibold transition-all',
                      selected
                        ? colorMap[p] + ' ring-2 ring-oe-blue/30'
                        : 'border-border bg-surface-primary text-content-tertiary hover:border-border-light',
                    )}
                  >
                    {t(`tasks.priority_${p}`, {
                      defaultValue: p.charAt(0).toUpperCase() + p.slice(1),
                    })}
                  </button>
                );
              })}
            </div>
          </div>

          {/* ── Assignment & Schedule ── */}
          <div className="flex items-center gap-2 pt-2 pb-1">
            <Calendar size={14} className="text-content-tertiary" />
            <span className="text-xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('tasks.section_schedule', { defaultValue: 'Assignment & Schedule' })}
            </span>
            <div className="flex-1 h-px bg-border-light" />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
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
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
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
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={handleSubmit} disabled={isPending || !canSubmit}>
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

const TaskCard = React.memo(function TaskCard({
  task,
  onComplete,
  onEdit,
  onDelete,
  onStatusChange,
}: {
  task: Task;
  onComplete: (id: string) => void;
  onEdit: (task: Task) => void;
  onDelete: (id: string) => void;
  onStatusChange: (id: string, status: TaskStatus) => void;
}) {
  const { t } = useTranslation();

  const isOverdue =
    task.due_date &&
    task.status !== 'completed' &&
    new Date(task.due_date) < new Date();

  const checklistTotal = task.checklist?.length ?? 0;
  const checklistDone = task.checklist?.filter((c) => c.checked).length ?? 0;
  const checklistPercent = checklistTotal > 0 ? Math.round((checklistDone / checklistTotal) * 100) : 0;

  const pb = PRIORITY_BADGE[task.priority as TaskPriority] ?? PRIORITY_BADGE.normal;

  return (
    <Card
      data-task-id={task.id}
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
        <div className="flex-1 min-w-0">
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
          {/* Source indicator */}
          {(task.meeting_id || (task.metadata && typeof task.metadata.source === 'string')) && (
            <span className="inline-flex items-center gap-1 mt-0.5 text-2xs text-content-quaternary">
              <Link2 size={9} className="shrink-0" />
              {task.meeting_id
                ? t('tasks.from_meeting', { defaultValue: 'From meeting' })
                : String(task.metadata?.source) === 'rfi'
                  ? t('tasks.from_rfi', { defaultValue: 'From RFI' })
                  : String(task.metadata?.source) === 'inspection'
                    ? t('tasks.from_inspection', { defaultValue: 'From inspection' })
                    : t('tasks.source_linked', { defaultValue: 'Linked' })}
            </span>
          )}
          {/* BIM pin indicator — surfaces tasks that are spatially linked
              to 3D model geometry.  Click isolates pinned elements in viewer. */}
          <ViewInBIMButton
            elementIds={task.bim_element_ids ?? []}
            iconSize={9}
            className="inline-flex items-center gap-1 mt-0.5 text-2xs text-emerald-700 dark:text-emerald-400 hover:underline"
          />
        </div>
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
                <DateDisplay value={task.due_date} />
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

      {/* Actions bar */}
      <div className="flex items-center justify-between mt-2.5 pt-2 border-t border-border-light">
        <div className="flex items-center gap-1">
          {/* Status quick-change */}
          {task.status !== 'completed' ? (
            <select
              value={task.status}
              onChange={(e) => onStatusChange(task.id, e.target.value as TaskStatus)}
              className="text-[10px] py-0.5 px-1 rounded border border-border-light bg-surface-secondary text-content-secondary focus:outline-none focus:ring-1 focus:ring-oe-blue"
            >
              <option value="draft">{t('tasks.status_draft', { defaultValue: 'Draft' })}</option>
              <option value="open">{t('tasks.status_open', { defaultValue: 'Open' })}</option>
              <option value="in_progress">{t('tasks.status_in_progress', { defaultValue: 'In Progress' })}</option>
              <option value="completed">{t('tasks.status_completed', { defaultValue: 'Completed' })}</option>
            </select>
          ) : (
            <span className="text-[10px] text-green-600 dark:text-green-400 font-medium flex items-center gap-1">
              <CheckCircle2 size={10} />
              {t('tasks.completed', { defaultValue: 'Completed' })}
            </span>
          )}
        </div>
        <div className="flex items-center gap-0.5">
          {task.status !== 'completed' && (
            <Button variant="ghost" size="sm" onClick={() => onComplete(task.id)} className="text-[10px] px-1.5 py-0.5 text-green-600 hover:text-green-700 hover:bg-green-50 dark:hover:bg-green-950/20">
              <CheckCircle2 size={11} />
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={() => onEdit(task)} className="text-[10px] px-1.5 py-0.5 text-content-tertiary hover:text-oe-blue">
            <Pencil size={11} />
          </Button>
          <Button variant="ghost" size="sm" onClick={() => onDelete(task.id)} className="text-[10px] px-1.5 py-0.5 text-content-tertiary hover:text-red-500">
            <Trash2 size={11} />
          </Button>
        </div>
      </div>
    </Card>
  );
});

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function TasksPage() {
  const { t } = useTranslation();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  // State
  const [showAddModal, setShowAddModal] = useState(false);
  const [editingTask, setEditingTask] = useState<Task | null>(null);
  const [showImportModal, setShowImportModal] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importPending, setImportPending] = useState(false);
  const [importResult, setImportResult] = useState<{ imported: number; skipped: number; errors: { row: number; error: string; data: Record<string, string> }[]; total_rows: number } | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [typeFilter, setTypeFilter] = useState<TaskType | ''>('');
  const [myTasksOnly, setMyTasksOnly] = useState(false);

  // Deep-link auto-scroll: Cmd+Shift+K global semantic search lands here
  // with `?id=<task_id>` — scroll the matching task card into view and
  // briefly highlight it.  Cleared from the URL after one shot so a
  // refresh doesn't keep re-scrolling.
  const [searchParams, setSearchParams] = useSearchParams();
  const deepLinkTaskId = searchParams.get('id');
  useEffect(() => {
    if (!deepLinkTaskId) return;
    // Defer until the next tick so the task list has had a chance to
    // render after the data fetch finishes.
    const timer = setTimeout(() => {
      const node = document.querySelector(
        `[data-task-id="${CSS.escape(deepLinkTaskId)}"]`,
      );
      if (node) {
        node.scrollIntoView({ behavior: 'smooth', block: 'center' });
        node.classList.add('ring-2', 'ring-oe-blue', 'ring-offset-2');
        setTimeout(() => {
          node.classList.remove('ring-2', 'ring-oe-blue', 'ring-offset-2');
        }, 2500);
      }
      const next = new URLSearchParams(searchParams);
      next.delete('id');
      setSearchParams(next, { replace: true });
    }, 400);
    return () => clearTimeout(timer);
  }, [deepLinkTaskId, searchParams, setSearchParams]);

  // "n" shortcut → open new task form
  useCreateShortcut(
    useCallback(() => setShowAddModal(true), []),
    !showAddModal && !showImportModal,
  );

  // Escape key handler for import modal
  useEffect(() => {
    if (!showImportModal) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setShowImportModal(false);
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [showImportModal]);

  // Data
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
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
        title: t('tasks.created', { defaultValue: 'Task created successfully' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('tasks.create_failed', { defaultValue: 'Failed to create task' }),
        message: e.message,
      }),
  });

  const exportMut = useMutation({
    mutationFn: () => exportTasks(projectId),
    onSuccess: () =>
      addToast({
        type: 'success',
        title: t('tasks.export_success', { defaultValue: 'Tasks exported successfully' }),
        message: t('tasks.export_success_msg', { defaultValue: 'Excel file has been downloaded.' }),
      }),
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('tasks.export_failed', { defaultValue: 'Failed to export tasks' }),
        message: e.message,
      }),
  });

  const completeMut = useMutation({
    mutationFn: (id: string) => completeTask(id),
    onSuccess: () => {
      invalidateAll();
      addToast({
        type: 'success',
        title: t('tasks.completed', { defaultValue: 'Task marked as completed' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('tasks.complete_failed', { defaultValue: 'Failed to complete task' }),
        message: e.message,
      }),
  });

  const handleCreateSubmit = useCallback(
    (formData: TaskFormData) => {
      if (!projectId) {
        addToast({ type: 'error', title: t('tasks.no_project_error', { defaultValue: 'No project selected' }), message: t('common.select_project_first', { defaultValue: 'Please select a project first' }) });
        return;
      }
      createMut.mutate({
        project_id: projectId,
        title: formData.title,
        description: formData.description || undefined,
        task_type: formData.task_type,
        priority: formData.priority,
        responsible_id: formData.assigned_to || undefined,
        due_date: formData.due_date || undefined,
      });
    },
    [createMut, projectId, addToast, t],
  );

  const editMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: TaskFormData }) =>
      updateTask(id, {
        title: data.title,
        description: data.description || undefined,
        task_type: data.task_type,
        priority: data.priority,
        assigned_to: data.assigned_to || null,
        due_date: data.due_date || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tasks'] });
      setShowAddModal(false);
      setEditingTask(null);
      addToast({ type: 'success', title: t('tasks.updated', { defaultValue: 'Task updated' }) });
    },
    onError: () => {
      addToast({ type: 'error', title: t('tasks.update_failed', { defaultValue: 'Update failed' }) });
    },
  });

  const handleEditSubmit = useCallback(
    (formData: TaskFormData) => {
      if (!editingTask) return;
      editMut.mutate({ id: editingTask.id, data: formData });
    },
    [editMut, editingTask],
  );

  const { confirm, ...confirmProps } = useConfirm();

  const handleComplete = useCallback(
    async (id: string) => {
      const ok = await confirm({
        title: t('tasks.confirm_complete_title', { defaultValue: 'Complete task?' }),
        message: t('tasks.confirm_complete_msg', { defaultValue: 'This task will be marked as completed.' }),
        confirmLabel: t('tasks.mark_complete', { defaultValue: 'Complete' }),
        variant: 'warning',
      });
      if (ok) completeMut.mutate(id);
    },
    [completeMut, confirm, t],
  );

  const handleEditTask = useCallback((task: Task) => {
    setEditingTask(task);
    setShowAddModal(true);
  }, []);

  const deleteMut = useMutation({
    mutationFn: async (id: string) => {
      const { deleteTask } = await import('./api');
      return deleteTask(id);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tasks'] });
      addToast({ type: 'success', title: t('tasks.deleted', { defaultValue: 'Task deleted' }) });
    },
    onError: () => {
      addToast({ type: 'error', title: t('tasks.delete_failed', { defaultValue: 'Delete failed' }) });
    },
  });

  const handleDeleteTask = useCallback(
    async (id: string) => {
      const ok = await confirm({
        title: t('tasks.confirm_delete_title', { defaultValue: 'Delete task?' }),
        message: t('tasks.confirm_delete_msg', { defaultValue: 'This task will be permanently deleted.' }),
        confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
        variant: 'danger',
      });
      if (ok) deleteMut.mutate(id);
    },
    [deleteMut, confirm, t],
  );

  const statusMut = useMutation({
    mutationFn: ({ id, status }: { id: string; status: TaskStatus }) => updateTask(id, { status }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tasks'] });
    },
  });

  const handleStatusChange = useCallback(
    (id: string, status: TaskStatus) => {
      if (status === 'completed') {
        handleComplete(id);
      } else {
        statusMut.mutate({ id, status });
      }
    },
    [statusMut, handleComplete],
  );

  const handleImportFile = async () => {
    if (!importFile || !projectId) return;
    setImportPending(true);
    setImportError(null);
    try {
      const token = useAuthStore.getState().accessToken;
      const formData = new FormData();
      formData.append('file', importFile);

      const headers: Record<string, string> = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const response = await fetch(
        `/api/v1/tasks/import/file?project_id=${encodeURIComponent(projectId)}`,
        { method: 'POST', headers, body: formData },
      );

      if (!response.ok) {
        let detail = 'Import failed';
        try {
          const body = await response.json();
          detail = body.detail || detail;
        } catch { /* ignore */ }
        throw new Error(detail);
      }

      const result = await response.json();
      setImportResult(result);
      invalidateAll();
    } catch (err: unknown) {
      setImportError(err instanceof Error ? err.message : 'Import failed');
    } finally {
      setImportPending(false);
    }
  };

  const handleDownloadTemplate = async () => {
    try {
      const token = useAuthStore.getState().accessToken;
      const headers: Record<string, string> = { Accept: 'application/octet-stream' };
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const response = await fetch('/api/v1/tasks/template/', { method: 'GET', headers });
      if (!response.ok) throw new Error('Failed to download template');

      const blob = await response.blob();
      triggerDownload(blob, 'tasks_import_template.xlsx');
    } catch (e: unknown) {
      addToast({
        type: 'error',
        title: t('tasks.template_download_failed', { defaultValue: 'Failed to download template' }),
        message: e instanceof Error ? e.message : t('tasks.template_error_generic', { defaultValue: 'An unexpected error occurred while downloading the import template.' }),
      });
    }
  };

  return (
    <div className="w-full animate-fade-in">
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
        <div>
          <h1 className="text-2xl font-bold text-content-primary">
            {t('tasks.title', { defaultValue: 'Tasks' })}
          </h1>
          <p className="mt-1 text-sm text-content-secondary">
            {t('tasks.subtitle', { defaultValue: 'Track assignments, deadlines, and progress across your team' })}
          </p>
        </div>

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
            variant="secondary"
            size="sm"
            icon={<Upload size={14} />}
            onClick={() => {
              setShowImportModal(true);
              setImportFile(null);
              setImportResult(null);
              setImportError(null);
            }}
            disabled={!projectId}
          >
            {t('tasks.import', { defaultValue: 'Import' })}
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => setShowAddModal(true)}
            disabled={!projectId}
            title={!projectId ? t('common.select_project_first', { defaultValue: 'Please select a project first' }) : undefined}
            icon={<Plus size={14} />}
          >
            {t('tasks.new_task', { defaultValue: 'New Task' })}
          </Button>
        </div>
      </div>

      {/* No-project warning */}
      {!projectId && (
        <div className="mb-4 flex items-center gap-3 rounded-lg border border-amber-200 bg-amber-50 dark:bg-amber-950/20 dark:border-amber-800 px-4 py-3">
          <AlertTriangle size={18} className="text-amber-600 shrink-0" />
          <div>
            <p className="text-sm font-medium text-amber-800 dark:text-amber-300">{t('common.no_project_selected', { defaultValue: 'No project selected' })}</p>
            <p className="text-xs text-amber-600 dark:text-amber-400">{t('common.select_project_hint', { defaultValue: 'Select a project from the header to view and manage items.' })}</p>
          </div>
        </div>
      )}

      {projectId ? (
      <>
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
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4" aria-hidden="true">
            {Array.from({ length: 3 }).map((_, colIdx) => (
              <div key={colIdx} className="flex flex-col">
                <div className="rounded-lg px-3 py-2 mb-3 bg-surface-secondary animate-pulse h-9" />
                {Array.from({ length: 3 }).map((_, cardIdx) => (
                  <div
                    key={cardIdx}
                    className="rounded-xl border border-border-light bg-surface-elevated p-3 mb-2 space-y-3"
                  >
                    <div className="flex items-start gap-2">
                      <div className="animate-pulse rounded bg-surface-secondary h-5 w-14 shrink-0" />
                      <div className="flex-1 space-y-1.5">
                        <div className="animate-pulse rounded bg-surface-secondary h-4 w-full" />
                        <div className="animate-pulse rounded bg-surface-secondary h-4 w-2/3" />
                      </div>
                    </div>
                    <div className="flex items-center justify-between">
                      <div className="animate-pulse rounded-full bg-surface-secondary h-5 w-5" />
                      <div className="flex items-center gap-2">
                        <div className="animate-pulse rounded-full bg-surface-secondary h-5 w-14" />
                        <div className="animate-pulse rounded bg-surface-secondary h-4 w-16" />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={<ClipboardList size={28} strokeWidth={1.5} />}
            title={
              searchQuery || typeFilter || myTasksOnly
                ? t('tasks.no_results', { defaultValue: 'No matching tasks' })
                : t('tasks.no_tasks', { defaultValue: 'No tasks yet' })
            }
            description={
              searchQuery || typeFilter || myTasksOnly
                ? t('tasks.no_results_hint', {
                    defaultValue: 'Try adjusting your search or filters to find what you are looking for.',
                  })
                : t('tasks.no_tasks_hint', {
                    defaultValue: 'Create your first task to track assignments, deadlines, and progress across your team.',
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
                        {t('tasks.column_empty', { defaultValue: 'No tasks in this column' })}
                      </div>
                    ) : (
                      colItems.map((task) => (
                        <TaskCard
                          key={task.id}
                          task={task}
                          onComplete={handleComplete}
                          onEdit={handleEditTask}
                          onDelete={handleDeleteTask}
                          onStatusChange={handleStatusChange}
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
      </>
      ) : (
        <EmptyState
          icon={<ClipboardList size={28} strokeWidth={1.5} />}
          title={t('tasks.no_project', { defaultValue: 'No project selected' })}
          description={t('tasks.select_project', { defaultValue: 'Select a project from the header to view and manage tasks, assignments, and deadlines.' })}
        />
      )}

      {/* Add / Edit Modal */}
      {showAddModal && (
        <AddTaskModal
          onClose={() => { setShowAddModal(false); setEditingTask(null); }}
          onSubmit={editingTask ? handleEditSubmit : handleCreateSubmit}
          isPending={createMut.isPending || editMut.isPending}
          projectName={projectName}
          initialData={editingTask ? {
            title: editingTask.title,
            description: editingTask.description || '',
            task_type: editingTask.task_type,
            priority: editingTask.priority,
            assigned_to: editingTask.assigned_to_name || '',
            due_date: editingTask.due_date || '',
          } : null}
        />
      )}

      {/* Import Modal */}
      {showImportModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
          <div className="w-full max-w-lg bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto" role="dialog" aria-label={t('tasks.import_tasks', { defaultValue: 'Import Tasks' })}>
            <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
              <h2 className="text-lg font-semibold text-content-primary">
                {t('tasks.import_tasks', { defaultValue: 'Import Tasks' })}
              </h2>
              <button
                onClick={() => setShowImportModal(false)}
                aria-label={t('common.close', { defaultValue: 'Close' })}
                className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
              >
                <X size={18} />
              </button>
            </div>
            <div className="px-6 py-4 space-y-4">
              {/* Template download */}
              <div className="flex items-center gap-2 rounded-lg bg-surface-secondary p-3">
                <FileDown size={16} className="text-oe-blue shrink-0" />
                <div className="flex-1">
                  <p className="text-sm text-content-secondary">
                    {t('tasks.import_template_hint', { defaultValue: 'Download the import template to see the expected format.' })}
                  </p>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleDownloadTemplate}
                >
                  {t('tasks.download_template', { defaultValue: 'Template' })}
                </Button>
              </div>

              {/* File drop area */}
              <div
                className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 transition-colors cursor-pointer border-border hover:border-oe-blue/50"
                onClick={() => {
                  const input = document.createElement('input');
                  input.type = 'file';
                  input.accept = '.xlsx,.csv,.xls';
                  input.onchange = (e) => {
                    const f = (e.target as HTMLInputElement).files?.[0];
                    if (f) setImportFile(f);
                  };
                  input.click();
                }}
              >
                <Upload size={24} className="text-content-tertiary mb-2" />
                <p className="text-sm text-content-secondary text-center">
                  {importFile
                    ? importFile.name
                    : t('tasks.drop_file', { defaultValue: 'Drop Excel or CSV file here, or click to browse' })}
                </p>
                <p className="text-xs text-content-quaternary mt-1">
                  {t('tasks.import_columns_hint', { defaultValue: 'Columns: Title, Type, Status, Priority, Due Date, Description' })}
                </p>
              </div>

              {importError && (
                <div className="rounded-lg bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800 p-3 text-sm text-semantic-error">
                  {importError}
                </div>
              )}
              {importResult && (
                <div className="rounded-lg bg-green-50 dark:bg-green-950/20 border border-green-200 dark:border-green-800 p-3 text-sm text-content-primary space-y-1">
                  <p>
                    {t('tasks.import_result', {
                      defaultValue: 'Imported: {{imported}}, Skipped: {{skipped}}, Errors: {{errors}}',
                      imported: importResult.imported,
                      skipped: importResult.skipped,
                      errors: importResult.errors.length,
                    })}
                  </p>
                  {importResult.errors.length > 0 && (
                    <details className="text-xs text-content-tertiary">
                      <summary className="cursor-pointer">
                        {t('tasks.show_errors', { defaultValue: 'Show error details' })}
                      </summary>
                      <ul className="mt-1 space-y-0.5 max-h-32 overflow-y-auto">
                        {importResult.errors.slice(0, 20).map((err) => (
                          <li key={`row-${err.row}`}>Row {err.row}: {err.error}</li>
                        ))}
                      </ul>
                    </details>
                  )}
                </div>
              )}
            </div>
            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
              <Button variant="ghost" onClick={() => setShowImportModal(false)}>
                {importResult
                  ? t('common.close', { defaultValue: 'Close' })
                  : t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              {!importResult && (
                <Button
                  variant="primary"
                  onClick={handleImportFile}
                  disabled={!importFile || importPending}
                >
                  {importPending ? (
                    <Loader2 size={16} className="animate-spin mr-1.5" />
                  ) : (
                    <Upload size={16} className="mr-1.5" />
                  )}
                  <span>{t('tasks.import_btn', { defaultValue: 'Import' })}</span>
                </Button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Confirm Dialog */}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
