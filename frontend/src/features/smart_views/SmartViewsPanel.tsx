// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// SmartViewsPanel — side-panel shown next to the BIM viewer.
//
// Layout:
//   ┌───────────────────────┐
//   │ Header: title + close │
//   │ Tabs: My / Project    │
//   │ "New view"            │
//   │ ─ Card list ─         │
//   │   • SmartViewCard …   │
//   │   • …                 │
//   │ "Clear applied" (when applied) │
//   └───────────────────────┘
//
// React-Query owns the list; clicking a card kicks the evaluator API and
// publishes the result through {@link useSmartViewState} so the parent
// page can hand the eval result to the viewer.

import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { X, Plus, Sparkles, Filter, Folder, ChevronDown, ChevronRight } from 'lucide-react';
import clsx from 'clsx';
import {
  Button,
  EmptyState,
  Skeleton,
  ConfirmDialog,
} from '@/shared/ui';
import { useTabKeyboardNav } from '@/shared/hooks/useTabKeyboardNav';
import { useToastStore } from '@/stores/useToastStore';
import {
  deleteSmartView,
  duplicateSmartView,
  evaluateSmartView,
  listSmartViews,
} from './api';
import type { SmartViewResponse, SmartViewScopeType } from './types';
import { SmartViewCard } from './SmartViewCard';
import { SmartViewRuleEditor } from './SmartViewRuleEditor';
import { SmartViewPresetsTab } from './SmartViewPresetsTab';
import { SmartViewShareModal } from './SmartViewShareModal';
import { useSmartViewState } from './useSmartViewState';

/** One folder bucket of saved views. ``folder === null`` is the ungrouped
 *  bucket, always rendered first. */
export interface SmartViewFolderGroup {
  folder: string | null;
  views: SmartViewResponse[];
}

/** Group a flat view list into ordered folder buckets (B4). Ungrouped views
 *  come first; folders follow in natural-sort order. Folder labels are
 *  trimmed and blank labels fold into the ungrouped bucket. */
export function groupViewsByFolder(
  views: SmartViewResponse[],
): SmartViewFolderGroup[] {
  const ungrouped: SmartViewResponse[] = [];
  const byFolder = new Map<string, SmartViewResponse[]>();
  for (const v of views) {
    const folder = (v.folder ?? '').trim();
    if (!folder) {
      ungrouped.push(v);
      continue;
    }
    const bucket = byFolder.get(folder) ?? [];
    bucket.push(v);
    byFolder.set(folder, bucket);
  }
  const collator = new Intl.Collator(undefined, {
    numeric: true,
    sensitivity: 'base',
  });
  const groups: SmartViewFolderGroup[] = [];
  if (ungrouped.length) groups.push({ folder: null, views: ungrouped });
  for (const folder of Array.from(byFolder.keys()).sort((a, b) =>
    collator.compare(a, b),
  )) {
    groups.push({ folder, views: byFolder.get(folder) ?? [] });
  }
  return groups;
}

export interface SmartViewsPanelProps {
  /** BIM model whose elements the evaluator runs against. ``null`` when
   *  no model is loaded — the panel disables the Apply path. */
  modelId: string | null;
  /** Project id used as the scope_id for the Project tab. ``null`` when
   *  outside a project context (e.g. /bim without a project) → the
   *  Project tab is hidden. */
  projectId: string | null;
  /** Current user id used as the scope_id for the My tab. */
  userId: string;
  /** Close button. */
  onClose: () => void;
}

type Tab = 'user' | 'project' | 'presets';

export function SmartViewsPanel({
  modelId,
  projectId,
  userId,
  onClose,
}: SmartViewsPanelProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const appliedViewId = useSmartViewState((s) => s.appliedViewId);
  const setApplied = useSmartViewState((s) => s.setApplied);
  const clearApplied = useSmartViewState((s) => s.clear);

  const [tab, setTab] = useState<Tab>(projectId ? 'project' : 'user');
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingView, setEditingView] = useState<SmartViewResponse | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [sharingView, setSharingView] = useState<SmartViewResponse | null>(null);
  /** Folders the user has collapsed in the list (B4). */
  const [collapsedFolders, setCollapsedFolders] = useState<Set<string>>(
    () => new Set(),
  );
  const toggleFolder = (folder: string): void => {
    setCollapsedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(folder)) next.delete(folder);
      else next.add(folder);
      return next;
    });
  };

  // The project tab is conditionally rendered, so its id is only
  // included in the keyboard nav set when projectId is present —
  // otherwise ArrowRight on "user" would skip to a non-existent tab.
  const enabledTabIds = useMemo<readonly Tab[]>(
    () => (projectId ? ['user', 'project', 'presets'] : ['user', 'presets']),
    [projectId],
  );
  const onTabKeyDown = useTabKeyboardNav<Tab>({
    ids: enabledTabIds,
    activeId: tab,
    onChange: setTab,
    orientation: 'horizontal',
  });

  // The "presets" tab is a UX layer over the active list scope — installs
  // land in whichever scope was last active. We default to ``user`` so a
  // user without a project context still has a sensible target.
  const listScope: 'user' | 'project' = tab === 'project' ? 'project' : 'user';
  const scopeId = listScope === 'user' ? userId : projectId ?? userId;
  const scopeType: SmartViewScopeType = listScope === 'user' ? 'user' : 'project';

  /* ── Fetch ────────────────────────────────────────────────────────── */

  const listQuery = useQuery({
    queryKey: ['smart-views', scopeType, scopeId],
    queryFn: () => listSmartViews({ scopeType, scopeId }),
    enabled: Boolean(scopeId) && tab !== 'presets',
  });

  const views: SmartViewResponse[] = useMemo(
    () => listQuery.data ?? [],
    [listQuery.data],
  );

  /** Distinct folder labels across the current list, for the editor's folder
   *  autocomplete (B4). */
  const existingFolders = useMemo<string[]>(() => {
    const set = new Set<string>();
    for (const v of views) {
      const f = (v.folder ?? '').trim();
      if (f) set.add(f);
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }, [views]);

  /* ── Apply ────────────────────────────────────────────────────────── */

  const applyMutation = useMutation({
    mutationFn: async (viewId: string) => {
      if (!modelId) {
        throw new Error(
          t('smartViews.error_no_model', {
            defaultValue: 'Load a BIM model before applying a view.',
          }),
        );
      }
      const result = await evaluateSmartView(viewId, modelId);
      return { viewId, result };
    },
    onSuccess: ({ viewId, result }) => {
      setApplied(viewId, result);
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('smartViews.error_apply_title', {
          defaultValue: 'Could not apply view',
        }),
        message: err instanceof Error ? err.message : String(err),
      });
    },
  });

  /* ── Duplicate ────────────────────────────────────────────────────── */

  const duplicateMutation = useMutation({
    mutationFn: (source: SmartViewResponse) =>
      duplicateSmartView(source, { scopeType, scopeId }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['smart-views', scopeType, scopeId],
      });
      addToast({
        type: 'success',
        title: t('smartViews.duplicate_success', {
          defaultValue: 'View duplicated',
        }),
      });
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('smartViews.error_duplicate_title', {
          defaultValue: 'Could not duplicate view',
        }),
        message: err instanceof Error ? err.message : String(err),
      });
    },
  });

  /* ── Delete ───────────────────────────────────────────────────────── */

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteSmartView(id),
    onSuccess: (_data, id) => {
      // Clear the applied state if the deleted view was the one applied.
      if (useSmartViewState.getState().appliedViewId === id) {
        clearApplied();
      }
      queryClient.invalidateQueries({
        queryKey: ['smart-views', scopeType, scopeId],
      });
      addToast({
        type: 'success',
        title: t('smartViews.delete_success', { defaultValue: 'View deleted' }),
      });
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('smartViews.error_delete_title', {
          defaultValue: 'Could not delete view',
        }),
        message: err instanceof Error ? err.message : String(err),
      });
    },
    onSettled: () => setPendingDeleteId(null),
  });

  /* ── Render ───────────────────────────────────────────────────────── */

  const renderCard = (v: SmartViewResponse) => (
    <SmartViewCard
      key={v.id}
      view={v}
      applied={appliedViewId === v.id}
      onApply={() => applyMutation.mutate(v.id)}
      onEdit={() => {
        setEditingView(v);
        setEditorOpen(true);
      }}
      onDuplicate={() => duplicateMutation.mutate(v)}
      onDelete={() => setPendingDeleteId(v.id)}
      // Only the authoring user gets a share_token in the payload; gate the
      // menu item on that so a collaborator does not see a 403-on-click button.
      onShare={v.created_by === userId ? () => setSharingView(v) : undefined}
    />
  );

  return (
    <div
      className="flex flex-col h-full bg-surface-primary"
      data-testid="smart-views-panel"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border-light">
        <div className="flex items-center gap-1.5">
          <Sparkles size={14} className="text-oe-blue" />
          <h3 className="text-sm font-semibold text-content-primary">
            {t('smartViews.title', { defaultValue: 'Smart Views' })}
          </h3>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md p-1 text-content-tertiary hover:bg-surface-secondary"
          aria-label={t('common.close', { defaultValue: 'Close' })}
          data-testid="smart-views-panel-close"
        >
          <X size={14} />
        </button>
      </div>

      {/* Tabs */}
      <div
        className="flex items-center border-b border-border-light px-2"
        role="tablist"
        aria-label={t('smartViews.title', { defaultValue: 'Smart Views' })}
        onKeyDown={onTabKeyDown}
      >
        <TabButton
          id="user"
          active={tab === 'user'}
          onClick={() => setTab('user')}
          label={t('smartViews.scope_user', { defaultValue: 'My views' })}
          testId="smart-views-tab-user"
        />
        {projectId && (
          <TabButton
            id="project"
            active={tab === 'project'}
            onClick={() => setTab('project')}
            label={t('smartViews.scope_project', { defaultValue: 'Project views' })}
            testId="smart-views-tab-project"
          />
        )}
        <TabButton
          id="presets"
          active={tab === 'presets'}
          onClick={() => setTab('presets')}
          label={t('smartViews.presets_tab', { defaultValue: 'Presets' })}
          testId="smart-views-tab-presets"
        />
      </div>

      {/* New + Clear bar (suppressed on the presets tab — it has its own
          install affordances on every card) */}
      {tab !== 'presets' && (
        <div className="flex items-center gap-2 px-3 py-2 border-b border-border-light">
          <Button
            size="sm"
            variant="primary"
            icon={<Plus size={12} />}
            onClick={() => {
              setEditingView(null);
              setEditorOpen(true);
            }}
            data-testid="smart-views-new"
          >
            {t('smartViews.new', { defaultValue: 'New view' })}
          </Button>
          {appliedViewId && (
            <Button
              size="sm"
              variant="ghost"
              icon={<Filter size={12} />}
              onClick={clearApplied}
              data-testid="smart-views-clear"
            >
              {t('smartViews.clear', { defaultValue: 'Clear applied' })}
            </Button>
          )}
        </div>
      )}

      {/* List / Presets */}
      <div className="flex-1 overflow-y-auto px-3 py-2">
        {tab === 'presets' && (
          <SmartViewPresetsTab
            scopeType={scopeType}
            scopeId={scopeId}
            onInstalled={() => setTab(listScope)}
          />
        )}
        {tab !== 'presets' && listQuery.isLoading && (
          <div className="space-y-2" data-testid="smart-views-loading">
            <Skeleton height={72} />
            <Skeleton height={72} />
            <Skeleton height={72} />
          </div>
        )}
        {tab !== 'presets' && listQuery.isError && (
          <div
            className="rounded-lg border border-semantic-error/30 bg-semantic-error-bg/40 p-3 text-sm text-semantic-error"
            data-testid="smart-views-error"
          >
            {t('smartViews.error_load', {
              defaultValue: 'Could not load views.',
            })}
          </div>
        )}
        {tab !== 'presets' && listQuery.isSuccess && views.length === 0 && (
          <div className="py-4" data-testid="smart-views-empty">
            <EmptyState
              icon={<Sparkles size={28} className="text-oe-blue/60" />}
              title={t('smartViews.empty_title', {
                defaultValue: 'No smart views yet',
              })}
              description={t('smartViews.empty_desc', {
                defaultValue:
                  'Create a rule-based view to colour, hide, or isolate elements by property.',
              })}
              action={{
                label: t('smartViews.new', { defaultValue: 'New view' }),
                onClick: () => {
                  setEditingView(null);
                  setEditorOpen(true);
                },
              }}
            />
          </div>
        )}
        {tab !== 'presets' && listQuery.isSuccess && views.length > 0 && (
          <div className="space-y-3" data-testid="smart-views-list">
            {groupViewsByFolder(views).map((group) =>
              group.folder === null ? (
                <div key="__ungrouped" className="space-y-2">
                  {group.views.map(renderCard)}
                </div>
              ) : (
                <div
                  key={group.folder}
                  data-testid={`smart-views-folder-${group.folder}`}
                >
                  <button
                    type="button"
                    onClick={() => toggleFolder(group.folder as string)}
                    aria-expanded={!collapsedFolders.has(group.folder)}
                    className="flex w-full items-center gap-1.5 rounded-md px-1 py-1 text-xs font-semibold text-content-secondary hover:bg-surface-secondary hover:text-content-primary"
                    data-testid={`smart-views-folder-toggle-${group.folder}`}
                  >
                    {collapsedFolders.has(group.folder) ? (
                      <ChevronRight size={13} />
                    ) : (
                      <ChevronDown size={13} />
                    )}
                    <Folder size={13} className="text-oe-blue/70" />
                    <span className="truncate">{group.folder}</span>
                    <span className="ms-auto font-normal text-content-tertiary">
                      {group.views.length}
                    </span>
                  </button>
                  {!collapsedFolders.has(group.folder) && (
                    <div className="mt-1 space-y-2 ps-2">
                      {group.views.map(renderCard)}
                    </div>
                  )}
                </div>
              ),
            )}
          </div>
        )}
      </div>

      {/* Editor modal */}
      <SmartViewRuleEditor
        open={editorOpen}
        onClose={() => {
          setEditorOpen(false);
          setEditingView(null);
        }}
        initialView={editingView}
        scopeType={scopeType}
        scopeId={scopeId}
        existingFolders={existingFolders}
        onSaved={() => {
          queryClient.invalidateQueries({
            queryKey: ['smart-views', scopeType, scopeId],
          });
        }}
      />

      {/* Share modal */}
      {sharingView && (
        <SmartViewShareModal
          open={sharingView !== null}
          onClose={() => setSharingView(null)}
          viewId={sharingView.id}
          viewName={sharingView.name}
          initialShareToken={sharingView.share_token ?? null}
          onChanged={() => {
            queryClient.invalidateQueries({
              queryKey: ['smart-views', scopeType, scopeId],
            });
          }}
        />
      )}

      {/* Delete confirm */}
      <ConfirmDialog
        open={pendingDeleteId !== null}
        onCancel={() => setPendingDeleteId(null)}
        onConfirm={() => {
          if (pendingDeleteId) deleteMutation.mutate(pendingDeleteId);
        }}
        title={t('smartViews.delete_confirm_title', {
          defaultValue: 'Delete this view?',
        })}
        message={t('smartViews.delete_confirm_msg', {
          defaultValue:
            'The view will be removed for every collaborator with access. This cannot be undone.',
        })}
        variant="danger"
        loading={deleteMutation.isPending}
      />
    </div>
  );
}

interface TabButtonProps {
  id: Tab;
  active: boolean;
  onClick: () => void;
  label: string;
  testId: string;
}

function TabButton({ id, active, onClick, label, testId }: TabButtonProps) {
  return (
    <button
      type="button"
      role="tab"
      id={`smart-views-tab-${id}`}
      aria-selected={active}
      aria-controls={`smart-views-panel-${id}`}
      tabIndex={active ? 0 : -1}
      onClick={onClick}
      className={clsx(
        'px-3 py-2 text-xs font-medium border-b-2 -mb-px transition-colors',
        active
          ? 'border-oe-blue text-oe-blue'
          : 'border-transparent text-content-tertiary hover:text-content-secondary',
      )}
      data-testid={testId}
    >
      {label}
    </button>
  );
}

export default SmartViewsPanel;
