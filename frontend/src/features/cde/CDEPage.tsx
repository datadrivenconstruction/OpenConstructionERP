import React, { useState, useMemo, useCallback, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import clsx from 'clsx';
import {
  Database,
  Search,
  Plus,
  X,
  ChevronDown,
  ChevronRight,
  ArrowRight,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, Breadcrumb, DateDisplay, ConfirmDialog, SkeletonTable } from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { apiGet } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  fetchCDEContainers,
  createCDEContainer,
  transitionContainer,
  fetchContainerRevisions,
  type CDEContainer,
  type CDEState,
  type CDEDiscipline,
  type CDERevision,
  type CreateCDEContainerPayload,
} from './api';

/* ── Constants ─────────────────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
}

/** Helper to read the CDE state from a container (backend returns `cde_state`). */
function getContainerState(c: CDEContainer): CDEState {
  return (c.cde_state ?? 'wip') as CDEState;
}

/** Helper to read the discipline from a container (backend returns `discipline_code`). */
function getContainerDiscipline(c: CDEContainer): CDEDiscipline {
  return (c.discipline_code ?? 'other') as CDEDiscipline;
}

const STATE_CONFIG: Record<
  CDEState,
  { variant: 'neutral' | 'blue' | 'success' | 'warning'; cls: string; label: string }
> = {
  wip: {
    variant: 'warning',
    cls: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400',
    label: 'WIP',
  },
  shared: { variant: 'blue', cls: '', label: 'Shared' },
  published: { variant: 'success', cls: '', label: 'Published' },
  archived: {
    variant: 'neutral',
    cls: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
    label: 'Archived',
  },
};

const STATE_ORDER: CDEState[] = ['wip', 'shared', 'published', 'archived'];

const DISCIPLINE_LABELS: Record<CDEDiscipline, string> = {
  architecture: 'Architecture',
  structural: 'Structural',
  mep: 'MEP',
  civil: 'Civil',
  landscape: 'Landscape',
  interior: 'Interior',
  other: 'Other',
};

const DISCIPLINE_COLORS: Record<CDEDiscipline, string> = {
  architecture: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  structural: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
  mep: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
  civil: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  landscape: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
  interior: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
  other: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
};

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

/* ── Create Modal ─────────────────────────────────────────────────────── */

interface CDEFormData {
  container_code: string;
  title: string;
  discipline: CDEDiscipline;
  suitability_code: string;
  classification: string;
}

const EMPTY_FORM: CDEFormData = {
  container_code: '',
  title: '',
  discipline: 'architecture',
  suitability_code: '',
  classification: '',
};

function CreateCDEModal({
  onClose,
  onSubmit,
  isPending,
}: {
  onClose: () => void;
  onSubmit: (data: CDEFormData) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<CDEFormData>(EMPTY_FORM);
  const [touched, setTouched] = useState(false);

  const set = <K extends keyof CDEFormData>(key: K, value: CDEFormData[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const codeError = touched && form.container_code.trim().length === 0;
  const titleError = touched && form.title.trim().length === 0;
  const canSubmit = form.container_code.trim().length > 0 && form.title.trim().length > 0;

  const handleSubmit = () => {
    setTouched(true);
    if (canSubmit) onSubmit(form);
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
      <div className="w-full max-w-2xl bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto" role="dialog" aria-label={t('cde.new_container', { defaultValue: 'New Container' })}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <h2 className="text-lg font-semibold text-content-primary">
            {t('cde.new_container', { defaultValue: 'New Container' })}
          </h2>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Form */}
        <div className="px-6 py-4 space-y-4">
          {/* Two-column: Code + Discipline */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('cde.field_code', { defaultValue: 'Container Code' })}{' '}
                <span className="text-semantic-error">*</span>
              </label>
              <input
                value={form.container_code}
                onChange={(e) => {
                  set('container_code', e.target.value);
                  setTouched(true);
                }}
                placeholder={t('cde.code_placeholder', {
                  defaultValue: 'e.g. PRJ-ARC-DWG-001',
                })}
                className={clsx(
                  inputCls,
                  codeError &&
                    'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
                )}
                autoFocus
              />
              {codeError && (
                <p className="mt-1 text-xs text-semantic-error">
                  {t('cde.code_required', { defaultValue: 'Container code is required' })}
                </p>
              )}
            </div>
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('cde.field_discipline', { defaultValue: 'Discipline' })}
              </label>
              <div className="relative">
                <select
                  value={form.discipline}
                  onChange={(e) => set('discipline', e.target.value as CDEDiscipline)}
                  className={inputCls + ' appearance-none pr-9'}
                >
                  {(Object.keys(DISCIPLINE_LABELS) as CDEDiscipline[]).map((d) => (
                    <option key={d} value={d}>
                      {t(`cde.discipline_${d}`, { defaultValue: DISCIPLINE_LABELS[d] })}
                    </option>
                  ))}
                </select>
                <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2.5 text-content-tertiary">
                  <ChevronDown size={14} />
                </div>
              </div>
            </div>
          </div>

          {/* Title */}
          <div>
            <label className="block text-sm font-medium text-content-secondary mb-1">
              {t('cde.field_title', { defaultValue: 'Title' })}{' '}
              <span className="text-semantic-error">*</span>
            </label>
            <input
              value={form.title}
              onChange={(e) => {
                set('title', e.target.value);
                setTouched(true);
              }}
              placeholder={t('cde.title_placeholder', {
                defaultValue: 'e.g. Ground Floor Plan - General Arrangement',
              })}
              className={clsx(
                inputCls,
                titleError &&
                  'border-semantic-error focus:ring-red-300 focus:border-semantic-error',
              )}
            />
            {titleError && (
              <p className="mt-1 text-xs text-semantic-error">
                {t('cde.title_required', { defaultValue: 'Title is required' })}
              </p>
            )}
          </div>

          {/* Two-column: Suitability Code + Classification */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('cde.field_suitability', { defaultValue: 'Suitability Code' })}
              </label>
              <input
                value={form.suitability_code}
                onChange={(e) => set('suitability_code', e.target.value)}
                placeholder={t('cde.suitability_placeholder', { defaultValue: 'e.g. S2' })}
                className={inputCls}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-content-secondary mb-1">
                {t('cde.field_classification', { defaultValue: 'Classification' })}
              </label>
              <input
                value={form.classification}
                onChange={(e) => set('classification', e.target.value)}
                placeholder={t('cde.classification_placeholder', {
                  defaultValue: 'e.g. Uniclass Ss_20_05',
                })}
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
          <Button variant="primary" onClick={handleSubmit} disabled={isPending}>
            {isPending ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent mr-2 shrink-0" />
            ) : (
              <Plus size={16} className="mr-1.5 shrink-0" />
            )}
            <span>{t('cde.create_container', { defaultValue: 'Create Container' })}</span>
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── Container Row (expandable with revision history) ─────────────────── */

const ContainerRow = React.memo(function ContainerRow({
  container,
  onPromote,
}: {
  container: CDEContainer;
  onPromote: (c: CDEContainer) => void;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const containerState = getContainerState(container);
  const containerDiscipline = getContainerDiscipline(container);
  const stateCfg = STATE_CONFIG[containerState] ?? STATE_CONFIG.wip;
  const disciplineCls =
    DISCIPLINE_COLORS[containerDiscipline] ?? DISCIPLINE_COLORS.other;

  // Fetch revisions on expand
  const { data: revisions = [], isLoading: revisionsLoading } = useQuery({
    queryKey: ['cde-revisions', container.id],
    queryFn: () => fetchContainerRevisions(container.id),
    enabled: expanded,
  });

  // Can promote if not archived
  const canPromote = containerState !== 'archived';
  const nextState = STATE_ORDER[STATE_ORDER.indexOf(containerState) + 1] as
    | CDEState
    | undefined;

  return (
    <div className="border-b border-border-light last:border-b-0">
      {/* Main row */}
      <div
        className={clsx(
          'flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-surface-secondary/50 transition-colors',
          expanded && 'bg-surface-secondary/30',
        )}
        onClick={() => setExpanded((prev) => !prev)}
      >
        <ChevronRight
          size={14}
          className={clsx(
            'text-content-tertiary transition-transform shrink-0',
            expanded && 'rotate-90',
          )}
        />

        {/* Container Code */}
        <span className="text-sm font-mono font-semibold text-content-secondary w-36 shrink-0 truncate">
          {container.container_code}
        </span>

        {/* Title */}
        <span className="text-sm text-content-primary truncate flex-1 min-w-0">
          {container.title}
        </span>

        {/* Discipline badge */}
        <Badge variant="neutral" size="sm" className={clsx(disciplineCls, 'hidden md:inline-flex')}>
          {t(`cde.discipline_${containerDiscipline}`, {
            defaultValue: DISCIPLINE_LABELS[containerDiscipline] ?? containerDiscipline,
          })}
        </Badge>

        {/* CDE State badge */}
        <Badge variant={stateCfg.variant} size="sm" className={stateCfg.cls}>
          {t(`cde.state_${containerState}`, { defaultValue: stateCfg.label })}
        </Badge>

        {/* Suitability Code */}
        <span className="text-xs text-content-tertiary w-12 text-center shrink-0 hidden lg:block font-mono">
          {container.suitability_code || '-'}
        </span>

        {/* Current Revision */}
        <span className="text-xs text-content-tertiary w-12 text-center shrink-0 tabular-nums hidden sm:block">
          {container.current_revision_id ? 'Rev' : '-'}
        </span>

        {/* Classification */}
        <span className="text-xs text-content-tertiary w-28 truncate shrink-0 hidden lg:block">
          {container.classification_code || '-'}
        </span>
      </div>

      {/* Expanded detail: revision history */}
      {expanded && (
        <div className="px-4 pb-4 pl-12 space-y-3 animate-fade-in">
          {/* Promote action */}
          {canPromote && nextState && (
            <div className="flex items-center gap-2">
              <Button
                variant="primary"
                size="sm"
                onClick={(e) => {
                  e.stopPropagation();
                  onPromote(container);
                }}
              >
                <ArrowRight size={14} className="mr-1" />
                {t('cde.action_promote', {
                  defaultValue: 'Promote to {{state}}',
                  state: t(`cde.state_${nextState}`, {
                    defaultValue: STATE_CONFIG[nextState].label,
                  }),
                })}
              </Button>
            </div>
          )}

          {/* Revision history */}
          <div>
            <p className="text-xs text-content-tertiary mb-2 font-medium uppercase tracking-wide">
              {t('cde.label_revisions', { defaultValue: 'Revision History' })}
            </p>
            {revisionsLoading ? (
              <div className="space-y-2">
                {Array.from({ length: 2 }).map((_, i) => (
                  <div
                    key={i}
                    className="h-10 animate-pulse rounded bg-surface-tertiary"
                  />
                ))}
              </div>
            ) : revisions.length === 0 ? (
              <p className="text-sm text-content-tertiary">
                {t('cde.no_revisions', { defaultValue: 'No revisions recorded' })}
              </p>
            ) : (
              <div className="space-y-1">
                {revisions.map((rev) => (
                  <RevisionItem key={rev.id} revision={rev} />
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
});

function RevisionItem({ revision }: { revision: CDERevision }) {
  return (
    <div className="flex items-center gap-3 rounded-lg bg-surface-secondary p-2.5 text-sm">
      <span className="font-mono font-semibold text-content-secondary w-12 shrink-0">
        {revision.revision_code}
      </span>
      <DateDisplay value={revision.created_at} className="text-xs text-content-tertiary w-24 shrink-0" />
      <Badge variant="neutral" size="sm">
        {revision.status}
      </Badge>
      {revision.file_name && (
        <span className="text-xs text-content-tertiary truncate">{revision.file_name}</span>
      )}
      {revision.change_summary && (
        <span className="text-xs text-content-tertiary truncate flex-1">
          {revision.change_summary}
        </span>
      )}
    </div>
  );
}

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function CDEPage() {
  const { t } = useTranslation();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  // State
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [stateFilter, setStateFilter] = useState<CDEState | ''>('');

  // Data
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
  });

  const projectId = routeProjectId || activeProjectId || projects[0]?.id || '';
  const projectName = projects.find((p) => p.id === projectId)?.name || '';

  const { data: containers = [], isLoading } = useQuery({
    queryKey: ['cde-containers', projectId, stateFilter],
    queryFn: () =>
      fetchCDEContainers({
        project_id: projectId,
        state: stateFilter || undefined,
      }),
    enabled: !!projectId,
  });

  // Client-side search
  const filtered = useMemo(() => {
    if (!searchQuery.trim()) return containers;
    const q = searchQuery.toLowerCase();
    return containers.filter(
      (c) =>
        c.container_code.toLowerCase().includes(q) ||
        c.title.toLowerCase().includes(q) ||
        (c.classification_code && c.classification_code.toLowerCase().includes(q)),
    );
  }, [containers, searchQuery]);

  // State counts for filter tabs
  const stateCounts = useMemo(() => {
    const counts: Record<string, number> = { all: containers.length };
    for (const s of STATE_ORDER) {
      counts[s] = containers.filter((c) => getContainerState(c) === s).length;
    }
    return counts;
  }, [containers]);

  // Invalidation
  const invalidateAll = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['cde-containers'] });
    qc.invalidateQueries({ queryKey: ['cde-revisions'] });
  }, [qc]);

  // Mutations
  const createMut = useMutation({
    mutationFn: (data: CreateCDEContainerPayload) => createCDEContainer(data),
    onSuccess: () => {
      invalidateAll();
      setShowCreateModal(false);
      addToast({
        type: 'success',
        title: t('cde.created', { defaultValue: 'Container created' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const transitionMut = useMutation({
    mutationFn: ({ id, targetState }: { id: string; targetState: CDEState }) =>
      transitionContainer(id, { target_state: targetState }),
    onSuccess: () => {
      invalidateAll();
      addToast({
        type: 'success',
        title: t('cde.promoted', { defaultValue: 'Container promoted' }),
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
    (formData: CDEFormData) => {
      if (!projectId) {
        addToast({
          type: 'error',
          title: t('common.error', { defaultValue: 'Error' }),
          message: t('cde.select_project_first', { defaultValue: 'Please select a project first' }),
        });
        return;
      }
      createMut.mutate({
        project_id: projectId,
        container_code: formData.container_code,
        title: formData.title,
        discipline_code: formData.discipline,
        suitability_code: formData.suitability_code || undefined,
        classification_code: formData.classification || undefined,
      });
    },
    [createMut, projectId, addToast, t],
  );

  const { confirm, ...confirmProps } = useConfirm();

  const handlePromote = useCallback(
    async (container: CDEContainer) => {
      const currentState = getContainerState(container);
      const nextIdx = STATE_ORDER.indexOf(currentState) + 1;
      const nextState = STATE_ORDER[nextIdx];
      if (!nextState) return;
      const ok = await confirm({
        title: t('cde.confirm_promote_title', { defaultValue: 'Promote container?' }),
        message: t('cde.confirm_promote_msg', {
          defaultValue: 'This will move the container to the "{{state}}" state.',
          state: nextState,
        }),
        confirmLabel: t('cde.action_promote', { defaultValue: 'Promote' }),
        variant: 'warning',
      });
      if (ok) transitionMut.mutate({ id: container.id, targetState: nextState });
    },
    [transitionMut, confirm, t],
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
          { label: t('cde.title', { defaultValue: 'Common Data Environment' }) },
        ]}
        className="mb-4"
      />

      {/* Header */}
      <div className="mb-6 flex items-center justify-between gap-3 flex-wrap">
        <h1 className="text-2xl font-bold text-content-primary shrink-0">
          {t('cde.page_title', { defaultValue: 'Common Data Environment' })}
        </h1>

        <div className="flex items-center gap-2 shrink-0">
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
                {t('cde.select_project', { defaultValue: 'Project...' })}
              </option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          )}
          <Button
            variant="primary"
            size="sm"
            onClick={() => setShowCreateModal(true)}
            disabled={!projectId}
            title={!projectId ? t('cde.select_project_first', { defaultValue: 'Please select a project first' }) : undefined}
            className="shrink-0 whitespace-nowrap"
          >
            <Plus size={14} className="mr-1 shrink-0" />
            <span>{t('cde.new_container', { defaultValue: 'New Container' })}</span>
          </Button>
        </div>
      </div>

      {/* State filter tabs */}
      <div className="mb-6 flex items-center gap-1 overflow-x-auto pb-1">
        {[
          { key: '' as CDEState | '', label: 'All', count: stateCounts.all },
          ...STATE_ORDER.map((s) => ({
            key: s as CDEState | '',
            label: STATE_CONFIG[s].label,
            count: stateCounts[s] ?? 0,
          })),
        ].map((tab) => (
          <button
            key={tab.key}
            onClick={() => setStateFilter(tab.key)}
            className={clsx(
              'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors whitespace-nowrap',
              stateFilter === tab.key
                ? 'bg-oe-blue-subtle text-oe-blue'
                : 'text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
            )}
          >
            {t(`cde.tab_${tab.key || 'all'}`, { defaultValue: tab.label })}
            <span
              className={clsx(
                'text-2xs tabular-nums px-1.5 py-0.5 rounded-full',
                stateFilter === tab.key
                  ? 'bg-oe-blue/10 text-oe-blue'
                  : 'bg-surface-tertiary text-content-tertiary',
              )}
            >
              {tab.count}
            </span>
          </button>
        ))}
      </div>

      {/* Search */}
      <div className="mb-6 relative max-w-sm">
        <Search
          size={16}
          className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
        />
        <input
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder={t('cde.search_placeholder', {
            defaultValue: 'Search containers...',
          })}
          className={inputCls + ' pl-9'}
        />
      </div>

      {/* No project selected banner */}
      {!projectId && (
        <div className="mb-6 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300">
          {t('cde.no_project_selected', {
            defaultValue: 'Please select a project to view and manage CDE containers.',
          })}
        </div>
      )}

      {/* Table */}
      <div>
        {!projectId ? null : isLoading ? (
          <SkeletonTable rows={5} columns={5} />
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={<Database size={24} strokeWidth={1.5} />}
            title={
              searchQuery || stateFilter
                ? t('cde.no_results', { defaultValue: 'No matching containers' })
                : t('cde.no_containers', { defaultValue: 'No containers yet' })
            }
            description={
              searchQuery || stateFilter
                ? t('cde.no_results_hint', {
                    defaultValue: 'Try adjusting your search or filters',
                  })
                : t('cde.no_containers_hint', {
                    defaultValue:
                      'Create your first information container following ISO 19650',
                  })
            }
            action={
              !searchQuery && !stateFilter
                ? {
                    label: t('cde.new_container', { defaultValue: 'New Container' }),
                    onClick: () => setShowCreateModal(true),
                  }
                : undefined
            }
          />
        ) : (
          <>
            <p className="mb-3 text-sm text-content-tertiary">
              {t('cde.showing_count', {
                defaultValue: '{{count}} containers',
                count: filtered.length,
              })}
            </p>
            <Card padding="none" className="overflow-x-auto">
              {/* Table header */}
              <div className="flex items-center gap-3 px-4 py-2.5 border-b border-border bg-surface-secondary/50 text-xs font-medium text-content-tertiary uppercase tracking-wide min-w-[640px]">
                <span className="w-5" />
                <span className="w-36">
                  {t('cde.col_code', { defaultValue: 'Code' })}
                </span>
                <span className="flex-1">
                  {t('cde.col_title', { defaultValue: 'Title' })}
                </span>
                <span className="w-24 hidden md:block">
                  {t('cde.col_discipline', { defaultValue: 'Discipline' })}
                </span>
                <span className="w-20 text-center">
                  {t('cde.col_state', { defaultValue: 'State' })}
                </span>
                <span className="w-12 text-center hidden lg:block">
                  {t('cde.col_suitability', { defaultValue: 'Suit.' })}
                </span>
                <span className="w-12 text-center hidden sm:block">
                  {t('cde.col_revision', { defaultValue: 'Rev' })}
                </span>
                <span className="w-28 hidden lg:block">
                  {t('cde.col_classification', { defaultValue: 'Classification' })}
                </span>
              </div>

              {/* Rows */}
              {filtered.map((c) => (
                <ContainerRow
                  key={c.id}
                  container={c}
                  onPromote={handlePromote}
                />
              ))}
            </Card>
          </>
        )}
      </div>

      {/* Create Modal */}
      {showCreateModal && (
        <CreateCDEModal
          onClose={() => setShowCreateModal(false)}
          onSubmit={handleCreateSubmit}
          isPending={createMut.isPending}
        />
      )}

      {/* Confirm Dialog */}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
