// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Find and remove the demo records older versions wrote into real projects.
 *
 * Up to 18.2 every restart could put demo diaries, bid packages, quality plans
 * and the like into a person's own projects. The server command
 * `demo-cleanup` finds them, but a desktop install has no console, so the same
 * pass is offered here: first a preview, grouped by project and module, and
 * only then a Remove button behind a confirmation. The removal names exactly
 * the rows the preview showed, and the server removes only those that still
 * match the seed, so nothing appears in between the look and the click.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Search, Trash2 } from 'lucide-react';

import { Button, ConfirmDialog } from '@/shared/ui';
import { apiGet, apiPost } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { invalidateProjectLists } from '@/features/projects/invalidateProjectLists';

export interface DemoLeftoverRow {
  group: string;
  module: string;
  table: string;
  id: string;
  project_id: string | null;
  project_name: string;
  title: string;
  reason?: string;
}

export interface DemoLeftoversReport {
  real_projects: number;
  applied: boolean;
  total: number;
  groups: Record<string, number>;
  rows: DemoLeftoverRow[];
  kept: DemoLeftoverRow[];
  company_rows_kept_reason: string;
}

export const DEMO_LEFTOVERS_URL = '/v1/projects/demo-data/leftovers/';
export const DEMO_LEFTOVERS_REMOVE_URL = '/v1/projects/demo-data/leftovers/remove/';

/** Rows by project, then by module, in the order the preview shows them. */
export function groupLeftovers(rows: DemoLeftoverRow[]): [string, [string, DemoLeftoverRow[]][]][] {
  const byProject = new Map<string, Map<string, DemoLeftoverRow[]>>();
  for (const row of rows) {
    const modules = byProject.get(row.project_name) ?? new Map<string, DemoLeftoverRow[]>();
    const list = modules.get(row.module) ?? [];
    list.push(row);
    modules.set(row.module, list);
    byProject.set(row.project_name, modules);
  }
  return [...byProject.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([project, modules]) => [project, [...modules.entries()].sort(([a], [b]) => a.localeCompare(b))]);
}

export function DemoLeftoversPanel() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [preview, setPreview] = useState<DemoLeftoversReport | null>(null);
  const [confirming, setConfirming] = useState(false);

  const findMutation = useMutation({
    mutationFn: () => apiGet<DemoLeftoversReport>(DEMO_LEFTOVERS_URL),
    onSuccess: (data) => setPreview(data),
    onError: (error: Error) =>
      addToast({
        type: 'error',
        title: t('settings.demo_leftovers_find_failed', { defaultValue: 'Could not look for leftover demo records' }),
        message: error.message,
      }),
  });

  const removeMutation = useMutation({
    mutationFn: (ids: string[]) => apiPost<DemoLeftoversReport>(DEMO_LEFTOVERS_REMOVE_URL, { ids }),
    onSuccess: (data) => {
      setConfirming(false);
      setPreview(null);
      invalidateProjectLists(queryClient);
      queryClient.invalidateQueries({ queryKey: ['project'] });
      addToast({
        type: 'success',
        title: t('settings.demo_leftovers_removed_title', { defaultValue: 'Leftover demo records removed' }),
        message: t('settings.demo_leftovers_removed_message', {
          defaultValue: '{{count}} demo records were removed from your projects.',
          count: data.total,
        }),
      });
    },
    onError: (error: Error) => {
      setConfirming(false);
      addToast({
        type: 'error',
        title: t('settings.demo_leftovers_remove_failed', { defaultValue: 'Could not remove the demo records' }),
        message: error.message,
      });
    },
  });

  const grouped = useMemo(() => groupLeftovers(preview?.rows ?? []), [preview]);
  const companyWide = t('settings.demo_leftovers_company_wide', { defaultValue: 'Company-wide (no project)' });

  return (
    <div
      data-testid="demo-leftovers-panel"
      className="mt-3 rounded-lg border border-semantic-error/20 bg-surface-elevated px-4 py-3"
    >
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium text-content-primary">
            {t('settings.demo_leftovers_title', { defaultValue: 'Find leftover demo records' })}
          </p>
          <p className="text-xs text-content-secondary mt-0.5">
            {t('settings.demo_leftovers_desc', {
              defaultValue:
                'Older versions could add demo records to your own projects on restart. Look for them first; nothing is removed until you confirm.',
            })}
          </p>
        </div>
        <Button
          variant="secondary"
          icon={<Search size={14} />}
          loading={findMutation.isPending}
          onClick={() => findMutation.mutate()}
        >
          {t('settings.demo_leftovers_find', { defaultValue: 'Find leftover demo records' })}
        </Button>
      </div>

      {preview && (
        <div className="mt-3 border-t border-border-light pt-3" data-testid="demo-leftovers-preview">
          {preview.rows.length === 0 ? (
            <p className="text-sm text-content-secondary">
              {t('settings.demo_leftovers_none', { defaultValue: 'No leftover demo records in your projects.' })}
            </p>
          ) : (
            <>
              <p className="text-sm text-content-primary">
                {t('settings.demo_leftovers_found', {
                  defaultValue: '{{count}} demo records found in your projects:',
                  count: preview.total,
                })}
              </p>
              <div className="mt-2 max-h-80 overflow-y-auto space-y-3">
                {grouped.map(([project, modules]) => (
                  <div key={project || '-'}>
                    <p className="text-xs font-semibold text-content-primary">{project || companyWide}</p>
                    {modules.map(([module, rows]) => (
                      <details key={module} className="ml-3 mt-1">
                        <summary className="cursor-pointer text-xs text-content-secondary">
                          {module} ({rows.length})
                        </summary>
                        <ul className="ml-4 mt-1 space-y-0.5">
                          {rows.map((row) => (
                            <li key={row.id} className="text-xs text-content-tertiary">
                              {row.title}
                            </li>
                          ))}
                        </ul>
                      </details>
                    ))}
                  </div>
                ))}
              </div>
            </>
          )}

          {preview.kept.length > 0 && (
            <div className="mt-3">
              <p className="text-xs font-medium text-content-primary">
                {t('settings.demo_leftovers_kept', {
                  defaultValue: '{{count}} demo records stay because someone has worked on them since:',
                  count: preview.kept.length,
                })}
              </p>
              <ul className="ml-4 mt-1 space-y-0.5">
                {preview.kept.map((row) => (
                  <li key={row.id} className="text-xs text-content-tertiary">
                    {(row.project_name || companyWide) + ' / ' + row.module + ': ' + row.title}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {preview.rows.length > 0 && (
            <div className="mt-3 flex justify-end">
              <Button variant="danger" icon={<Trash2 size={14} />} onClick={() => setConfirming(true)}>
                {t('settings.demo_leftovers_remove', { defaultValue: 'Remove' })}
              </Button>
            </div>
          )}
        </div>
      )}

      <ConfirmDialog
        open={confirming}
        loading={removeMutation.isPending}
        title={t('settings.demo_leftovers_confirm_title', { defaultValue: 'Remove these demo records?' })}
        message={t('settings.demo_leftovers_confirm_message', {
          defaultValue:
            'The {{count}} demo records listed will be permanently deleted from your projects. Your own records are not touched. This cannot be undone.',
          count: preview?.total ?? 0,
        })}
        confirmLabel={t('settings.demo_leftovers_remove', { defaultValue: 'Remove' })}
        onCancel={() => {
          if (!removeMutation.isPending) setConfirming(false);
        }}
        onConfirm={() => removeMutation.mutate((preview?.rows ?? []).map((r) => r.id))}
      />
    </div>
  );
}
