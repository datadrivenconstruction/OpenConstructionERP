// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  AlertTriangle,
  Bookmark,
  ChevronRight,
  Clock,
  Eye,
  Filter,
  Globe,
  Loader2,
  Lock,
  Pin,
  Search,
  Trash2,
  Users,
  X,
} from 'lucide-react';
import { Badge, CollapsibleSection, EmptyState } from '@/shared/ui';
import { getIntlLocale } from '@/shared/lib/formatters';
import type { BadgeVariant } from '@/shared/ui';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import {
  useSavedViews,
  useDeleteSavedView,
  type SavedView,
  type ShareScope,
} from './api';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SCOPE_BADGE_VARIANT: Record<ShareScope, BadgeVariant> = {
  private: 'neutral',
  team: 'blue',
  project: 'success',
  workspace: 'warning',
};

const SCOPE_ICON: Record<ShareScope, typeof Lock> = {
  private: Lock,
  team: Users,
  project: Eye,
  workspace: Globe,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(getIntlLocale(), {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

// ---------------------------------------------------------------------------
// Explainer
// ---------------------------------------------------------------------------

function SavedViewsExplainer() {
  const { t } = useTranslation();

  const steps = [
    {
      num: 1,
      title: t('saved_views.flow_step_1', { defaultValue: 'Build a filter' }),
      desc: t('saved_views.flow_step_1_desc', {
        defaultValue:
          'Open any list in the platform (positions, contacts, submittals, etc.) and set the columns, sorting and conditions you need.',
      }),
    },
    {
      num: 2,
      title: t('saved_views.flow_step_2', { defaultValue: 'Save the view' }),
      desc: t('saved_views.flow_step_2_desc', {
        defaultValue:
          'Give the filter a name, choose who can see it (private, team, project or workspace) and pin it for quick access.',
      }),
    },
    {
      num: 3,
      title: t('saved_views.flow_step_3', { defaultValue: 'Run or reuse' }),
      desc: t('saved_views.flow_step_3_desc', {
        defaultValue:
          'Open a saved view to get the latest results, use its count on a dashboard tile, or export the rows to CSV.',
      }),
    },
    {
      num: 4,
      title: t('saved_views.flow_step_4', { defaultValue: 'Stay healthy' }),
      desc: t('saved_views.flow_step_4_desc', {
        defaultValue:
          'Views are validated against the current schema. A stale badge appears when a referenced field is removed or renamed so you can fix it before it breaks.',
      }),
    },
  ];

  return (
    <CollapsibleSection
      storageKey="saved_views.how"
      icon={<Bookmark size={15} className="text-oe-blue" />}
      title={t('saved_views.flow_title', { defaultValue: 'How saved views work' })}
    >
      <p className="text-xs text-content-tertiary">
        {t('saved_views.flow_intro', {
          defaultValue:
            'Save a filter spec against any registered entity, share it with a team or a project, and reuse it as a list, count, tile or export.',
        })}
      </p>
      <ol className="mt-3 space-y-2">
        {steps.map((s) => (
          <li key={s.num} className="flex gap-3 text-xs">
            <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-oe-blue/10 text-[10px] font-bold text-oe-blue-text">
              {s.num}
            </span>
            <div>
              <span className="font-medium text-content-primary">{s.title}</span>
              <span className="text-content-tertiary"> - {s.desc}</span>
            </div>
          </li>
        ))}
      </ol>
    </CollapsibleSection>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function SavedViewsPage() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore(
    (s: { activeProjectId: string | null }) => s.activeProjectId,
  );
  const projectId = activeProjectId ?? undefined;

  // Filters
  const [search, setSearch] = useState('');
  const [entityFilter, setEntityFilter] = useState('');
  const [scopeFilter, setScopeFilter] = useState<ShareScope | ''>('');

  // Delete confirmation
  const [deleteTarget, setDeleteTarget] = useState<SavedView | null>(null);
  const [deleting, setDeleting] = useState(false);

  // All hooks above any early return
  const { data: views, isLoading, error } = useSavedViews(projectId, entityFilter || undefined);
  const deleteMutation = useDeleteSavedView();

  const items = views ?? [];

  // Client-side filtering
  const filtered = useMemo(() => {
    let result = items;
    if (scopeFilter) {
      result = result.filter((v) => v.share_scope === scopeFilter);
    }
    if (search) {
      const q = search.toLowerCase();
      result = result.filter(
        (v) =>
          v.name.toLowerCase().includes(q) ||
          v.entity_type.toLowerCase().includes(q) ||
          (v.description && v.description.toLowerCase().includes(q)),
      );
    }
    return result;
  }, [items, search, scopeFilter]);

  // Distinct entity types for the filter dropdown
  const entityTypes = useMemo(() => {
    const set = new Set<string>();
    items.forEach((v) => set.add(v.entity_type));
    return Array.from(set).sort();
  }, [items]);

  const handleDelete = useCallback(
    async () => {
      if (!deleteTarget) return;
      setDeleting(true);
      try {
        await deleteMutation.mutateAsync({ id: deleteTarget.id, projectId });
        addToast({
          type: 'success',
          title: t('saved_views.deleted', { defaultValue: 'View deleted' }),
        });
      } catch (err) {
        addToast({
          type: 'error',
          title: t('saved_views.delete_failed', { defaultValue: 'Could not delete view' }),
          message: err instanceof Error ? err.message : undefined,
        });
      } finally {
        setDeleting(false);
        setDeleteTarget(null);
      }
    },
    [deleteTarget, deleteMutation, projectId, addToast, t],
  );

  // -- No project selected ---------------------------------------------------
  if (!projectId) {
    return (
      <div className="space-y-5">
        <PageHeader
          srTitle={t('saved_views.page_title', { defaultValue: 'Saved Views' })}
          subtitle={t('saved_views.subtitle', {
            defaultValue: 'Reusable filter specs you can share, pin and export.',
          })}
        />
        <SavedViewsExplainer />
        <EmptyState
          icon={<Bookmark className="h-6 w-6" />}
          title={t('saved_views.no_project', { defaultValue: 'Select a project' })}
          description={t('saved_views.no_project_desc', {
            defaultValue: 'Choose a project from the header to manage its saved views.',
          })}
        />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <PageHeader
        srTitle={t('saved_views.page_title', { defaultValue: 'Saved Views' })}
        subtitle={t('saved_views.subtitle', {
          defaultValue: 'Reusable filter specs you can share, pin and export.',
        })}
      />

      <SavedViewsExplainer />

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-[200px] flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder={t('saved_views.search', { defaultValue: 'Search views...' })}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-lg border border-gray-200 bg-white py-2 pe-4 ps-10 text-sm
              focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500
              dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
          />
          {search && (
            <button
              onClick={() => setSearch('')}
              className="absolute right-3 top-1/2 -translate-y-1/2"
              aria-label={t('common.clear_search', { defaultValue: 'Clear search' })}
            >
              <X className="h-4 w-4 text-gray-400 hover:text-gray-600" aria-hidden />
            </button>
          )}
        </div>

        <select
          value={entityFilter}
          onChange={(e) => setEntityFilter(e.target.value)}
          className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm
            dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
        >
          <option value="">{t('saved_views.all_entities', { defaultValue: 'All entities' })}</option>
          {entityTypes.map((et) => (
            <option key={et} value={et}>{et}</option>
          ))}
        </select>

        <select
          value={scopeFilter}
          onChange={(e) => setScopeFilter(e.target.value as ShareScope | '')}
          className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm
            dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
        >
          <option value="">{t('saved_views.all_scopes', { defaultValue: 'All scopes' })}</option>
          <option value="private">{t('saved_views.scope_private', { defaultValue: 'Private' })}</option>
          <option value="team">{t('saved_views.scope_team', { defaultValue: 'Team' })}</option>
          <option value="project">{t('saved_views.scope_project', { defaultValue: 'Project' })}</option>
          <option value="workspace">{t('saved_views.scope_workspace', { defaultValue: 'Workspace' })}</option>
        </select>
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="flex items-center justify-center py-16 text-content-tertiary">
          <Loader2 className="mr-2 h-5 w-5 animate-spin" />
          {t('common.loading', { defaultValue: 'Loading...' })}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          {t('saved_views.load_error', { defaultValue: 'Could not load saved views.' })}
        </div>
      )}

      {/* Empty */}
      {!isLoading && !error && filtered.length === 0 && (
        <EmptyState
          icon={<Filter className="h-12 w-12" />}
          title={t('saved_views.empty', { defaultValue: 'No saved views yet' })}
          description={t('saved_views.empty_desc', {
            defaultValue:
              'Saved views are created from the filter bar on any list page. Build a filter, click "Save view" and it will appear here.',
          })}
        />
      )}

      {/* View list */}
      {!isLoading && filtered.length > 0 && (
        <div className="space-y-2">
          {filtered.map((view) => {
            const ScopeIcon = SCOPE_ICON[view.share_scope as ShareScope] ?? Lock;
            return (
              <div
                key={view.id}
                className="flex items-center gap-4 rounded-xl border border-border-light bg-surface-elevated/90 px-4 py-3 shadow-xs transition-shadow hover:shadow-sm"
              >
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-oe-blue/10 text-oe-blue-text">
                  <Bookmark className="h-5 w-5" />
                </div>

                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p className="truncate text-sm font-medium text-content-primary">{view.name}</p>
                    {view.is_pinned && (
                      <Pin className="h-3.5 w-3.5 shrink-0 text-oe-blue" aria-hidden />
                    )}
                    {view.is_stale && (
                      <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-semantic-warning" aria-hidden />
                    )}
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 text-xs text-content-tertiary">
                    <span className="inline-flex items-center gap-1">
                      <Clock className="h-3 w-3" aria-hidden />
                      {formatDate(view.updated_at)}
                    </span>
                    <span className="text-border">|</span>
                    <span>{view.entity_type}</span>
                  </div>
                </div>

                <div className="hidden items-center gap-3 sm:flex">
                  <Badge
                    variant={SCOPE_BADGE_VARIANT[view.share_scope as ShareScope] ?? 'neutral'}
                    size="sm"
                  >
                    <ScopeIcon className="mr-1 inline h-3 w-3" aria-hidden />
                    {t(`saved_views.scope_${view.share_scope}`, {
                      defaultValue: view.share_scope.charAt(0).toUpperCase() + view.share_scope.slice(1),
                    })}
                  </Badge>

                  {view.is_stale && (
                    <Badge variant="warning" size="sm">
                      {t('saved_views.stale', { defaultValue: 'Stale' })}
                    </Badge>
                  )}
                </div>

                <div className="flex items-center gap-1">
                  <button
                    onClick={() => setDeleteTarget(view)}
                    className="shrink-0 rounded-lg p-2 text-content-tertiary hover:bg-semantic-error-bg hover:text-semantic-error transition-colors"
                    aria-label={t('common.delete', { defaultValue: 'Delete' })}
                  >
                    <Trash2 className="h-4 w-4" aria-hidden />
                  </button>
                  <ChevronRight className="h-4 w-4 text-content-tertiary" aria-hidden />
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Delete confirmation */}
      <ConfirmDialog
        open={!!deleteTarget}
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
        title={t('saved_views.delete_title', { defaultValue: 'Delete saved view' })}
        message={t('saved_views.delete_message', {
          defaultValue: 'This will permanently remove the saved view. Other users who shared this view will lose access.',
        })}
        confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
        loading={deleting}
      />
    </div>
  );
}
