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
import {
  ArrowUpRight,
  Cuboid,
  Download,
  Edit3,
  Package,
  Search,
} from 'lucide-react';

import { Badge, Breadcrumb, Button, Card, DismissibleInfo, IntroRichText, EmptyState, Input } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';

import { AssetDetailDrawer } from './AssetDetailDrawer';
import { AssetEditModal } from './AssetEditModal';
import {
  downloadCobieXlsx,
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
  const [detailing, setDetailing] = useState<AssetSummary | null>(null);

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
      <div className="mb-4 space-y-5">
        <Breadcrumb
          items={[
            { label: activeProjectName || t('nav.project', { defaultValue: 'Project' }), to: `/projects/${activeProjectId}` },
            { label: t('nav.assets', { defaultValue: 'Assets' }) },
          ]}
        />

        {/* ── Header ───────────────────────────────────────────────────── */}
        <PageHeader
          srTitle={t('assets.title', { defaultValue: 'Asset Register' })}
          subtitle={t('assets.subtitle', {
            defaultValue: 'Equipment, fixtures and systems extracted from your BIM models.',
          })}
          actions={<Badge variant="neutral">{total}</Badge>}
        />

        {/* ── Purpose intro ─────────────────────────────────────────────── */}
        <DismissibleInfo
          storageKey="assets"
          title={t('assets.intro_title', {
            defaultValue: 'Carry the model through to handover',
          })}
          more={
            t('assets.intro_more', { defaultValue: '' })
              ? <IntroRichText text={t('assets.intro_more')} />
              : undefined
          }
          links={[
            { label: t('assets.intro_link_bim', { defaultValue: 'BIM viewer' }), onClick: () => navigate('/bim') },
            {
              label: t('assets.intro_link_equipment', {
                defaultValue: 'Equipment & Fleet',
              }),
              onClick: () => navigate('/equipment'),
            },
          ]}
        >
          {t('assets.intro_body', {
            defaultValue:
              'Lists every BIM element flagged as a tracked asset in the active project, with search across manufacturer, model and serial and a status filter. Edit a row to record operational data on the element, open it in the 3D viewer, or export the register as COBie for facilities handover. This register is for installed building assets and fixtures from the model; for plant, vehicles and movable machinery use Equipment & Fleet.',
          })}
        </DismissibleInfo>
      </div>

      {/* ── Filters ──────────────────────────────────────────────────── */}
      <Card className="mb-4">
        <div className="flex flex-wrap items-center gap-3 p-3">
          <div className="relative flex-1 min-w-[200px]">
            <Search
              size={16}
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
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
                  ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                  : 'border-border-medium text-content-secondary hover:bg-surface-secondary'
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
                    ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                    : 'border-border-medium text-content-secondary hover:bg-surface-secondary'
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
          <div className="p-6 text-sm text-content-secondary">
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
                {t('assets.cta.open_bim', { defaultValue: 'Open CAD-BIM Viewer' })}
              </Button>
            }
          />
        ) : (
          <table className="w-full text-sm" data-testid="asset-table">
            <thead className="sticky top-0 z-10 bg-surface-primary text-xs uppercase tracking-wider text-content-tertiary shadow-sm">
              <tr>
                <th className="w-10 px-2 py-2"></th>
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
                  className="cursor-pointer border-t border-border-light transition-colors hover:bg-surface-secondary"
                  data-testid={`asset-row-${asset.id}`}
                  onClick={() => setDetailing(asset)}
                >
                  <td className="px-2 py-2">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setDetailing(asset);
                      }}
                      className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-border-medium text-oe-blue hover:border-oe-blue hover:bg-oe-blue/10"
                      title={t('assets.view_geometry', {
                        defaultValue: 'View geometry & properties',
                      })}
                      aria-label={t('assets.view_geometry', {
                        defaultValue: 'View geometry & properties',
                      })}
                      data-testid={`asset-view-${asset.id}`}
                    >
                      <Cuboid size={14} />
                    </button>
                  </td>
                  <td className="px-3 py-2">
                    <div className="font-medium text-content-primary">
                      {asset.name || asset.element_type}
                    </div>
                    <div className="text-xs text-content-tertiary">{asset.stable_id}</div>
                  </td>
                  <td className="px-3 py-2 text-content-primary">
                    {asset.asset_info.manufacturer ?? <span className="text-content-quaternary">—</span>}
                  </td>
                  <td className="px-3 py-2 text-content-primary">
                    {asset.asset_info.model ?? <span className="text-content-quaternary">—</span>}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs text-content-secondary">
                    {asset.asset_info.serial_number ?? <span className="text-content-quaternary">—</span>}
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
                      <span className="text-content-quaternary">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-content-secondary">
                    {asset.asset_info.warranty_until ?? <span className="text-content-quaternary">—</span>}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex flex-col items-start gap-0.5">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          navigate(`/bim/${asset.model_id}?element=${asset.id}`);
                        }}
                        className="inline-flex max-w-[180px] items-center gap-1 truncate text-oe-blue hover:underline"
                        title={t('assets.open_in_bim', {
                          defaultValue: 'Open in 3D Viewer',
                        })}
                      >
                        <span className="truncate">{asset.model_name}</span>
                        <ArrowUpRight size={12} className="shrink-0 opacity-60" />
                      </button>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          downloadCobieXlsx(
                            asset.model_id,
                            `${asset.model_name || 'model'}-cobie.xlsx`,
                          ).catch((err) => {
                            toast({
                              type: 'error',
                              title: t('assets.cobie_failed', {
                                defaultValue: 'COBie export failed',
                              }),
                              message: err instanceof Error ? err.message : undefined,
                            });
                          });
                        }}
                        className="inline-flex items-center gap-1 text-2xs text-content-tertiary hover:text-oe-blue"
                        title={t('assets.cobie_export', {
                          defaultValue: 'Download COBie (XLSX) for this model',
                        })}
                      >
                        <Download size={11} /> COBie
                      </button>
                    </div>
                  </td>
                  <td className="px-3 py-2 text-right" onClick={(e) => e.stopPropagation()}>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => setEditing(asset)}
                      data-testid={`asset-edit-${asset.id}`}
                    >
                      <Edit3 size={14} />
                      {t('common.edit')}
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

      {detailing && (
        <AssetDetailDrawer
          asset={detailing}
          onClose={() => setDetailing(null)}
        />
      )}
    </div>
  );
}

export default AssetsPage;
