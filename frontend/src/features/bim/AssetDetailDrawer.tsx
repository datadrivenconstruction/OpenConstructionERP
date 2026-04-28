/**
 * Asset detail drawer — slides in from the right of the Asset Register.
 *
 * Shows the asset's full picture without leaving /assets:
 *   • Header  : element name, type chip, model badge.
 *   • Actions : "Open in 3D Viewer" deep-link (`/bim/{modelId}?element={id}`),
 *               "Edit asset info" (re-uses ``AssetEditModal``), COBie export.
 *   • Asset   : manufacturer / model / serial / status / warranty / notes —
 *               all populated from the row already loaded by AssetsPage.
 *   • Geometry: lightweight quantity summary (area / volume / length) when
 *               the BIMElement has a quantities blob.
 *   • Props   : full Parquet row fetched lazily via
 *               ``fetchBIMElementProperties(model_id, stable_id)`` — same
 *               endpoint the BIM viewer uses, so what users see matches
 *               the in-3D Properties panel exactly.
 *
 * Lazy fetch keeps the list page fast: properties only load when the
 * drawer opens for that asset. Closes on Esc or backdrop click.
 */
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  ArrowUpRight,
  Box,
  Cuboid,
  Download,
  Edit3,
  Loader2,
  Package,
  Ruler,
  X,
} from 'lucide-react';

import { Badge, Button, KvList, Kv, QtyTile } from '@/shared/ui';

import { useToastStore } from '@/stores/useToastStore';

import { AssetEditModal } from './AssetEditModal';
import {
  downloadCobieXlsx,
  fetchBIMElementProperties,
  fetchBIMElementsByIds,
  type AssetSummary,
} from './api';

interface AssetDetailDrawerProps {
  asset: AssetSummary;
  onClose: () => void;
}

const STATUS_TONES: Record<string, string> = {
  operational: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  under_maintenance: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  decommissioned: 'bg-rose-500/15 text-rose-300 border-rose-500/30',
  planned: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
};

function statusTone(status?: string | null): string {
  if (!status) return 'bg-neutral-700/40 text-neutral-300 border-neutral-600/50';
  return STATUS_TONES[status] ?? 'bg-neutral-700/40 text-neutral-300 border-neutral-600/50';
}

const PROP_PRIORITY: Record<string, number> = {
  category: -100,
  family: -90,
  type: -80,
  level: -70,
  storey: -65,
  ifcguid: -60,
  uniqueid: -55,
  workset: -50,
};

function isEmpty(v: unknown): boolean {
  return (
    v === null ||
    v === undefined ||
    v === '' ||
    (typeof v === 'number' && Number.isNaN(v)) ||
    (Array.isArray(v) && v.length === 0)
  );
}

function prettyKey(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function sortProps(props: Record<string, unknown>): Array<[string, unknown]> {
  return Object.entries(props)
    .filter(([, v]) => !isEmpty(v))
    .sort(([a], [b]) => {
      const pa = PROP_PRIORITY[a.toLowerCase()] ?? 0;
      const pb = PROP_PRIORITY[b.toLowerCase()] ?? 0;
      if (pa !== pb) return pa - pb;
      return a.localeCompare(b);
    });
}

export function AssetDetailDrawer({ asset, onClose }: AssetDetailDrawerProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const toast = useToastStore((s) => s.addToast);
  const [editing, setEditing] = useState(false);

  // Esc to close
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  // Quantities + storey from the BIMElement row (cheap, single round-trip).
  const elementQuery = useQuery({
    queryKey: ['bim-element-detail', asset.model_id, asset.id],
    queryFn: () => fetchBIMElementsByIds(asset.model_id, [asset.id]),
    staleTime: 30_000,
  });
  const element = elementQuery.data?.items?.[0] ?? null;
  const quantities = (element?.quantities ?? {}) as Record<string, number>;
  const storey = element?.storey ?? null;

  // Full Parquet row — same endpoint the BIM viewer uses for parity.
  const propsQuery = useQuery({
    queryKey: ['bim-element-props', asset.model_id, asset.stable_id],
    queryFn: () => fetchBIMElementProperties(asset.model_id, asset.stable_id),
    staleTime: 60_000,
    enabled: !!asset.stable_id,
  });

  const sortedProps = useMemo(() => {
    if (!propsQuery.data) return [];
    return sortProps(propsQuery.data);
  }, [propsQuery.data]);

  const openInViewer = () => {
    navigate(`/bim/${asset.model_id}?element=${asset.id}`);
  };

  const headerName = asset.name || asset.element_type || 'Element';

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[1px]"
        onClick={onClose}
        data-testid="asset-detail-backdrop"
      />

      {/* Drawer */}
      <aside
        className="fixed right-0 top-0 z-50 flex h-full w-full max-w-[460px] flex-col border-l border-border-light bg-surface-primary shadow-2xl"
        data-testid="asset-detail-drawer"
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-3 border-b border-border-light px-4 py-3">
          <div className="min-w-0 flex-1">
            <div className="mb-1 flex items-center gap-2 text-xs text-content-tertiary">
              <Cuboid size={12} className="text-oe-blue" />
              <span className="truncate" title={asset.element_type}>
                {asset.element_type}
              </span>
              {storey && (
                <>
                  <span className="text-content-quaternary">·</span>
                  <span className="truncate" title={String(storey)}>
                    {String(storey)}
                  </span>
                </>
              )}
            </div>
            <h2
              className="truncate text-lg font-semibold text-content-primary"
              title={headerName}
            >
              {headerName}
            </h2>
            <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-content-tertiary">
              <Badge variant="neutral">{asset.model_name}</Badge>
              <span className="font-mono text-[10px] text-content-quaternary">
                {asset.stable_id}
              </span>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
            aria-label={t('common.close', { defaultValue: 'Close' })}
            data-testid="asset-detail-close"
          >
            <X size={16} />
          </button>
        </div>

        {/* Action bar */}
        <div className="flex flex-wrap gap-2 border-b border-border-light px-4 py-3">
          <Button
            variant="primary"
            size="sm"
            onClick={openInViewer}
            data-testid="asset-detail-open-viewer"
          >
            <ArrowUpRight size={14} />
            {t('assets.detail.open_in_viewer', { defaultValue: 'Open in 3D Viewer' })}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setEditing(true)}
            data-testid="asset-detail-edit"
          >
            <Edit3 size={14} />
            {t('assets.detail.edit', { defaultValue: 'Edit asset info' })}
          </Button>
          <button
            type="button"
            onClick={() =>
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
              })
            }
            className="inline-flex items-center gap-1 rounded-md border border-border-medium px-2.5 py-1 text-xs text-content-secondary hover:bg-surface-secondary hover:text-oe-blue"
            title={t('assets.cobie_export', { defaultValue: 'Download COBie (XLSX)' })}
          >
            <Download size={12} />
            COBie
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-4 py-4 text-sm">
          {/* Asset info section */}
          <Section
            icon={<Package size={13} className="text-primary-400" />}
            title={t('assets.detail.section.asset_info', { defaultValue: 'Asset info' })}
          >
            <KvList>
              <Kv
                label={t('assets.field.manufacturer', { defaultValue: 'Manufacturer' })}
                value={asset.asset_info.manufacturer ?? null}
              />
              <Kv
                label={t('assets.field.model', { defaultValue: 'Model' })}
                value={asset.asset_info.model ?? null}
              />
              <Kv
                label={t('assets.field.serial', { defaultValue: 'Serial number' })}
                value={asset.asset_info.serial_number ?? null}
                mono
              />
              <Kv
                label={t('assets.field.status', { defaultValue: 'Status' })}
                value={
                  asset.asset_info.operational_status ? (
                    <span
                      className={`inline-block rounded-md border px-2 py-0.5 text-[11px] ${statusTone(
                        asset.asset_info.operational_status,
                      )}`}
                    >
                      {asset.asset_info.operational_status.replace('_', ' ')}
                    </span>
                  ) : null
                }
              />
              <Kv
                label={t('assets.field.installation_date', { defaultValue: 'Installation date' })}
                value={asset.asset_info.installation_date ?? null}
              />
              <Kv
                label={t('assets.field.warranty_until', { defaultValue: 'Warranty until' })}
                value={asset.asset_info.warranty_until ?? null}
              />
              <Kv
                label={t('assets.field.parent_system', { defaultValue: 'Parent system' })}
                value={asset.asset_info.parent_system ?? null}
              />
              <Kv
                label={t('assets.field.notes', { defaultValue: 'Notes' })}
                value={asset.asset_info.notes ?? null}
              />
            </KvList>
          </Section>

          {/* Geometry / quantities */}
          {(quantities.area ||
            quantities.volume ||
            quantities.length ||
            quantities.height) && (
            <Section
              icon={<Ruler size={13} className="text-emerald-400" />}
              title={t('assets.detail.section.quantities', { defaultValue: 'Quantities' })}
            >
              <div className="grid grid-cols-2 gap-2">
                {quantities.area != null && (
                  <QtyTile label="Area" value={quantities.area} unit="m²" />
                )}
                {quantities.volume != null && (
                  <QtyTile label="Volume" value={quantities.volume} unit="m³" />
                )}
                {quantities.length != null && (
                  <QtyTile label="Length" value={quantities.length} unit="m" />
                )}
                {quantities.height != null && (
                  <QtyTile label="Height" value={quantities.height} unit="m" />
                )}
                {quantities.width != null && (
                  <QtyTile label="Width" value={quantities.width} unit="m" />
                )}
                {quantities.thickness != null && (
                  <QtyTile label="Thickness" value={quantities.thickness} unit="m" />
                )}
              </div>
            </Section>
          )}

          {/* All BIM properties */}
          <Section
            icon={<Box size={13} className="text-sky-400" />}
            title={t('assets.detail.section.properties', { defaultValue: 'BIM properties' })}
            count={sortedProps.length || undefined}
          >
            {propsQuery.isLoading ? (
              <div className="flex items-center gap-2 py-4 text-xs text-content-tertiary">
                <Loader2 size={12} className="animate-spin" />
                {t('common.loading', { defaultValue: 'Loading…' })}
              </div>
            ) : propsQuery.isError ? (
              <p className="py-2 text-xs text-rose-500">
                {t('assets.detail.props_error', {
                  defaultValue: 'Could not load BIM properties.',
                })}
              </p>
            ) : sortedProps.length === 0 ? (
              <p className="py-2 text-xs italic text-content-tertiary">
                {t('assets.detail.no_props', {
                  defaultValue: 'No additional BIM properties stored for this element.',
                })}
              </p>
            ) : (
              <div className="space-y-1">
                {sortedProps.map(([key, value]) => (
                  <div
                    key={key}
                    className="flex items-start justify-between gap-3 rounded border border-border-light bg-surface-secondary/50 px-2 py-1"
                  >
                    <span
                      className="max-w-[45%] shrink-0 truncate text-[11px] text-content-tertiary"
                      title={key}
                    >
                      {prettyKey(key)}
                    </span>
                    <span
                      className="min-w-0 break-words text-right text-[11px] font-medium text-content-primary"
                      title={String(value)}
                    >
                      {String(value)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </Section>
        </div>
      </aside>

      {editing && (
        <AssetEditModal
          asset={asset}
          onClose={() => setEditing(false)}
          onSaved={() => setEditing(false)}
        />
      )}
    </>
  );
}

function Section({
  icon,
  title,
  count,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  count?: number;
  children: React.ReactNode;
}) {
  return (
    <section className="mb-4">
      <header className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-content-tertiary">
        {icon}
        <span>{title}</span>
        {count != null && (
          <span className="ml-1 rounded bg-surface-secondary px-1.5 py-0.5 text-[10px] font-normal text-content-secondary">
            {count}
          </span>
        )}
      </header>
      {children}
    </section>
  );
}

export default AssetDetailDrawer;
