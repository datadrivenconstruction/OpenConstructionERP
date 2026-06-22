// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// ApprovalRoutesPage — admin surface for managing approval-route
// templates and observing running instances.
//
// Wave-2, Epic A: route templates live behind /approval-routes and are
// admin-scoped. Other features (markups, submittals, …) consume a
// running instance via <ApprovalInstanceCard /> on their own pages.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Edit3, Plus, ShieldCheck, Trash2, Workflow } from 'lucide-react';

import {
  Badge,
  BetaBanner,
  Breadcrumb,
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  ModuleGuideButton,
  RecoveryCard,
  SkeletonTable,
} from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  approvalRoutesKeys,
  deleteRoute,
  getMeta,
  listRoutes,
} from './api';
import { ApprovalInstancesList } from './ApprovalInstancesList';
import { approvalRoutesGuide } from './approvalRoutesGuide';
import { kindLabel } from './labels';
import { RouteEditor } from './RouteEditor';
import type { ApprovalRoute } from './types';

type TabId = 'routes' | 'instances';

export function ApprovalRoutesPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [tab, setTab] = useState<TabId>('routes');
  const [kindFilter, setKindFilter] = useState<string>('');
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingRoute, setEditingRoute] = useState<ApprovalRoute | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ApprovalRoute | null>(null);

  // Admin surface — show archived routes too (includeInactive defaults
  // to true on the backend; we keep it explicit for clarity).
  const routesQuery = useQuery({
    queryKey: approvalRoutesKeys.routes(null, kindFilter || null),
    queryFn: () =>
      listRoutes({
        targetKind: kindFilter || null,
        includeInactive: true,
      }),
    staleTime: 30_000,
  });

  // Target kinds from the backend whitelist so the filter never drifts.
  const { data: meta } = useQuery({
    queryKey: approvalRoutesKeys.meta(),
    queryFn: () => getMeta(),
    staleTime: 10 * 60_000,
  });
  const targetKinds = meta?.target_kinds ?? [];

  // Resolve project_id → name so project-scoped routes are distinguishable
  // in the Scope column (shares the cached ['projects'] query the editor
  // already uses).
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<{ id: string; name: string }[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });
  const projectName = useMemo(() => {
    const m = new Map<string, string>();
    for (const p of projects) m.set(p.id, p.name);
    return m;
  }, [projects]);

  const delMut = useMutation({
    mutationFn: (id: string) => deleteRoute(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['approval-routes'] });
      setDeleteTarget(null);
      addToast({
        type: 'success',
        title: t('approvalRoutes.toast_deleted', { defaultValue: 'Route deleted' }),
      });
    },
    onError: (e: Error) => {
      setDeleteTarget(null);
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      });
    },
  });

  const groupedRoutes = useMemo(() => {
    const rows = routesQuery.data ?? [];
    const map = new Map<string, ApprovalRoute[]>();
    for (const r of rows) {
      const key = r.target_kind;
      const arr = map.get(key) ?? [];
      arr.push(r);
      map.set(key, arr);
    }
    return Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [routesQuery.data]);

  return (
    <div className="px-4 py-4 animate-fade-in">
      <Breadcrumb
        items={[
          { label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
          {
            label: t('approvalRoutes.title', {
              defaultValue: 'Approval routes',
            }),
          },
        ]}
      />
      <BetaBanner moduleKey="approval-routes" className="mt-3" />

      <div className="mt-3 flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-lg font-bold text-content-primary flex items-center gap-2">
            <Workflow size={20} className="text-oe-blue" />
            {t('approvalRoutes.title', { defaultValue: 'Approval routes' })}
          </h1>
          <p className="mt-1 text-xs text-content-tertiary max-w-3xl">
            {t('approvalRoutes.page_intro', {
              defaultValue:
                'Reusable approval workflows applied to markups, submittals, RFIs and other records. Each step pins an approver (role or user) and a decision mode.',
            })}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <ModuleGuideButton
            content={approvalRoutesGuide}
            onCta={() => {
              setEditingRoute(null);
              setEditorOpen(true);
            }}
          />
          <Button
            variant="primary"
            size="sm"
            onClick={() => {
              setEditingRoute(null);
              setEditorOpen(true);
            }}
            icon={<Plus size={14} />}
          >
            {t('approvalRoutes.newRoute', { defaultValue: 'New route' })}
          </Button>
        </div>
      </div>

      <div
        className="mt-3 inline-flex items-center rounded-lg border border-border-light bg-surface-primary p-0.5"
        role="tablist"
      >
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'routes'}
          onClick={() => setTab('routes')}
          className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
            tab === 'routes'
              ? 'bg-oe-blue text-content-inverse'
              : 'text-content-secondary hover:bg-surface-secondary'
          }`}
        >
          {t('approvalRoutes.tab_routes', { defaultValue: 'Route templates' })}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === 'instances'}
          onClick={() => setTab('instances')}
          className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
            tab === 'instances'
              ? 'bg-oe-blue text-content-inverse'
              : 'text-content-secondary hover:bg-surface-secondary'
          }`}
        >
          {t('approvalRoutes.tab_instances', { defaultValue: 'Running & history' })}
        </button>
      </div>

      {tab === 'routes' ? (
        <div className="mt-3 space-y-3">
          <div className="flex items-center gap-2">
            <label className="text-xs text-content-secondary">
              {t('approvalRoutes.filter_kind', { defaultValue: 'Filter by kind' })}
            </label>
            <select
              value={kindFilter}
              onChange={(e) => setKindFilter(e.target.value)}
              className="h-8 rounded-md border border-border bg-surface-primary px-2 text-xs focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue cursor-pointer"
              aria-label={t('approvalRoutes.filter_kind', {
                defaultValue: 'Filter by kind',
              })}
            >
              <option value="">
                {t('approvalRoutes.all_kinds', {
                  defaultValue: 'All target kinds',
                })}
              </option>
              {targetKinds.map((k) => (
                <option key={k} value={k}>
                  {kindLabel(t, k)}
                </option>
              ))}
            </select>
          </div>

          {routesQuery.isLoading ? (
            <SkeletonTable rows={4} columns={4} />
          ) : routesQuery.isError ? (
            <RecoveryCard
              error={routesQuery.error as Error}
              onRetry={() => routesQuery.refetch()}
            />
          ) : (routesQuery.data?.length ?? 0) === 0 ? (
            <EmptyState
              icon={<Workflow size={28} strokeWidth={1.5} />}
              title={t('approvalRoutes.empty_title', {
                defaultValue: 'No routes yet',
              })}
              description={t('approvalRoutes.empty_desc', {
                defaultValue:
                  'Create your first approval route - e.g. a 2-step submittal review (engineer → manager).',
              })}
              action={{
                label: t('approvalRoutes.newRoute', { defaultValue: 'New route' }),
                onClick: () => {
                  setEditingRoute(null);
                  setEditorOpen(true);
                },
              }}
            />
          ) : (
            groupedRoutes.map(([kind, rows]) => (
              <div key={kind}>
                <h2 className="text-xs font-semibold uppercase tracking-wide text-content-tertiary mb-1.5">
                  {kindLabel(t, kind)}
                </h2>
                <Card padding="none" className="overflow-hidden">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border-light bg-surface-secondary/40">
                        <th className="px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary">
                          {t('approvalRoutes.col_name', { defaultValue: 'Name' })}
                        </th>
                        <th className="px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary w-[80px]">
                          {t('approvalRoutes.col_steps', { defaultValue: 'Steps' })}
                        </th>
                        <th className="px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary w-[110px]">
                          {t('approvalRoutes.col_scope', { defaultValue: 'Scope' })}
                        </th>
                        <th className="px-3 py-2 text-left text-2xs font-semibold uppercase tracking-wider text-content-tertiary w-[90px]">
                          {t('approvalRoutes.col_active', { defaultValue: 'Active' })}
                        </th>
                        <th className="px-3 py-2 text-right text-2xs font-semibold uppercase tracking-wider text-content-tertiary w-[80px]">
                          {t('common.actions', { defaultValue: 'Actions' })}
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border-light">
                      {rows
                        .sort((a, b) => a.name.localeCompare(b.name))
                        .map((r) => (
                          <tr key={r.id}>
                            <td className="px-3 py-2.5">
                              <div className="flex flex-col">
                                <span className="text-sm font-medium text-content-primary">
                                  {r.name}
                                </span>
                              </div>
                            </td>
                            <td className="px-3 py-2.5 text-xs text-content-secondary tabular-nums">
                              <span className="inline-flex items-center gap-1">
                                <ShieldCheck size={11} className="text-content-tertiary" />
                                {r.steps.length}
                              </span>
                            </td>
                            <td className="px-3 py-2.5 text-xs text-content-secondary">
                              {r.project_id ? (
                                <span
                                  className="truncate"
                                  title={
                                    projectName.get(r.project_id) ?? r.project_id
                                  }
                                >
                                  {projectName.get(r.project_id) ??
                                    t('approvalRoutes.scope_project', {
                                      defaultValue: 'Project',
                                    })}
                                </span>
                              ) : (
                                <Badge variant="blue" size="sm">
                                  {t('approvalRoutes.scope_global', {
                                    defaultValue: 'Global',
                                  })}
                                </Badge>
                              )}
                            </td>
                            <td className="px-3 py-2.5">
                              {r.is_active ? (
                                <Badge variant="success" size="sm">
                                  {t('approvalRoutes.active', {
                                    defaultValue: 'Active',
                                  })}
                                </Badge>
                              ) : (
                                <Badge variant="neutral" size="sm">
                                  {t('approvalRoutes.archived', {
                                    defaultValue: 'Archived',
                                  })}
                                </Badge>
                              )}
                            </td>
                            <td className="px-3 py-2.5 text-right">
                              <div className="inline-flex items-center gap-0.5">
                                <button
                                  onClick={() => {
                                    setEditingRoute(r);
                                    setEditorOpen(true);
                                  }}
                                  className="p-1 rounded hover:bg-surface-secondary text-content-tertiary transition-colors"
                                  title={t('common.edit', { defaultValue: 'Edit' })}
                                >
                                  <Edit3 size={13} />
                                </button>
                                <button
                                  onClick={() => setDeleteTarget(r)}
                                  className="p-1 rounded hover:bg-surface-secondary text-semantic-error/70 hover:text-semantic-error transition-colors"
                                  title={t('common.delete', {
                                    defaultValue: 'Delete',
                                  })}
                                >
                                  <Trash2 size={13} />
                                </button>
                              </div>
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </Card>
              </div>
            ))
          )}
        </div>
      ) : (
        <div className="mt-3 space-y-2">
          <p className="text-xs text-content-tertiary max-w-3xl">
            {t('approvalRoutes.instances_intro', {
              defaultValue:
                'Every approval workflow started across the app. Click a row to open the step ladder and approve, reject or cancel a pending workflow without leaving this page.',
            })}
          </p>
          <ApprovalInstancesList />
        </div>
      )}

      <RouteEditor
        open={editorOpen}
        onClose={() => setEditorOpen(false)}
        route={editingRoute}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        onConfirm={() => deleteTarget && delMut.mutate(deleteTarget.id)}
        onCancel={() => setDeleteTarget(null)}
        title={t('approvalRoutes.delete_title', {
          defaultValue: 'Delete approval route',
        })}
        message={t('approvalRoutes.delete_message', {
          defaultValue:
            'Running instances are not deleted. New approvals can no longer use this template. This action cannot be undone.',
        })}
        confirmLabel={t('common.delete', { defaultValue: 'Delete' })}
        cancelLabel={t('common.cancel', { defaultValue: 'Cancel' })}
        variant="danger"
        loading={delMut.isPending}
      />
    </div>
  );
}
