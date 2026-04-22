/**
 * Asset Register page (v2.3.0).
 *
 * Lists every BIM element flagged ``is_tracked_asset=true`` in the active
 * project. Supports free-text search across manufacturer / model /
 * serial / notes and an operational-status filter. Edit an asset row to
 * open a modal that patches the ``asset_info`` JSON on the underlying
 * BIMElement.
 *
 * URL conventions:
 *   - `?search=...`        — restores the search box
 *   - `?status=operational`— restores the status filter
 *
 * Clears state when the active project changes so you never see stale
 * rows from a previous project.
 */
import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { ClipboardList, Download, Edit3, Package, Search } from 'lucide-react';

import { Badge, Breadcrumb, Button, Card, EmptyState, Input } from '@/shared/ui';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';

import { AssetEditModal } from './AssetEditModal';
import {
  cobieExportUrl,
  listTrackedAssets,
  type AssetSummary,
} from './api';

/* ── Constants ─────────────────────────────────────────────────────────── */

const OPERATIONAL_STATUSES: Array<{ value: string; labelKey: string; tone: string }> = [
  { value: 'operational', labelKey: 'assets.status.operational', tone: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
  { value: 'under_maintenance', labelKey: 'assets.status.under_maintenance', tone: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
  { value: 'decommissioned', labelKey: 'assets.status.decommissioned', tone: 'bg-rose-500/15 text-rose-300 border-rose-500/30' },
  { value: 'planned', labelKey: 'assets.status.planned', tone: 'bg-sky-500/15 text-sky-300 border-sky-500/30' },
];

function statusTone(status?: string | null): string {
  return (
    OPERATIONAL_STATUSES.find((s) => s.value === status)?.tone ??
    'bg-neutral-700/40 text-neutral-300 border-neutral-600/50'
  );
}

/* ── AssetsPage ────────────────────────────────────────────────────────── */

export function AssetsPage() {
  const { t } = useTranslation();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const activeProjectName = useProjectContextStore((s) => s.activeProjectName);
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToastStore((s) => s.addToast);

  const search = searchParams.get('search') ?? '';
  const status = searchParams.get('status') ?? '';

  const [editing, setEditing] = useState<AssetSummary | null>(null);

  const patchSearch = useCallback(
    (next: Partial<Record<'search' | 'status', string>>) => {
      const updated = new URLSearchParams(searchParams);
      for (const [key, value] of Object.entries(next)) {
        if (!value) updated.delete(key);
        else updated.set(key, value);
      }
      setSearchParams(updated, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  const assetsQuery = useQuery({
    queryKey: ['bim-assets', activeProjectId, search, status],
    queryFn: () =>
      listTrackedAssets(activeProjectId!, {
        search: search || undefined,
        operationalStatus: status || undefined,
      }),
    enabled: !!activeProjectId,
    staleTime: 30_000,
    // Avoids an edge-case re-render that detaches filter-chip / edit
    // buttons when a focus event lands between the user's click and
    // Playwright's click-retry. Harmless in prod — users rarely tab
    // out of this page, and the 30 s staleTime still forces a refresh.
    refetchOnWindowFocus: false,
  });

  const items = assetsQuery.data?.items ?? [];
  const total = assetsQuery.data?.total ?? 0;

  if (!activeProjectId) {
    return (
      <div className="p-6">
        <Breadcrumb items={[{ label: t('nav.assets', { defaultValue: 'Assets' }) }]} />
        <EmptyState
          icon={<Package size={48} />}
          title={t('assets.no_project.title', { defaultValue: 'No active project' })}
          description={t('assets.no_project.desc', {
            defaultValue: 'Pick a project first from the Projects page to see its tracked assets.',
          })}
          action={
            <Button onClick={() => navigate('/projects')}>
              {t('assets.cta.go_projects', { defaultValue: 'Go to Projects' })}
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col p-6">
      <Breadcrumb
        items={[
          { label: t('nav.projects', { defaultValue: 'Projects' }), to: '/projects' },
          { label: activeProjectName || t('nav.project', { defaultValue: 'Project' }) },
          { label: t('nav.assets', { defaultValue: 'Assets' }) },
        ]}
      />

      {/* ── Header ───────────────────────────────────────────────────── */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <ClipboardList size={22} className="text-primary-400" />
          <h1 className="text-2xl font-semibold text-neutral-100">
            {t('assets.title', { defaultValue: 'Asset Register' })}
          </h1>
          <Badge variant="neutral">{total}</Badge>
        </div>
        <div className="text-sm text-neutral-400">
          {t('assets.subtitle', {
            defaultValue: 'Equipment, fixtures and systems extracted from your BIM models.',
          })}
        </div>
      </div>

      {/* ── Filters ──────────────────────────────────────────────────── */}
      <Card className="mb-4">
        <div className="flex flex-wrap items-center gap-3 p-3">
          <div className="relative flex-1 min-w-[200px]">
            <Search
              size={16}
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500"
            />
            <Input
              value={search}
              onChange={(e) => patchSearch({ search: e.target.value })}
              placeholder={t('assets.search_placeholder', {
                defaultValue: 'Search manufacturer, model, serial…',
              })}
              className="pl-9"
              data-testid="asset-search"
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => patchSearch({ status: '' })}
              className={`rounded-md border px-3 py-1 text-xs ${
                status === ''
                  ? 'border-primary-500 bg-primary-500/15 text-primary-200'
                  : 'border-neutral-700 text-neutral-300 hover:bg-neutral-800'
              }`}
              data-testid="asset-status-all"
            >
              {t('assets.status.all', { defaultValue: 'All statuses' })}
            </button>
            {OPERATIONAL_STATUSES.map((s) => (
              <button
                key={s.value}
                type="button"
                onClick={() => patchSearch({ status: s.value })}
                className={`rounded-md border px-3 py-1 text-xs ${
                  status === s.value
                    ? 'border-primary-500 bg-primary-500/15 text-primary-200'
                    : 'border-neutral-700 text-neutral-300 hover:bg-neutral-800'
                }`}
                data-testid={`asset-status-${s.value}`}
              >
                {t(s.labelKey, { defaultValue: s.value.replace('_', ' ') })}
              </button>
            ))}
          </div>
        </div>
      </Card>

      {/* ── Table ───────────────────────────────────────────────────── */}
      <Card className="flex-1 overflow-auto">
        {assetsQuery.isLoading ? (
          <div className="p-6 text-sm text-neutral-400">
            {t('common.loading', { defaultValue: 'Loading…' })}
          </div>
        ) : items.length === 0 ? (
          <EmptyState
            icon={<Package size={40} />}
            title={t('assets.empty.title', { defaultValue: 'No tracked assets yet' })}
            description={t('assets.empty.desc', {
              defaultValue:
                'Open a BIM model, pick an element, and set a manufacturer or serial to register it as an asset.',
            })}
            action={
              <Button variant="secondary" onClick={() => navigate('/bim')}>
                {t('assets.cta.open_bim', { defaultValue: 'Open BIM Viewer' })}
              </Button>
            }
          />
        ) : (
          <table className="w-full text-sm" data-testid="asset-table">
            <thead className="sticky top-0 bg-neutral-900/95 text-xs uppercase tracking-wider text-neutral-400">
              <tr>
                <th className="px-3 py-2 text-left">{t('assets.col.element', { defaultValue: 'Element' })}</th>
                <th className="px-3 py-2 text-left">{t('assets.col.manufacturer', { defaultValue: 'Manufacturer' })}</th>
                <th className="px-3 py-2 text-left">{t('assets.col.model', { defaultValue: 'Model' })}</th>
                <th className="px-3 py-2 text-left">{t('assets.col.serial', { defaultValue: 'Serial' })}</th>
                <th className="px-3 py-2 text-left">{t('assets.col.status', { defaultValue: 'Status' })}</th>
                <th className="px-3 py-2 text-left">{t('assets.col.warranty', { defaultValue: 'Warranty until' })}</th>
                <th className="px-3 py-2 text-left">{t('assets.col.model_file', { defaultValue: 'BIM model' })}</th>
                <th className="px-3 py-2 text-right">{t('assets.col.actions', { defaultValue: 'Actions' })}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((asset) => (
                <tr
                  key={asset.id}
                  className="border-t border-neutral-800 hover:bg-neutral-800/30"
                  data-testid={`asset-row-${asset.id}`}
                >
                  <td className="px-3 py-2">
                    <div className="font-medium text-neutral-100">
                      {asset.name || asset.element_type}
                    </div>
                    <div className="text-xs text-neutral-500">{asset.stable_id}</div>
                  </td>
                  <td className="px-3 py-2 text-neutral-200">
                    {asset.asset_info.manufacturer ?? <span className="text-neutral-600">—</span>}
                  </td>
                  <td className="px-3 py-2 text-neutral-200">
                    {asset.asset_info.model ?? <span className="text-neutral-600">—</span>}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs text-neutral-300">
                    {asset.asset_info.serial_number ?? <span className="text-neutral-600">—</span>}
                  </td>
                  <td className="px-3 py-2">
                    {asset.asset_info.operational_status ? (
                      <span
                        className={`inline-block rounded-md border px-2 py-0.5 text-xs ${statusTone(
                          asset.asset_info.operational_status,
                        )}`}
                      >
                        {asset.asset_info.operational_status.replace('_', ' ')}
                      </span>
                    ) : (
                      <span className="text-neutral-600">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-neutral-300">
                    {asset.asset_info.warranty_until ?? <span className="text-neutral-600">—</span>}
                  </td>
                  <td className="px-3 py-2">
                    <button
                      type="button"
                      onClick={() => navigate(`/bim/${asset.model_id}?element=${asset.id}`)}
                      className="text-primary-300 hover:underline"
                    >
                      {asset.model_name}
                    </button>
                    {' '}
                    <a
                      href={cobieExportUrl(asset.model_id)}
                      className="ml-2 inline-flex items-center gap-1 text-xs text-neutral-400 hover:text-primary-300"
                      title={t('assets.cobie_export', { defaultValue: 'Download COBie (XLSX)' })}
                    >
                      <Download size={12} /> COBie
                    </a>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => setEditing(asset)}
                      data-testid={`asset-edit-${asset.id}`}
                    >
                      <Edit3 size={14} />
                      {t('common.edit', { defaultValue: 'Edit' })}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {editing && (
        <AssetEditModal
          asset={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            toast({
              type: 'success',
              title: t('assets.saved', { defaultValue: 'Asset info saved' }),
            });
            setEditing(null);
          }}
        />
      )}
    </div>
  );
}

export default AssetsPage;
