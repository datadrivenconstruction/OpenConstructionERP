/**
 * Floating asset-info card for the BIM viewer.
 *
 * Rendered only when exactly one element is selected. Shows the current
 * asset-info (manufacturer / model / serial / operational status) and
 * an "Edit" CTA that opens the shared ``AssetEditModal``.
 *
 * The card fetches the element's full row via the asset-list endpoint
 * filtered to a single id — cheap (indexed lookup) and reuses the same
 * payload shape as the Asset Register list. If the element is *not* yet
 * tracked (``is_tracked_asset=false``), the card shows a register CTA
 * instead of the populated fields.
 *
 * Positioning matches the dimensions card in ``BIMPage`` (top-right,
 * respects the filter-panel offset).
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Package, Edit3 } from 'lucide-react';

import { AssetEditModal } from './AssetEditModal';
import { listTrackedAssets, type AssetSummary } from './api';

interface ElementAssetCardProps {
  projectId: string;
  elementId: string | null;
  /** The selected element's DB id or stable_id — needed to synth a summary
   *  for the modal when the element is still untracked. */
  element: {
    id: string;
    stable_id: string;
    name?: string | null;
    element_type?: string | null;
    model_id?: string;
    model_name?: string;
  } | null;
  /** Horizontal offset in px (keeps the card out of the filter panel). */
  insetInlineStart: number;
  /** Vertical offset so it stacks below the dimensions card. */
  topPx: number;
  visible: boolean;
}

export default function ElementAssetCard({
  projectId,
  elementId,
  element,
  insetInlineStart,
  topPx,
  visible,
}: ElementAssetCardProps) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState<AssetSummary | null>(null);

  // Fetch the project's tracked assets and pick out this element. We
  // piggy-back on the list endpoint instead of adding a dedicated GET
  // so we don't fan out the API surface — the list is indexed and
  // cached by React Query (30 s staleTime matches AssetsPage).
  const assetsQuery = useQuery({
    queryKey: ['bim-assets', projectId],
    queryFn: () => listTrackedAssets(projectId),
    enabled: !!projectId && visible && !!elementId,
    staleTime: 30_000,
  });

  const tracked = useMemo(() => {
    if (!elementId) return null;
    return assetsQuery.data?.items.find((a) => a.id === elementId) ?? null;
  }, [assetsQuery.data, elementId]);

  if (!visible || !elementId || !element) return null;

  const handleEditClick = () => {
    if (tracked) {
      setEditing(tracked);
    } else {
      // Element isn't registered yet — synth a minimal summary so the
      // modal can still prefill the header. Saving will flip
      // is_tracked_asset to true on the backend.
      setEditing({
        id: element.id,
        stable_id: element.stable_id,
        element_type: element.element_type ?? 'Element',
        name: element.name ?? null,
        model_id: element.model_id ?? '',
        model_name: element.model_name ?? '',
        project_id: projectId,
        asset_info: {},
      });
    }
  };

  return (
    <>
      <div
        className="absolute z-30 select-none rounded-lg border border-oe-blue/30 bg-surface-primary/95 backdrop-blur-sm shadow-md px-3 py-2 min-w-[200px] transition-[inset-inline-start] duration-200"
        style={{ insetInlineStart, top: topPx }}
        data-testid="bim-asset-card"
      >
        <div className="flex items-center justify-between gap-2 mb-1.5">
          <div className="flex items-center gap-1.5">
            <Package size={12} className="text-oe-blue shrink-0" />
            <span className="text-[10px] font-semibold uppercase tracking-wide text-content-tertiary">
              {t('assets.card_title', { defaultValue: 'Asset info' })}
            </span>
          </div>
          <button
            type="button"
            onClick={handleEditClick}
            className="inline-flex items-center gap-1 text-[10px] text-oe-blue hover:underline"
            data-testid="bim-asset-edit"
          >
            <Edit3 size={10} />
            {tracked
              ? t('common.edit', { defaultValue: 'Edit' })
              : t('assets.register', { defaultValue: 'Register' })}
          </button>
        </div>

        {tracked ? (
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[11px]">
            {tracked.asset_info.manufacturer && (
              <>
                <dt className="text-content-tertiary">
                  {t('assets.field.manufacturer', { defaultValue: 'Mfr.' })}
                </dt>
                <dd className="font-medium text-content-primary truncate" title={tracked.asset_info.manufacturer}>
                  {tracked.asset_info.manufacturer}
                </dd>
              </>
            )}
            {tracked.asset_info.model && (
              <>
                <dt className="text-content-tertiary">
                  {t('assets.field.model', { defaultValue: 'Model' })}
                </dt>
                <dd className="font-medium text-content-primary truncate" title={tracked.asset_info.model}>
                  {tracked.asset_info.model}
                </dd>
              </>
            )}
            {tracked.asset_info.serial_number && (
              <>
                <dt className="text-content-tertiary">
                  {t('assets.field.serial_short', { defaultValue: 'S/N' })}
                </dt>
                <dd className="font-mono text-[10px] text-content-primary truncate" title={tracked.asset_info.serial_number}>
                  {tracked.asset_info.serial_number}
                </dd>
              </>
            )}
            {tracked.asset_info.operational_status && (
              <>
                <dt className="text-content-tertiary">
                  {t('assets.field.status_short', { defaultValue: 'Status' })}
                </dt>
                <dd className="text-[11px] text-content-secondary">
                  {tracked.asset_info.operational_status.replace('_', ' ')}
                </dd>
              </>
            )}
            {tracked.asset_info.warranty_until && (
              <>
                <dt className="text-content-tertiary">
                  {t('assets.field.warranty_short', { defaultValue: 'Warranty' })}
                </dt>
                <dd className="text-[11px] text-content-secondary">
                  {tracked.asset_info.warranty_until}
                </dd>
              </>
            )}
          </dl>
        ) : (
          <p className="text-[11px] text-content-tertiary italic">
            {t('assets.not_tracked', {
              defaultValue: 'Not tracked yet — register to capture manufacturer, serial, warranty…',
            })}
          </p>
        )}
      </div>

      {editing && (
        <AssetEditModal
          asset={editing}
          onClose={() => setEditing(null)}
          onSaved={() => setEditing(null)}
        />
      )}
    </>
  );
}
